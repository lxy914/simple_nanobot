"""Tests for tools.py —— ShellTool.execute 的 mock 单元测试."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from tools import ShellTool, _decode_output


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

            # 验证调用参数（bytes 模式，不依赖 locale 编码）
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
            assert "[stderr]" in result
            assert "stderr msg" in result

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

    # ── 输出解码 ──────────────────────────────────────────────────────

    async def test_utf8_output_decoded(self):
        """UTF-8 输出（officecli 等）应正确解码"""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = "中文帮助信息".encode("utf-8")
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "officecli help"})

            assert "中文帮助信息" in result

    async def test_gbk_output_decoded(self):
        """GBK 输出（pwsh 中文 Windows 默认）应正确解码"""
        with (
            patch("tools.sys.platform", "win32"),
            patch("tools.subprocess.run") as mock_run,
        ):
            mock_run.return_value.stdout = "中文输出".encode("gbk")
            mock_run.return_value.stderr = b""
            mock_run.return_value.returncode = 0

            result = await ShellTool().execute({"command": "Write-Output '测试'"})

            assert "中文输出" in result

    def test_decode_output_fallback_replace(self):
        """无法解码的字节流不应崩溃，回退替换符"""
        decoded = _decode_output(b"\xff\xfe\x00\x01")
        assert isinstance(decoded, str)