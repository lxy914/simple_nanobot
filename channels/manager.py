"""
通道管理器 —— 同时运行多个通道，协调它们的生命周期。

职责：
1. 注册和管理多个 Channel 实例
2. 并发启动所有通道的 start() 协程
3. 监听总线出站队列，根据 OutboundMessage.channel 分发给正确的通道
4. 优雅关闭所有通道

数据流：
    ChannelManager
    ├── 启动 N 个通道的 start() 协程（并发）
    └── 出站分发循环 ── 从 bus.outbound 取消息 → channel.send(msg)

和原版对比：
- 原版 ChannelManager 有 channel 自动发现、重试策略、流式事件合并等
- 精简版只保留了注册、启动、分发三个核心功能
"""

import asyncio

from bus import MessageBus
from channels.base import Channel


class ChannelManager:
    """通道管理器"""

    def __init__(self, bus: MessageBus):
        """
        初始化通道管理器。

        参数：
        - bus: 消息总线实例
        """
        self.bus = bus
        self._channels: dict[str, Channel] = {}
        self._shutdown = asyncio.Event()

    def register(self, channel: Channel) -> None:
        """
        注册一个通道。

        同一个名称的通道只能注册一次。
        自动将共享的 shutdown 事件注入到通道配置中，
        这样 CliChannel 可以在用户输入 /exit 时通知管理器关闭。
        """
        if channel.name in self._channels:
            print(f"[管理器] 通道 '{channel.name}' 已注册，跳过")
            return

        # 注入共享 shutdown 事件到通道配置
        channel.config["_shutdown_event"] = self._shutdown

        self._channels[channel.name] = channel
        print(f"[管理器] 已注册通道: {channel.name} ({channel.display_name})")

    async def start_all(self) -> None:
        """
        启动所有已注册的通道。

        同时启动：
        1. 所有通道的 start() 协程（并发运行）
        2. 出站消息分发循环（从 bus.outbound 取消息，分发给对应通道）
        """

        if not self._channels:
            print("[管理器] 没有注册任何通道")
            return

        print(f"\n[管理器] 启动 {len(self._channels)} 个通道: "
              f"{[c.display_name for c in self._channels.values()]}")

        # 并发启动所有通道 + 出站分发
        tasks = [
            asyncio.create_task(channel.start())
            for channel in self._channels.values()
        ]
        tasks.append(asyncio.create_task(self._dispatch_outbound()))

        # 等待 shutdown 信号（由 CliChannel 在用户输入 /exit 时触发）
        # 或者等待所有任务完成
        await self._shutdown.wait()
        print("[管理器] 收到 shutdown 信号，正在停止通道...")

        # 优雅关闭
        for channel in self._channels.values():
            await channel.stop()

        for t in tasks:
            t.cancel()

        print("[管理器] 所有通道已停止")

    async def shutdown(self) -> None:
        """发出关闭信号"""
        self._shutdown.set()

    async def _dispatch_outbound(self) -> None:
        """
        出站消息分发循环。

        从总线的出站队列取出 OutboundMessage，
        根据 msg.channel 找到对应的 Channel 实例，
        调用 channel.send(msg) 发送到外部平台。

        为什么不用 asyncio.Queue 而用轮询？
        因为 OutboundMessage.channel 决定了发给哪个通道，
        如果直接从队列取，需要单独一个协程做分发。
        """
        while not self._shutdown.is_set():
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            # 找到目标通道
            channel = self._channels.get(msg.channel)
            if channel is None:
                print(f"[管理器] 未找到通道 '{msg.channel}'，消息丢弃")
                continue

            try:
                await channel.send(msg)
            except Exception as e:
                print(f"[管理器] 通道 '{msg.channel}' 发送失败: {e}")
