"""
技能加载工具 —— 让 AI 按需获取技能完整内容。

普通技能在 system prompt 中只展示名称和描述，
AI 决定使用某个技能时，调用本工具的 load_skill 获取 SKILL.md 正文。
技能文件的路径对 AI 透明，无需暴露在提示词中。
"""

from skills.skills_loader import SkillsLoader
from tools import Tool


class LoadSkillTool(Tool):
    """加载技能完整内容的工具"""

    name = "load_skill"
    description = (
        "加载指定技能的完整操作指南。"
        "技能列表见 system prompt 中的 Available Skills，"
        "当用户的需求与某技能相关时，先调用本工具获取该技能的完整内容。"
    )

    def __init__(self, skills_loader: SkillsLoader):
        self._loader = skills_loader

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要加载的技能名称（见 system prompt 中的 Available Skills 列表）",
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        name = args.get("name", "")
        if not name:
            return "错误：请提供要加载的技能名称（name 参数）"

        content = self._loader.load_skill_content(name)
        if content is None:
            available = self._loader.build_summary() or "(暂无可用技能)"
            return f"错误：未找到技能 '{name}'。可用技能：\n{available}"

        # 开头标注内容大小，让 AI 对上下文占用有感知
        return f"技能 '{name}' 内容（共 {len(content)} 字符）：\n\n{content}"
