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
        reply, msgs = await runner.run(
            initial_messages=[
                {"role": "system", "content": "bot"},
                {"role": "user", "content": "hello"},
            ],
            tools=tools,
            provider=TextProvider(),
        )
        assert reply == "你好呀!"
        assert msgs[-1] == {"role": "assistant", "content": "你好呀!"}

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
        reply, msgs = await runner.run(
            initial_messages=[
                {"role": "system", "content": "bot"},
                {"role": "user", "content": "帮我看文件"},
            ],
            tools=tools,
            provider=ToolCallProvider(),
        )
        assert reply == "执行完毕"
        # verify tool_calls and tool result are in messages
        roles = [m["role"] for m in msgs]
        assert "tool" in roles
        assert msgs[-1] == {"role": "assistant", "content": "执行完毕"}

    async def test_error_finish_reason(self, tools):
        class ErrorProvider(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="API 挂了", finish_reason="error")

        runner = AgentRunner()
        reply, _ = await runner.run(
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
        reply, _ = await runner.run(
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
