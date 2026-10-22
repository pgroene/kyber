"""Assemble the chat prompt from its parts and fit it into the context window.

The prompt used to be built as one string and cut with ``[:limit]``, which
always removed its end: the user's question, the ``Assistant:`` marker and the
newest tool results. ``ChatPrompt`` keeps the parts apart so a render can drop
the least important text first.

Order, the same on every path: the stable ``core`` first (rules and the
home structure, no live states), so prompt caching can reuse it from one
request to the next (OpenAI/Azure automatically, Anthropic via cache_control,
llama.cpp via its KV cache). Then the conversation, which only grows at its
end. Then what changes with every request (memory facts, live states, editor
YAML, response mode) and the question. Tool rounds of this turn come last.

``render`` returns one text (the ai_task path, where Home Assistant builds the
roles); ``render_messages`` returns the same selection as a system part plus
user/assistant messages for the cloud providers, so the history reaches them
exactly once and within the budget.

When the prompt does not fit, text goes in this order:

1. history, oldest message first
2. the compacted summary of earlier turns
3. changes made earlier in the conversation, oldest first
4. older tool rounds of this turn, oldest first
5. recalled memory facts
6. last resort: the middle of the core, then of the request block
never: the question and the newest tool round

Independently of overflow, memory facts never take more than their own slice
of the limit (``knowledge_char_budget``).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .const import (
    CHARS_PER_TOKEN,
    KNOWLEDGE_BUDGET_CHARS,
    KNOWLEDGE_BUDGET_SHARE,
    PROMPT_CONTEXT_SHARE,
)

SUMMARY_HEADER = "[Earlier in this conversation]\n"
CHANGES_HEADER = "[Changes made earlier in this conversation]\n"
RECENT_HEADER = "[Recent messages]\n"
HISTORY_OMITTED = "[Older messages omitted to fit the context window]"
TOOL_ROUNDS_OMITTED = "\n[Earlier tool results omitted to fit the context window]\n"
CONVERSATION_CONTINUES = "[The conversation continues]"
CUT_MARKER = "\n[…]\n"


def prompt_char_limit(context_tokens: int) -> int:
    """Return the prompt budget in chars for a context window of ``context_tokens``."""
    return max(0, int(int(context_tokens or 0) * CHARS_PER_TOKEN * PROMPT_CONTEXT_SHARE))


def knowledge_char_budget(limit: int) -> int:
    """Return the slice of ``limit`` reserved for recalled memory facts."""
    return max(KNOWLEDGE_BUDGET_CHARS, int(limit * KNOWLEDGE_BUDGET_SHARE))


def _cut_middle(text: str, excess: int) -> str:
    """Remove at least ``excess`` chars from the middle of ``text``."""
    keep = len(text) - excess - len(CUT_MARKER)
    if keep <= 0:
        return ""
    head = keep - keep // 2
    tail = keep // 2
    return text[:head] + CUT_MARKER + (text[-tail:] if tail else "")


def _speaker(role: str) -> str:
    return "User" if role == "user" else "Assistant"


@dataclass(frozen=True)
class ToolRound:
    """One tool exchange of the current turn.

    ``reply`` is what the model said (its tool calls), empty for a note from
    Kyber; ``feedback`` is what goes back to the model (tool results, a check
    result or a redirect note).
    """

    reply: str
    feedback: str

    @property
    def text(self) -> str:
        """The round as a continuation of the text prompt, ending with the next "Assistant:"."""
        reply = f"{self.reply}\n" if self.reply else "\n"
        return f"{reply}{self.feedback}\nAssistant:"

    def with_note(self, note: str) -> ToolRound:
        """The round with ``note`` added to what goes back to the model."""
        return ToolRound(self.reply, self.feedback + note)


@dataclass(frozen=True)
class PromptFit:
    """A rendered prompt plus a record of what had to go.

    ``text`` is always set. A ``render_messages`` fit also carries ``system``
    and ``messages`` (role/content dicts, starting with a user message, roles
    alternating, ending with a user message).
    """

    text: str
    limit: int | None = None
    # True when the prompt did not fit and parts were left out for that reason
    # (memory facts over their own budget alone do not count).
    trimmed: bool = False
    history_dropped: int = 0
    summary_dropped: bool = False
    changes_dropped: int = 0
    tool_rounds_dropped: int = 0
    knowledge_dropped: int = 0
    core_cut: int = 0
    system: str = ""
    messages: tuple[dict, ...] = ()

    def describe(self) -> str:
        """One-line summary for the log."""
        parts = []
        if self.history_dropped:
            parts.append(f"{self.history_dropped} history message(s)")
        if self.summary_dropped:
            parts.append("conversation summary")
        if self.changes_dropped:
            parts.append(f"{self.changes_dropped} earlier change record(s)")
        if self.tool_rounds_dropped:
            parts.append(f"{self.tool_rounds_dropped} older tool round(s)")
        if self.knowledge_dropped:
            parts.append(f"{self.knowledge_dropped} memory fact block(s)")
        if self.core_cut:
            parts.append(f"{self.core_cut} chars of system context")
        return ", ".join(parts) or "nothing"


@dataclass(frozen=True)
class _Selection:
    """The parts that made it into one render."""

    core: str
    summary: str
    changes: list[str]
    history: list[tuple[str, str]]
    knowledge: list[str]
    request: str
    rounds: list[ToolRound]
    total_rounds: int


@dataclass
class ChatPrompt:
    """The chat prompt as separate parts, rendered on demand within a limit."""

    # Stable system part: rules, home structure, user and dashboards. Must not
    # carry anything that changes between requests (prompt cache).
    core: str
    # The user's question of this turn.
    question: str
    # What changes with every request: live states, editor YAML, response
    # mode and similar sections, placed right before the question.
    request: str = ""
    # Compacted summary of turns older than ``history``.
    summary: str = ""
    # [CHANGE] records that left the history through compaction, oldest first.
    changes: list[str] = field(default_factory=list)
    # (role, content) pairs, oldest first; role is "user" or "assistant".
    history: list[tuple[str, str]] = field(default_factory=list)
    # Heading of the recalled memory section, shown when any block is kept.
    knowledge_header: str = ""
    # One block per recalled fact, most relevant first; extra context last.
    knowledge: list[str] = field(default_factory=list)

    @property
    def turn(self) -> str:
        """The current turn as it ends the text prompt."""
        return f"User: {self.question}\nAssistant:"

    @property
    def conversation_block(self) -> str:
        """The full, untrimmed conversation history as it appears in the prompt."""
        return self._conversation(self.summary, self.changes, self.history)

    def render(self, limit: int | None = None, tool_rounds: Sequence[ToolRound] = ()) -> PromptFit:
        """Return the prompt as one text with ``tool_rounds`` appended, fitted into ``limit`` chars."""
        return self._fit(limit, tool_rounds, as_messages=False)

    def render_messages(self, limit: int | None = None, tool_rounds: Sequence[ToolRound] = ()) -> PromptFit:
        """Return the same selection as ``render``, as a system part and role messages."""
        return self._fit(limit, tool_rounds, as_messages=True)

    # ── fitting ──────────────────────────────────────────────────────────

    def _fit(self, limit: int | None, tool_rounds: Sequence[ToolRound], *, as_messages: bool) -> PromptFit:
        rounds = [r for r in tool_rounds if r]
        total_rounds = len(rounds)

        def done(sel: _Selection, text: str | None = None, **record) -> PromptFit:
            text = self._text(sel) if text is None else text
            if not as_messages:
                return PromptFit(text, limit, **record)
            return PromptFit(text, limit, system=sel.core, messages=tuple(self._messages(sel)), **record)

        if limit is None:
            return done(_Selection(
                self.core, self.summary, list(self.changes), list(self.history),
                list(self.knowledge), self.request, rounds, total_rounds,
            ))

        # Memory facts always stay within their own slice, most relevant first;
        # a block too big for what is left is skipped, smaller ones still fit.
        budgeted_knowledge: list[str] = []
        knowledge_budget = knowledge_char_budget(limit)
        for block in self.knowledge:
            candidate = budgeted_knowledge + [block]
            if len(self._knowledge(candidate)) <= knowledge_budget:
                budgeted_knowledge = candidate

        full = _Selection(
            self.core, self.summary, list(self.changes), list(self.history),
            budgeted_knowledge, self.request, rounds, total_rounds,
        )
        if len(self._text(full)) <= limit:
            return done(full, knowledge_dropped=len(self.knowledge) - len(budgeted_knowledge))

        def size(**parts) -> int:
            sel = _Selection(**{
                "core": core, "summary": "", "changes": [], "history": [], "knowledge": [],
                "request": request, "rounds": kept_rounds, "total_rounds": total_rounds, **parts,
            })
            return len(self._text(sel))

        # Mandatory parts first; only if they alone overflow are core and request cut.
        core, request = self.core, self.request
        kept_rounds = rounds[-1:]
        base = size()
        if base > limit:
            core = _cut_middle(core, base - limit)
            base = size()
            if base > limit:
                request = _cut_middle(request, base - limit)
            sel = _Selection(core, "", [], [], [], request, kept_rounds, total_rounds)
            text = self._text(sel)
            if len(text) > limit:
                # Pathological: question plus newest round exceed the window.
                # Keep the end, which carries the question and "Assistant:".
                text = text[-limit:]
            return done(
                sel,
                text,
                trimmed=True,
                history_dropped=len(self.history),
                summary_dropped=bool(self.summary),
                changes_dropped=len(self.changes),
                tool_rounds_dropped=total_rounds - len(kept_rounds),
                knowledge_dropped=len(self.knowledge),
                core_cut=len(self.core) - len(core),
            )

        kept_knowledge: list[str] = []
        for block in budgeted_knowledge:
            candidate = kept_knowledge + [block]
            if size(knowledge=candidate) <= limit:
                kept_knowledge = candidate

        for older in reversed(rounds[:-1]):
            candidate = [older] + kept_rounds
            if size(knowledge=kept_knowledge, rounds=candidate) > limit:
                break
            kept_rounds = candidate

        kept_changes: list[str] = []
        for change in reversed(self.changes):
            candidate = [change] + kept_changes
            if size(knowledge=kept_knowledge, changes=candidate) > limit:
                break
            kept_changes = candidate

        summary = self.summary
        if summary and size(knowledge=kept_knowledge, changes=kept_changes, summary=summary) > limit:
            summary = ""

        kept_history: list[tuple[str, str]] = []
        for message in reversed(self.history):
            candidate = [message] + kept_history
            if size(knowledge=kept_knowledge, changes=kept_changes, summary=summary, history=candidate) > limit:
                break
            kept_history = candidate

        return done(
            _Selection(core, summary, kept_changes, kept_history, kept_knowledge, request, kept_rounds, total_rounds),
            trimmed=True,
            history_dropped=len(self.history) - len(kept_history),
            summary_dropped=bool(self.summary) and not summary,
            changes_dropped=len(self.changes) - len(kept_changes),
            tool_rounds_dropped=total_rounds - len(kept_rounds),
            knowledge_dropped=len(self.knowledge) - len(kept_knowledge),
        )

    # ── text form ────────────────────────────────────────────────────────

    def _conversation_intro(self, summary: str, changes: list[str]) -> str:
        parts = []
        if summary:
            parts.append(SUMMARY_HEADER + summary)
        if changes:
            parts.append(CHANGES_HEADER + "\n".join(changes))
        return "\n\n".join(parts)

    def _conversation(self, summary: str, changes: list[str], history: list[tuple[str, str]]) -> str:
        parts = []
        intro = self._conversation_intro(summary, changes)
        if intro:
            parts.append(intro)
        lines = [f"{_speaker(role)}: {content}" for role, content in history]
        if len(history) < len(self.history):
            lines.insert(0, HISTORY_OMITTED)
        if lines:
            parts.append(RECENT_HEADER + "\n".join(lines))
        return "\n\n".join(parts) + "\n\n" if parts else ""

    def _knowledge(self, blocks: list[str]) -> str:
        if not blocks:
            return ""
        return "\n".join([self.knowledge_header, *blocks]) + "\n\n"

    def _exchange(self, sel: _Selection) -> str:
        exchange = "".join(r.text for r in sel.rounds)
        if len(sel.rounds) < sel.total_rounds:
            exchange = TOOL_ROUNDS_OMITTED + exchange
        return exchange

    def _text(self, sel: _Selection) -> str:
        return (
            sel.core
            + self._conversation(sel.summary, sel.changes, sel.history)
            + self._knowledge(sel.knowledge)
            + sel.request
            + self.turn
            + self._exchange(sel)
        )

    # ── message form ─────────────────────────────────────────────────────

    def _messages(self, sel: _Selection) -> list[dict]:
        """Role messages for the cloud providers (``sel.core`` is the system part)."""
        messages: list[dict] = []
        intro = self._conversation_intro(sel.summary, sel.changes)
        if len(sel.history) < len(self.history):
            intro = f"{intro}\n\n{HISTORY_OMITTED}" if intro else HISTORY_OMITTED
        if intro:
            messages.append({"role": "user", "content": intro})
        for role, content in sel.history:
            messages.append({"role": role, "content": content})

        question = self._knowledge(sel.knowledge) + sel.request + self.question
        if len(sel.rounds) < sel.total_rounds:
            question += TOOL_ROUNDS_OMITTED.rstrip("\n")
        messages.append({"role": "user", "content": question})
        for r in sel.rounds:
            if r.reply:
                messages.append({"role": "assistant", "content": r.reply})
            messages.append({"role": "user", "content": r.feedback.strip()})
        return _alternate(messages)


def _alternate(messages: list[dict]) -> list[dict]:
    """Merge neighbours of the same role and start with a user message.

    Anthropic requires strictly alternating roles starting with "user"; for
    OpenAI and Azure the merged form says the same.
    """
    merged: list[dict] = []
    for message in messages:
        content = message["content"]
        if not content:
            continue
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + content}
        else:
            merged.append({"role": message["role"], "content": content})
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": CONVERSATION_CONTINUES})
    return merged
