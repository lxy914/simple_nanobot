"""
调试辅助测试 —— 打印项目实际使用的系统提示词。

用法：
    uv run pytest tests/test_system_prompt.py -s    # 打印到控制台
    uv run pytest tests/test_system_prompt.py       # 不打印，但写入文件

提示词全文会保存到 tests/output/system_prompt.txt，方便在编辑器中查看。
"""

from pathlib import Path

from context import ContextBuilder
from skills_loader import SkillsLoader
from tools import (EditFileTool, ListDirTool, ReadFileTool,
                   ShellTool, ToolRegistry, WriteFileTool)

# 项目根目录（tests/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
OUTPUT_FILE = PROJECT_ROOT / "tests" / "output" / "system_prompt.txt"


def _build_real_context_builder() -> ContextBuilder:
    """按 main.py 的方式构建真实的 ContextBuilder（真实技能 + 全部工具）"""
    tools = ToolRegistry()
    tools.register(ShellTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())
    tools.register(ListDirTool())

    skills_loader = SkillsLoader(SKILLS_DIR)
    return ContextBuilder(
        skills_loader=skills_loader,
        tool_names=tools.tool_names(),
    )


def test_print_system_prompt():
    """构建系统提示词，打印并保存到文件"""
    builder = _build_real_context_builder()
    prompt = builder.build_system_prompt()

    # 断言非空，确保提示词确实被构建出来
    assert prompt

    # 保存到文件，方便在编辑器中查看完整内容
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(prompt, encoding="utf-8")

    print("\n" + "=" * 60)
    print("系统提示词（已保存到 tests/output/system_prompt.txt）：")
    print("=" * 60)
    print(prompt)
    print("=" * 60)


def test_print_full_messages():
    """打印发给 AI 的完整消息列表（system + 历史 + 当前消息）"""
    builder = _build_real_context_builder()
    messages = builder.build_messages(
        history=[
            {"role": "user", "content": "帮我看看当前目录"},
            {"role": "assistant", "content": "好的，我先查看一下目录内容。"},
        ],
        current_message="继续",
    )

    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "继续"}

    print("\n" + "=" * 60)
    print(f"完整消息列表（共 {len(messages)} 条）：")
    print("=" * 60)
    for i, msg in enumerate(messages):
        print(f"\n── 第 {i + 1} 条 [{msg['role']}] ──")
        print(msg["content"])
    print("\n" + "=" * 60)
