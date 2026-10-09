"""The chat prompt is fitted into the context window by priority.

It used to be cut with ``[:limit]``, which removed the user's question, the
``Assistant:`` marker and the newest tool results first.
"""
from __future__ import annotations

from custom_components.kyber.prompt_budget import (
    CUT_MARKER,
    HISTORY_OMITTED,
    TOOL_ROUNDS_OMITTED,
    ChatPrompt,
    knowledge_char_budget,
    prompt_char_limit,
)

_TURN = "User: which lights are on?\nAssistant:"


def _prompt(**kw) -> ChatPrompt:
    kw.setdefault("core", "SYSTEM " + "c" * 2_000 + "\n---\n\n")
    kw.setdefault("turn", _TURN)
    return ChatPrompt(**kw)


def test_limit_follows_the_context_window() -> None:
    assert prompt_char_limit(8_192) == 24_576  # 4 chars/token, 75 % of the window
    assert prompt_char_limit(0) == 0
    assert knowledge_char_budget(100_000) == 10_000
    assert knowledge_char_budget(5_000) == 2_000  # floor


def test_fits_unchanged() -> None:
    prompt = _prompt(summary="earlier", history=["User: hi", "Assistant: hello"])
    fit = prompt.render(100_000)
    assert not fit.trimmed
    assert fit.text == prompt.render().text
    assert fit.text.endswith(_TURN)
    assert "[Earlier in this conversation]\nearlier" in fit.text
    assert "[Recent messages]\nUser: hi\nAssistant: hello" in fit.text


def test_oldest_history_goes_first_question_stays() -> None:
    history = [f"User: message {i} " + "x" * 1_100 for i in range(10)]
    prompt = _prompt(history=history)
    fit = prompt.render(len(prompt.core) + len(_TURN) + 4_000)

    assert fit.text.endswith(_TURN)
    assert "message 9" in fit.text and "message 0" not in fit.text
    assert HISTORY_OMITTED in fit.text
    assert fit.history_dropped == 10 - sum(f"message {i} " in fit.text for i in range(10))
    assert len(fit.text) <= fit.limit
    assert fit.trimmed


def test_summary_outlives_the_messages() -> None:
    prompt = _prompt(summary="s" * 300, history=["User: " + "h" * 1_000])
    fit = prompt.render(len(prompt.render().text) - 10)
    assert "s" * 300 in fit.text
    assert fit.history_dropped == 1
    assert not fit.summary_dropped


def test_newest_tool_round_stays_older_rounds_go() -> None:
    prompt = _prompt(history=["User: old " + "h" * 500])
    rounds = [
        "first\n[TOOL_RESULT: a]\n" + "1" * 3_000 + "\nAssistant:",
        "second\n[TOOL_RESULT: b]\n" + "2" * 3_000 + "\nAssistant:",
    ]
    fit = prompt.render(len(prompt.core) + len(_TURN) + 3_500, rounds)

    assert fit.text.endswith(rounds[-1])
    assert "1" * 3_000 not in fit.text
    assert TOOL_ROUNDS_OMITTED in fit.text
    assert _TURN in fit.text
    assert fit.tool_rounds_dropped == 1
    assert fit.history_dropped == 1  # history goes before tool results


def test_older_tool_rounds_beat_history() -> None:
    prompt = _prompt(history=["User: old " + "h" * 1_000])
    rounds = ["r1 " + "1" * 500 + "\nAssistant:", "r2 " + "2" * 500 + "\nAssistant:"]
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
    prompt = _prompt(core=core, history=["User: hi"], knowledge_header="## F", knowledge=["- f"])
    fit = prompt.render(5_000)

    assert len(fit.text) <= 5_000
    assert fit.text.startswith("HEAD-RULES")
    assert "TAIL-MODE" in fit.text
    assert CUT_MARKER in fit.text
    assert fit.text.endswith(_TURN)
    assert fit.core_cut > 0 and fit.history_dropped == 1 and fit.knowledge_dropped == 1


def test_question_survives_even_a_hopeless_limit() -> None:
    fit = _prompt().render(30)
    assert fit.text == _TURN[-30:]


def test_conversation_block_is_untrimmed() -> None:
    prompt = _prompt(summary="sum", history=["User: a", "Assistant: b"])
    assert prompt.conversation_block == (
        "[Earlier in this conversation]\nsum\n\n[Recent messages]\nUser: a\nAssistant: b\n\n"
    )
