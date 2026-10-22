import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import logger
from app.core.ai_client import stream_chat
from app.crud.ai.AIChatDao import AIChatDao
from app.crud.ai.AIModelDao import AIModelDao
from app.crud.ai.AIVendorDao import AIVendorDao
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.schema.ai import ChatSessionInsertForm, ChatSessionUpdateForm, ChatStreamForm

# 独立 router 实例: main.py 注册 ai_router 时带了 request_info 依赖,
# 它会把 POST body 写进 DEBUG 日志, 聊天 prompt 不该明文落盘
router = APIRouter(prefix="/ai")

# 送给模型的上下文最大条数(约 10 轮), 防止长会话撑爆 context
MAX_HISTORY = 20


def _sse(obj, event="message") -> str:
    return f"event: {event}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.get("/chat/session/list", description="我的会话列表")
async def list_chat_session(user_info=Depends(Permission())):
    try:
        data = await AIChatDao.list_session(user_info['id'])
        result = []
        for item in data:
            s = PityResponse.model_to_dict(item["session"])
            s["preview"] = (item["preview"] or "")[:60]
            result.append(s)
        return PityResponse.success(result)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/chat/session/insert", description="新建会话")
async def insert_chat_session(form: ChatSessionInsertForm, user_info=Depends(Permission())):
    try:
        model_name = None
        if form.model_id:
            model_name = await _find_model_name(form.vendor_id, form.model_id)
        data = await AIChatDao.insert_session(user_info['id'], form.vendor_id, model_name)
        return PityResponse.success(PityResponse.model_to_dict(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/chat/session/update", description="修改会话标题或模型")
async def update_chat_session(form: ChatSessionUpdateForm, user_info=Depends(Permission())):
    try:
        model_name = None
        if form.model_id:
            model_name = await _find_model_name(form.vendor_id, form.model_id)
        await AIChatDao.update_session(form.session_id, user_info['id'],
                                       form.title, form.vendor_id, model_name)
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/chat/session/delete", description="删除会话")
async def delete_chat_session(session_id: int, user_info=Depends(Permission())):
    try:
        await AIChatDao.delete_session(session_id, user_info['id'])
        return PityResponse.success()
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/chat/message/list", description="会话消息列表")
async def list_chat_message(session_id: int, user_info=Depends(Permission())):
    try:
        session = await AIChatDao.query_session(session_id, user_info['id'])
        if session is None:
            return PityResponse.failed("会话不存在或无权访问")
        data = await AIChatDao.list_message(session_id)
        return PityResponse.success(PityResponse.model_to_list(data))
    except Exception as e:
        return PityResponse.failed(e)


@router.get("/chat/models", description="可用的对话模型(已启用的厂商与模型)")
async def list_chat_models(_=Depends(Permission())):
    """
    给聊天页用的聚合列表, 只返回展示所需字段。
    不返回 api_key / base_url —— 普通用户没有查看厂商配置的权限。
    """
    try:
        vendors = await AIVendorDao.list_vendor(_)
        result = []
        for item in vendors:
            vendor = item["vendor"]
            if not vendor.enable or not vendor.api_key:
                continue
            models = await AIModelDao.list_model(vendor.id)
            # 只给启用的对话类模型, embedding/rerank 不能拿去聊天
            usable = [m for m in models if m.enable and m.model_type == "chat"]
            if not usable:
                continue
            result.append({
                "vendor_id": vendor.id,
                "vendor_name": vendor.name,
                "vendor_code": vendor.code,
                "models": [{"model_id": m.id, "model_name": m.name} for m in usable],
            })
        return PityResponse.success(result)
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/chat/stream", description="AI对话(SSE流式)")
async def chat_stream(form: ChatStreamForm, user_info=Depends(Permission())):
    user_id = user_info['id']
    session = await AIChatDao.query_session(form.session_id, user_id)
    if session is None:
        return PityResponse.failed("会话不存在或无权访问")

    vendor_id = form.vendor_id or session.vendor_id
    model_id = form.model_id
    if not vendor_id or not model_id:
        return PityResponse.failed("请先在右上角选择模型")

    vendor = await AIVendorDao.query_vendor(vendor_id)
    if vendor is None:
        return PityResponse.failed("模型厂商不存在")
    if not vendor.enable or not vendor.api_key:
        return PityResponse.failed("该厂商未启用或未配置 API Key, 请联系管理员")

    model_row = None
    for m in await AIModelDao.list_model(vendor_id):
        if m.id == model_id:
            model_row = m
            break
    if model_row is None:
        return PityResponse.failed("模型不存在")
    if not model_row.enable or model_row.model_type != "chat":
        return PityResponse.failed("该模型未启用或不是对话模型")
    model_name = model_row.name
    params = {}
    if model_row.params:
        try:
            params = json.loads(model_row.params)
        except Exception:
            params = {}

    # 先落库用户消息, 拿到完整历史再组装上下文
    await AIChatDao.insert_message(form.session_id, "user", form.content, user_id)
    history = await AIChatDao.list_message(form.session_id)
    # 排除刚落库这条(最后一条), 只带最近 MAX_HISTORY 条作为上下文
    context = history[:-1][-MAX_HISTORY:]
    messages = [{"role": m.role, "content": m.content} for m in context]
    messages.append({"role": "user", "content": form.content})

    # 会话还是默认标题时, 用首条消息前 30 字当标题
    if session.title == "新会话" and len(history) == 1:
        try:
            await AIChatDao.update_session(form.session_id, user_id,
                                           title=form.content.strip().replace("\n", " ")[:30])
        except Exception:
            pass

    async def gen():
        chunks, tokens = [], 0
        try:
            # 握手帧: 让前端尽早确认 content-type 正确
            yield _sse({"role": "assistant", "model_name": model_name})
            async for piece, usage in stream_chat(vendor.base_url, vendor.api_key,
                                                  model_name, messages, params):
                if usage:
                    tokens = usage.get("total_tokens", 0)
                    continue
                if piece:
                    chunks.append(piece)
                    yield _sse({"content": piece})
            yield "data: [DONE]\n\n"
        except Exception as e:
            # ★ 必须在这里兜底: 异常若逃出生成器, 全局 ServerErrorMiddleware 会重抛,
            #   客户端拿到的是被截断的响应体而不是错误信息
            logger.bind(name=None).error(f"chat stream error: {e}")
            yield _sse({"error": str(e)}, event="error")
            yield "data: [DONE]\n\n"
        finally:
            # 这里只落库, 不能再 yield(生成器被取消时 yield 会抛)
            if chunks:
                try:
                    await AIChatDao.insert_message(form.session_id, "assistant", "".join(chunks),
                                                   user_id, model_name, tokens)
                except Exception as e:
                    logger.bind(name=None).error(f"保存 AI 回复失败: {e}")

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # nginx 默认会缓冲响应, 不加这个生产环境 SSE 会退化成一次性返回
        "X-Accel-Buffering": "no",
    })


async def _find_model_name(vendor_id: int, model_id: int) -> str:
    if not vendor_id:
        raise Exception("请先选择厂商")
    for m in await AIModelDao.list_model(vendor_id):
        if m.id == model_id:
            return m.name
    raise Exception("模型不存在")