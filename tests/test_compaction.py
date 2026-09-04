"""Tests for loop.py 的 COMPACT 状态 —— 上下文压缩."""

import asyncio
from pathlib import Path

import pytest

from context import ContextBuilder
from events import InboundMessage
from loop import (
    COMPACT_KEEP_RECENT,
    AgentLoop,
    _estimate_tokens,
    _message_to_text,
)
from provider import LLMProvider, LLMResponse
from storage import SessionStorage
from tools import ToolRegistry


# ── helpers ────────────────────────────────────────────────────────


class SummaryProvider(LLMProvider):
    """总是返回固定摘要文本的 Provider（记录调用次数）"""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="这是历史摘要", finish_reason="stop")


class ErrorProvider(LLMProvider):
    """总是返回 API 错误的 Provider"""

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        return LLMResponse(content="API 挂了", finish_reason="error")


class CallRecordingProvider(LLMProvider):
    """记录调用次数但不返回有效内容（用于断言"未触发时不调用"）"""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="x", finish_reason="stop")


class SlowSummaryProvider(LLMProvider):
    """延迟 0.1 秒才返回摘要的 Provider（模拟 LLM 压缩耗时）"""

    async def generate(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        await asyncio.sleep(0.1)
        return LLMResponse(content="这是历史摘要", finish_reason="stop")


def make_long_history(n: int = 30, filler: str = "这是一条用于撑大上下文的历史消息内容") -> list[dict]:
    """构造 n 条长消息的历史"""
    return [{"role": "user", "content": filler} for _ in range(n)]


@pytest.fixture
def loop() -> AgentLoop:
    return AgentLoop(
        bus=None,  # _maybe_compact 不使用 bus
        provider=SummaryProvider(),
        tools=ToolRegistry(),
        context_builder=ContextBuilder(),
    )


# ── _estimate_tokens ───────────────────────────────────────────────


def test_estimate_tokens_empty() -> None:
    assert _estimate_tokens([]) == 0


def test_estimate_tokens_text_messages() -> None:
    messages = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 100},
    ]
    assert _estimate_tokens(messages) == 100  # (100 + 100) // 2


def test_estimate_tokens_counts_tool_calls() -> None:
    messages = [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": "shell", "arguments": '{"command": "ls"}'},
        }],
    }]
    expected = (len("shell") + len('{"command": "ls"}')) // 2
    assert _estimate_tokens(messages) == expected


# ── _message_to_text ───────────────────────────────────────────────


def test_message_to_text_plain() -> None:
    text = _message_to_text({"role": "user", "content": "你好"})
    assert text == "[user] 你好"


def test_message_to_text_tool_calls() -> None:
    text = _message_to_text({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": "shell", "arguments": '{"command": "ls"}'},
        }],
    })
    assert "[assistant]" in text
    assert "shell" in text
    assert "调用工具" in text


def test_message_to_text_empty_content() -> None:
    assert _message_to_text({"role": "tool", "content": ""}) == "[tool] (无文本内容)"


# ── _maybe_compact 触发逻辑 ────────────────────────────────────────


async def test_no_compact_below_threshold(loop: AgentLoop, monkeypatch: pytest.MonkeyPatch) -> None:
    """低于阈值：不调用 LLM，原样返回"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 10_000_000)
    provider = CallRecordingProvider()
    loop.provider = provider

    history = make_long_history(5)
    result = await loop._maybe_compact("cli:default", history)

    assert result is history  # 原样返回（同一对象）
    assert provider.calls == 0


async def test_compact_triggers_on_long_history(loop: AgentLoop, monkeypatch: pytest.MonkeyPatch) -> None:
    """超阈值：调用 LLM 总结，返回 [摘要] + 最近 KEEP 条"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)

    history = make_long_history(30)
    result = await loop._maybe_compact("cli:default", history)

    assert len(result) == COMPACT_KEEP_RECENT + 1
    assert result[0]["role"] == "user"
    assert "[此前对话摘要]" in result[0]["content"]
    assert "这是历史摘要" in result[0]["content"]
    # 保留的是最近 KEEP 条
    assert result[1:] == history[-COMPACT_KEEP_RECENT:]


async def test_compact_syncs_memory_cache(loop: AgentLoop, monkeypatch: pytest.MonkeyPatch) -> None:
    """压缩结果应同步到内存 _sessions，后续 SAVE 会落盘"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)

    history = make_long_history(30)
    result = await loop._maybe_compact("cli:default", history)

    assert loop._sessions["cli:default"] is result


async def test_compact_degrades_on_provider_error(
    loop: AgentLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    """总结失败（API 错误）→ 原样返回历史，不阻塞对话"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)
    loop.provider = ErrorProvider()

    history = make_long_history(30)
    result = await loop._maybe_compact("cli:default", history)

    assert result is history
    assert len(result) == 30


async def test_compact_skips_when_history_short(
    loop: AgentLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    """历史条数不超过 KEEP 时即使超阈值也不压缩（没有可省略的旧消息）"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)
    provider = CallRecordingProvider()
    loop.provider = provider

    history = make_long_history(COMPACT_KEEP_RECENT)  # 恰好等于 KEEP
    result = await loop._maybe_compact("cli:default", history)

    assert result is history
    assert provider.calls == 0


async def test_compact_persists_to_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """压缩结果落盘：storage 文件内容 = 压缩后历史（下一轮直接生效）"""
    storage = SessionStorage(tmp_path)
    loop = AgentLoop(
        bus=None,
        provider=SummaryProvider(),
        tools=ToolRegistry(),
        context_builder=ContextBuilder(),
        storage=storage,
    )
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)

    loop._sessions["cli:default"] = make_long_history(30)
    result = await loop._maybe_compact("cli:default", loop._sessions["cli:default"])

    assert len(result) == COMPACT_KEEP_RECENT + 1
    assert storage.load("cli:default") == result


# ── 回复速度：压缩不阻塞回复 ────────────────────────────────────────


def _make_msg(content: str = "继续") -> InboundMessage:
    return InboundMessage(
        channel="cli", sender_id="user", chat_id="default", content=content
    )


def _make_loop_with_slow_provider() -> AgentLoop:
    return AgentLoop(
        bus=None,
        provider=SlowSummaryProvider(),
        tools=ToolRegistry(),
        context_builder=ContextBuilder(),
    )


async def test_compact_does_not_block_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """_process_message 返回回复时不等待压缩（压缩在后台执行，随后写回）"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)
    loop_agent = _make_loop_with_slow_provider()
    loop_agent._sessions["cli:default"] = make_long_history(30)

    out = await loop_agent._process_message(_make_msg())

    assert out.content == "这是历史摘要"
    # 回复返回时压缩尚未完成：历史里还没有摘要
    assert not any(
        "[此前对话摘要]" in m.get("content", "") for m in loop_agent._sessions["cli:default"]
    )

    # 稍等后台压缩任务完成：摘要写入内存
    await asyncio.sleep(0.5)
    assert any(
        "[此前对话摘要]" in m.get("content", "")
        for m in loop_agent._sessions["cli:default"]
    )


async def test_compact_aborts_when_new_messages_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """压缩运行期间有新消息写入历史 → 放弃写回，不覆盖新消息"""
    monkeypatch.setattr("loop.COMPACT_THRESHOLD_TOKENS", 1)
    loop_agent = _make_loop_with_slow_provider()
    loop_agent._sessions["cli:default"] = make_long_history(30)

    # 触发一轮对话（内部会调度后台压缩任务）
    await loop_agent._process_message(_make_msg())
    # 让压缩任务进入 LLM 调用（0.1s 延迟）
    await asyncio.sleep(0.02)
    # 压缩运行期间新一轮消息写入历史（模拟 SAVE）
    loop_agent._sessions["cli:default"].append({"role": "user", "content": "新的一轮"})

    # 等压缩任务结束：应放弃写回，历史保留新消息且无摘要
    await asyncio.sleep(0.5)
    sessions = loop_agent._sessions["cli:default"]
    assert not any(
        "[此前对话摘要]" in m.get("content", "") for m in sessions
    )
    assert sessions[-1]["content"] == "新的一轮"


# ── 测试范围说明 ────────────────────────────────────────
# 本文件通过直接调用 _maybe_compact 测试 COMPACT 状态；
# RESTORE/SAVE 与 storage 的集成测试见 test_core.py 与 test_storage.py。

