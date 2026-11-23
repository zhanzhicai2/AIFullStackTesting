import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from pprint import pformat

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from loguru._defaults import LOGURU_FORMAT
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.types import Message

from app.exception.request import AuthException
from app.exception.request import PermissionException
from app.utils.log_sanitize import sanitize_url
from app.utils.logger import Log
from config import Config

sys.path.append(__file__)

# 模块级日志 —— 中间件与异常 handler 用。走 Log 类而不是裸 logger.bind(name=...),
# 因为 INFO_FORMAT / ERROR_FORMAT 要读 extra[filename]/[func]/[line], 少绑一个就 KeyError
log = Log("app")


def _client(request: Request) -> str:
    """取请求方 IP —— 鉴权失败日志要能看出是谁在试。"""
    return request.client.host if request.client else "unknown"

# from starlette_context import middleware, plugins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 0.95+ 推荐的 lifespan context manager,替代 @app.on_event('startup')。
    启动顺序保持与原 on_event 一致:Redis → APScheduler → 数据库建表。
    启动逻辑放在 app/__init__.py 里,因为 FastAPI 实例化也在这;
    main.py 通过 from app import pity 拿到已带 lifespan 的实例。
    """
    # 延迟 import 避免 app/__init__.py → main.py → app/__init__.py 的循环
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.crud import create_table
    from app.middleware.RedisManager import RedisHelper
    from app.utils.scheduler import Scheduler

    # 启动日志单独一个 business —— 出问题时一眼能从模块列里认出来
    startup = Log("startup")

    # 1. init_redis
    try:
        await RedisHelper.ping()
        startup.success("redis connected success.        ✔")
    except Exception:
        if not Config.REDIS_ON:
            startup.warning(
                f"Redis is not selected, So we can't ensure that the task is not executed repeatedly.        🚫")
        else:
            # exception 而不是 error: 启动失败必须带完整堆栈落盘
            startup.exception(
                f"Redis connect failed, Please check config.py for redis config.        ❌")
            # 用 raise 而不是 raise e —— 后者会把 traceback 重置到这一行, 丢掉真正的抛出点
            raise

    # 2. init_scheduler
    job_store = {
        'default': SQLAlchemyJobStore(
            url=Config.SQLALCHEMY_DATABASE_URI,
            engine_options={"pool_recycle": 1500},
            pickle_protocol=3,
        )
    }
    scheduler = AsyncIOScheduler()
    Scheduler.init(scheduler)
    Scheduler.configure(jobstores=job_store)
    Scheduler.start()
    startup.success("ApScheduler started success.        ✔")

    # 3. init_database
    try:
        # 必须 await: 之前用 asyncio.create_task 让建表在后台跑,
        # 但日志已经打印"created success"且 lifespan 已经放行请求,
        # 首个请求可能撞上"表还不存在"。建表是幂等 DDL,await 只多花几十毫秒。
        await create_table()
        startup.success("database and tables created success.        ✔")
        # 预置 AI 厂商不在这里插: 交给 AIVendorDao.ensure_seed 在首次 /ai 访问时
        # 用真实操作人 id 写入,避免 create_user 落成 0
    except Exception as e:
        startup.exception(
            f"database and tables  created failed.        ❌\nerror: {e}")
        raise

    # 4. 注册内置 UI 执行节点 —— 用户无需额外配置就能执行 UI 用例(spec FR-019)
    try:
        from app.crud.ui.UINodeDao import UINodeDao
        await UINodeDao.ensure_local_node()
        startup.success("ui local node registered.        ✔")
    except Exception as e:
        # 节点注册失败不该拖垮整个服务 —— UI 用例执行时会自己再注册
        startup.warning(f"注册内置 UI 执行节点失败: {e}")

    yield
    # shutdown 阶段:原 stop_test 是 pass,目前不需要额外清理
    # APScheduler / Redis 连接由各自实现负责关闭


pity = FastAPI(lifespan=lifespan)

# pity.add_middleware(
#     middleware.ContextMiddleware,
#     plugins=(
#         plugins.ForwardedForPlugin(),
#     ),
# )

# 配置日志格式
INFO_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> " \
              "| <level>{level: <8}</level> | <cyan>文件: {extra[filename]}</cyan> " \
              "| 模块: <cyan>{extra[business]}</cyan> | 方法: <cyan>{extra[func]}</cyan> " \
              "| <cyan>行数: {extra[line]}</cyan> | - <level>{message}</level>"

ERROR_FORMAT = "<red>{time:YYYY-MM-DD HH:mm:ss.SSS}</red> " \
               "| <level>{level: <8}</level> | <cyan>文件: {extra[filename]}</cyan> " \
               "| 模块: <cyan>{extra[business]}</cyan> | 方法: <cyan>{extra[func]}</cyan> " \
               "| <cyan>行数: {extra[line]}</cyan> | - <level>{message}</level>"


async def set_body(request: Request, body: bytes):
    async def receive() -> Message:
        return {"type": "http.request", "body": body}

    request._receive = receive


async def get_body(request: Request) -> bytes:
    body = await request.body()
    await set_body(request, body)
    return body


@pity.middleware("http")
async def errors_handling(request: Request, call_next):
    # body = await request.body()
    try:
        # await set_body(request, await request.body())
        return await call_next(request)
    except Exception as exc:
        # 之前是 traceback.print_exc(), 只进 stderr —— 容器一重建就没了。
        # 换成落盘的结构化日志, 带上请求上下文(方法/路径/来源 IP)。
        log.exception(f"请求未捕获异常: {request.method} {sanitize_url(str(request.url))} "
                      f"| client={_client(request)}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder({
                "code": 110,
                "msg": str(exc),
                # "request_data": body,
            })
        )


def error_map(error_type: str, field: str, msg: str = None):
    if "missing" in error_type:
        return f"缺少参数: {field}"
    if "params" in error_type:
        return f"参数: {field} {'不规范' if msg is None else msg}"
    if "not_allowed" in error_type:
        return f"参数: {field} 类型不正确"
    if "type_error" in error_type:
        return f"参数: {field} 类型不合法"


@pity.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 参数错误也要留痕 —— 它是接口被改坏 / 被探测的第一信号, 之前完全无日志
    detail = error_map(exc.errors()[0]["type"], exc.errors()[0].get("loc", ['unknown'])[-1],
                       exc.errors()[0].get("msg")) if len(exc.errors()) > 0 else "参数解析失败"
    log.warning(f"400 参数校验失败: {request.method} {sanitize_url(str(request.url))} "
                f"| {detail} | client={_client(request)}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder({
            "code": 101,
            "msg": detail,
        })
    )


@pity.exception_handler(PermissionException)
async def permission_exception_handler(request: Request, exc: PermissionException):
    # 越权访问必须留痕 —— 之前这条路径一条日志都没有, 安全审计时查不到谁在试
    log.warning(f"403 无权限: {request.method} {sanitize_url(str(request.url))} "
                f"| {exc.detail} | client={_client(request)}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder({
            "code": 403,
            "msg": exc.detail,
        })
    )


@pity.exception_handler(AuthException)
async def auth_exception_handler(request: Request, exc: AuthException):
    # 未登录 / token 失效同样要留痕(含 client IP, 便于识别撞库与 token 猜测)
    log.warning(f"401 未认证: {request.method} {sanitize_url(str(request.url))} "
                f"| {exc.detail} | client={_client(request)}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=jsonable_encoder({
            "code": 401,
            "msg": str(exc.detail),
        })
    )


async def global_execution_handler(request: Request, exc: Exception):
    # 兜底 500 —— 之前一条日志都不记, 服务端错误在文件里完全查不到。
    # 这里**不在 except 块内**, log.exception() 取不到活动异常, 得自己格式化堆栈。
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error(f"500 未处理异常: {request.method} {sanitize_url(str(request.url))} "
              f"| client={_client(request)}\n{stack}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=dict(code=110, msg="unknown error: " + str(exc)),
    )


# add global error
pity.add_middleware(
    ServerErrorMiddleware,
    handler=global_execution_handler,
)
# add cors
pity.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InterceptHandler(logging.Handler):
    """
    Default handler from examples in loguru documentaion.
    See https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging
    """

    def emit(self, record: logging.LogRecord):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def format_record(record: dict) -> str:
    """
    这里的代码是copy的，记录日志格式的
    Custom format for loguru loggers.
    Uses pformat for log any data like request/response body during debug.
    Works with logging if loguru handler it.
    Example:
    # >>> payload = [{"users":[{"name": "Nick", "age": 87, "is_active": True}, {"name": "Alex", "age": 27, "is_active": True}], "count": 2}]
    # >>> logger.bind(payload=).debug("users payload")
    # >>> [   {   'count': 2,
    # >>>         'users': [   {'age': 87, 'is_active': True, 'name': 'Nick'},
    # >>>                      {'age': 27, 'is_active': True, 'name': 'Alex'}]}]
    """

    format_string = LOGURU_FORMAT
    if record["extra"].get("payload") is not None:
        record["extra"]["payload"] = pformat(
            record["extra"]["payload"], indent=4, compact=True, width=88
        )
        format_string += "\n<level>{extra[payload]}</level>"

    format_string += "{exception}\n"
    return format_string


def make_filter(name):
    # 过滤操作，当日志要选择对应的日志文件的时候，通过filter进行筛选
    def filter_(record):
        return record["extra"].get("name") == name

    return filter_


def init_logging():
    loggers = (
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict
        if name.startswith("uvicorn.")
    )
    for uvicorn_logger in loggers:
        uvicorn_logger.handlers = []

    # 这里的操作是为了改变uvicorn默认的logger，使之采用loguru的logger
    # change handler for default uvicorn logger
    intercept_handler = InterceptHandler()
    logging.getLogger("uvicorn").handlers = [intercept_handler]

    # 为pity添加一个info log文件，主要记录debug和info级别的日志
    pity_info = os.path.join(Config.LOG_DIR, f"{Config.PITY_INFO}.log")
    # 为pity添加一个error log文件，主要记录warning和error级别的日志
    pity_error = os.path.join(Config.LOG_DIR, f"{Config.PITY_ERROR}.log")

    # ⚠️ **只能用 configure, 不能先 logger.add() 再 configure** ——
    # configure 是替换式的(会先清掉已有 sink), 先 add 的 rotation / enqueue 会被它
    # 整个丢掉, 两个日志文件因此永不轮转、无限增长。
    # 所有 sink 参数(level / filter / rotation / retention / enqueue)集中在这一处写。
    #
    # info 侧 level 必须是 DEBUG —— Log.debug() 也往这里写, 且 CLAUDE.md 承诺
    # "pity_info.log — DEBUG 及以上"。
    logger.configure(handlers=[
        {"sink": sys.stdout, "level": logging.DEBUG, "format": format_record},
        {"sink": pity_info, "level": logging.DEBUG, "format": INFO_FORMAT,
         "filter": make_filter(Config.PITY_INFO),
         "rotation": "20 MB", "retention": "30 days", "enqueue": True},
        {"sink": pity_error, "level": logging.WARNING, "format": ERROR_FORMAT,
         "filter": make_filter(Config.PITY_ERROR),
         "rotation": "10 MB", "retention": "30 days", "enqueue": True},
    ])
    return logger
