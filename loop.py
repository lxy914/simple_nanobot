"""
AgentLoop —— 智能体的大脑。

它是整个系统的"主循环"，循环执行：
1. 等待用户消息
2. 启动状态机处理
3. 输出回复
4. 回到第 1 步

状态机（简化版，4 个状态）：
    RESTORE → BUILD → RUN → RESPOND → (等待下一条消息)

和原版对比：
- 原版有 8 个状态：RESTORE, COMPACT, COMMAND, BUILD, RUN, SAVE, RESPOND, DONE
- 精简版去掉了 COMPACT(上下文压缩)、COMMAND(斜杠命令)、SAVE(持久化)、DONE(清理)
- 保留了最核心的 4 个状态

数据流：
    bus.inbound.get() → RESTORE(恢复历史) → BUILD(拼消息) → RUN(调AI) → RESPOND(输出)
"""

import asyncio

from bus import MessageBus
from context import ContextBuilder
from provider import LLMProvider
from runner import AgentRunner
from tools import ToolRegistry


class AgentLoop:
    """智能体主循环"""

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        tools: ToolRegistry,
        context_builder: ContextBuilder,
    ):
        self.bus = bus
        self.provider = provider
        self.tools = tools
        self.context_builder = context_builder
        self.runner = AgentRunner()

        # 会话历史存储（内存字典）
        # key: "channel:chat_id", value: [{"role": "user", ...}, ...]
        # 在精简版中，历史只存内存，程序退出就丢失
        self._sessions: dict[str, list[dict]] = {}

    async def run(self, shutdown: asyncio.Event) -> None:
        """
        主循环 —— 运行直到收到 shutdown 信号。

        循环执行：
        1. 从 bus 取一条入站消息（没有就等着）
        2. 用状态机处理这条消息
        3. 继续等待下一条
        """
        while not shutdown.is_set():
            try:
                # 用超时来定期检查 shutdown 信号
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            await self._process_message(msg)

        print("已退出。")

    async def _process_message(self, msg) -> None:
        """
        状态机：RESTORE → BUILD → RUN → RESPOND

        每一步的职责：
        - RESTORE:  从内存中恢复之前的对话历史
        - BUILD:    拼装 system prompt + 历史 + 当前消息
        - RUN:      调用 AI 执行多轮对话
        - RESPOND:  把 AI 回复放进出站队列
        """

        session_key = msg.session_key
        print(f"\n[状态机] 开始处理 session={session_key}")

        # ── 状态 1: RESTORE ──────────────────────────────
        # 从内存中取出历史对话（如果第一次，就是空列表）
        print(f"[状态机] RESTORE: 恢复历史")
        history = self._restore_history(session_key)
        print(f"  历史消息数: {len(history)}")

        # ── 状态 2: BUILD ────────────────────────────────
        # 拼装完整消息列表
        print(f"[状态机] BUILD: 构建上下文")
        messages = self.context_builder.build_messages(
            history=history,
            current_message=msg.content,
        )
        print(f"  消息列表: system({len(self.context_builder.build_system_prompt())}字) + "
              f"{len(history)}条历史 + 当前消息")

        # ── 状态 3: RUN ──────────────────────────────────
        # 调用 AI 进行多轮对话（runner 会在 messages 上原地累积新消息）
        print(f"[状态机] RUN: 启动 AI 对话")
        base_len = len(messages)
        reply = await self.runner.run(
            initial_messages=messages,
            tools=self.tools,
            provider=self.provider,
            max_iterations=50,
        )

        # ── 状态 4: RESPOND ──────────────────────────────
        # 把 AI 的回复放进出站队列
        print(f"[状态机] RESPOND: 输出回复")

        # 保存本轮新增消息（runner 累积的 tool_calls/tool/assistant）
        new_messages = messages[base_len:]
        self._save_to_history(
            session_key,
            new_messages,
            user_msg=msg.content,  # 用户消息不在新增部分中，需单独保存
        )

        # 输出回复
        from events import OutboundMessage
        out = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=reply,
        )
        await self.bus.publish_outbound(out)

        print(f"[状态机] 本轮处理完成，等待下一条消息...")

    def _restore_history(self, session_key: str) -> list[dict]:
        """从内存中恢复历史"""
        return self._sessions.get(session_key, [])

    def _save_to_history(
        self,
        session_key: str,
        new_messages: list[dict],
        user_msg: str | None = None,
    ) -> None:
        """
        保存本轮新增消息到历史。

        new_messages: runner 返回的增量（tool_calls + tool 结果 + assistant 回复）
        user_msg: 本轮用户消息（不在 runner 增量中，需单独保存）
        """
        if session_key not in self._sessions:
            self._sessions[session_key] = []

        if user_msg is not None:
            self._sessions[session_key].append({
                "role": "user",
                "content": user_msg,
            })
        self._sessions[session_key].extend(new_messages)
