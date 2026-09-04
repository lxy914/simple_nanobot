"""
命令行入口 —— 启动整个简洁版系统。

做的事：
1. 创建 MessageBus（消息总线）
2. 注册工具（shell）
3. 创建 Provider（Mock 或 OpenAI）
4. 注册通道（CLI + QQ）
5. 并发启动 AgentLoop 和 ChannelManager
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from bus import MessageBus
from channels import ChannelManager, CliChannel, QQChannel
from context import ContextBuilder
from loop import AgentLoop
from provider import LLMProvider, MockProvider, OpenAIProvider, _load_dotenv
from skills_loader import SkillsLoader
from storage import SessionStorage
from tools import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    ShellTool,
    ToolRegistry,
    WriteFileTool,
)


def _create_skills_loader() -> SkillsLoader:
    """创建技能加载器"""
    from pathlib import Path

    # 技能目录：项目内的 skills/
    skills_dir = Path(__file__).resolve().parent / "skills"
    loader = SkillsLoader(skills_dir)
    count = len(loader.list_skills())
    if count > 0:
        print(f"[技能] 已加载 {count} 个技能")
    return loader


def _create_provider() -> LLMProvider:
    """
    智能创建 Provider。

    优先级：
    1. 检查环境变量 LLM_API_KEY（.env 或系统环境变量）
       → 有 → 创建 OpenAIProvider（真实大模型）
       → 无 → 降级为 MockProvider（模拟 AI）
    """
    import os

    # Provider.__init__ 内部会自动从 .env 加载 LLM_* 配置，
    # 这里只需检查是否有 API Key 来决定用哪个 Provider

    api_key = os.getenv("LLM_API_KEY", "")
    if api_key:
        provider = OpenAIProvider()
        print(f"[Provider] 使用真实大模型: {provider.model}")
        print(f"[Provider] API 地址: {provider.base_url}")
        return provider

    print("[Provider] 未检测到 LLM_API_KEY，降级为 MockProvider（模拟 AI）")
    return MockProvider()


def _register_qq_if_configured(manager: ChannelManager, bus: MessageBus) -> None:
    """如果 .env 中配置了 QQ 凭据，自动注册 QQ 通道"""
    import os

    app_id = os.getenv("QQ_APP_ID", "")
    secret = os.getenv("QQ_SECRET", "")

    if app_id and secret:
        manager.register(QQChannel(bus, config={
            "app_id": app_id,
            "secret": secret,
        }))
        print(f"[通道] QQ 通道已配置 (app_id={app_id[:6]}...)")
    else:
        print("[通道] 未检测到 QQ_APP_ID / QQ_SECRET，跳过 QQ 通道")


async def main() -> None:
    """主启动函数"""

    # ── 第 0 步：先加载 .env ───────────────────────────
    # 必须在读取任何 os.getenv 之前完成，否则 _create_provider /
    # _register_qq_if_configured 会因为环境变量还没注入而走 Mock / 跳过 QQ。
    _load_dotenv()

    # ── 第 1 步：创建基础设施 ─────────────────────────
    bus = MessageBus()

    # 会话持久化：每会话一个 JSON 文件，原子写入
    storage = SessionStorage(Path(__file__).resolve().parent / "data" / "sessions")

    # ── 第 2 步：创建技能加载器 ────────────────────────
    skills_loader = _create_skills_loader()

    # ── 第 3 步：注册工具 ──────────────────────────────
    tools = ToolRegistry()
    tools.register(ShellTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(EditFileTool())
    tools.register(ListDirTool())

    # 登记技能名 → SKILL.md 路径（幻觉兑底：技能名被当工具调用时给出引导）
    tools.register_skills(skills_loader.list_skills())

    # ── 第 4 步：创建 Provider ─────────────────────────
    provider = _create_provider()

    # ── 第 5 步：创建上下文构建器和 AgentLoop ─────────
    context_builder = ContextBuilder(
        skills_loader=skills_loader,
        tool_names=tools.tool_names(),
    )
    loop_agent = AgentLoop(
        bus=bus,
        provider=provider,
        tools=tools,
        context_builder=context_builder,
        storage=storage,
    )

    # ── 第 6 步：注册通道 ─────────────────────────────
    manager = ChannelManager(bus)

    # CLI 通道 —— 命令行交互（始终启用）
    manager.register(CliChannel(bus, config={}))

    # QQ 通道 —— 从 .env 自动检测凭据
    _register_qq_if_configured(manager, bus)

    # ── 第 7 步：并发启动 AgentLoop 和 ChannelManager ─
    print("\n" + "="*50)
    print("Simple Nanobot 启动中...")
    print(f"已加载工具: {tools.tool_names()}")
    print(f"已加载技能: {len(skills_loader.list_skills())} 个")
    print("="*50 + "\n")

    await asyncio.gather(
        loop_agent.run(manager._shutdown),
        manager.start_all(),
    )


def run() -> None:
    """同步入口 —— 供 `python main.py` 和 console_scripts 调用。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n再见！")


if __name__ == "__main__":
    run()
