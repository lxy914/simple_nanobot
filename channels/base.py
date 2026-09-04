"""
Channel 基类 —— 所有通道的抽象基类。

和原版对比：
- 原版 BaseChannel 有 send_delta、send_reasoning、transcribe_audio 等流式方法
- 精简版只保留核心的 start/stop/send，去掉流式、权限检查、配对等复杂功能

数据流（以 QQ 为例）：
    QQ 服务器 ──消息──→ QQChannel._on_message()
                              │
                              ├── 构造 InboundMessage
                              └── bus.publish_inbound(msg)
                                          │
                                          ▼
                                   AgentLoop 处理
                                          │
                                          ▼
                              bus.publish_outbound(OutboundMessage)
                                          │
                                          ▼
                              ChannelManager 取出 OutboundMessage
                              → channel.send(msg) → QQ API 发送
"""

from abc import ABC, abstractmethod

from bus import MessageBus
from events import InboundMessage, OutboundMessage


class Channel(ABC):
    """消息通道的抽象基类"""

    # 子类必须定义的类属性

    name: str = ""          # 通道内部标识名，如 "cli"、"qq"
    display_name: str = ""  # 通道展示名，如 "命令行"、"QQ"

    def __init__(self, bus: MessageBus, config: dict | None = None):
        """
        初始化通道。

        参数：
        - bus:    消息总线，通道通过它发送入站消息、接收出站消息
        - config: 通道配置，如 QQ 的 app_id、secret 等
        """
        self.bus = bus
        self.config = config or {}

    # ── 抽象方法（每个通道必须实现） ──────────────────────

    @abstractmethod
    async def start(self) -> None:
        """
        启动通道。

        这是一个长期运行的协程，需要：
        1. 连接外部平台（如 WebSocket 连接 QQ 服务器）
        2. 循环监听新消息
        3. 收到消息时调用 self._handle_message() 投递到总线
        """
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """停止通道，清理资源（关闭连接、取消任务等）"""
        raise NotImplementedError

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        发送出站消息到外部平台。

        参数：
        - msg: OutboundMessage 实例，包含 channel、chat_id、content 等字段

        实现方需要把 OutboundMessage 翻译成对应平台的 API 调用。
        """
        raise NotImplementedError

    # ── 共享方法（所有通道都用到） ──────────────────────

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        处理入站消息 —— 将外部平台的消息投递到总线。

        这是所有通道统一的"消息翻译层"：
        各平台的原始消息 → 这个方法的参数 → InboundMessage → bus.inbound

        参数：
        - sender_id: 发送者 ID（如 QQ 用户的 openid）
        - chat_id:   会话 ID（群聊的 group_openid 或私聊的 openid）
        - content:   消息正文
        - media:     附件路径列表
        - metadata:  通道特有的元数据（如消息 ID，用于回复定位）
        """
        msg = InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=metadata or {},
        )
        await self.bus.publish_inbound(msg)
