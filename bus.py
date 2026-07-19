"""
消息总线 —— 解耦"谁发消息"和"谁处理消息"。

它只有两个异步队列：
- inbound:  收件箱 —— 外部把消息放进来，AgentLoop 取走
- outbound: 发件箱 —— AgentLoop 把回复放进来，外部取走

这样 AgentLoop 不需要知道消息从哪个平台来，
发送方也不需要知道谁在处理消息。
"""

import asyncio

from events import InboundMessage, OutboundMessage


class MessageBus:
    """
    异步消息总线。

    类比：大楼的信报箱系统
    - 住户把信投入收件箱（publish_inbound）
    - 物业从收件箱取信处理（consume_inbound）
    - 物业把回信投入发件箱（publish_outbound）
    - 住户从发件箱取回信（consume_outbound）
    """

    def __init__(self):
        # asyncio.Queue 是协程安全的队列
        # 队列为空时，get() 会阻塞等待（不消耗 CPU）
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """把用户消息放进收件箱"""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """从收件箱取出下一条消息（没有就等着）"""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """把智能体回复放进发件箱"""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """从发件箱取出下一条回复（没有就等着）"""
        return await self.outbound.get()
