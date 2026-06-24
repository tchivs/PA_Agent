"""Unit tests for Cursor SDK stream event mapping."""
from __future__ import annotations

from types import SimpleNamespace

from pa_agent.ai.cursor_sdk_client import _consume_cursor_stream_event


def test_consume_thinking_delta_emits_reasoning_callback() -> None:
    reasoning: list[str] = []
    content: list[str] = []
    emitted: list[str] = []

    event = SimpleNamespace(
        interaction_update=SimpleNamespace(type="thinking-delta", text="alpha "),
        sdk_message=None,
        step=None,
    )
    _consume_cursor_stream_event(
        event,
        reasoning_parts=reasoning,
        content_parts=content,
        on_reasoning_token=emitted.append,
        on_content_token=None,
    )

    assert reasoning == ["alpha "]
    assert emitted == ["alpha "]
    assert content == []


def test_consume_text_delta_emits_content_callback() -> None:
    reasoning: list[str] = []
    content: list[str] = []
    emitted: list[str] = []

    event = SimpleNamespace(
        interaction_update=SimpleNamespace(type="text-delta", text='{"ok":'),
        sdk_message=None,
        step=None,
    )
    _consume_cursor_stream_event(
        event,
        reasoning_parts=reasoning,
        content_parts=content,
        on_reasoning_token=None,
        on_content_token=emitted.append,
    )

    assert content == ['{"ok":']
    assert emitted == ['{"ok":']
    assert reasoning == []
