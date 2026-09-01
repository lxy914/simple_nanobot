"""
技能加载器 —— 发现和加载 SKILL.md 文件。

机制对齐原版 nanobot（HKUDS/nanobot 的 nanobot/agent/skills.py）：
1. 标准 YAML 解析 frontmatter（yaml.safe_load，支持多行块、嵌套结构）
2. 技能身份契约：name 必须与目录名一致且匹配 [a-z0-9-] 格式
3. 渐进式加载：摘要只含名称 + 描述 + 相对路径，AI 用 read_file 读取完整内容

目录结构：
    skills/
    ├── memory/SKILL.md          # always: true → 每次会话都加载完整内容
    ├── summarize/SKILL.md       # 普通技能 → 仅在摘要中列出
    └── file-ops/SKILL.md        # 普通技能 → 仅在摘要中列出
"""

import re
from pathlib import Path

import yaml

# frontmatter 提取：开头的 --- 到独立一行的 ---（兼容 CRLF 换行）
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)

# 技能名身份契约：小写字母/数字开头结尾，中间可含连字符（不允许连续 --）
_SKILL_NAME = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

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
                meta = self._parse_skill(raw, skill_dir.name)
            except Exception as e:
                print(f"[技能] 解析失败 {skill_file}: {e}")
                continue

            if meta is None:
                continue

            meta["path"] = str(skill_file)
            self._skills[meta["name"]] = meta

    @staticmethod
    def _parse_skill(content: str, dir_name: str) -> dict | None:
        """
        解析单个 SKILL.md → 元数据字典；不满足身份契约时返回 None。

        SKILL.md 格式：
            ---
            name: memory
            description: 记忆系统
            always: true
            ---
            正文内容...
        """
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            # 无 frontmatter：按无元数据技能处理（描述兜底为技能名）
            return {"name": dir_name, "description": dir_name, "content": content}

        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            print(f"[技能] frontmatter YAML 解析失败: {e}")
            return None

        if not isinstance(frontmatter, dict):
            return None

        name = frontmatter.get("name", dir_name)
        # 身份契约：name 必须与目录名一致，且格式合法
        if name != dir_name or not _SKILL_NAME.fullmatch(name) or len(name) > 64:
            print(f"[技能] 跳过 {dir_name}: name 与目录名不一致或格式非法 ('{name}')")
            return None

        description = frontmatter.get("description")
        if not isinstance(description, str) or not description.strip():
            description = dir_name  # 兜底：用技能名作为描述

        return {
            "name": name,
            "description": description.strip(),
            "always": frontmatter.get("always") is True,
            "content": content[match.end():].strip(),
        }

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
            ### Skill: memory
            正文内容...

            ---

            ### Skill: another-skill
            正文内容...
        """
        return self.load_skills_for_context(self.get_always_skills())

    def load_skills_for_context(self, names: list[str]) -> str:
        """加载多个技能的正文，拼接为上下文块（用于 always 技能）"""
        parts = []
        for name in names:
            content = self.load_skill_content(name)
            if content:
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts)

    def build_summary(self, exclude: set[str] | None = None) -> str:
        """
        生成所有技能的摘要（名称 + 描述 + 绝对路径）。

        格式：
            - **memory** — 记忆系统  `C:/.../skills/memory/SKILL.md`
            - **summarize** — 总结长文本  `C:/.../skills/summarize/SKILL.md`

        绝对路径可直接传给 read_file 读取完整内容（渐进式加载）。

        排除列表中的技能不会出现在摘要中。
        """
        exclude = exclude or set()
        lines = []

        for name, meta in self._skills.items():
            if name in exclude:
                continue
            desc = meta.get("description") or name
            path = Path(meta["path"]).as_posix()
            lines.append(f"- **{name}** — {desc}  `{path}`")

        return "\n".join(lines) if lines else ""

    @property
    def skill_count(self) -> int:
        """已发现技能数"""
        return len(self._skills)
