"""
技能加载器 —— 发现和加载 SKILL.md 文件。

简化自原版 nanobot/agent/skills.py，保留了核心功能：
1. 扫描 skills/ 目录下的所有 SKILL.md 文件
2. 解析 YAML frontmatter（name, description, always）
3. 区分"始终激活"技能和普通技能
4. 生成技能摘要（名称 + 描述）

目录结构：
    skills/
    ├── memory/SKILL.md          # always: true → 每次会话都加载完整内容
    ├── summarize/SKILL.md       # 普通技能 → 仅在摘要中列出
    └── file-ops/SKILL.md        # 普通技能 → 仅在摘要中列出
"""

import re
from pathlib import Path


class SkillsLoader:
    """技能加载器"""

    def __init__(self, skills_dir: Path):
        """
        参数：
        - skills_dir: skills/ 目录的路径
        """
        self._skills_dir = Path(skills_dir)
        self._skills: dict[str, dict] = {}
        self._scan()

    # ── 扫描与解析 ─────────────────────────────────────

    def _scan(self) -> None:
        """扫描 skills/ 目录下所有的 SKILL.md，解析 frontmatter"""
        if not self._skills_dir.exists():
            return

        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                raw = skill_file.read_text(encoding="utf-8")
                meta = self._parse_frontmatter(raw)
                meta["path"] = str(skill_file)
                self._skills[meta.get("name", skill_dir.name)] = meta
            except Exception as e:
                print(f"[技能] 解析失败 {skill_file}: {e}")

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """
        解析 YAML frontmatter。

        SKILL.md 格式：
            ---
            name: memory
            description: 记忆系统
            always: true
            ---
            正文内容...
        """
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not match:
            return {"content": content}

        frontmatter_text = match.group(1)
        body = content[match.end():].strip()

        meta = {"content": body}

        for line in frontmatter_text.strip().split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # 布尔值转换
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                meta[key] = value

        return meta

    # ── 公共接口 ───────────────────────────────────────

    def get_always_skills(self) -> list[str]:
        """返回所有标记为 always: true 的技能名称列表"""
        return [
            name for name, meta in self._skills.items()
            if meta.get("always") is True
        ]

    def load_skill_content(self, name: str) -> str | None:
        """加载单个技能的正文内容（去除 frontmatter）"""
        meta = self._skills.get(name)
        if meta is None:
            return None
        return meta.get("content", "")

    def load_always_skills_content(self) -> str:
        """
        加载所有 always 技能的正文，用分隔线拼接。

        返回格式：
            # memory
            正文内容...

            ---

            # another-skill
            正文内容...
        """
        parts = []
        for name in self.get_always_skills():
            content = self.load_skill_content(name)
            if content:
                parts.append(f"# {name}\n\n{content}")

        return "\n\n---\n\n".join(parts)

    def build_summary(self, exclude: set[str] | None = None) -> str:
        """
        生成所有技能的摘要（名称 + 描述）。

        格式：
            - **memory** — 记忆系统 (始终激活)
            - **summarize** — 总结长文本
            - **file-ops** — 文件操作

        排除列表中的技能不会出现在摘要中。
        """
        exclude = exclude or set()
        lines = []

        for name, meta in self._skills.items():
            if name in exclude:
                continue
            desc = meta.get("description", "")
            tag = " (始终激活)" if meta.get("always") else ""
            lines.append(f"- **{name}** — {desc}{tag}")

        return "\n".join(lines) if lines else ""

    @property
    def skill_count(self) -> int:
        """已发现技能数"""
        return len(self._skills)
