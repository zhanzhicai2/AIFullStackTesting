import asyncio
from mimetypes import guess_type
from os.path import isfile

from fastapi import Request, WebSocket, WebSocketDisconnect, Depends
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app import pity, init_logging
from app.core.msg.wss_msg import WebSocketMessage
from app.core.ws_connection_manager import ws_manage
from app.crud.notification.NotificationDao import PityNotificationDao
from app.enums.MessageEnum import MessageStateEnum, MessageTypeEnum
from app.routers.ai import router as ai_router
from app.routers.ai.chat import router as ai_chat_router
from app.routers.auth import user
from app.routers.config import router as config_router
from app.routers.datafactory import router as datafactory_router
from app.routers.mock.admin import router as mock_admin_router
from app.routers.mock.service import router as mock_service_router
from app.routers.notification import router as msg_router
from app.routers.online import router as online_router
from app.routers.operation import router as operation_router
from app.routers.oss import router as oss_router
from app.routers.project import project
from app.routers.request import http
from app.routers.testcase import router as testcase_router
from app.routers.ui import router as ui_router
from app.routers.workspace import router as workspace_router
from app.utils.log_sanitize import MAX_BODY_LOG_BYTES, sanitize_payload, sanitize_url
from app.utils.logger import Log
from config import Config, PITY_ENV, BANNER

init_logging()

startup = Log("startup")
# 请求日志单独一个 business —— 它是访问记录, 与业务日志分开好过滤
http_log = Log("http")
ws_log = Log("websocket")

startup.success(f"pity is running at <red>{PITY_ENV}</red>")
startup.success(BANNER)


async def request_info(request: Request):
    # URL 必须过 sanitize_url: /auth/reset/check/<token> 这类 path 段本身就是凭据
    http_log.debug(f"{request.method} {sanitize_url(str(request.url))}")
    try:
        body = await request.json()
        # 必须拼进 message —— 文件 sink 用的 INFO_FORMAT 不含 extra[payload],
        # 走 logger.bind(payload=...) 的话内容根本不会出现在日志文件里
        http_log.debug(f"request_json: {sanitize_payload(body)}")
    except Exception:
        try:
            body = await request.body()
            if len(body) == 0:
                pass
            elif len(body) > MAX_BODY_LOG_BYTES:
                # 附件 / OSS 上传可能几十 MB, 只记字节数
                http_log.debug(f"request_body: <{len(body)} bytes, 超长省略>")
            else:
                # 有请求体，记录日志(过脱敏 + 截断)
                http_log.debug(f"request_body: "
                               f"{sanitize_payload(body.decode('utf-8', errors='replace'))}")
        except Exception:
            # 忽略文件上传类型的数据
            pass


# 注册路由
# user(登录/注册/OAuth)也要挂 request_info —— 登录成功/失败是审计必须的访问记录;
# body 已过 sanitize_payload, 密码不会落盘
pity.include_router(user.router, dependencies=[Depends(request_info)])
pity.include_router(project.router, dependencies=[Depends(request_info)])
pity.include_router(http.router, dependencies=[Depends(request_info)])
pity.include_router(testcase_router, dependencies=[Depends(request_info)])
pity.include_router(config_router, dependencies=[Depends(request_info)])
pity.include_router(online_router, dependencies=[Depends(request_info)])
pity.include_router(oss_router, dependencies=[Depends(request_info)])
pity.include_router(operation_router, dependencies=[Depends(request_info)])
pity.include_router(msg_router, dependencies=[Depends(request_info)])
pity.include_router(workspace_router, dependencies=[Depends(request_info)])
pity.include_router(datafactory_router, dependencies=[Depends(request_info)])
pity.include_router(ai_router, dependencies=[Depends(request_info)])
pity.include_router(ui_router, dependencies=[Depends(request_info)])
# Mock 管理路由(带 request_info)必须先注册, 对外 catch-all(不带 request_info)后注册 ——
# Starlette 按注册顺序匹配, 顺序颠倒会把 /mock/rule/* 当成「app=rule」的对外请求吞掉。
# 对外的 mock_service_router **刻意不挂 request_info**: 无鉴权入口, 挂上只会被
# 被测系统的压测流量刷爆日志(CLAUDE.md 硬约定)
pity.include_router(mock_admin_router, dependencies=[Depends(request_info)])
pity.include_router(mock_service_router)
# 聊天流式接口刻意不挂 request_info: 它会把 POST body 写进 DEBUG 日志,
# prompt 明文落盘不合适
pity.include_router(ai_chat_router)

# pity.mount("/statics", StaticFiles(directory="statics"), name="statics")

# templates = Jinja2Templates(directory="statics")


# @pity.get("/")
# async def serve_spa(request: Request):
#     return templates.TemplateResponse("index.html", {"request": request})


# @pity.get("/{filename}")
# async def get_site(filename):
#     filename = './statics/' + filename
#
#     if not isfile(filename):
#         return Response(status_code=404)
#
#     with open(filename, mode='rb') as f:
#         content = f.read()
#
#     content_type, _ = guess_type(filename)
#     return Response(content, media_type=content_type)


# @pity.get("/static/{filename}")
# async def get_site_static(filename):
#     filename = './statics/static/' + filename
#
#     if not isfile(filename):
#         return Response(status_code=404)
#
#     with open(filename, mode='rb') as f:
#         content = f.read()
#
#     content_type, _ = guess_type(filename)
#     return Response(content, media_type=content_type)


@pity.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    async def send_heartbeat():
        while True:
            ws_log.debug("sending heartbeat")
            await websocket.send_json({
                'type': 3
            })
            await asyncio.sleep(Config.HEARTBEAT)

    await ws_manage.connect(websocket, user_id)
    try:
        # 定义特殊值的回复，配合前端实现确定连接，心跳检测等逻辑
        questions_and_answers_map: dict = {
            "HELLO SERVER": F"hello {user_id}",
            "HEARTBEAT": F"{user_id}",
        }

        # 存储连接后获取消息
        msg_records = await PityNotificationDao.list_messages(msg_type=MessageTypeEnum.all.value, receiver=user_id,
                                                              msg_status=MessageStateEnum.unread.value)
        # 如果有未读消息, 则推送给前端对应的count
        if len(msg_records) > 0:
            await websocket.send_json(WebSocketMessage.msg_count(len(msg_records), True))
        # 发送心跳包
        # asyncio.create_task(send_heartbeat())
        while True:
            data: str = await websocket.receive_text()
            du = data.upper()
            if du in questions_and_answers_map:
                await ws_manage.send_personal_message(message=questions_and_answers_map.get(du), websocket=websocket)
    except WebSocketDisconnect:
        if user_id in ws_manage.active_connections:
            ws_manage.disconnect(user_id)
    except Exception as e:
        # exception 而不是 debug: 连接异常退出要在 error 文件里查得到
        ws_log.exception(f"websocket: 用户: {user_id} 异常退出: {e}")
