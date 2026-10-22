"""The chat prompt is fitted into the context window by priority and
rendered with a stable start, once as text and once as role messages.

It used to be cut with ``[:limit]``, which removed the user's question, the
``Assistant:`` marker and the newest tool results first.
"""
from __future__ import annotations

from custom_components.kyber.prompt_budget import (
    CHANGES_HEADER,
    CONVERSATION_CONTINUES,
    CUT_MARKER,
    HISTORY_OMITTED,
    TOOL_ROUNDS_OMITTED,
    ChatPrompt,
    ToolRound,
    knowledge_char_budget,
    prompt_char_limit,
)

_QUESTION = "which lights are on?"
_TURN = f"User: {_QUESTION}\nAssistant:"


def _prompt(**kw) -> ChatPrompt:
    kw.setdefault("core", "SYSTEM " + "c" * 2_000 + "\n---\n\n")
    kw.setdefault("question", _QUESTION)
    return ChatPrompt(**kw)


def _round(tag: str, size: int) -> ToolRound:
    return ToolRound(f"{tag} [TOOL_CALL]", f"[TOOL_RESULT: {tag}]\n" + tag[-1] * size)


def test_limit_follows_the_context_window() -> None:
    assert prompt_char_limit(8_192) == 24_576  # 4 chars/token, 75 % of the window
    assert prompt_char_limit(0) == 0
    assert knowledge_char_budget(100_000) == 10_000
    assert knowledge_char_budget(5_000) == 2_000  # floor


def test_fits_unchanged() -> None:
    prompt = _prompt(summary="earlier", history=[("user", "hi"), ("assistant", "hello")])
    fit = prompt.render(100_000)
    assert not fit.trimmed
    assert fit.text == prompt.render().text
    assert fit.text.endswith(_TURN)
    assert "[Earlier in this conversation]\nearlier" in fit.text
    assert "[Recent messages]\nUser: hi\nAssistant: hello" in fit.text


def test_order_core_conversation_request_question() -> None:
    """Stable parts first, what changes per request right before the question."""
    prompt = _prompt(
        history=[("user", "hi")],
        knowledge_header="## Facts",
        knowledge=["- fact"],
        request="## Live home state\nlight.kitchen on\n",
    )
    text = prompt.render().text
    assert text.startswith("SYSTEM")
    assert text.index("User: hi") < text.index("## Facts") < text.index("## Live home state") < text.index(_TURN)


def test_core_start_survives_changed_states_and_a_new_turn() -> None:
    """Two requests in a row share the start up to the end of the earlier history (cache reuse)."""
    first = _prompt(history=[("user", "q1")], request="state: off\n", question="q2")
    second = _prompt(
        history=[("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")],
        request="state: on\n",
        question="q3",
    )
    a, b = first.render().text, second.render().text
    shared = a[: a.index("state: off")]
    assert shared.startswith(first.core)
    assert b.startswith(first.core + "[Recent messages]\nUser: q1")


def test_oldest_history_goes_first_question_stays() -> None:
    history = [("user", f"message {i} " + "x" * 1_100) for i in range(10)]
    prompt = _prompt(history=history)
    fit = prompt.render(len(prompt.core) + len(_TURN) + 4_000)

    assert fit.text.endswith(_TURN)
    assert "message 9" in fit.text and "message 0" not in fit.text
    assert HISTORY_OMITTED in fit.text
    assert fit.history_dropped == 10 - sum(f"message {i} " in fit.text for i in range(10))
    assert len(fit.text) <= fit.limit
    assert fit.trimmed


def test_summary_outlives_the_messages() -> None:
    prompt = _prompt(summary="s" * 300, history=[("user", "h" * 1_000)])
    fit = prompt.render(len(prompt.render().text) - 10)
    assert "s" * 300 in fit.text
    assert fit.history_dropped == 1
    assert not fit.summary_dropped


def test_changes_outlive_the_summary() -> None:
    """Change records answer "what did you change?" and go after the summary (#223)."""
    changes = ["[CHANGE] Turned on light.kitchen", "[CHANGE] Renamed light.hall"]
    prompt = _prompt(summary="s" * 1_000, changes=changes, history=[("user", "h" * 500)])
    fit = prompt.render(len(prompt.render().text) - 600)
    assert CHANGES_HEADER + "\n".join(changes) in fit.text
    assert fit.summary_dropped
    assert fit.changes_dropped == 0


def test_newest_tool_round_stays_older_rounds_go() -> None:
    prompt = _prompt(history=[("user", "old " + "h" * 500)])
    rounds = [_round("first1", 3_000), _round("second2", 3_000)]
    fit = prompt.render(len(prompt.core) + len(_TURN) + 3_500, rounds)

    assert fit.text.endswith(rounds[-1].text)
    assert "1" * 3_000 not in fit.text
    assert TOOL_ROUNDS_OMITTED in fit.text
    assert _TURN in fit.text
    assert fit.tool_rounds_dropped == 1
    assert fit.history_dropped == 1  # history goes before tool results


def test_older_tool_rounds_beat_history() -> None:
    prompt = _prompt(history=[("user", "old " + "h" * 1_000)])
    rounds = [_round("r1", 500), _round("r2", 500)]
    fit = prompt.render(len(prompt.core) + len(_TURN) + 1_200, rounds)
    assert fit.tool_rounds_dropped == 0
    assert fit.history_dropped == 1


def test_knowledge_has_its_own_budget() -> None:
    blocks = [f"- [fact] f{i}: " + "k" * 600 for i in range(10)]
    prompt = _prompt(knowledge_header="## Recalled memory facts", knowledge=blocks)
    limit = 20_000  # knowledge slice: 2 000 chars
    fit = prompt.render(limit)

    kept = [b for b in blocks if b in fit.text]
    assert 1 <= len(kept) <= 3
    assert kept == blocks[: len(kept)]  # most relevant first
    assert fit.knowledge_dropped == 10 - len(kept)
    assert not fit.trimmed  # the budget alone is not "shortened to fit"
    assert fit.text.index("## Recalled memory facts") < fit.text.index(_TURN)


def test_knowledge_skips_a_large_block_but_keeps_smaller_ones() -> None:
    blocks = ["- big " + "b" * 5_000, "- small fact"]
    prompt = _prompt(knowledge_header="## Facts", knowledge=blocks)
    fit = prompt.render(20_000)
    assert "- small fact" in fit.text
    assert "b" * 5_000 not in fit.text


def test_core_is_cut_in_the_middle_only_as_last_resort() -> None:
    core = "HEAD-RULES " + "m" * 10_000 + " TAIL-MODE\n---\n\n"
    prompt = _prompt(core=core, history=[("user", "hi")], knowledge_header="## F", knowledge=["- f"],
                     request="EDITOR-YAML\n")
    fit = prompt.render(5_000)

    assert len(fit.text) <= 5_000
    assert fit.text.startswith("HEAD-RULES")
    assert "TAIL-MODE" in fit.text
    assert "EDITOR-YAML" in fit.text  # the request block is mandatory
    assert CUT_MARKER in fit.text
    assert fit.text.endswith(_TURN)
    assert fit.core_cut > 0 and fit.history_dropped == 1 and fit.knowledge_dropped == 1


def test_question_survives_even_a_hopeless_limit() -> None:
    fit = _prompt().render(30)
    assert fit.text == _TURN[-30:]


def test_conversation_block_is_untrimmed() -> None:
    prompt = _prompt(summary="sum", changes=["[CHANGE] x"], history=[("user", "a"), ("assistant", "b")])
    assert prompt.conversation_block == (
        "[Earlier in this conversation]\nsum\n\n"
        "[Changes made earlier in this conversation]\n[CHANGE] x\n\n"
        "[Recent messages]\nUser: a\nAssistant: b\n\n"
    )


# ── role messages for cloud providers ─────────────────────────────────

def test_messages_carry_the_history_once_as_roles() -> None:
    prompt = _prompt(
        summary="sum",
        history=[("user", "hi"), ("assistant", "hello")],
        knowledge_header="## Facts",
        knowledge=["- fact"],
        request="## Live\nlight on\n",
    )
    fit = prompt.render_messages(100_000)

    assert fit.system == prompt.core
    # The summary message and the first history message are both "user": merged
    assert [m["role"] for m in fit.messages] == ["user", "assistant", "user"]
    assert fit.messages[0]["content"] == "[Earlier in this conversation]\nsum\n\nhi"
    assert fit.messages[1]["content"] == "hello"
    last = fit.messages[-1]["content"]
    assert last.endswith(_QUESTION) and "## Facts" in last and "## Live" in last
    everything = fit.system + "".join(m["content"] for m in fit.messages)
    assert everything.count("hello") == 1


def test_messages_follow_the_same_trimming_as_the_text() -> None:
    history = [("user", f"message {i} " + "x" * 1_100) for i in range(10)]
    prompt = _prompt(history=history)
    limit = len(prompt.core) + len(_TURN) + 4_000
    text_fit, msg_fit = prompt.render(limit), prompt.render_messages(limit)
    assert msg_fit.history_dropped == text_fit.history_dropped > 0
    contents = "".join(m["content"] for m in msg_fit.messages)
    assert HISTORY_OMITTED in contents
    assert "message 9" in contents and "message 0" not in contents


def test_messages_turn_tool_rounds_into_replies_and_results() -> None:
    rounds = [ToolRound("calling search", "[TOOL_RESULT: search]\nlight.kitchen"), ToolRound("", "[SYSTEM: stop]")]
    fit = _prompt().render_messages(100_000, rounds)
    roles = [m["role"] for m in fit.messages]
    assert roles == ["user", "assistant", "user"]
    assert fit.messages[1]["content"] == "calling search"
    # A note without a model reply joins the tool results of the round before
    assert fit.messages[2]["content"] == "[TOOL_RESULT: search]\nlight.kitchen\n\n[SYSTEM: stop]"


def test_messages_start_with_a_user_message() -> None:
    """Anthropic rejects a conversation that opens with the assistant."""
    fit = _prompt(history=[("assistant", "earlier answer"), ("user", "follow-up")]).render_messages()
    assert fit.messages[0] == {"role": "user", "content": CONVERSATION_CONTINUES}
    roles = [m["role"] for m in fit.messages]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_tool_round_text_and_notes() -> None:
    r = ToolRound("reply", "[TOOL_RESULT: x]\ndata")
    assert r.text == "reply\n[TOOL_RESULT: x]\ndata\nAssistant:"
    assert r.with_note("\nhint").feedback == "[TOOL_RESULT: x]\ndata\nhint"
    assert ToolRound("", "[SYSTEM: x]").text == "\n[SYSTEM: x]\nAssistant:"
