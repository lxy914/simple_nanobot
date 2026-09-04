"""Tests for storage.py —— SessionStorage 持久化单元测试."""

import json
from pathlib import Path

from storage import SessionStorage


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """save 后 load 应还原相同内容"""
    storage = SessionStorage(tmp_path)
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你？"},
    ]

    storage.save("cli:default", messages)

    assert storage.load("cli:default") == messages


def test_load_missing_session_returns_empty(tmp_path: Path) -> None:
    """不存在的 session_key → 空列表"""
    storage = SessionStorage(tmp_path)

    assert storage.load("cli:default") == []


def test_special_chars_in_session_key(tmp_path: Path) -> None:
    """session_key 中的冒号等非法字符应替换为下划线（Windows 文件名安全）"""
    storage = SessionStorage(tmp_path)
    messages = [{"role": "user", "content": "hi"}]

    storage.save("cli:default", messages)

    # 文件名不含冒号
    files = [f.name for f in tmp_path.iterdir()]
    assert files == ["cli_default.json"]
    assert storage.load("cli:default") == messages


def test_load_corrupted_json_returns_empty(tmp_path: Path) -> None:
    """损坏的 JSON 文件 → 返回空列表，不抛异常"""
    storage = SessionStorage(tmp_path)
    target = tmp_path / "cli_default.json"
    target.write_text("{not valid json", encoding="utf-8")

    assert storage.load("cli:default") == []


def test_load_non_list_json_returns_empty(tmp_path: Path) -> None:
    """JSON 内容不是列表（如对象）→ 返回空列表"""
    storage = SessionStorage(tmp_path)
    target = tmp_path / "cli_default.json"
    target.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    assert storage.load("cli:default") == []


def test_save_leaves_no_tmp_file(tmp_path: Path) -> None:
    """原子写完成后目录中不应残留 .tmp 文件"""
    storage = SessionStorage(tmp_path)

    storage.save("cli:default", [{"role": "user", "content": "hi"}])

    files = [f.name for f in tmp_path.iterdir()]
    assert files == ["cli_default.json"]
    assert not (tmp_path / "cli_default.tmp").exists()


def test_save_overwrites_existing(tmp_path: Path) -> None:
    """重复 save 应覆盖旧内容（全量写语义）"""
    storage = SessionStorage(tmp_path)

    storage.save("cli:default", [{"role": "user", "content": "第一轮"}])
    storage.save("cli:default", [
        {"role": "user", "content": "第一轮"},
        {"role": "user", "content": "第二轮"},
    ])

    loaded = storage.load("cli:default")
    assert len(loaded) == 2
    assert loaded[-1]["content"] == "第二轮"
