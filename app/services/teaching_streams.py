"""Teaching 会话流式生成管理器。

问题：页面刷新/断开 SSE 时，生成过程依赖 HTTP 请求生命周期 —— 一旦断开，
已生成的内容不会落库（assistant 消息只在生成结束时写入），
重新加载的页面也无法继续接收实时输出。

方案：生成任务与 HTTP 连接解耦。
- 首次连接时以独立 asyncio 任务启动生成（按最后一条待回复的 user 消息为 key）；
- 任意时刻的连接只是"订阅者"：断开/刷新不影响生成，最终结果必然落库；
- 新订阅者会先收到已生成文本的回放（partial_text），再继续实时接收；
- 生成结束（成功/失败）时向所有订阅者广播终止事件并清理注册。
"""

import asyncio
from collections.abc import Awaitable, Callable

_streams: dict[str, "StreamState"] = {}


class StreamState:
    """一次生成任务的状态。key = 待回复的 user 消息 id。"""

    def __init__(self, session_id: str, user_message_id: str):
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.status = "running"  # running / done / error
        self.error: str | None = None
        self.partial_text = ""  # 已生成文本（供刷新后的新订阅者回放）
        self.subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None


def ensure_stream(
    session_id: str,
    user_message_id: str,
    run_coro: Callable[["StreamState"], Awaitable[None]],
) -> tuple["StreamState", asyncio.Queue]:
    """确保针对该 user 消息的生成任务在运行，并注册一个新订阅。

    已有同消息的流在运行则复用（多页面/刷新后附加订阅）。
    返回 (state, subscriber_queue)。调用方必须在事件循环内调用。
    """
    state = _streams.get(user_message_id)
    if state is None:
        state = StreamState(session_id, user_message_id)
        _streams[user_message_id] = state
        state._task = asyncio.create_task(run_coro(state))
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.add(queue)
    # 回放：新订阅者（刷新后的页面）一定先收到 thinking（保证 pending 容器存在），
    # 再补齐已生成的文本，之后继续实时输出
    queue.put_nowait({"type": "thinking", "replay": True})
    if state.partial_text:
        queue.put_nowait({"type": "text", "content": state.partial_text, "replay": True})
    return state, queue


def broadcast(state: StreamState, event: dict) -> None:
    """向所有订阅者推送事件（无界队列，put_nowait 不会失败）。"""
    for queue in list(state.subscribers):
        queue.put_nowait(event)


def unsubscribe(state: StreamState, queue: asyncio.Queue) -> None:
    state.subscribers.discard(queue)


def finish(state: StreamState) -> None:
    """生成结束（成功/失败/取消）：移除注册并关闭所有订阅连接。"""
    _streams.pop(state.user_message_id, None)
    for queue in list(state.subscribers):
        queue.put_nowait(None)  # 终止哨兵
    state.subscribers.clear()
