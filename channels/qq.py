"""
QQ 通道 —— 连接 QQ 机器人。

简化自原版 nanobot/channels/qq.py，保留了核心流程：
1. 通过 botpy SDK 的 WebSocket 连接到 QQ 服务器
2. 接收群聊 @ 消息和私聊消息
3. 翻译成 InboundMessage 投递到总线
4. 从总线接收 OutboundMessage 并发送回 QQ

去掉的功能：
- 附件下载/上传
- 去重机制
- 权限检查/配对
- ACK 消息
- 流式传输
- Markdown 格式

使用方式：
    1. 安装 botpy: pip install qq-botpy
    2. 在 QQ 开放平台创建机器人，获取 app_id 和 secret
    3. 配置 config:
       {
           "app_id": "123456",
           "secret": "your-secret"
       }
"""

from __future__ import annotations

import asyncio
import traceback

from channels.base import Channel

# botpy 是可选依赖，没有安装也能导入模块
try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage, Message
    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False


class QQChannel(Channel):
    """QQ 机器人通道"""

    name = "qq"
    display_name = "QQ"

    def __init__(self, bus, config=None):
        super().__init__(bus, config)
        self._client = None
        self._running = False

        self._app_id = str(self.config.get("app_id", ""))
        self._secret = str(self.config.get("secret", ""))

    # ── start / stop ──────────────────────────────────────

    async def start(self) -> None:
        """启动 QQ 通道 —— 连接 QQ WebSocket"""

        if not QQ_AVAILABLE:
            print("[通道] QQ 通道需要安装 qq-botpy: pip install qq-botpy")
            return

        if not self._app_id or not self._secret:
            print("[通道] QQ 通道缺少 app_id 或 secret，跳过启动")
            return

        self._running = True
        print(f"[通道] {self.display_name} 已启动 (app_id={self._app_id[:6]}...)")

        # 创建 botpy 客户端
        self._client = _make_bot_client(self)

        # 连接循环：断线自动重连
        while self._running:
            try:
                await self._client.start(
                    appid=self._app_id,
                    secret=self._secret,
                )
            except Exception:
                if self._running:
                    print(f"[通道] QQ 连接断开，5 秒后重连...\n{traceback.format_exc()}")
                    await asyncio.sleep(5)

        print("[通道] QQ 已停止")

    async def stop(self) -> None:
        """停止 QQ 通道"""
        self._running = False
        if self._client:
            try:
                await self._client.stop()
            except Exception:
                pass

    # ── send ─────────────────────────────────────────────

    async def send(self, msg) -> None:
        """发送回复到 QQ"""

        if not self._client or not QQ_AVAILABLE:
            return

        content = msg.content
        chat_id = msg.chat_id
        metadata = msg.metadata or {}
        is_group = metadata.get("is_group", False)

        try:
            if is_group:
                await self._client.api.post_group_message(
                    group_openid=chat_id,
                    content=content,
                    msg_type=0,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=chat_id,
                    content=content,
                    msg_type=0,
                )
        except Exception as e:
            print(f"[通道] QQ 发送失败: {e}")

    # ── 消息回调（被 botpy 框架调用） ─────────────────────

    async def _on_group_message(self, message: GroupMessage) -> None:
        """处理群聊 @ 机器人的消息"""
        try:
            content = message.content.strip() if message.content else ""
            if not content:
                return

            chat_id = getattr(message, "group_openid", "")
            sender_id = getattr(message.author, "member_openid", "")
            if not chat_id or not sender_id:
                return

            print(f"[通道] QQ 收到群聊消息 from={sender_id[:8]}... content={content[:50]}...")

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                metadata={"message_id": getattr(message, "id", ""), "is_group": True},
            )
        except Exception as e:
            print(f"[通道] QQ 群聊消息处理异常: {e}\n{traceback.format_exc()}")

    async def _on_c2c_message(self, message: C2CMessage) -> None:
        """处理私聊消息"""
        try:
            content = message.content.strip() if message.content else ""
            if not content:
                return

            # C2CMessage 的 author 字段结构
            sender_id = getattr(message.author, "id", "") or getattr(message.author, "user_openid", "")
            chat_id = sender_id

            if not chat_id:
                return

            print(f"[通道] QQ 收到私聊消息 from={sender_id[:8]}... content={content[:50]}...")

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                metadata={"message_id": getattr(message, "id", ""), "is_group": False},
            )
        except Exception as e:
            print(f"[通道] QQ 私聊消息处理异常: {e}\n{traceback.format_exc()}")


# ── 动态创建 botpy Client 子类 ──────────────────────────


def _make_bot_client(channel: "QQChannel"):
    """动态创建 botpy.Client 子类，注册消息回调"""

    class _QQBotClient(botpy.Client):
        async def on_ready(self):
            print(f"[通道] QQ 机器人已上线: {self.robot.name}")

        async def on_group_at_message_create(self, message: GroupMessage):
            await channel._on_group_message(message)

        async def on_c2c_message_create(self, message: C2CMessage):
            await channel._on_c2c_message(message)

    intents = botpy.Intents(public_messages=True)
    return _QQBotClient(intents=intents)
