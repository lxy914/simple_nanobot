"""
工具系统 —— AI 可以调用的"能力"。

每个工具是一个 Tool 子类，需要实现：
1. get_definition() → 返回 JSON Schema，告诉 AI"有这个工具、参数长这样"
2. execute(args)    → 真正执行工具逻辑，返回结果

ToolRegistry 是工具箱，用字典管理所有工具：
    {"shell": ShellTool, "read_file": ReadFileTool, ...}
"""

import asyncio
import subprocess
import sys
from pathlib import Path
from abc import ABC, abstractmethod


class Tool(ABC):
    """
    工具的抽象基类。

    每个工具必须有一个唯一的 name（工具名）和 description（描述）。
    AI 会看到所有工具的 name + description，然后决定调用哪个。
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def get_definition(self) -> dict:
        """
        返回这个工具的 JSON Schema 定义。

        这个定义会发给 AI，告诉它：
        - 这个工具叫什么名字
        - 它的功能是什么
        - 它接受哪些参数、每个参数的类型和含义

        AI 看到这些定义后，就能决定"我该用哪个工具、传什么参数"。
        """
        raise NotImplementedError

    @abstractmethod
    async def execute(self, args: dict) -> str:
        """
        执行工具逻辑。

        args 是 AI 传过来的参数，格式和 get_definition() 中声明的参数一致。
        返回字符串结果（会追加到对话中发给 AI）。
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# ShellTool —— 执行命令
#
# 这是精简版中唯一的工具，功能是执行 shell 命令并返回结果。
# 实际上 nanobot 的 shell 工具更复杂（支持沙箱、超时等），
# 这里做了最大简化。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------


def _decode_output(data: bytes) -> str:
    """\n    自适应解码子进程输出。

    Windows 没有统一的管道编码标准。不同 CLI 输出不同的编码：
    - officecli（Rust CLI）→ UTF-8
    - pwsh cmdlet（Write-Output 等） → GBK（中文系统默认）
    - tvly（外部原生程序） → GBK（中文系统代码页）

    先严格试 UTF-8（原生 UTF-8 工具不走弯路），
    不行再试 GBK（中文 Windows 最通用），
    最后 replace 兜底保证永不崩溃。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class ShellTool(Tool):
    """执行 shell 命令的工具"""

    name = "shell"
    description = "在终端执行 shell 命令，返回 stdout 和 stderr"

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的shell命令",
                        },
                    },
                    "required": ["command"],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        command = args.get("command", "")

        def _run():
            # Windows 下使用 pwsh（PowerShell 7），而非默认的 cmd.exe
            if sys.platform == "win32":
                return subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    capture_output=True,
                    timeout=30,
                )
            return subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=30,
            )

        try:
            result = await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            return "错误：命令执行超时（30 秒）"
        except FileNotFoundError:
            return "错误：找不到 pwsh（PowerShell 7），请确认已安装且位于 PATH 中"
        except Exception as e:
            return f"错误：{e}"

        output = _decode_output(result.stdout)
        if result.stderr:
            output += "\n" + _decode_output(result.stderr)
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(命令执行成功，没有输出)"


# ---------------------------------------------------------------------------
# ReadFileTool —— 读取文件内容
# ---------------------------------------------------------------------------


class ReadFileTool(Tool):
    """读取文件内容的工具"""

    name = "read_file"
    description = "读取指定文件的内容，返回文本"

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件的绝对路径",
                        },
                        "max_bytes": {
                            "type": "integer",
                            "description": "最大读取字节数，默认 100000",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        path = args.get("path", "")
        max_bytes = args.get("max_bytes", 100_000)

        try:
            p = Path(path)
            if not p.exists():
                return f"错误：文件不存在: {path}"
            if not p.is_file():
                return f"错误：不是文件: {path}"

            size = p.stat().st_size
            if size > max_bytes:
                return f"错误：文件过大 ({size} 字节，上限 {max_bytes})。" \
                       f"请用 shell 工具分块读取。"

            content = p.read_text(encoding="utf-8", errors="replace")
            return content

        except Exception as e:
            return f"错误：{e}"


# ---------------------------------------------------------------------------
# WriteFileTool —— 写入文件
# ---------------------------------------------------------------------------


class WriteFileTool(Tool):
    """写入文件的工具"""

    name = "write_file"
    description = "创建或覆盖写入文件内容"

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件的绝对路径",
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的文件内容",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")

        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            size = p.stat().st_size
            return f"文件写入成功: {path} ({size} 字节)"
        except Exception as e:
            return f"错误：{e}"


# ---------------------------------------------------------------------------
# EditFileTool —— 精确编辑文件
#
# 支持两种模式：
# - search_replace: 搜索并替换文件中唯一匹配的文本
# - insert: 在唯一匹配的锚点文本前后插入新内容
# ---------------------------------------------------------------------------


class EditFileTool(Tool):
    """精确编辑文件内容的工具"""

    name = "edit_file"
    description = "编辑文件：搜索替换指定文本，或在指定位置前后插入新内容"

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "文件的绝对路径",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["search_replace", "insert"],
                            "description": "操作模式：search_replace（搜索替换）或 insert（插入）",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "搜索替换时要被替换的文本，或插入模式中的定位锚点文本。"
                                           "必须在文件中唯一匹配。",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "替换后的新文本（search_replace 模式必填）",
                        },
                        "insert_content": {
                            "type": "string",
                            "description": "要插入的内容（insert 模式必填）",
                        },
                        "position": {
                            "type": "string",
                            "enum": ["after", "before"],
                            "description": "插入位置（insert 模式）：在锚点之后或之前",
                        },
                    },
                    "required": ["path", "old_text"],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        path = args.get("path", "")
        mode = args.get("mode", "search_replace")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        insert_content = args.get("insert_content", "")
        position = args.get("position", "after")

        # ── 校验路径 ──────────────────────────────────
        try:
            p = Path(path)
            if not p.exists():
                return f"错误：文件不存在: {path}"
            if not p.is_file():
                return f"错误：不是文件: {path}"
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            return f"错误：{e}"

        # ── 计数 old_text 出现次数 ──────────────────
        count = content.count(old_text)

        if count == 0:
            return (
                f"错误：在文件中未找到匹配文本。请检查 old_text 是否准确。\n"
                f"文件: {path}\n"
                f"文件大小: {len(content)} 字符"
            )

        if count > 1:
            return (
                f"错误：old_text 在文件中出现 {count} 次，必须唯一匹配。\n"
                f"请提供更多上下文以确保文本唯一。"
            )

        # ── 执行操作 ──────────────────────────────────
        try:
            if mode == "search_replace":
                if not new_text:
                    return "错误：search_replace 模式需要提供 new_text"
                content = content.replace(old_text, new_text, 1)

            elif mode == "insert":
                if not insert_content:
                    return "错误：insert 模式需要提供 insert_content"
                pos = content.index(old_text)  # 唯一匹配，不会抛 ValueError
                if position == "after":
                    content = (
                        content[:pos + len(old_text)]
                        + "\n" + insert_content
                        + content[pos + len(old_text):]
                    )
                else:  # before
                    content = (
                        content[:pos]
                        + insert_content + "\n"
                        + content[pos:]
                    )

            else:
                return f"错误：未知的操作模式 '{mode}'"

            # ── 写回文件 ──────────────────────────────
            p.write_text(content, encoding="utf-8")
            size = p.stat().st_size
            return f"文件编辑成功: {path} ({size} 字节)"

        except Exception as e:
            return f"错误：{e}"


# ---------------------------------------------------------------------------
# ListDirTool —— 列出目录内容
# ---------------------------------------------------------------------------


class ListDirTool(Tool):
    """列出目录内容的工具"""

    name = "list_dir"
    description = "列出指定目录下的文件和子目录"

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "目录的绝对路径，默认当前工作目录",
                        },
                    },
                    "required": [],
                },
            },
        }

    async def execute(self, args: dict) -> str:
        path = args.get("path", str(Path.cwd()))

        try:
            p = Path(path)
            if not p.exists():
                return f"错误：目录不存在: {path}"
            if not p.is_dir():
                return f"错误：不是目录: {path}"

            lines = []
            for item in sorted(p.iterdir()):
                suffix = "/" if item.is_dir() else ""
                lines.append(f"  {item.name}{suffix}")

            if not lines:
                return f"目录 {path} 为空"

            return f"{path} 的内容：\n" + "\n".join(lines)

        except Exception as e:
            return f"错误：{e}"


# ---------------------------------------------------------------------------
# ToolRegistry —— 工具箱
#
# 把所有工具注册到一起，提供统一的查询和执行接口。
# AgentRunner 通过这个注册中心来获取工具定义 + 执行工具。
# ---------------------------------------------------------------------------


class ToolRegistry:
    """工具箱 —— 管理所有可用工具"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        # 技能名 → SKILL.md 绝对路径（幻觉兑底引导用）
        self._skill_locations: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        """注册一个新工具"""
        self._tools[tool.name] = tool
        print(f"[工具] 已注册: {tool.name} — {tool.description}")

    def register_skills(self, skills: list[dict]) -> None:
        """
        登记技能名与 SKILL.md 路径（技能不是工具，不参与 get_definitions）。

        模型偶尔会把技能名当工具调用（如 tavily-search 与 Tavily MCP
        工具重名），execute 命中时返回引导信息，把它拉回正确路径：
        先 read_file 读取技能正文，而不是报"找不到工具"后让模型瞎猜命令。
        """
        for skill in skills:
            name = skill.get("name")
            path = skill.get("path")
            if name and path:
                self._skill_locations[name] = path

    def get(self, name: str) -> Tool | None:
        """根据名称获取工具"""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        """
        获取所有工具的 JSON Schema 定义列表。

        这个列表会发给 AI，让 AI 知道有哪些工具可以用。
        格式是 OpenAI 兼容的 tool definitions 格式。
        """
        return [tool.get_definition() for tool in self._tools.values()]

    def tool_names(self) -> list[str]:
        """列出所有已注册的工具名"""
        return list(self._tools.keys())

    async def execute(self, name: str, args: dict) -> str:
        """根据名称执行工具"""
        tool = self._tools.get(name)
        if tool is None:
            location = self._skill_locations.get(name)
            if location:
                return (
                    f"错误：'{name}' 是技能而非工具，不能直接调用。\n"
                    f"请先调用 read_file(path=\"{location}\") 读取该技能的 "
                    "SKILL.md 正文，再严格按正文中的说明执行。"
                )
            return f"错误：找不到工具 '{name}'"
        return await tool.execute(args)
