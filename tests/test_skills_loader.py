"""Tests for skills.skills_loader.SkillsLoader."""

from pathlib import Path

from skills.skills_loader import SkillsLoader


# ── helpers ────────────────────────────────────────────────────────


def _make_skill(directory: Path, name: str, *, description: str = "", body: str = "",
                always: bool = False) -> Path:
    """Create directory/name/SKILL.md with YAML frontmatter."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if name:
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


def _raw_skill(directory: Path, subdir_name: str, content: str) -> Path:
    """Write a SKILL.md with raw content (no parsing assumptions)."""
    skill_dir = directory / subdir_name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── scan & top-level ───────────────────────────────────────────────


def test_empty_when_directory_missing(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path / "no_such_dir")
    assert loader.skill_count == 0
    assert loader.get_always_skills() == []
    assert loader.build_summary() == ""
    assert loader.load_always_skills_content() == ""


def test_empty_when_directory_exists_but_empty(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 0
    assert loader.get_always_skills() == []


def test_skips_non_directories_and_missing_skill_md(tmp_path: Path) -> None:
    (tmp_path / "not_a_dir.txt").write_text("x", encoding="utf-8")
    (tmp_path / "no_skill_md").mkdir()
    _make_skill(tmp_path, "ok", description="唯一")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert "ok" in loader.build_summary()


def test_single_skill_basic_attrs(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", description="技能A", body="# Alpha body",
                always=True)

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert loader.get_always_skills() == ["alpha"]

    summary = loader.build_summary()
    assert "alpha" in summary
    assert "技能A" in summary


def test_multiple_skills_distinction(tmp_path: Path) -> None:
    _make_skill(tmp_path, "always1", always=True, description="始终1",
                body="# Always one")
    _make_skill(tmp_path, "always2", always=True, description="始终2",
                body="# Always two")
    _make_skill(tmp_path, "normal", always=False, description="普通技能",
                body="# Normal")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 3
    assert sorted(loader.get_always_skills()) == ["always1", "always2"]


# ── load_always_skills_content ─────────────────────────────────────


def test_load_always_skills_content_single(tmp_path: Path) -> None:
    _make_skill(tmp_path, "mem", always=True, body="# 记忆系统\n回顾对话历史")

    loader = SkillsLoader(tmp_path)
    content = loader.load_always_skills_content()
    assert "# mem" in content
    assert "回顾对话历史" in content


def test_load_always_skills_content_multiple(tmp_path: Path) -> None:
    _make_skill(tmp_path, "a", always=True, body="AAA body")
    _make_skill(tmp_path, "b", always=True, body="BBB body")

    loader = SkillsLoader(tmp_path)
    content = loader.load_always_skills_content()
    assert "# a" in content
    assert "AAA body" in content
    assert "---" in content
    assert "# b" in content
    assert "BBB body" in content


def test_load_always_skills_content_skips_non_always(tmp_path: Path) -> None:
    _make_skill(tmp_path, "always", always=True, body="Always")
    _make_skill(tmp_path, "normal", always=False, body="Normal")

    loader = SkillsLoader(tmp_path)
    content = loader.load_always_skills_content()
    assert "Always" in content
    assert "Normal" not in content


# ── build_summary ──────────────────────────────────────────────────


def test_build_summary_includes_always_tag(tmp_path: Path) -> None:
    _make_skill(tmp_path, "s1", always=True, description="始终活跃")
    _make_skill(tmp_path, "s2", always=False, description="可选")

    loader = SkillsLoader(tmp_path)
    summary = loader.build_summary()
    assert "(始终激活)" in summary


def test_build_summary_respects_exclude(tmp_path: Path) -> None:
    _make_skill(tmp_path, "a", always=True, description="A")
    _make_skill(tmp_path, "b", always=False, description="B")
    _make_skill(tmp_path, "c", always=False, description="C")

    loader = SkillsLoader(tmp_path)
    summary_with_exclude = loader.build_summary(exclude={"a", "b"})
    assert "a" not in summary_with_exclude
    assert "b" not in summary_with_exclude
    assert "c" in summary_with_exclude


def test_build_summary_empty_when_no_skills(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    assert loader.build_summary() == ""


# ── load_skill_content ─────────────────────────────────────────────


def test_load_skill_content_returns_body(tmp_path: Path) -> None:
    _make_skill(tmp_path, "test", body="# Title\nBody text\n\nMore")

    loader = SkillsLoader(tmp_path)
    assert loader.load_skill_content("test") == "# Title\nBody text\n\nMore"


def test_load_skill_content_none_for_missing(tmp_path: Path) -> None:
    loader = SkillsLoader(tmp_path)
    assert loader.load_skill_content("nope") is None


# ── frontmatter edge cases ─────────────────────────────────────────


def test_no_frontmatter_at_all(tmp_path: Path) -> None:
    _raw_skill(tmp_path, "raw", "# Just body\nno frontmatter here")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    meta = loader._skills.get("raw", {})
    assert meta.get("always") is None


def test_empty_body_after_frontmatter(tmp_path: Path) -> None:
    _raw_skill(tmp_path, "bare", "---\nname: bare\nalways: false\n---\n")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert loader.load_skill_content("bare") == ""


def test_quoted_description(tmp_path: Path) -> None:
    _raw_skill(tmp_path, "q",
               '---\nname: q\ndescription: "引号内的描述"\nalways: true\n---\nBody')

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert "引号内的描述" in loader.build_summary()


def test_skill_without_name_uses_dir_name(tmp_path: Path) -> None:
    _raw_skill(tmp_path, "unnamed", "---\ndescription: 我无名\nalways: false\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert "unnamed" in loader.build_summary()


def test_frontmatter_with_comments_skipped(tmp_path: Path) -> None:
    _raw_skill(tmp_path, "commented",
               "---\n# 这是注释\nname: commented\nalways: false\n---\nBody")

    loader = SkillsLoader(tmp_path)
    assert loader.skill_count == 1
    assert loader._skills["commented"]["always"] is False
