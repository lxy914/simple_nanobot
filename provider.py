"""
LLM Provider 接口 —— 定义"怎么和 AI 模型通信"。

在真实项目中，这里会有 AnthropicProvider、OpenAIProvider 等，
分别对接不同的 AI 服务。在精简版中，我们用 MockProvider 模拟 AI 的行为，
让整个流程跑通，方便你理解数据是如何流转的。

所有 Provider 都遵循同一个接口：
    async generate(messages, tools) -> LLMResponse
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCallRequest:
    """
    AI 要求调用的工具。

    当 AI 认为需要某种工具来完成任务时会返回这个结构，
    例如 "帮我看看目录里有什么文件" → AI 返回 ToolCallRequest(name="shell", arguments={"command": "ls"})
    """

    id: str          # 工具调用 ID，用于关联请求和结果
    name: str        # 工具名："shell"
    arguments: dict  # 参数：{"command": "ls"}


@dataclass
class LLMResponse:
    """
    AI 模型的回复。

    有两种可能：
    1. 纯文本回复：content 有内容，tool_calls 为空
       → 表示 AI 已经完成任务，可以直接回复用户了
    2. 工具调用请求：tool_calls 有内容
       → AI 想要调用工具，调完后需要把结果返回给 AI 继续对话
    """

    content: str = ""                       # 文本回复
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # 工具调用请求
    finish_reason: str = "stop"             # "stop"(完成), "tool_calls"(要调工具)


class LLMProvider(ABC):
    """
    AI 模型提供商的抽象基类。

    produce() 是唯一需要实现的方法。输入消息列表和工具定义，
    返回 AI 的回复。所有 Provider（不管是真 AI 还是 Mock）都遵循这个接口。
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# MockProvider —— 模拟 AI 行为
#
# 它不真的调用 AI，而是根据用户消息的内容返回不同的回复，
# 模拟 AI "看到消息 → 判断需要工具 → 调用工具 → 回复" 的过程。
#
# 规则：
#   消息包含"文件"且不包含"创建" → 返回 tool_call: shell("ls")
#   消息包含"创建"或"写"        → 返回 tool_call: shell("echo 文件创建成功")
#   其他情况                     → 返回文本: "收到你的消息：{原消息}"
#
# 这样做的好处是：你可以看到完整的工具调用链路，又不需要真实的 API Key。
# ---------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """
    模拟的 AI 模型 —— 用于演示和测试。

    它按照一套简单的规则判断"要不要调工具"、"调什么工具"，
    让你能跑通整个工具调用链路。
    """

    def __init__(self) -> None:
        self._call_counter = 0  # 每个实例独立的 tool_call ID 计数器

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        # 取出最后一条用户消息
        user_msg = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_msg = m["content"]
                break

        # 检查之前的消息中有没有 tool 返回结果
        # 如果有，说明 AI 已经收到工具结果了，该给文本回复了
        has_tool_result = any(m["role"] == "tool" for m in messages)

        # 规则：如果 AI 已经收到了工具结果，就返回文本回复
        if has_tool_result:
            # 找到最近一条 tool 结果
            for m in reversed(messages):
                if m["role"] == "tool":
                    tool_result = m.get("content", "")
                    break
            else:
                tool_result = ""
            return LLMResponse(
                content=f"好，我已经执行了工具，返回结果：\n{tool_result}",
                finish_reason="stop",
            )

        # AI 还没调过工具，根据消息内容决定要不要调
        if "文件" in user_msg and "创建" not in user_msg:
            self._call_counter += 1
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{self._call_counter}",
                        name="shell",
                        arguments={"command": "ls -la"},
                    )
                ],
                finish_reason="tool_calls",
            )

        if "创建" in user_msg or "写" in user_msg:
            self._call_counter += 1
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{self._call_counter}",
                        name="shell",
                        arguments={"command": "echo '文件创建成功！'"},
                    )
                ],
                finish_reason="tool_calls",
            )

        # 都不匹配，直接回复
        return LLMResponse(
            content=f"收到你的消息：「{user_msg}」\n"
                    f"我目前是一个模拟 AI，可以执行 shell 命令。\n"
                    f"试试说'看看当前目录有什么文件'或'帮我创建一个文件'？",
            finish_reason="stop",
        )


# ---------------------------------------------------------------------------
# OpenAIProvider —— 使用官方 openai 库调用真实大模型
#
# 通过 openai.AsyncOpenAI 客户端调用 API，支持：
# - OpenAI 官方
# - DeepSeek
# - 阿里通义千问
# - 任何兼容 OpenAI 接口的服务
#
# 配置通过 .env 文件加载：
#   LLM_API_KEY=sk-xxx           # API 密钥（必填）
#   LLM_BASE_URL=https://...      # API 地址（可选，默认 OpenAI 官方）
#   LLM_MODEL=gpt-4o-mini         # 模型名（可选，默认 gpt-4o-mini）
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """加载项目根目录的 .env 文件"""
    import os
    from pathlib import Path

    try:
        from dotenv import load_dotenv
        # 从项目根目录加载
        env_path = Path(__file__).resolve().parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        pass


class OpenAIProvider(LLMProvider):
    """使用 openai 库调用真实大模型"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        import os

        # 参数优先级：构造函数 > 环境变量 > 默认值
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 创建异步 openai 客户端
        self._client = None

    def _get_client(self):
        """延迟初始化 openai 客户端"""
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            # openai 库期望的 tools 格式
            kwargs["tools"] = tools

        try:
            response = await client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            finish_reason = choice.finish_reason or "stop"

            # 情况 A：AI 要调工具
            if finish_reason == "tool_calls" and choice.message.tool_calls:
                import json

                tool_calls = []
                for tc in choice.message.tool_calls:
                    tool_calls.append(ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    ))
                return LLMResponse(tool_calls=tool_calls, finish_reason="tool_calls")

            # 情况 B：AI 返回文本
            content = choice.message.content or ""
            return LLMResponse(content=content, finish_reason=finish_reason)

        except Exception as e:
            return LLMResponse(
                content=f"API 调用失败: {e}",
                finish_reason="error",
            )
