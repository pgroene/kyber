"""Assemble the chat prompt from its parts and fit it into the context window.

The prompt used to be built as one string and cut with ``[:limit]``, which
always removed its end: the user's question, the ``Assistant:`` marker and the
newest tool results. ``ChatPrompt`` keeps the parts apart so ``render`` can
drop the least important text first:

1. never: the current turn (question + ``Assistant:``) and the newest tool round
2. history, oldest message first
3. the compacted summary of earlier turns
4. older tool rounds of this turn, oldest first
5. recalled memory facts
6. last resort: the middle of the core (system prompt and home context)

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
RECENT_HEADER = "[Recent messages]\n"
HISTORY_OMITTED = "[Older messages omitted to fit the context window]"
TOOL_ROUNDS_OMITTED = "\n[Earlier tool results omitted to fit the context window]\n"
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


@dataclass(frozen=True)
class PromptFit:
    """A rendered prompt plus a record of what had to go."""

    text: str
    limit: int | None = None
    # True when the prompt did not fit and parts were left out for that reason
    # (memory facts over their own budget alone do not count).
    trimmed: bool = False
    history_dropped: int = 0
    summary_dropped: bool = False
    tool_rounds_dropped: int = 0
    knowledge_dropped: int = 0
    core_cut: int = 0

    def describe(self) -> str:
        """One-line summary for the log."""
        parts = []
        if self.history_dropped:
            parts.append(f"{self.history_dropped} history message(s)")
        if self.summary_dropped:
            parts.append("conversation summary")
        if self.tool_rounds_dropped:
            parts.append(f"{self.tool_rounds_dropped} older tool round(s)")
        if self.knowledge_dropped:
            parts.append(f"{self.knowledge_dropped} memory fact block(s)")
        if self.core_cut:
            parts.append(f"{self.core_cut} chars of system context")
        return ", ".join(parts) or "nothing"


@dataclass
class ChatPrompt:
    """The chat prompt as separate parts, rendered on demand within a limit."""

    # System prompt, home context and editor sections; ends with "---\n\n".
    core: str
    # The current turn: "User: <question>\nAssistant:".
    turn: str
    # Compacted summary of turns older than ``history``.
    summary: str = ""
    # "User: …" / "Assistant: …" lines, oldest first.
    history: list[str] = field(default_factory=list)
    # Heading of the recalled memory section, shown when any block is kept.
    knowledge_header: str = ""
    # One block per recalled fact, most relevant first; extra context last.
    knowledge: list[str] = field(default_factory=list)

    @property
    def conversation_block(self) -> str:
        """The full, untrimmed conversation history as it appears in the prompt."""
        return self._conversation(self.summary, self.history)

    def render(self, limit: int | None = None, tool_rounds: Sequence[str] = ()) -> PromptFit:
        """Return the prompt with ``tool_rounds`` appended, fitted into ``limit`` chars."""
        rounds = [r for r in tool_rounds if r]
        if limit is None:
            return PromptFit(self._assemble(
                self.core, self.summary, self.history, self.knowledge, rounds, len(rounds),
            ))

        # Memory facts always stay within their own slice, most relevant first;
        # a block too big for what is left is skipped, smaller ones still fit.
        budgeted_knowledge: list[str] = []
        knowledge_budget = knowledge_char_budget(limit)
        for block in self.knowledge:
            candidate = budgeted_knowledge + [block]
            if len(self._knowledge(candidate)) <= knowledge_budget:
                budgeted_knowledge = candidate

        full = self._assemble(self.core, self.summary, self.history, budgeted_knowledge, rounds, len(rounds))
        if len(full) <= limit:
            return PromptFit(full, limit, knowledge_dropped=len(self.knowledge) - len(budgeted_knowledge))

        total_rounds = len(rounds)
        kept_rounds = rounds[-1:]

        def size(core: str, summary: str, history: list[str], knowledge: list[str], kept: list[str]) -> int:
            return len(self._assemble(core, summary, history, knowledge, kept, total_rounds))

        # Mandatory parts first; only if they alone overflow is the core cut.
        core = self.core
        base = size(core, "", [], [], kept_rounds)
        if base > limit:
            core = _cut_middle(core, base - limit)
            text = self._assemble(core, "", [], [], kept_rounds, total_rounds)
            if len(text) > limit:
                # Pathological: question plus newest round exceed the window.
                # Keep the end, which carries the question and "Assistant:".
                text = text[-limit:]
            return PromptFit(
                text,
                limit,
                trimmed=True,
                history_dropped=len(self.history),
                summary_dropped=bool(self.summary),
                tool_rounds_dropped=total_rounds - len(kept_rounds),
                knowledge_dropped=len(self.knowledge),
                core_cut=len(self.core) - len(core),
            )

        kept_knowledge: list[str] = []
        for block in budgeted_knowledge:
            candidate = kept_knowledge + [block]
            if size(core, "", [], candidate, kept_rounds) <= limit:
                kept_knowledge = candidate

        for older in reversed(rounds[:-1]):
            candidate = [older] + kept_rounds
            if size(core, "", [], kept_knowledge, candidate) > limit:
                break
            kept_rounds = candidate

        summary = self.summary
        if summary and size(core, summary, [], kept_knowledge, kept_rounds) > limit:
            summary = ""

        kept_history: list[str] = []
        for line in reversed(self.history):
            candidate = [line] + kept_history
            if size(core, summary, candidate, kept_knowledge, kept_rounds) > limit:
                break
            kept_history = candidate

        return PromptFit(
            self._assemble(core, summary, kept_history, kept_knowledge, kept_rounds, total_rounds),
            limit,
            trimmed=True,
            history_dropped=len(self.history) - len(kept_history),
            summary_dropped=bool(self.summary) and not summary,
            tool_rounds_dropped=total_rounds - len(kept_rounds),
            knowledge_dropped=len(self.knowledge) - len(kept_knowledge),
        )

    def _conversation(self, summary: str, history: list[str]) -> str:
        parts = []
        if summary:
            parts.append(SUMMARY_HEADER + summary)
        lines = list(history)
        if len(history) < len(self.history):
            lines.insert(0, HISTORY_OMITTED)
        if lines:
            parts.append(RECENT_HEADER + "\n".join(lines))
        return "\n\n".join(parts) + "\n\n" if parts else ""

    def _knowledge(self, blocks: list[str]) -> str:
        if not blocks:
            return ""
        return "\n".join([self.knowledge_header, *blocks]) + "\n\n"

    def _assemble(
        self,
        core: str,
        summary: str,
        history: list[str],
        knowledge: list[str],
        rounds: list[str],
        total_rounds: int,
    ) -> str:
        exchange = "".join(rounds)
        if len(rounds) < total_rounds:
            exchange = TOOL_ROUNDS_OMITTED + exchange
        return (
            core
            + self._conversation(summary, history)
            + self._knowledge(knowledge)
            + self.turn
            + exchange
        )
