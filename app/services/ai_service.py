from typing import AsyncGenerator, List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.config import settings

client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL
)

async def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "deepseek-v4-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096
) -> str:
    """调用AI生成响应"""
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content

async def stream_chat_completion(
    messages: List[Dict[str, str]],
    model: str = "deepseek-v4-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096
) -> AsyncGenerator[str, None]:
    """流式调用AI生成响应"""
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

async def stream_chat_completion_with_tools(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    model: str = "deepseek-v4-flash",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    reasoning_effort: str = "high"
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式输出并支持工具调用，启用思考模式"""
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        reasoning_effort=reasoning_effort,
        extra_body={"thinking": {"type": "enabled"}}
    )

    # 用于累积工具调用
    tool_calls_accumulator = {}
    has_tool_calls = False

    # 用于累积reasoning_content（必须传回给API）
    reasoning_content_accumulated = ""

    # 用于累积输出内容（简化日志用）
    output_content_accumulated = ""

    # 写入Tools信息到日志文件
    with open("ai_response.log", "a", encoding="utf-8") as log_file:
        log_file.write(f"\n=== New AI Response ===\n")
        log_file.write(f"Tools: {tools}\n")

    async for chunk in stream:
        delta = chunk.choices[0].delta

        # 处理思考内容（reasoning_content） - 必须保存并传回给API
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            reasoning_content_accumulated += delta.reasoning_content

        # 返回文本内容
        if delta.content:
            output_content_accumulated += delta.content
            yield {"type": "text", "content": delta.content}

        # 处理工具调用
        if delta.tool_calls:
            has_tool_calls = True
            for tool_call in delta.tool_calls:
                index = tool_call.index
                
                # 初始化工具调用累积器
                if index not in tool_calls_accumulator:
                    tool_calls_accumulator[index] = {
                        "id": tool_call.id,
                        "name": "",
                        "arguments": ""
                    }
                
                # 累积工具名称和参数
                if tool_call.function.name:
                    tool_calls_accumulator[index]["name"] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_calls_accumulator[index]["arguments"] += tool_call.function.arguments

    # 写入简化的日志文件
    with open("ai_response.log", "a", encoding="utf-8") as log_file:
        log_file.write("\n【模型思考内容】\n")
        if reasoning_content_accumulated:
            log_file.write(reasoning_content_accumulated)
        log_file.write("\n\n【模型输出内容】\n")
        if output_content_accumulated:
            log_file.write(output_content_accumulated)
        log_file.write("\n")

    # 在流结束后，输出完整的工具调用
    if has_tool_calls:
        for index, tool_call_data in tool_calls_accumulator.items():
            if tool_call_data["name"]:
                print(f"Complete tool call: {tool_call_data['name']}, args: {tool_call_data['arguments']}")

                yield {
                    "type": "tool_call",
                    "id": tool_call_data["id"],  # 添加 tool_call_id
                    "name": tool_call_data["name"],
                    "arguments": tool_call_data["arguments"]
                }
    
    # 重要：在流结束时，如果有reasoning_content，必须传回给后续API调用
    if reasoning_content_accumulated:
        yield {
            "type": "reasoning",
            "content": reasoning_content_accumulated
        }
