"""
上下文构建器 —— 拼装发送给 AI 的完整消息列表。

它的工作是：
1. 生成 system 消息（身份 + 技能 + 工具说明）
2. 把 system + 历史 + 当前用户消息拼成一个列表
3. 这个列表直接传给 Provider.generate()
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

        # 身份 + 环境
        parts.append(
            "# 身份\n"
            f"你是一个由liuxy创建的轻量的nanobot AI 助手。\n"
            f"# 运行环境:\n{_detect_environment()}\n"
        )

        # always 技能（完整正文）
        if self.skills:
            always_content = self.skills.load_always_skills_content()
            if always_content:
                parts.append(always_content)

        # 可用技能摘要
        if self.skills:
            always = set(self.skills.get_always_skills())
            summary = self.skills.build_summary(exclude=always)
            if summary:
                parts.append(
                    "# 技能"
                    "**使用任何技能前，必须先 read_file工具 加载对应 SKILL.md 文件**，当 skill（技能）文件里引用了相对路径时，要以skill 目录（即 `SKILL.md` 所在文件夹）作为基准路径做路径解析\n"
                    f"{summary}"
                )

        # 工具列表
        # if self.tool_names:
        #     parts.append(f"工具: {', '.join(self.tool_names)}")

        return "\n\n".join(parts)

    def build_messages(
        self,
        history: list[dict],
        current_message: str,
    ) -> list[dict]:
        """构建完整的消息列表"""
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": current_message})

        return messages
