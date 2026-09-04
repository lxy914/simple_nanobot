"""
CLI 通道 —— 通过标准输入/输出进行对话。

这是最简单的通道实现，把之前 main.py 里的 input_reader/output_writer
逻辑封装成一个标准的 Channel 实例。

数据流：
    stdin.readline() → _handle_message() → bus.inbound
    bus.outbound → ChannelManager 分发 → send() → print()
"""

import asyncio
import sys
import threading
from typing import TYPE_CHECKING

from channels.base import Channel

if TYPE_CHECKING:
    from bus import MessageBus
    from events import OutboundMessage


class CliChannel(Channel):
    """命令行交互通道"""

    name = "cli"
    display_name = "命令行"

    def __init__(self, bus: "MessageBus", config: dict | None = None) -> None:
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

        stdin 由 daemon 线程读取，再线程安全地投递到 asyncio 队列。

        为什么不用 run_in_executor(input)：默认线程池的线程是非 daemon 的，
        按 Ctrl+C 时 asyncio.run 退出前会等待线程池线程结束，而阻塞的
        input() 永不返回，程序会挂死。daemon 线程不阻止进程退出，
        Ctrl+C 抛 KeyboardInterrupt 后程序可直接结束。
        读到 /exit 或 EOF 时退出，并触发共享 shutdown 信号通知 ChannelManager。
        """
        print(f"[通道] {self.display_name} 已启动")
        print("输入消息，输入 /exit 退出\n")

        loop = asyncio.get_running_loop()
        lines: asyncio.Queue[str | None] = asyncio.Queue()

        def _reader() -> None:
            """daemon 线程：阻塞读 stdin，EOF 时投递 None 结束"""
            while True:
                line = sys.stdin.readline()
                loop.call_soon_threadsafe(
                    lines.put_nowait,
                    line.strip() if line else None,
                )
                if not line:  # EOF（Ctrl+Z + Enter / 管道关闭）
                    return

        threading.Thread(target=_reader, daemon=True, name="cli-stdin").start()

        print("> ", end="", flush=True)
        while True:
            line = await lines.get()
            if line is None:  # EOF
                break
            if not line:
                print("> ", end="", flush=True)
                continue
            if line == "/exit" or line == "exit":
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

    async def send(self, msg: "OutboundMessage") -> None:
        """发送回复到标准输出"""
        print(f"\n🤖  {msg.content}")
        print("\n> ", end="", flush=True)
