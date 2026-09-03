"""Tests for tools.py —— ShellTool.execute 的 mock 单元测试."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from tools import EditFileTool, ShellTool, _decode_output


class TestEditFileTool:
    """EditFileTool 的单元测试，使用临时文件验证实际读写"""

    # ── search_replace 模式 ────────────────────────────────────────────

    async def test_search_replace_basic(self, tmp_path):
        """基本搜索替换：old_text 被 new_text 替换"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "search_replace",
            "old_text": "world",
            "new_text": "nanobot",
        })

        assert "编辑成功" in result
        assert f.read_text(encoding="utf-8") == "hello nanobot"

    async def test_search_replace_not_found(self, tmp_path):
        """old_text 不存在时返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "search_replace",
            "old_text": "xyz",
            "new_text": "abc",
        })

        assert "未找到" in result

    async def test_search_replace_multiple_matches(self, tmp_path):
        """old_text 出现多次时返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "search_replace",
            "old_text": "foo",
            "new_text": "baz",
        })

        assert "唯一" in result
        assert "2 次" in result

    async def test_search_replace_missing_new_text(self, tmp_path):
        """search_replace 模式未提供 new_text 时返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "search_replace",
            "old_text": "hello",
        })

        assert "new_text" in result

    # ── insert 模式 ────────────────────────────────────────────────────

    async def test_insert_after(self, tmp_path):
        """在锚点文本后插入内容"""
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "insert",
            "old_text": "line2",
            "insert_content": "inserted",
            "position": "after",
        })

        assert "编辑成功" in result
        content = f.read_text(encoding="utf-8")
        assert "line2\ninserted\nline3" in content

    async def test_insert_before(self, tmp_path):
        """在锚点文本前插入内容"""
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "insert",
            "old_text": "line2",
            "insert_content": "inserted",
            "position": "before",
        })

        assert "编辑成功" in result
        content = f.read_text(encoding="utf-8")
        assert "line1\ninserted\nline2" in content

    async def test_insert_anchor_not_found(self, tmp_path):
        """锚点不存在时返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "insert",
            "old_text": "xyz",
            "insert_content": "new",
        })

        assert "未找到" in result

    async def test_insert_missing_content(self, tmp_path):
        """insert 模式未提供 insert_content 时返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "insert",
            "old_text": "hello",
        })

        assert "insert_content" in result

    # ── 通用异常路径 ──────────────────────────────────────────────────

    async def test_file_not_found(self):
        """文件不存在时返回错误"""
        result = await EditFileTool().execute({
            "path": "C:\\nonexistent\\file.txt",
            "mode": "search_replace",
            "old_text": "x",
            "new_text": "y",
        })

        assert "不存在" in result

    async def test_unknown_mode(self, tmp_path):
        """未知操作模式返回错误"""
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")

        result = await EditFileTool().execute({
            "path": str(f),
            "mode": "unknown_mode",
            "old_text": "hello",
        })

        assert "未知" in result


class TestShellToolExecute:
    """ShellTool.execute 的单元测试，mock subprocess.run 以避免实际执行命令."""

    # ── Windows pwsh 路径 ─────────────────────────────────────────────

    async def test_windows_uses_pwsh(self):
        """在 Windows (sys.platform == 'win32') 下应调用 pwsh -Command."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b"ok"
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "echo hello"})

            # 验证调用参数（bytes 模式，自适应解码）
            mock_run.assert_called_once_with(
                ["pwsh", "-NoProfile", "-Command", "echo hello"],
                capture_output=True,
                timeout=30,
            )
            assert result == "ok"

    async def test_windows_does_not_use_shell_true(self):
        """Windows 路径不应使用 shell=True."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            await ShellTool().execute({"command": "dir"})

            # 确保没传 shell=True
            args, kwargs = mock_run.call_args
            assert kwargs.get("shell") is not True

    # ── 非 Windows 路径 ───────────────────────────────────────────────

    async def test_non_windows_uses_shell_true(self):
        """非 Windows 平台应使用 shell=True + 字符串命令."""
        with (
            patch("tools.sys.platform", "linux"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b"ok"
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            await ShellTool().execute({"command": "ls -la"})

            mock_run.assert_called_once_with(
                "ls -la",
                shell=True,
                capture_output=True,
                timeout=30,
            )

    # ── 异常路径：超时 ────────────────────────────────────────────────

    async def test_timeout_expired(self):
        """subprocess.TimeoutExpired 应返回超时错误提示."""
        with patch("tools.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)

            result = await ShellTool().execute({"command": "sleep 100"})

            assert "超时" in result
            assert "30" in result

    # ── 异常路径：找不到 pwsh ─────────────────────────────────────────

    async def test_file_not_found(self):
        """FileNotFoundError 应返回找不到 pwsh 的错误提示."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = FileNotFoundError()

            result = await ShellTool().execute({"command": "Get-ChildItem"})

            assert "pwsh" in result or "PowerShell" in result

    # ── 通用异常路径 ─────────────────────────────────────────────────

    async def test_generic_exception(self):
        """其他异常应返回通用错误提示."""
        with patch("tools.subprocess.run") as mock_run:
            mock_run.side_effect = PermissionError("访问被拒绝")

            result = await ShellTool().execute({"command": "some_command"})

            assert "访问被拒绝" in result or "错误" in result

    # ── 输出拼接逻辑 ──────────────────────────────────────────────────

    async def test_stderr_appended(self):
        """stderr 有内容时应追加到输出."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b"stdout msg"
            mock_run.return_value.stderr = b"stderr msg"
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "echo test"})

            assert "stdout msg" in result
            assert "stderr msg" in result
            # stderr 直接拼接，不再加 [stderr] 标记

    async def test_nonzero_exit_code_appended(self):
        """非零退出码应追加 exit code 信息."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 1

            result = await ShellTool().execute({"command": "exit 1"})

            assert "exit code: 1" in result

    async def test_empty_output_shows_message(self):
        """无 stdout/stderr 且退出码为 0 时返回默认提示."""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "Write-Output ''"})

            assert "命令执行成功" in result

    # ── 自适应解码 ────────────────────────────────────────────────────

    async def test_utf8_output_decoded(self):
        """UTF-8 输出（officecli）解码正确"""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = "中文帮助".encode("utf-8")
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "officecli help"})

            assert "中文帮助" in result

    async def test_gbk_output_decoded(self):
        """GBK 输出（tvly/pwsh 中文环境）解码正确"""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = "中文输出".encode("gbk")
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "tvly search"})

            assert "中文输出" in result

    def test_decode_output_fallback_replace(self):
        """无法解码的字节不崩溃，回退替换符"""
        decoded = _decode_output(b"\xff\xfe\x00\x01")
        assert isinstance(decoded, str)