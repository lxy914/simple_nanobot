"""
AgentLoop —— 智能体的大脑。

它是整个系统的"主循环"，循环执行：
1. 等待用户消息
2. 启动状态机处理
3. 输出回复
4. 回到第 1 步

状态机（6 个状态）：
    RESTORE → BUILD → RUN → SAVE → RESPOND → (等待下一条消息)

- RESTORE: 从内存缓存/磁盘恢复会话历史
- BUILD:   拼装 system prompt + 历史 + 当前消息
- RUN:     调用 AI 执行多轮对话
- SAVE:    增量历史写入内存缓存 + 磁盘
- RESPOND: 把回复放进出站队列
- COMPACT: 回复发送后后台执行（不阻塞回复速度）：历史超阈值时用
           LLM 总结压缩，结果落盘，下一轮生效

和原版对比：
- 原版有 8 个状态：RESTORE, COMPACT, COMMAND, BUILD, RUN, SAVE, RESPOND, DONE
- 精简版去掉了 COMMAND(斜杠命令)、DONE(清理)
- COMPACT 改为回复发送后的后台任务：压缩要调用 LLM（耗时），
  放在 RESPOND 前会让用户等压缩完成才能看到回复

数据流：
    bus.inbound.get() → RESTORE → BUILD → RUN → SAVE → RESPOND → 后台 COMPACT
"""

import asyncio
import json

from bus import MessageBus
from context import ContextBuilder
from provider import LLMProvider
from runner import AgentRunner
from storage import SessionStorage
from tools import ToolRegistry
from events import InboundMessage, OutboundMessage

# ── 压缩参数 ────────────────────────────────────────

# 历史估算 token 超过此值时触发压缩
COMPACT_THRESHOLD_TOKENS = 10_000
# 压缩时保留最近的消息条数（连同摘要一起构成新历史）
COMPACT_KEEP_RECENT = 10


def _estimate_tokens(messages: list[dict]) -> int:
    """
    粗略估算消息列表的 token 数。

    中英混合场景按 2 字符 ≈ 1 token 估算，仅供触发压缩的参考，
    不追求精确（精确计数需要 tokenizer，超出教学范围）。
    """
    total_chars = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        else:
            # tool_calls 消息（content 为 None）：按函数名 + 参数长度计
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                total_chars += len(fn.get("name", "")) + len(fn.get("arguments", ""))
    return total_chars // 2


def _message_to_text(m: dict) -> str:
    """把一条消息转为纯文本，供 LLM 总结历史使用"""
    role = m.get("role", "?")
    content = m.get("content")
    if isinstance(content, str) and content:
        return f"[{role}] {content}"

    calls = m.get("tool_calls")
    if calls:
        parts = [
            f"{tc.get('function', {}).get('name', '?')}({tc.get('function', {}).get('arguments', '')})"
            for tc in calls
        ]
        return f"[{role}] 调用工具: {'; '.join(parts)}"

    return f"[{role}] (无文本内容)"


class AgentLoop:
    """智能体主循环"""

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        tools: ToolRegistry,
        context_builder: ContextBuilder,
        storage: SessionStorage | None = None,
    ) -> None:
        self.bus = bus
        self.provider = provider
        self.tools = tools
        self.context_builder = context_builder
        self.runner = AgentRunner()

        # 会话持久化（None = 只存内存，不落盘）
        self.storage = storage

        # 会话历史内存缓存
        # key: "channel:chat_id", value: [{"role": "user", ...}, ...]
        # 缓存未命中时从 storage 加载；每轮 SAVE 后写回缓存 + 磁盘
        self._sessions: dict[str, list[dict]] = {}

        # 每个会话的后台压缩任务锁（防止同一会话并发压缩互相覆盖）
        self._compact_locks: dict[str, asyncio.Lock] = {}

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

            out: OutboundMessage = await self._process_message(msg)
            await self.bus.publish_outbound(out)

        print("[agent loop] 已停止")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage:

        session_key = msg.session_key
        # ── 状态 1: RESTORE ──────────────────────────────
        # 从内存缓存（未命中则从磁盘）取出历史对话（如果第一次，就是空列表）
        history = self._restore_history(session_key)

        # ── 状态 2: BUILD ────────────────────────────────
        # 拼装完整消息列表
        messages = self.context_builder.build_messages(
            history=history,
            current_message=msg.content,
        )
        # ── 状态 3: RUN ──────────────────────────────────
        # 调用 AI 进行多轮对话（runner 会在 messages 上原地累积新消息）
        base_len = len(messages)
        reply = await self.runner.run(
            initial_messages=messages,
            tools=self.tools,
            provider=self.provider,
            max_iterations=50,
        )


        # ── 状态 4: SAVE ─────────────────────────────────
        # 保存本轮消息：用户消息是构造时 messages 的末位（runner 不动它），
        # 从 base_len - 1 切片即可把用户消息与 runner 增量（tool_calls/tool/assistant）一起收入历史
        self._save_to_history(session_key, messages[base_len - 1:])

        # ── 状态 5: COMPACT ─────────────────────────
        # 回复已生成，压缩转入后台执行（调用 LLM 耗时，不能拖慢回复），
        # 结果同步内存并落盘，下一轮直接生效
        self._schedule_compact(session_key)

        # ── 状态 6: RESPOND ─────────────────────────────
        # 输出回复
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=reply)

    def _restore_history(self, session_key: str) -> list[dict]:
        """RESTORE：先查内存缓存，未命中且有存储时从磁盘加载"""
        if session_key in self._sessions:
            return self._sessions[session_key]

        if self.storage is not None:
            history = self.storage.load(session_key)
            self._sessions[session_key] = history
            return history

        return []

    def _schedule_compact(self, session_key: str) -> None:
        """
        COMPACT 调度：创建后台压缩任务，不阻塞回复发送。

        仅当历史确实超阈值且该会话没有压缩任务在跑时才创建任务。
        任务启动后若历史又变长（新一轮对话已写入），会自动放弃，
        由那一轮消息重新触发压缩。

        注意：SAVE 是原地 extend，_sessions 中的列表对象从不替换，
        所以必须在调度瞬间记录长度快照，任务侧才能发现"历史又变长"。
        """
        history = self._sessions.get(session_key, [])
        if _estimate_tokens(history) < COMPACT_THRESHOLD_TOKENS:
            return
        if len(history) <= COMPACT_KEEP_RECENT:
            return

        lock = self._compact_locks.setdefault(session_key, asyncio.Lock())
        if lock.locked():
            return  # 已有压缩任务在跑，等它完成（结果写入后下一轮自然不再触发）

        asyncio.create_task(
            self._run_compact(session_key, history, len(history), lock)
        )

    async def _run_compact(
        self,
        session_key: str,
        history: list[dict],
        snapshot_len: int,
        lock: asyncio.Lock,
    ) -> None:
        """后台压缩任务体：拿锁后校验历史长度仍与调度时一致，再执行压缩"""
        async with lock:
            current = self._sessions.get(session_key)
            if current is not None and len(current) != snapshot_len:
                # 调度后已有新消息写入（原地 extend），压缩结果会覆盖新消息，放弃
                return
            await self._maybe_compact(session_key, history, expected_len=snapshot_len)

    async def _maybe_compact(
        self,
        session_key: str,
        history: list[dict],
        expected_len: int | None = None,
    ) -> list[dict]:
        """
        COMPACT：对完整历史做压缩。

        历史估算 token 超过阈值时，用 LLM 把旧消息总结为摘要，
        新历史 = [摘要消息] + 最近 COMPACT_KEEP_RECENT 条，并落盘
        （下一轮对话直接使用压缩后的历史）。
        总结失败（LLM 出错）时降级：保留原历史，不阻塞对话。

        expected_len：后台压缩路径传入调度时的历史长度快照。
        LLM 压缩期间若历史又被原地 extend（新一轮对话写入），
        写回会覆盖新消息，此时放弃本次压缩（由新消息轮次重新触发）。
        直接调用（如测试）不传则不做该校验。
        """
        if _estimate_tokens(history) < COMPACT_THRESHOLD_TOKENS:
            return history

        if len(history) <= COMPACT_KEEP_RECENT:
            return history

        keep = history[-COMPACT_KEEP_RECENT:]
        old = history[:-COMPACT_KEEP_RECENT]
        transcript = "\n".join(_message_to_text(m) for m in old)

        prompt = (
            "你是会话摘要助手。请将以下对话历史压缩为一份简洁摘要，保留：\n"
            "1. 用户的核心需求与偏好；\n"
            "2. 已完成的关键操作及其结果；\n"
            "3. 未完成的任务与待办；\n"
            "4. 重要的事实与约定。\n"
            "直接输出摘要正文，不要额外解释。\n\n"
            f"对话历史：\n{transcript}"
        )

        print(f"[compact] 历史过长（约 {_estimate_tokens(history)} tokens），开始压缩...")
        response = await self.provider.generate(messages=[{"role": "user", "content": prompt}])

        if response.finish_reason == "error" or not response.content:
            print("[compact] 历史总结失败，跳过压缩")
            return history

        summary_msg = {"role": "user", "content": f"[此前对话摘要]\n{response.content}"}
        new_history = [summary_msg] + keep

        # 写回前校验：压缩期间历史若已被原地 extend（长度变化），放弃本次结果
        if expected_len is not None:
            current = self._sessions.get(session_key)
            if current is None or len(current) != expected_len:
                print("[compact] 压缩期间有新消息写入，跳过本次压缩")
                return history

        # 压缩结果同步到内存缓存，并落盘（下一轮对话直接使用压缩后历史）
        self._sessions[session_key] = new_history
        if self.storage is not None:
            self.storage.save(session_key, new_history)
        print(f"[compact] 压缩完成: {len(history)} 条 → {len(new_history)} 条")
        return new_history

    def _save_to_history(self, session_key: str, new_messages: list[dict]) -> None:
        """
        SAVE：保存本轮增量消息到历史。

        new_messages: 本轮用户消息 + runner 累积的增量
                     （tool_calls + tool 结果 + assistant 回复）
        """
        sessions = self._sessions.setdefault(session_key, [])
        sessions.extend(new_messages)

        # 持久化到磁盘（storage 为 None 时仅内存）
        if self.storage is not None:
            self.storage.save(session_key, sessions)
