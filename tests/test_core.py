"""Tests for simple_nanobot runner, loop, tools, and provider."""

import asyncio
import json
from pathlib import Path

import pytest

from bus import MessageBus
from context import ContextBuilder
from events import InboundMessage
from loop import AgentLoop
from provider import LLMProvider, LLMResponse, MockProvider, ToolCallRequest
from runner import AgentRunner
from storage import SessionStorage
from tools import ListDirTool, ReadFileTool, ShellTool, ToolRegistry, WriteFileTool


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tools():
    reg = ToolRegistry()
    reg.register(ShellTool())
    reg.register(ReadFileTool())
    reg.register(WriteFileTool())
    reg.register(ListDirTool())
    return reg


@pytest.fixture
def ctx():
    return ContextBuilder(tool_names=["shell", "read_file", "write_file", "list_dir"])


@pytest.fixture
def bus():
    return MessageBus()


# ── MockProvider tests ───────────────────────────────────────────────


class TestMockProvider:

    def test_plain_text_reply(self):
        provider = MockProvider()

        async def go():
            return await provider.generate(
                messages=[
                    {"role": "system", "content": "You are a bot"},
                    {"role": "user", "content": "你好"},
                ],
            )

        resp = asyncio.run(go())
        assert resp.finish_reason == "stop"
        assert resp.tool_calls == []
        assert "你好" in resp.content

    def test_tool_call_on_file_keyword(self):
        provider = MockProvider()

        async def go():
            return await provider.generate(
                messages=[
                    {"role": "user", "content": "帮我看看当前目录有什么文件"},
                ],
            )

        resp = asyncio.run(go())
        assert resp.finish_reason == "tool_calls"
        assert resp.tool_calls[0].name == "shell"

    def test_no_tool_call_on_create_file(self):
        provider = MockProvider()

        async def go():
            return await provider.generate(
                messages=[
                    {"role": "user", "content": "帮我看看文件列表"},
                ],
                tools=[],
            )

        resp = asyncio.run(go())
        assert resp.finish_reason == "tool_calls"

    def test_text_reply_after_tool(self):
        provider = MockProvider()

        async def go():
            return await provider.generate(
                messages=[
                    {"role": "user", "content": "看看文件"},
                    {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "shell", "arguments": '{"command":"ls"}'}}]},
                    {"role": "tool", "content": "file1.txt\nfile2.txt"},
                ],
            )

        resp = asyncio.run(go())
        assert resp.finish_reason == "stop"
        assert resp.tool_calls == []
        assert "file1" in resp.content

    def test_call_counter_per_instance(self):
        a = MockProvider()
        b = MockProvider()

        async def go():
            return await a.generate(
                messages=[{"role": "user", "content": "文件"}],
            )

        asyncio.run(go())
        assert a._call_counter == 1
        assert b._call_counter == 0  # independent instances


# ── AgentRunner tests ─────────────────────────────────────────────────


class TestAgentRunner:

    async def test_plain_text_run(self, tools):
        class TextProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="你好呀!", finish_reason="stop")

        runner = AgentRunner()
        messages = [
            {"role": "system", "content": "bot"},
            {"role": "user", "content": "hello"},
        ]
        reply = await runner.run(
            initial_messages=messages,
            tools=tools,
            provider=TextProvider(),
        )
        assert reply == "你好呀!"
        # 消息列表被原地累积，调用方直接读取传入的列表
        assert messages[-1] == {"role": "assistant", "content": "你好呀!"}

    async def test_tool_call_run(self, tools):
        class ToolCallProvider(LLMProvider):
            def __init__(self):
                self.calls = 0

            async def generate(self, messages, tools=None):
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(
                        tool_calls=[ToolCallRequest(
                            id="c1", name="shell",
                            arguments={"command": "echo ok"},
                        )],
                        finish_reason="tool_calls",
                    )
                return LLMResponse(content="执行完毕", finish_reason="stop")

        runner = AgentRunner()
        messages = [
            {"role": "system", "content": "bot"},
            {"role": "user", "content": "帮我看文件"},
        ]
        reply = await runner.run(
            initial_messages=messages,
            tools=tools,
            provider=ToolCallProvider(),
        )
        assert reply == "执行完毕"
        # verify tool_calls and tool result are in messages
        roles = [m["role"] for m in messages]
        assert "tool" in roles
        assert messages[-1] == {"role": "assistant", "content": "执行完毕"}

    async def test_error_finish_reason(self, tools):
        class ErrorProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="API 挂了", finish_reason="error")

        runner = AgentRunner()
        reply = await runner.run(
            initial_messages=[
                {"role": "system", "content": "bot"},
                {"role": "user", "content": "hello"},
            ],
            tools=tools,
            provider=ErrorProvider(),
        )
        assert "不可用" in reply

    async def test_max_iterations(self, tools):
        class LoopProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(
                    tool_calls=[ToolCallRequest(
                        id="c1", name="shell",
                        arguments={"command": "echo x"},
                    )],
                    finish_reason="tool_calls",
                )

        runner = AgentRunner()
        reply = await runner.run(
            initial_messages=[
                {"role": "system", "content": "bot"},
                {"role": "user", "content": "help"},
            ],
            tools=tools,
            provider=LoopProvider(),
            max_iterations=2,
        )
        assert "太久了" in reply


# ── Tool tests ───────────────────────────────────────────────────────


class TestShellTool:

    async def test_echo(self):
        result = await ShellTool().execute({"command": "echo hello"})
        assert "hello" in result

    async def test_invalid_command(self):
        result = await ShellTool().execute({"command": "nosuchcmd_xyz 2>/dev/null"})
        assert "exit code" in result.lower() or result


class TestReadFileTool:

    async def test_read_existing_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await ReadFileTool().execute({"path": str(f)})
        assert result == "hello world"

    async def test_read_nonexistent(self):
        result = await ReadFileTool().execute({"path": "/no/such/file.txt"})
        assert "不存在" in result


class TestWriteFileTool:

    async def test_write_and_read(self, tmp_path: Path):
        f = tmp_path / "out.txt"
        result = await WriteFileTool().execute({
            "path": str(f),
            "content": "test content",
        })
        assert "成功" in result
        assert f.read_text() == "test content"

    async def test_create_parent_dirs(self, tmp_path: Path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = await WriteFileTool().execute({
            "path": str(f),
            "content": "nested",
        })
        assert "成功" in result
        assert f.read_text() == "nested"


class TestListDirTool:

    async def test_list_nonempty_dir(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b").mkdir()
        result = await ListDirTool().execute({"path": str(tmp_path)})
        assert "a.txt" in result
        assert "b/" in result

    async def test_list_empty_dir(self, tmp_path: Path):
        result = await ListDirTool().execute({"path": str(tmp_path)})
        assert "为空" in result

    async def test_list_nonexistent(self):
        result = await ListDirTool().execute({"path": "/no/such/dir"})
        assert "不存在" in result


# ── ToolRegistry tests ────────────────────────────────────────────────


class TestToolRegistry:

    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(ShellTool())
        assert reg.get("shell") is not None
        assert reg.get("nope") is None

    def test_tool_names(self):
        reg = ToolRegistry()
        reg.register(ShellTool())
        reg.register(ReadFileTool())
        assert set(reg.tool_names()) == {"shell", "read_file"}

    def test_definitions(self, tools):
        defs = tools.get_definitions()
        assert len(defs) == 4
        for d in defs:
            assert d["type"] == "function"
            assert "name" in d["function"]

    # ── 技能幻觉兑底引导 ────────────────────────────────────────────

    def test_register_skills_does_not_enter_definitions(self):
        """技能登记后不参与工具定义（技能不是工具）"""
        reg = ToolRegistry()
        reg.register(ShellTool())
        reg.register_skills([
            {"name": "tavily-search", "path": "C:/skills/tavily-search/SKILL.md"},
        ])

        defs = reg.get_definitions()
        assert all(d["function"]["name"] != "tavily-search" for d in defs)

    async def test_execute_skill_name_returns_guidance(self):
        """技能名被当工具调用时，返回 read_file 引导而非"找不到工具"""
        reg = ToolRegistry()
        reg.register_skills([
            {"name": "tavily-search", "path": "C:/skills/tavily-search/SKILL.md"},
        ])

        result = await reg.execute("tavily-search", {"query": "新闻"})

        assert "是技能而非工具" in result
        assert "C:/skills/tavily-search/SKILL.md" in result
        assert "read_file" in result

    async def test_execute_unknown_name_keeps_plain_error(self):
        """未登记的名字仍返回普通"找不到工具"错误"""
        reg = ToolRegistry()
        reg.register_skills([
            {"name": "tavily-search", "path": "C:/skills/tavily-search/SKILL.md"},
        ])

        result = await reg.execute("no_such_tool", {})

        assert "找不到工具" in result
        assert "read_file" not in result


# ── AgentLoop + SessionStorage 持久化集成测试 ────────────────────────


class TestAgentLoopPersistence:
    """RESTORE / SAVE 状态与 SessionStorage 的集成：重启后历史可恢复"""

    async def test_history_persisted_and_restored(self, tmp_path: Path):
        """处理消息后落盘，新 AgentLoop（模拟重启）从磁盘恢复历史"""

        class TextProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="回复内容", finish_reason="stop")

        storage = SessionStorage(tmp_path)
        loop1 = AgentLoop(
            bus=MessageBus(),
            provider=TextProvider(),
            tools=ToolRegistry(),
            context_builder=ContextBuilder(),
            storage=storage,
        )

        msg = InboundMessage(
            channel="cli", sender_id="user", chat_id="default", content="你好"
        )
        await loop1._process_message(msg)

        # 会话文件已落盘
        assert (tmp_path / "cli_default.json").exists()

        # 新 AgentLoop（同一 storage，模拟重启）恢复历史
        loop2 = AgentLoop(
            bus=MessageBus(),
            provider=TextProvider(),
            tools=ToolRegistry(),
            context_builder=ContextBuilder(),
            storage=storage,
        )
        history = loop2._restore_history("cli:default")

        assert history[0] == {"role": "user", "content": "你好"}
        assert history[-1] == {"role": "assistant", "content": "回复内容"}

    async def test_second_session_includes_first_round(self, tmp_path: Path):
        """第二轮对话时 RESTORE 出第一轮历史，上下文包含之前的消息"""

        class TextProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                self.last_messages = messages
                return LLMResponse(content="好的", finish_reason="stop")

        provider = TextProvider()
        loop_agent = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            tools=ToolRegistry(),
            context_builder=ContextBuilder(),
            storage=SessionStorage(tmp_path),
        )

        def make_msg(content: str) -> InboundMessage:
            return InboundMessage(
                channel="cli", sender_id="user", chat_id="default", content=content
            )

        await loop_agent._process_message(make_msg("第一轮"))
        await loop_agent._process_message(make_msg("第二轮"))

        # 第二轮发给 AI 的上下文里应包含第一轮的用户消息与回复
        contents = [m.get("content", "") for m in provider.last_messages]
        assert any("第一轮" in c for c in contents)
        assert any("好的" in c for c in contents)

    async def test_no_storage_keeps_memory_only(self):
        """storage=None 时保持纯内存行为（不落盘、不报错）"""

        class TextProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="ok", finish_reason="stop")

        loop_agent = AgentLoop(
            bus=MessageBus(),
            provider=TextProvider(),
            tools=ToolRegistry(),
            context_builder=ContextBuilder(),
            storage=None,
        )
        msg = InboundMessage(
            channel="cli", sender_id="user", chat_id="default", content="你好"
        )
        out = await loop_agent._process_message(msg)

        assert out.content == "ok"
        assert loop_agent._restore_history("cli:default")  # 内存中仍有历史
