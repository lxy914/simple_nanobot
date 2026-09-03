"""
技能加载器 —— 发现和加载 SKILL.md 文件。

极简实现（参考原版 nanobot 的 agent/skills.py 教学版）：
1. 扫描 skills/ 目录下所有 SKILL.md
2. 用正则提取 frontmatter 中的单行 name / description（不做完整 YAML 解析）
3. 生成 XML 技能摘要；正文由 AI 通过 read_file 按需读取（渐进式加载）

SKILL.md 约定（name / description 均为单行，不支持 YAML 多行块语法）：
    ---
    name: skill-name
    description: 技能功能描述
    ---
    正文内容...
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

# frontmatter 提取：开头的 --- 到独立一行的 ---（兼容 CRLF 换行）
_FRONTMATTER_RE = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)

# YAML 多行块/折叠块标记：本实现不支持，识别后视为无 description
_YAML_BLOCK_MARKERS = {"|", "|-", "|+", ">", ">-", ">+"}


class SkillsLoader:
    """技能加载器"""

    def __init__(self, skills_dir: Path):
        """
        参数：
        - skills_dir: skills/ 目录的路径
        """
        self._skills_dir = Path(skills_dir)
        self._skills: list[dict] = []
        self._scan()

    # ── 扫描与解析 ─────────────────────────────────────

    def _scan(self) -> None:
        """扫描 skills/ 目录下所有 SKILL.md，提取元数据"""
        if not self._skills_dir.exists():
            return

        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
            except Exception as e:
                print(f"[技能] 读取失败 {skill_file}: {e}")
                continue

            self._skills.append({
                # name / description 均以 SKILL.md frontmatter 为准，缺失时兜底为目录名
                "name": self._extract_field(content, "name", skill_dir.name),
                "description": self._extract_field(content, "description", skill_dir.name),
                # 统一正斜杠：location 会直接给 read_file 使用，跨平台一致
                "path": skill_file.as_posix(),
            })

    @staticmethod
    def _extract_field(content: str, key: str, fallback: str) -> str:
        """
        从 frontmatter 提取单行字段值（自动去除引号）。

        无 frontmatter、字段缺失、或值为多行块标记时，
        兜底返回 fallback（目录名）。
        """
        match = _FRONTMATTER_RE.match(content)
        if match:
            field = re.search(rf"^{key}\s*:\s*(.+?)\s*$", match.group(1), re.MULTILINE)
            if field:
                value = field.group(1).strip().strip("\"'")
                if value not in _YAML_BLOCK_MARKERS:
                    return value
        return fallback

    # ── 公共接口 ───────────────────────────────────────

    def list_skills(self) -> list[dict]:
        """返回所有技能的元数据列表 [{name, description, path}]"""
        return [dict(skill) for skill in self._skills]

    def build_skills_summary(self) -> str:
        """
        生成技能摘要（XML 格式），没有技能时返回空字符串。

        <skills>
          <skill>
            <name>officecli</name>
            <description>处理 Office 文档</description>
            <location>C:/.../skills/officecli/SKILL.md</location>
          </skill>
        </skills>

        location 是 SKILL.md 的绝对路径，可直接传给 read_file
        读取完整正文（渐进式加载）。
        """
        if not self._skills:
            return ""

        lines = ["<skills>"]
        for skill in self._skills:
            lines.append("  <skill>")
            lines.append(f'    <name>{escape(skill["name"])}</name>')
            lines.append(f'    <description>{escape(skill["description"])}</description>')
            lines.append(f'    <location>{escape(skill["path"])}</location>')
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)
