"""Tests for channels.cli.CliChannel —— stdin 读取与退出路径."""

import asyncio
import io

from bus import MessageBus
from channels.cli import CliChannel


def _make_channel(bus: MessageBus) -> CliChannel:
    """构建带共享 shutdown 事件的 CLI 通道"""
    return CliChannel(bus, config={"_shutdown_event": asyncio.Event()})


async def test_message_line_is_published(monkeypatch) -> None:
    """stdin 读到的行应投递到入站队列"""
    bus = MessageBus()
    chan = _make_channel(bus)
    # 模拟 stdin：先来一行消息，随后 EOF（readline 返回 ""）
    monkeypatch.setattr("channels.cli.sys.stdin", io.StringIO("你好\n"))

    async def _noop_drain() -> None:
        return

    monkeypatch.setattr(chan, "_drain_messages", _noop_drain)

    # 后台启动通道：reader 线程读到消息投递后自然 EOF 退出
    task = asyncio.create_task(chan.start())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
    assert msg.content == "你好"
    assert msg.channel == "cli"

    # start 协程应因 EOF 正常退出并触发 shutdown
    await asyncio.wait_for(task, timeout=5)
    assert chan._get_shutdown_event().is_set()


async def test_eof_exits_and_sets_shutdown(monkeypatch) -> None:
    """EOF（Ctrl+Z+Enter / 管道关闭）时 start 应退出并触发 shutdown"""
    bus = MessageBus()
    chan = _make_channel(bus)
    monkeypatch.setattr("channels.cli.sys.stdin", io.StringIO(""))

    async def _noop_drain() -> None:
        """跳过真实的 3 秒等待"""
        return

    monkeypatch.setattr(chan, "_drain_messages", _noop_drain)

    await chan.start()

    assert chan._get_shutdown_event().is_set()


async def test_exit_command_exits(monkeypatch) -> None:
    """输入 /exit 时 start 应退出并触发 shutdown"""
    bus = MessageBus()
    chan = _make_channel(bus)
    monkeypatch.setattr("channels.cli.sys.stdin", io.StringIO("/exit\n"))

    async def _noop_drain() -> None:
        return

    monkeypatch.setattr(chan, "_drain_messages", _noop_drain)

    await chan.start()

    assert chan._get_shutdown_event().is_set()
