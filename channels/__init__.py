"""
通道系统 —— 把"消息从哪来、到哪去"抽象成可插拔的通道。

每个通道是一个 Channel 子类，需要实现：
1. start() → 连接外部平台，监听消息，调用 _handle_message() 投递到总线
2. stop()  → 断开连接，清理资源
3. _send() → 把 OutboundMessage 发送到外部平台

ChannelManager 是通道管理器，负责：
- 启动所有通道
- 从总线的出站队列取出回复，分发给正确的通道
"""

from channels.base import Channel
from channels.cli import CliChannel
from channels.manager import ChannelManager
from channels.qq import QQChannel

__all__ = ["Channel", "CliChannel", "QQChannel", "ChannelManager"]
