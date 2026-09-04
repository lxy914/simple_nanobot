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

from skills_loader import SkillsLoader


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
        """生成 system 提示词（统一为 XML 分节）"""
        parts: list[str] = []

        # 身份
        parts.append(
            "<identity>\n"
            "你是一个由liuxy创建的轻量的nanobot AI 助手。\n"
            "</identity>"
        )

        # 运行环境
        parts.append(
            f"<environment>\n{_detect_environment()}</environment>"
        )

        # 可用工具（仅这些名字可被 tool call 调用，技能不在此列）
        if self.tool_names:
            tools_xml = "\n".join(
                f"  <tool>{name}</tool>" for name in self.tool_names
            )
            parts.append(f"<tools>\n{tools_xml}\n</tools>")

        # 技能：使用准则 + XML 摘要（渐进式加载：正文由 AI 用 read_file 按需读取）
        if self.skills:
            summary = self.skills.build_skills_summary()
            if summary:
                parts.append(
                    "<skill-guidelines>\n"
                    "以下技能扩展了你的能力，使用技能的标准流程：\n"
                    "1. 在 <skills> 中选择匹配的技能；\n"
                    "2. 用 read_file 工具读取 <location> 指向的 SKILL.md 文件正文；\n"
                    "3. 严格按正文中的说明执行（命令、参数与步骤均以正文为准）。\n"
                    "禁止事项：\n"
                    "- <skills> 中的条目是技能，不是可调用的工具，禁止直接调用技能名；\n"
                    "- 技能名不代表系统里有同名命令，禁止在读取 SKILL.md 正文前猜测或执行与技能相关的任何命令。\n"
                    "当 SKILL.md 文件里引用了相对路径时，要以 skill 目录"
                    "（即 SKILL.md 所在文件夹）作为基准路径做路径解析。\n"
                    "</skill-guidelines>"
                )
                parts.append(summary)

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
