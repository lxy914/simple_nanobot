"""
会话存储 —— 会话历史的持久化。

每个会话（session_key）对应一个 JSON 文件，全量写入。
写入采用原子替换：先写临时文件（.tmp）再 replace 覆盖，
即使程序中途崩溃，磁盘上也只会有完整的旧数据或完整的新数据。

文件布局：
    data/sessions/
    ├── cli_default.json     # session_key "cli:default" 的历史
    └── qq_abc123.json
"""

import json
import re
from pathlib import Path


class SessionStorage:
    """会话历史持久化"""

    def __init__(self, base_dir: Path) -> None:
        """
        参数：
        - base_dir: 会话文件的存放目录（如 data/sessions/）
        """
        self._base_dir = Path(base_dir)

    def _path_for(self, session_key: str) -> Path:
        """
        session_key → 安全的文件路径。

        session_key 形如 "cli:default"，其中冒号在 Windows 文件名中非法，
        统一替换为下划线。
        """
        safe_name = re.sub(r"[^\w.-]", "_", session_key)
        return self._base_dir / f"{safe_name}.json"

    def load(self, session_key: str) -> list[dict]:
        """
        读取会话历史。

        文件不存在、内容损坏时返回空列表（新会话从零开始，不让存储问题阻塞对话）。
        """
        path = self._path_for(session_key)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[存储] 会话历史读取失败 {path}: {e}")
            return []

        return data if isinstance(data, list) else []

    def save(self, session_key: str, messages: list[dict]) -> None:
        """
        全量保存会话历史（原子写：先写 .tmp 再替换）。
        保存失败只打印警告，不抛异常——存储故障不应中断对话。
        """
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(session_key)
        tmp = path.with_suffix(".tmp")

        try:
            tmp.write_text(
                json.dumps(messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as e:
            print(f"[存储] 会话历史保存失败 {path}: {e}")
