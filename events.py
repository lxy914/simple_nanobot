"""
消息事件类型 —— 系统中最基础的数据结构。

InboundMessage:  从用户进入系统的消息（用户说了什么）
OutboundMessage: 系统回复给用户的消息（智能体回答了什么）

这两个类定义了整个系统流通的"语言"。
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class InboundMessage:
    """
    入站消息 —— 用户发来的消息。

    无论消息从终端命令行输入还是将来从聊天平台进入，
    都统一用这个结构表示。
    """

    channel: str          # 来源："cli"（命令行）
    sender_id: str        # 发送者 ID："user"
    chat_id: str          # 会话 ID："default"
    content: str          # 消息正文
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # 附件（暂不支持）
    metadata: dict = field(default_factory=dict)     # 额外信息

    @property
    def session_key(self) -> str:
        """
        会话唯一标识。

        格式："{channel}:{chat_id}"
        同一会话的所有消息共享同一个 key，用来串联上下文。
        """
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """
    出站消息 —— 系统要发给用户的回复。

    AgentLoop 处理完用户消息后生成这个结构，
    然后从 MessageBus 取出、打印到终端（或将来发送到聊天平台）。
    """

    channel: str     # "cli"
    chat_id: str     # "default"
    content: str     # 回复正文
    reply_to: str | None = None  # 回复哪条消息（暂未使用）
    media: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
