"""Tests for skills_loader.SkillsLoader."""

from pathlib import Path

from skills_loader import SkillsLoader


# ── helpers ────────────────────────────────────────────────────────


def _make_skill(directory: Path, name: str, *, description: str = "",
                body: str = "") -> Path:
    """Create directory/name/SKILL.md with a single-line description frontmatter."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if description:
        lines.append(f"description: {description}")
    lines.append("---")
    if body:
        lines.append(body)
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _raw_skill(directory: Path, subdir_name: str, content: str) -> Path:
    """Write a SKILL.md with raw content (no parsing assumptions)."""
    skill_dir = directory / subdir_name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── 扫描 ───────────────────────────────────────────────────────────


def test_empty_when_directory_missing(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path / "no_such_dir")
    assert loader.list_skills() == []
    assert loader.build_skills_summary() == ""


def test_empty_when_directory_exists_but_empty(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    assert loader.list_skills() == []


def test_skips_non_directories_and_missing_skill_md(tmp_path: Path) -> None:
    (tmp_path / "not_a_dir.txt").write_text("x", encoding="utf-8")
    (tmp_path / "no_skill_md").mkdir()
    _make_skill(tmp_path, "ok", description="唯一")

    loader = SkillsLoader(tmp_path)
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "ok"
    assert skills[0]["description"] == "唯一"


def test_single_skill_metadata(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", description="技能A", body="# Alpha body")

    loader = SkillsLoader(tmp_path)
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "alpha"
    assert skills[0]["description"] == "技能A"
    # path 指向 SKILL.md 文件本身
    assert Path(skills[0]["path"]).name == "SKILL.md"
    assert Path(skills[0]["path"]).parent.name == "alpha"


def test_name_reads_from_frontmatter(tmp_path: Path) -> None:
    """name 从 SKILL.md frontmatter 读取，而非目录名"""
    _raw_skill(tmp_path, "mydir",
               "---\nname: other-name\ndescription: X\n---\nBody")

    loader = SkillsLoader(tmp_path)
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0]["name"] == "other-name"
    # location 仍指向技能实际所在目录
    assert "mydir/SKILL.md" in skills[0]["path"]


def test_name_fallback_to_dir_name_when_missing(tmp_path: Path) -> None:
    """frontmatter 缺 name 字段 → 名称兜底为目录名"""
    _raw_skill(tmp_path, "unnamed", "---\ndescription: X\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["name"] == "unnamed"


def test_multiple_skills_sorted(tmp_path: Path) -> None:
    _make_skill(tmp_path, "beta", description="B")
    _make_skill(tmp_path, "alpha", description="A")

    loader = SkillsLoader(tmp_path)
    assert [s["name"] for s in loader.list_skills()] == ["alpha", "beta"]


# ── description 提取 ───────────────────────────────────────────────


def test_description_fallback_when_missing(tmp_path: Path) -> None:
    """有 frontmatter 但缺 description → 描述兜底为目录名"""
    _raw_skill(tmp_path, "nodesc", "---\nname: nodesc\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["description"] == "nodesc"


def test_description_fallback_when_no_frontmatter(tmp_path: Path) -> None:
    """无 frontmatter → 描述兜底为目录名"""
    _raw_skill(tmp_path, "raw", "# Just body")

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["description"] == "raw"


def test_quoted_description_unquoted(tmp_path: Path) -> None:
    """带引号的 description 应去除首尾引号"""
    _raw_skill(tmp_path, "q",
               '---\ndescription: "引号内的描述"\n---\nBody')

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["description"] == "引号内的描述"


def test_description_keeps_inner_colons(tmp_path: Path) -> None:
    """description 内含冒号不应截断"""
    _raw_skill(tmp_path, "colon",
               "---\ndescription: 注意: 这是说明\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["description"] == "注意: 这是说明"


def test_yaml_block_marker_falls_back(tmp_path: Path) -> None:
    """YAML 多行块（|）语法不支持：值仅为块标记时兜底为目录名"""
    _raw_skill(tmp_path, "multi",
               "---\ndescription: |\n  第一行描述\n  第二行描述\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.list_skills()[0]["description"] == "multi"


# ── XML 摘要 ───────────────────────────────────────────────────────


def test_build_skills_summary_xml_structure(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", description="技能A")
    _make_skill(tmp_path, "beta", description="技能B")

    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary()

    assert summary.startswith("<skills>")
    assert summary.endswith("</skills>")
    assert "<name>alpha</name>" in summary
    assert "<description>技能A</description>" in summary
    assert "<name>beta</name>" in summary


def test_build_skills_summary_includes_location(tmp_path: Path) -> None:
    """location 应包含 SKILL.md 绝对路径，AI 可直接传给 read_file"""
    _make_skill(tmp_path, "tavily", description="搜索")

    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary()

    assert "<location>" in summary
    assert "tavily/SKILL.md" in summary
    assert tmp_path.as_posix() in summary


def test_build_skills_summary_escapes_xml_special_chars(tmp_path: Path) -> None:
    """描述中的 XML 特殊字符（& < >）应被转义，避免破坏 XML 结构"""
    _raw_skill(tmp_path, "esc",
               '---\ndescription: "a & b <tag> > c"\n---\nBody')

    loader = SkillsLoader(tmp_path)
    summary = loader.build_skills_summary()

    assert "&amp;" in summary
    assert "&lt;" in summary
    assert "&gt;" in summary
    assert "a & b" not in summary


# ── list_skills 快照 ───────────────────────────────────────────────


def test_list_skills_returns_snapshot(tmp_path: Path) -> None:
    """修改返回的列表不应影响加载器内部状态"""
    _make_skill(tmp_path, "a", description="A")

    loader = SkillsLoader(tmp_path)
    skills = loader.list_skills()
    skills.clear()

    assert len(loader.list_skills()) == 1
