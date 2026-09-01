"""
AgentRunner —— AI 多轮对话执行器。

这是整个系统中最核心的循环。它不关心消息从哪来、到哪去，
只负责一件事：和 AI 反复对话，直到 AI 说"我回答完了"。

核心循环：
    for 第N轮 in range(最大轮数):
        1. 把 messages + 工具定义发给 AI
        2. 如果 AI 返回 tool_calls → 执行工具，结果追加到 messages，继续下一轮
        3. 如果 AI 返回文本 → 这就是最终回复，返回它

每轮 AI 看到的 messages 是累积的：
    第1轮：[system, user:"帮我..." ]
    第2轮：[system, user:"帮我...", assistant(tool_call:"shell"), tool("ls 结果")]
    第3轮：[...同上... , assistant("回复文本")]
"""

import json

from provider import LLMProvider, LLMResponse
from tools import ToolRegistry


class AgentRunner:
    """
    AI 对话执行器。

    职责：管理 messages 的累积、调用 AI、执行工具、判断何时结束。
    """

    def __init__(self):
        pass

    async def run(
        self,
        initial_messages: list[dict],
        tools: ToolRegistry,
        provider: LLMProvider,
        max_iterations: int = 50,
    ) -> str:
        """
        执行一次完整的 AI 对话。

        参数：
        - initial_messages: 初始消息列表（system + history + user message）。
                           ⚠️ 会被原地修改：本方法直接在该列表上累积
                           tool_calls / tool 结果 / assistant 回复
        - tools:            工具箱
        - provider:         AI 提供商（真 AI 或 Mock）
        - max_iterations:   最大对话轮数，防止无限循环

        返回：
        - 最终回复文本。完整的消息列表通过 initial_messages 传出
          （调用方传入的列表已被原地累积，可直接读取）。
        """

        # 直接在传入列表上累积（不拷贝），让调用方直接拿到完整消息
        messages = initial_messages
        tools_used = set()

        print(f"\n{'='*50}")
        print(f"开始 AI 对话，最多 {max_iterations} 轮")
        print(f"{'='*50}")

        for iteration in range(max_iterations):
            print(f"\n--- 第 {iteration + 1} 轮 ---")
            print(f"当前消息数: {len(messages)}")

            # 第 1 步：调用 AI
            response: LLMResponse = await provider.generate(
                messages=messages,
                tools=tools.get_definitions(),
            )

            # 第 2 步：判断 AI 返回了什么

            # 情况 A：AI 调用出错
            if response.finish_reason == "error":
                print(f"AI 调用失败: {response.content}")
                return f"抱歉，AI 服务暂时不可用：{response.content}"

            # 情况 B：AI 要调工具
            if response.tool_calls:
                print(f"AI 要求调用工具: {len(response.tool_calls)} 个")

                # 2a. 把 AI 的 tool_call 追加到 messages
                for tc in response.tool_calls:
                    # 执行工具时打印参数（长值截断，避免刷屏）
                    args_str = ", ".join(
                        f"{k}={str(v)[:50]}{'...' if len(str(v)) > 50 else ''}"
                        for k, v in tc.arguments.items()
                    )
                    print(f"  调用工具 {tc.name}({args_str})")

                    assistant_msg = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                    messages.append(assistant_msg)

                    # 2b. 执行工具
                    result = await tools.execute(tc.name, tc.arguments) or "(工具执行失败)"
                    tools_used.add(tc.name)
                    print(f"  工具 {tc.name} 执行结果: {str(result)[:50]}...")

                    # 2c. 把工具结果追加到 messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result,
                    })

                # 2d. 继续下一轮（把工具结果交给 AI 继续思考）
                continue

            # 情况 B：AI 给了文本回复
            final_text = response.content or "(空回复)"
            print(f"AI 返回文本: {final_text[:50]}...")

            # 把 AI 的文本回复追加到 messages
            messages.append({"role": "assistant", "content": final_text})

            print(f"\n{'='*50}")
            print(f"对话结束，共 {iteration + 1} 轮，使用工具: {tools_used}")
            print(f"{'='*50}")

            return final_text

        # 超出最大轮数
        return "抱歉，我思考太久了，请换个方式问我。"
