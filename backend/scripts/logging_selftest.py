"""
日志自测脚本(**不依赖数据库**)

不依赖 pytest, 直接跑:
    cd backend
    .venv/bin/python scripts/logging_selftest.py

覆盖(对应 backend/CLAUDE.md「日志」章节 + 本次修复的四条机制):
- **sink 分流**: Log 各级别落到正确文件, info 侧不再被 level 滤空
- **configure 参数**: rotation / retention / enqueue 真的生效(曾被 configure 覆盖丢掉)
- **脱敏**: 密码 / api_key / token 不进日志; reset path 与 query token 掩码;
  普通路径与雪花 id **不误伤**
- **request_info 不落明文密码** —— 这是打通 info sink 的前置条件
- **异常路径留痕**: 401 / 403 / 101 / 500 四个 handler 都要写出日志(此前全部零日志)

**需要数据库的部分**在启动后的实跑验证里, 本脚本只测纯逻辑与 handler。
"""
import asyncio
import os
import sys
import tempfile

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)

# 必须在 import app 之前换掉日志目录 —— Log.__init__ 与 init_logging 都读 Config.LOG_DIR
from config import Config  # noqa: E402

LOG_DIR = tempfile.mkdtemp(prefix="pity_log_selftest_")
Config.LOG_DIR = LOG_DIR

from app import (init_logging,  # noqa: E402
                 auth_exception_handler, global_execution_handler,
                 permission_exception_handler, validation_exception_handler)
from app.utils.log_sanitize import MASK, sanitize_payload, sanitize_url  # noqa: E402
from app.utils.logger import Log  # noqa: E402

init_logging()

from loguru import logger  # noqa: E402  (configure 之后再取, 拿到的是已配置的实例)
from starlette.requests import Request  # noqa: E402

FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def read(name: str) -> str:
    path = os.path.join(LOG_DIR, name)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def flush():
    """enqueue=True 的 sink 是异步写, 等队列排空再读文件。"""
    logger.complete()


def make_request(method="POST", path="/auth/login", query=b"", body=b"", client=("1.2.3.4", 9999)):
    """构造一个不经过 ASGI 生命周期的 Request —— 只够 handler 读 method/url/client。"""
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": [],
        "client": client,
        "server": ("testserver", 80),
        "root_path": "",
    }
    return Request(scope, receive=receive)


# ---------------------------------------------------------------------------
# sink 分流与配置
# ---------------------------------------------------------------------------


def test_sink_configuration():
    print("\n[sink 配置]")
    handlers = list(logger._core.handlers.values())
    # FileSink 的落盘路径在 _file_path(日志格式的 extra 字段无关, 只用来确认 sink 接对了文件)
    files = {str(h._sink._file_path): h for h in handlers if type(h._sink).__name__ == "FileSink"}

    info_path = os.path.join(LOG_DIR, "pity_info.log")
    error_path = os.path.join(LOG_DIR, "pity_error.log")
    check("info sink 指向 pity_info.log", info_path in files, f"实际: {list(files)}")
    check("error sink 指向 pity_error.log", error_path in files, f"实际: {list(files)}")

    info = files.get(info_path)
    error = files.get(error_path)
    if info is not None:
        check("info sink level == DEBUG(10)", info._levelno == 10, f"实际: {info._levelno}")
        check("info sink rotation 生效(20MB)", info._sink._rotation_function is not None,
              "rotation 是 None —— configure 把它丢了")
        check("info sink enqueue 生效", info._enqueue is True)
        check("info sink retention 生效", info._sink._retention_function is not None)
    if error is not None:
        check("error sink level == WARNING(30)", error._levelno == 30, f"实际: {error._levelno}")
        check("error sink rotation 生效(10MB)", error._sink._rotation_function is not None)
        check("error sink enqueue 生效", error._enqueue is True)


def test_level_routing():
    print("\n[级别分流]")
    log = Log("Selftest")
    log.debug("SELFTDEBUG")
    log.info("SELFTINFO")
    log.success("SELFTSUCCESS")
    log.warning("SELFTWARNING")
    log.error("SELFTERROR")
    flush()

    info = read("pity_info.log")
    error = read("pity_error.log")

    # 这三条曾因 Log.info 调 .debug() + sink level=INFO 而永远进不了文件
    check("debug 落 info 文件", "SELFTDEBUG" in info)
    check("info 落 info 文件", "SELFTINFO" in info, "Log.info() 走了 .debug() 被 level 滤掉?")
    check("success 落 info 文件", "SELFTSUCCESS" in info, "SUCCESS(25) < WARNING(30), 必须绑 info 侧")
    check("warning 落 error 文件", "SELFTWARNING" in error)
    check("error 落 error 文件", "SELFTERROR" in error)

    check("info 不串到 error 文件", "SELFTINFO" not in error)
    check("error 不串到 info 文件", "SELFTERROR" not in info)

    check("info 文件带定位信息", "文件:" in info and "行数:" in info,
          "INFO_FORMAT 的 extra 字段没绑全")


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------


def test_sanitize_payload():
    print("\n[请求体脱敏]")
    login = sanitize_payload({"username": "admin", "password": "SuperSecret123", "remember": True})
    check("顶层 password 掩码", login["password"] == MASK, f"实际: {login}")
    check("非敏感字段保留", login["username"] == "admin")

    nested = sanitize_payload({"data": [{"api_key": "sk-abc", "name": "x"}, {"token": "jwt"}]})
    check("嵌套列表里的 api_key 掩码", nested["data"][0]["api_key"] == MASK)
    check("嵌套列表里的 token 掩码", nested["data"][1]["token"] == MASK)
    check("同级非敏感字段保留", nested["data"][0]["name"] == "x")

    check("camelCase 的 apiKey 掩码",
          sanitize_payload({"apiKey": "x"})["apiKey"] == MASK)
    check("authorization 掩码",
          sanitize_payload({"authorization": "Bearer x"})["authorization"] == MASK)

    long_text = sanitize_payload({"content": "x" * 5000})["content"]
    check("超长字符串截断", len(long_text) < 3000, f"实际长度 {len(long_text)}")

    deep = sanitize_payload({"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}})
    check("过深嵌套有兜底", "层级过深" in str(deep), f"实际: {deep}")


def test_sanitize_url():
    print("\n[URL 脱敏]")
    check("reset check 的 token 掩码",
          sanitize_url("http://x/auth/reset/check/0123456789abcdef0123456789abcdef").endswith(MASK),
          sanitize_url("http://x/auth/reset/check/0123456789abcdef0123456789abcdef"))
    check("reset generate 的 email 掩码",
          sanitize_url("http://x/auth/reset/generate/zhang%40qq.com").endswith(MASK))

    query_url = sanitize_url("http://x/api?token=abc&page=1&name=test")
    check("query 敏感参数掩码", f"token={MASK}" in query_url, query_url)
    check("query 非敏感参数保留", "page=1" in query_url, query_url)
    check("掩码不被 urlencode 编码", "%2A" not in query_url, query_url)

    check("普通业务路径不误伤",
          sanitize_url("http://x/apiTest/case/list?id=123") == "http://x/apiTest/case/list?id=123")
    check("雪花 id 不误伤(纯数字)",
          sanitize_url("http://x/project/1234567890123456").endswith("/1234567890123456"),
          sanitize_url("http://x/project/1234567890123456"))
    check("高熵长段仍会掩码",
          MASK in sanitize_url("http://x/file/abc123def456ghi789jkl012mno345pqr"))


# ---------------------------------------------------------------------------
# request_info —— 打通 info sink 的前置条件
# ---------------------------------------------------------------------------


async def _post_request_info():
    from main import request_info

    body = b'{"username":"admin","password":"SuperSecret123","api_key":"sk-live-xyz"}'
    await request_info(make_request(method="POST", path="/auth/login", body=body))
    # 再打一条带 token 的 path 与 query
    await request_info(make_request(method="GET", path="/auth/reset/check/0123456789abcdef0123456789abcdef"))
    await request_info(make_request(method="GET", path="/api/list", query=b"token=abc123&page=2"))
    # 超大 body 只该记字节数
    await request_info(make_request(method="POST", path="/oss/upload", body=b"x" * (70 * 1024)))
    flush()


def test_request_info_not_leaking():
    print("\n[request_info 不落明文凭据]")
    asyncio.run(_post_request_info())
    info = read("pity_info.log")
    error = read("pity_error.log")
    all_logs = info + error

    check("访问日志已落 info 文件", "/auth/login" in info, "request_info 没写进文件")
    check("密码不落盘", "SuperSecret123" not in all_logs, "明文密码出现在日志里!")
    check("api_key 不落盘", "sk-live-xyz" not in all_logs, "明文 API Key 出现在日志里!")
    check("reset token 不落盘", "0123456789abcdef0123456789abcdef" not in all_logs)
    check("query token 不落盘", "token=abc123" not in all_logs)
    check("掩码在日志里可见", MASK in info and "password" in info,
          f"没在日志里找到掩码, 无法确认脱敏生效: {info[-300:]}")
    check("超大 body 只记字节数", "超长省略" in info, "70KB body 被整段写进日志")


# ---------------------------------------------------------------------------
# 异常路径留痕 —— 此前四个 handler 全部零日志
# ---------------------------------------------------------------------------


async def _exercise_handlers():
    from fastapi.exceptions import RequestValidationError

    from app.exception.request import AuthException, PermissionException

    req = make_request(method="POST", path="/auth/login")

    await auth_exception_handler(req, AuthException(200, "用户信息身份认证失败, 请检查"))
    await permission_exception_handler(req, PermissionException(200, "对不起, 你没有足够的权限"))
    await validation_exception_handler(
        req, RequestValidationError(errors=[{"type": "missing", "loc": ("body", "name"),
                                             "msg": "field required"}]))

    try:
        raise ValueError("boom for selftest")
    except ValueError as exc:
        await global_execution_handler(req, exc)
    flush()


def test_exception_handlers_log():
    print("\n[异常路径留痕]")
    asyncio.run(_exercise_handlers())
    error = read("pity_error.log")

    check("401 未认证有日志", "401 未认证" in error)
    check("403 无权限有日志", "403 无权限" in error)
    check("101 参数校验失败有日志", "400 参数校验失败" in error)
    check("500 未处理异常有日志", "500 未处理异常" in error)
    check("500 日志带堆栈", "ValueError: boom for selftest" in error, "堆栈没落盘")
    check("异常日志带来源 IP", "client=1.2.3.4" in error)


def test_deploy_config():
    """
    部署侧两条硬约束 —— 都是实测踩出来的, 改错了日志会**静默**出问题
    (丢日志 / 容器重建即丢, 运行时完全看不出来)。
    """
    print("\n[部署配置防回归]")

    supervisor = os.path.join(BACKEND_ROOT, "ops", "supervisor.conf")
    if os.path.exists(supervisor):
        with open(supervisor, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        # 只看真正的 command 行 —— 注释里也提到 -w 2(解释为什么不许改回去)
        cmd_line = next((line for line in lines if line.strip().startswith("command=")), "")
        check("gunicorn 单 worker(-w 1)", "-w 1" in cmd_line and "-w 2" not in cmd_line,
              f"改回 -w 2 会因 loguru rotation 跨进程竞态丢日志(实测丢 12.5%): {cmd_line[:120]}")
    else:
        check("supervisor.conf 存在", False, supervisor)

    deploy = os.path.join(BACKEND_ROOT, "ops", "docker-compose.deploy.yaml")
    if os.path.exists(deploy):
        with open(deploy, "r", encoding="utf-8") as handle:
            compose = handle.read()
        check("deploy compose 挂了日志卷", "/pity/logs" in compose,
              "不挂卷的话容器重建 / 换镜像后日志全丢")
    else:
        check("docker-compose.deploy.yaml 存在", False, deploy)


def main():
    test_sink_configuration()
    test_level_routing()
    test_sanitize_payload()
    test_sanitize_url()
    test_request_info_not_leaking()
    test_exception_handlers_log()
    test_deploy_config()
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")
    print(f"(日志目录 {LOG_DIR} —— 临时目录, 可直接删)")


if __name__ == '__main__':
    main()
