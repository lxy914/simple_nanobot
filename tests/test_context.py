"""Tests for context.py —— 动态环境检测与 system prompt 集成."""

from unittest.mock import patch

from context import ContextBuilder, _detect_environment


# ── _detect_environment ────────────────────────────────────────────


class TestDetectEnvironment:
    """动态环境检测的单元测试（mock platform / shutil / os.environ）"""

    def test_windows_with_pwsh(self):
        """Windows 且安装了 pwsh：报告 pwsh"""
        with (
            patch("context.platform.system", return_value="Windows"),
            patch("context.shutil.which", return_value=r"C:\Program Files\PowerShell\7\pwsh.exe"),
        ):
            info = _detect_environment()

        assert "Windows" in info
        assert "pwsh" in info
        assert "cmd" not in info

    def test_windows_without_pwsh(self):
        """Windows 但未安装 pwsh：回退为 cmd"""
        with (
            patch("context.platform.system", return_value="Windows"),
            patch("context.shutil.which", return_value=None),
        ):
            info = _detect_environment()

        assert "cmd" in info

    def test_linux_reads_shell_env(self):
        """非 Windows：读取 SHELL 环境变量"""
        with (
            patch("context.platform.system", return_value="Linux"),
            patch.dict("os.environ", {"SHELL": "/bin/zsh"}),
        ):
            info = _detect_environment()

        assert "Linux" in info
        assert "/bin/zsh" in info

    def test_linux_without_shell_env(self):
        """非 Windows 且无 SHELL 环境变量：回退为 sh"""
        with (
            patch("context.platform.system", return_value="Linux"),
            patch.dict("os.environ", {}, clear=True),
        ):
            info = _detect_environment()

        assert "sh" in info

    def test_reports_working_directory(self):
        """输出包含当前的 Shell 信息"""
        with patch("context.platform.system", return_value="Windows"):
            info = _detect_environment()

        assert "操作系统" in info
        assert "Shell" in info


# ── system prompt 集成 ─────────────────────────────────────────────


class TestSystemPromptEnvironment:
    """system prompt 采用 XML 分节（identity / environment / skills）"""

    def test_prompt_contains_environment(self):
        """环境信息应出现在 <environment> 分节中"""
        prompt = ContextBuilder().build_system_prompt()

        assert "<identity>" in prompt
        assert "<environment>" in prompt
        assert "操作系统" in prompt
        assert "Shell" in prompt

    def test_prompt_xml_sections_closed(self):
        """XML 分节标签应成对闭合"""
        prompt = ContextBuilder().build_system_prompt()

        assert "</identity>" in prompt
        assert "</environment>" in prompt


class TestSystemPromptTools:
    """system prompt 的 <tools> 分节列出可调用工具"""

    def test_prompt_lists_available_tools(self):
        """传入 tool_names 时应输出 <tools> 分节"""
        prompt = ContextBuilder(tool_names=["shell", "read_file"]).build_system_prompt()

        assert "<tools>" in prompt
        assert "<tool>shell</tool>" in prompt
        assert "<tool>read_file</tool>" in prompt

    def test_prompt_omits_tools_when_none(self):
        """未传 tool_names 时不输出 <tools> 分节"""
        prompt = ContextBuilder().build_system_prompt()

        assert "<tools>" not in prompt
