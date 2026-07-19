"""
CLI 通道 —— 通过标准输入/输出进行对话。

这是最简单的通道实现，把之前 main.py 里的 input_reader/output_writer
逻辑封装成一个标准的 Channel 实例。

数据流：
    stdin.readline() → _handle_message() → bus.inbound
    bus.outbound → ChannelManager 分发 → send() → print()
"""

import asyncio

from channels.base import Channel


class CliChannel(Channel):
    """命令行交互通道"""

    name = "cli"
    display_name = "命令行"

    def __init__(self, bus, config=None):
        super().__init__(bus, config)

    def _get_shutdown_event(self) -> asyncio.Event | None:
        """
        获取共享 shutdown 事件。

        从 config 中延迟读取，因为 ChannelManager.register() 会在 __init__ 之后
        才把 _shutdown_event 注入到 config 中。
        """
        return self.config.get("_shutdown_event")

    async def start(self) -> None:
        """
        启动 CLI 通道。

        在线程池中执行阻塞的 stdin.readline()，读到消息后投递到总线。
        读到 /exit 或 EOF 时退出，并触发共享 shutdown 信号通知 ChannelManager。
        """
        loop = asyncio.get_event_loop()

        print(f"[通道] {self.display_name} 已启动")
        print("输入消息，输入 /exit 退出\n")
        print("> ", end="", flush=True)

        while True:
            line = await loop.run_in_executor(None, input)

            if not line:  # EOF
                break

            line = line.strip()
            if not line:
                print("> ", end="", flush=True)
                continue

            if line == "/exit":
                break

            await self._handle_message(
                sender_id="user",
                chat_id="default",
                content=line,
            )

        # 等待已投递的消息被处理完毕，再触发 shutdown
        print("\n[通道] 等待消息处理完成...")
        await self._drain_messages()

        if shutdown := self._get_shutdown_event():
            shutdown.set()

        print("[通道] CLI 已停止")

    async def _drain_messages(self) -> None:
        """等待入站队列中的消息被 AgentLoop 全部处理完"""
        # 等待入站队列清空（所有消息已被 AgentLoop 取走开始处理）
        for _ in range(50):  # 最多等 5 秒
            if self.bus.inbound.qsize() == 0:
                # 队列空了，再等 3 秒让最后一条消息完成处理和出站
                await asyncio.sleep(3.0)
                return
            await asyncio.sleep(0.1)
        # 超时保护
        await asyncio.sleep(3.0)

    async def stop(self) -> None:
        """停止 CLI 通道 —— 触发共享 shutdown 信号"""
        if shutdown := self._get_shutdown_event():
            shutdown.set()

    async def send(self, msg) -> None:
        """发送回复到标准输出"""
        print(f"\n🤖  {msg.content}")
        print("\n> ", end="", flush=True)
