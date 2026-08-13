"""Tests for skills.load_skill_tool.LoadSkillTool."""

from pathlib import Path

from skills.load_skill_tool import LoadSkillTool
from skills.skills_loader import SkillsLoader
from tools import ToolRegistry


# ── helpers ────────────────────────────────────────────────────────


def _make_skill(directory: Path, name: str, *, description: str = "", body: str = "",
                always: bool = False) -> Path:
    """Create directory/name/SKILL.md with YAML frontmatter."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    lines.append(f"name: {name}")
    if description:
        lines.append(f'description: "{description}"')
    lines.append(f"always: {str(always).lower()}")
    lines.append("---")
    if body:
        lines.append(body)
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _make_tool(tmp_path: Path) -> LoadSkillTool:
    """用临时目录构建 SkillsLoader 并注入 LoadSkillTool"""
    return LoadSkillTool(SkillsLoader(tmp_path))


# ── execute：成功路径 ─────────────────────────────────────────────


class TestLoadSkillToolExecute:
    """LoadSkillTool.execute 的单元测试"""

    async def test_loads_normal_skill_body(self, tmp_path):
        """普通技能：返回 SKILL.md 正文（不含 frontmatter）"""
        _make_skill(tmp_path, "tavily", description="搜索",
                    body="# 使用说明\n运行 tvly search 命令")

        result = await _make_tool(tmp_path).execute({"name": "tavily"})

        assert "使用说明" in result
        assert "tvly search" in result
        # frontmatter 不应出现在返回内容中
        assert "always" not in result

    async def test_loads_always_skill(self, tmp_path):
        """always 技能同样可以通过 load_skill 加载"""
        _make_skill(tmp_path, "mem", always=True, body="# 记忆正文")

        result = await _make_tool(tmp_path).execute({"name": "mem"})

        assert "记忆正文" in result

    async def test_result_annotates_content_size(self, tmp_path):
        """返回内容开头应标注字符数，让 AI 感知上下文占用"""
        _make_skill(tmp_path, "alpha", body="短正文")

        result = await _make_tool(tmp_path).execute({"name": "alpha"})

        assert "共 3 字符" in result
        assert "短正文" in result

    # ── execute：异常路径 ─────────────────────────────────────────

    async def test_unknown_skill_returns_error_with_available_list(self, tmp_path):
        """不存在的技能：返回错误并附带可用技能列表"""
        _make_skill(tmp_path, "known", description="已知技能", body="body")

        result = await _make_tool(tmp_path).execute({"name": "nope"})

        assert "未找到技能" in result
        assert "known" in result

    async def test_unknown_skill_with_empty_skills_dir(self, tmp_path):
        """技能目录为空时：错误信息提示暂无可用技能"""
        result = await _make_tool(tmp_path).execute({"name": "anything"})

        assert "未找到技能" in result
        assert "暂无可用技能" in result

    async def test_missing_name_argument(self, tmp_path):
        """缺少 name 参数：返回错误提示"""
        result = await _make_tool(tmp_path).execute({})

        assert "错误" in result
        assert "name" in result


# ── 工具定义与注册 ────────────────────────────────────────────────


class TestLoadSkillToolDefinition:
    """工具定义与 ToolRegistry 集成"""

    async def test_get_definition_declares_required_name(self, tmp_path):
        """JSON Schema 声明 name 为必填参数"""
        definition = _make_tool(tmp_path).get_definition()
        func = definition["function"]

        assert func["name"] == "load_skill"
        assert "name" in func["parameters"]["required"]
        assert func["description"]

    async def test_registered_in_registry(self, tmp_path):
        """注册到 ToolRegistry 后可被查询和获取定义"""
        tool = _make_tool(tmp_path)
        registry = ToolRegistry()
        registry.register(tool)

        assert registry.get("load_skill") is tool
        assert "load_skill" in registry.tool_names()
        assert any(
            d["function"]["name"] == "load_skill"
            for d in registry.get_definitions()
        )

    async def test_execute_through_registry(self, tmp_path):
        """通过 ToolRegistry.execute 执行 load_skill"""
        _make_skill(tmp_path, "alpha", body="# Alpha body")
        registry = ToolRegistry()
        registry.register(_make_tool(tmp_path))

        result = await registry.execute("load_skill", {"name": "alpha"})

        assert "# Alpha body" in result
