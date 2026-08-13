"""
上下文构建器 —— 拼装发送给 AI 的完整消息列表。

它的工作是：
1. 生成 system 消息（身份 + 工具说明 + 技能摘要 + always 技能内容）
2. 把 system 消息 + 对话历史 + 当前用户消息拼成一个列表
3. 这个列表直接传给 Provider.generate()

system 消息的拼接顺序（用 --- 分隔）：
    1. 身份定义
    2. 始终激活的技能（完整 SKILL.md 正文）
    3. 可用技能摘要（名称 + 描述列表）
    4. 工具使用说明
"""

import os
import platform
import shutil
from pathlib import Path

from skills.skills_loader import SkillsLoader


def _detect_environment() -> str:
    """
    动态探测当前运行环境，生成环境描述。

    检测内容（与 ShellTool 的实际行为保持一致）：
    - 操作系统：Windows / Linux / Darwin
    - Shell：Windows 下检测 pwsh（ShellTool 用它执行命令）；
      其他系统读 SHELL 环境变量（ShellTool 用系统默认 shell）
    - 当前工作目录：文件操作类工具需要知道路径基准
    """
    os_name = platform.system()
    if os_name == "Windows":
        shell = "pwsh (PowerShell 7)" if shutil.which("pwsh") else "cmd"
    else:
        shell = os.environ.get("SHELL", "sh")

    return (
        f"操作系统: {os_name}\n"
        f"Shell: {shell}\n"
        f"当前工作目录: {Path.cwd()}"
    )


class ContextBuilder:
    """上下文构建器"""

    def __init__(self, skills_loader: SkillsLoader | None = None,
                 tool_names: list[str] | None = None):
        self.skills = skills_loader
        self.tool_names = tool_names or []

    def build_system_prompt(self) -> str:
        """生成 system 提示词"""
        parts = []

        # 第 1 段：身份定义
        parts.append(
            "你是一个简易的 AI 助手。\n"
            f"运行环境:\n{_detect_environment()}\n"
            "当用户需要查看文件、创建文件、执行操作时，请先调用相应工具。\n"
            "收到工具执行结果后，用中文总结结果告诉用户。"
        )

        # 第 2 段：始终激活的技能（完整正文）
        if self.skills:
            always_content = self.skills.load_always_skills_content()
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 第 3 段：可用技能摘要
        if self.skills:
            always = set(self.skills.get_always_skills())
            summary = self.skills.build_summary(exclude=always)
            if summary:
                parts.append(
                    "# Available Skills\n\n"
                    "以下技能可供使用，参考其指导来完成任务：\n\n"
                    f"{summary}\n\n"
                    "如需使用某个技能，请调用 load_skill 工具获取其完整内容。"
                )

        # 第 4 段：工具使用说明（从 ToolRegistry 动态生成）
        if self.tool_names:
            names = "\n".join(f"- {n}" for n in self.tool_names)
            parts.append(f"你可以使用以下工具：\n{names}")

        return "\n\n---\n\n".join(parts)

    def build_messages(
        self,
        history: list[dict],
        current_message: str,
    ) -> list[dict]:
        """
        构建完整的消息列表。

        参数：
        - history: 之前的对话历史，格式 [{"role": "user", "content": "..."}, ...]
        - current_message: 用户当前发送的消息文本

        返回：
        - 发给 AI 的完整消息列表
        """
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
        ]

        messages.extend(history)
        messages.append({"role": "user", "content": current_message})

        return messages
