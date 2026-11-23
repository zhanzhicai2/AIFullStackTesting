"""
持续集成(CI)自测脚本(**不依赖数据库**)

不依赖 pytest(后端目前没有测试框架), 直接跑:
    cd backend
    .venv/bin/python scripts/ci_selftest.py

覆盖(constitution 原则 V 门禁 + GATE-SEC 安全面):
- **凭据校验链正反例**: 摘要不匹配 / 前缀缺失 / 已删除 / 已停用 / 已过期 / 长期有效 /
  **前缀命中但摘要不符**(防止「前缀即放行」的错误实现)
- **凭据格式与明文约束**: 生成格式、前缀长度、**表里没有 `token` 列**(FR-008)
- **业务码与状态枚举**: 0/101/110/111/112/401/403 七档齐全、落同区段不碰 HTTP 段、
  `RunStatus` 六态齐全且 **`3`(测试未通过) 与 `5`(平台执行失败) 不混淆**(FR-015)
- **执行语义源码断言**: `run_test_plan` 有 `return report_dict` 且 `raise_on_error`
  默认 `False`; `ci_runner` 用 `asyncio.wait` 而非 `asyncio.wait_for`(后者超时会
  cancel, 违反 FR-011)
- **源码 AST 静态扫描**: CI 模块零出网(一期无回调)、零 `eval`/`exec`、
  无明文凭据落库 —— GATE-SEC 的机器可验证保证
- **跨端常量核对**(constitution 原则 III): `frontend/src/consts/ci.ts` 与后端
  `app/enums/CiEnum.py` 一致

**需要数据库的部分**(签发 / 触发 / 轮询 / 拒绝类 / 防重 / 重启恢复)在
`scripts/ci_e2e.py`。
"""
import ast
import os
import re
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crud.ci.CiIntegrationDao import CiIntegrationDao  # noqa: E402
from app.enums.CiEnum import (ALLOWED_URL_SCHEMES, CiErrorCode,  # noqa: E402
                              RunStatus, TOKEN_DEFAULT_EXPIRE_DAYS, TOKEN_PREFIX,
                              TOKEN_PREFIX_LEN, WAIT_TIMEOUT_DEFAULT_SEC,
                              WAIT_TIMEOUT_MAX_SEC)
from app.models.ci import PityCiIntegration, PityCiRun  # noqa: E402

FAILED = []

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


def cred(**kw):
    """构造校验链可用的凭据对象"""
    token = CiIntegrationDao.generate_token()
    base = dict(token_hash=CiIntegrationDao.compute_hash(token), token_prefix=token[:TOKEN_PREFIX_LEN],
                enabled=True, expires_at=None, deleted_at=0, id=1, project_id=1)
    base.update(kw)
    return SimpleNamespace(**base), token


# ---------------------------------------------------------------------------
# 凭据校验链
# ---------------------------------------------------------------------------


def test_credential_chain():
    print("== 凭据校验链(纯函数, 不查库) ==")
    # 合法凭据
    obj, token = cred()
    check("合法凭据通过", CiIntegrationDao.check_credential(obj, token) == "")
    # 摘要不匹配
    obj, _ = cred()
    check("摘要不匹配 → 无效",
          CiIntegrationDao.check_credential(obj, "pity_ci_" + "0" * 32) == "CI 凭据无效")
    # 前缀缺失(哪怕摘要对得上也要拒 —— 形态就不对)
    obj, token = cred()
    check("缺前缀 → 无效", CiIntegrationDao.check_credential(obj, token[len(TOKEN_PREFIX):])
          == "CI 凭据无效")
    # **前缀命中但摘要不符** —— 这是最容易写错的一条: 只比 token_prefix 就放行
    obj, _ = cred()
    obj.token_prefix = TOKEN_PREFIX + "abcdef"
    check("前缀命中但摘要不符 → 无效(前缀不参与校验)",
          CiIntegrationDao.check_credential(obj, TOKEN_PREFIX + "abcdef" + "0" * 22)
          == "CI 凭据无效")
    # 已删除
    obj, token = cred(deleted_at=1764000000000)
    check("已删除 → 无效", CiIntegrationDao.check_credential(obj, token) == "CI 凭据无效")
    # 已停用
    obj, token = cred(enabled=False)
    check("已停用 → 已停用", CiIntegrationDao.check_credential(obj, token) == "CI 凭据已停用")
    # 已过期
    obj, token = cred(expires_at=datetime.now() - timedelta(seconds=1))
    check("已过期 → 已过期", CiIntegrationDao.check_credential(obj, token) == "CI 凭据已过期")
    # 长期有效(决定 Q4): expires_at 为 None 永不过期
    obj, token = cred(expires_at=None)
    check("长期有效 → 通过", CiIntegrationDao.check_credential(obj, token) == "")
    # 未过期
    obj, token = cred(expires_at=datetime.now() + timedelta(days=30))
    check("未过期 → 通过", CiIntegrationDao.check_credential(obj, token) == "")
    # 空 token / None
    obj, _ = cred()
    check("空 token → 无效", CiIntegrationDao.check_credential(obj, "") == "CI 凭据无效")
    check("None token → 无效", CiIntegrationDao.check_credential(obj, None) == "CI 凭据无效")
    # 记录不存在(摘要查不到)
    check("记录不存在 → 无效", CiIntegrationDao.check_credential(None, "pity_ci_" + "a" * 32)
          == "CI 凭据无效")
    # 三种拒绝文案必须互不相同, 且都不回显凭据(SC-008 可区分)
    # 注意: 校验链**先比摘要再看状态**, 所以每个用例的记录与 token 必须来自同一次
    # cred() 调用 —— 交叉配对会先在摘要那一步就判成「无效」, 测不出状态分支
    _, t_ok = cred()
    o_off, t_off = cred(enabled=False)
    o_exp, t_exp = cred(expires_at=datetime.now() - timedelta(days=1))
    msgs = {"invalid": CiIntegrationDao.check_credential(None, t_ok),
            "off": CiIntegrationDao.check_credential(o_off, t_off),
            "expired": CiIntegrationDao.check_credential(o_exp, t_exp)}
    check("无效/停用/过期三种文案互不相同", len(set(msgs.values())) == 3, str(msgs))
    check("三种文案都不含凭据内容",
          all(TOKEN_PREFIX not in v and "pity_ci_" not in v for v in msgs.values()), str(msgs))


def test_token_format():
    print("== 凭据格式与明文约束 ==")
    token = CiIntegrationDao.generate_token()
    check("以 pity_ci_ 开头", token.startswith(TOKEN_PREFIX), token[:20])
    body = token[len(TOKEN_PREFIX):]
    check("正文 32 位十六进制", len(body) == 32 and re.fullmatch(r"[0-9a-f]{32}", body) is not None,
          body)
    check("总长 40 字符", len(token) == 40, str(len(token)))
    check("前缀长度 12", TOKEN_PREFIX_LEN == 12 and token[:TOKEN_PREFIX_LEN] == "pity_ci_" + body[:4])
    # 连续两次生成不得相同(128 bit 熵)
    check("两次生成不重复", CiIntegrationDao.generate_token() != CiIntegrationDao.generate_token())
    # 表里**没有** token 明文列 —— FR-008 / SC-007
    cols = set(PityCiIntegration.__table__.columns.keys())
    check("表里没有 `token` 列(只存摘要)", "token" not in cols, str(sorted(cols)))
    check("表里有 `token_hash` 列", "token_hash" in cols)
    check("表里有 `token_prefix` 列", "token_prefix" in cols)
    # 摘要是等值单向的: 摘要本身不能当凭据用
    h = CiIntegrationDao.compute_hash(token)
    check("摘要不能当凭据通过校验",
          CiIntegrationDao.check_credential(cred(token_hash=h)[0], h) == "CI 凭据无效")
    check("摘要长度 64(sha256 十六进制)", len(h) == 64)
    check("默认有效期 1 年(决定 Q4)", TOKEN_DEFAULT_EXPIRE_DAYS == 365)


# ---------------------------------------------------------------------------
# 业务码与状态枚举
# ---------------------------------------------------------------------------


def test_business_codes():
    print("== 业务码(七档齐全, 落同区段) ==")
    check("111 = 测试未通过", CiErrorCode.NOT_PASSED == 111)
    check("112 = 等待超时", CiErrorCode.WAIT_TIMEOUT == 112)
    check("与既有 110 相邻递增", CiErrorCode.NOT_PASSED == 110 + 1 and
          CiErrorCode.WAIT_TIMEOUT == 110 + 2)
    # 不碰 HTTP 段 —— CLAUDE.md「不要混入 200/300/500 这类 HTTP 段」
    for code in (CiErrorCode.NOT_PASSED, CiErrorCode.WAIT_TIMEOUT):
        check(f"{code} 不落在 HTTP 段(2xx/3xx/4xx/5xx)", not (200 <= code < 600), str(code))
    check("等待超时与未通过可区分(FR-015)",
          CiErrorCode.NOT_PASSED != CiErrorCode.WAIT_TIMEOUT)


def test_run_status():
    print("== 触发记录状态枚举 ==")
    expected = {"PENDING": 0, "RUNNING": 1, "SUCCESS": 2, "FAILED": 3, "TIMEOUT": 4, "ERROR": 5}
    for name, value in expected.items():
        check(f"RunStatus.{name} = {value}", getattr(RunStatus, name) == value)
    check("六态齐全", RunStatus.ALL == (0, 1, 2, 3, 4, 5), str(RunStatus.ALL))
    check("进行中 = {0,1}(重启恢复用)", RunStatus.IN_FLIGHT == (0, 1), str(RunStatus.IN_FLIGHT))
    check("终态 = {2,3,4,5}", RunStatus.TERMINAL == (2, 3, 4, 5), str(RunStatus.TERMINAL))
    # FR-015 / SC-006: 测试未通过 vs 平台执行失败必须可区分
    check("3(测试未通过) 与 5(平台执行失败) 是不同值", RunStatus.FAILED != RunStatus.ERROR)
    check("3 不在进行中集合", RunStatus.FAILED not in RunStatus.IN_FLIGHT)
    check("5 不在进行中集合", RunStatus.ERROR not in RunStatus.IN_FLIGHT)


def test_wait_defaults():
    print("== 等待语义默认值(决定 Q3) ==")
    from app.schema.ci import CiRunForm
    check("timeout_sec 默认 300", CiRunForm().timeout_sec == WAIT_TIMEOUT_DEFAULT_SEC)
    check("wait 默认 false(轮询为主推姿势)", CiRunForm().wait is False)
    check("timeout_sec 超上限被拒", _form_error(timeout_sec=WAIT_TIMEOUT_MAX_SEC + 1) is not None)
    check("timeout_sec 低于下限被拒", _form_error(timeout_sec=0) is not None)
    check("timeout_sec 边界 1800 通过", _form_error(timeout_sec=WAIT_TIMEOUT_MAX_SEC) is None)
    check("外部构建号超长被拒", _form_error(external_build_id="x" * 65) is not None)


def _form_error(**kw):
    """返回校验错误文案, 通过则返回 None"""
    from pydantic import ValidationError
    from app.schema.ci import CiRunForm
    try:
        CiRunForm(**kw)
        return None
    except ValidationError as e:
        return str(e)


# ---------------------------------------------------------------------------
# 执行语义源码断言
# ---------------------------------------------------------------------------


def _func_source(path: str, func_name: str) -> str:
    """用 AST 取出某个函数的源码段(比切行号稳, 不受上方插入代码影响)"""
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    return ""


def test_run_test_plan_signature():
    print("== run_test_plan 返回值与开关(research D4) ==")
    body = _func_source("app/core/executor.py", "run_test_plan")
    check("run_test_plan 存在", bool(body))
    check("成功路径 return report_dict(结果不再被丢弃)", "return report_dict" in body)
    check("带 raise_on_error 关键字开关", "raise_on_error" in body)
    check("raise_on_error 默认 False(既有 cron / plan/execute 行为不变)",
          re.search(r"raise_on_error\s*:\s*bool\s*=\s*False", body) is not None)
    check("开关是关键字-only(防止位置传参挤掉 executor)", re.search(
        r"executor\s*:\s*int\s*=\s*0\s*,\s*\*", body) is not None)
    check("计划不存在时 raise_on_error 下会上抛", "raise Exception" in body)
    check("通知失败不把已跑完的执行判成失败(独立 try)",
          "不影响执行结果" in body)


def test_ci_runner_uses_asyncio_wait():
    print("== ci_runner 等待语义(research D3 / FR-011) ==")
    path = os.path.join(ROOT, "app", "core", "ci_runner.py")
    check("ci_runner 存在", os.path.isfile(path), path)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        src = f.read()
    check("用 asyncio.wait(超时不取消)", "asyncio.wait(" in src)
    check("不用 asyncio.wait_for(它超时会 cancel, 违反 FR-011)",
          "asyncio.wait_for(" not in src)
    check("任务先 ensure_future 包成 Task(3.10+ 传裸协程会 DeprecationWarning)",
          "ensure_future(" in src or "create_task(" in src)
    check("超时任务有强引用防 GC", "strong" in src.lower() or "_running" in src
          or "REFS" in src or "_tasks" in src)


def test_lifespan_recovery():
    print("== 重启终态恢复(FR-031) ==")
    with open(os.path.join(ROOT, "app", "__init__.py"), encoding="utf-8") as f:
        src = f.read()
    check("lifespan 调用 recover_stale_runs", "recover_stale_runs" in src)
    check("恢复放在 create_table 之后", src.find("create_table()") < src.find("recover_stale_runs"))
    check("恢复失败不抛(不拖垮启动)",
          re.search(r'startup\.(?:exception|warning)\(f?"ci run 终态恢复失败', src) is not None)


def test_cipermission():
    print("== CIPermission(research D2) ==")
    with open(os.path.join(ROOT, "app", "routers", "__init__.py"), encoding="utf-8") as f:
        src = f.read()
    check("存在 CIPermission 类", "class CIPermission" in src)
    ci_body = src.split("class CIPermission")[1].split("async def get_session")[0]
    check("读同名 token header", 'token: str = Header' in ci_body)
    check("按前缀分流且引用 TOKEN_PREFIX 常量(不硬编码字面量)", "TOKEN_PREFIX" in ci_body)
    check("返回结构带 ci_integration(作用域)", 'user_info["ci_integration"]' in ci_body)
    # Permission() 本体未被改成识别 CI 凭据
    check("Permission 仍走 JWT(UserToken.parse_token)", "UserToken.parse_token" in src)
    check("CIPermission 不解析 JWT(不与 Permission 混用)",
          "UserToken.parse_token" not in ci_body)


# ---------------------------------------------------------------------------
# 源码静态扫描
# ---------------------------------------------------------------------------


def test_static_source_scan():
    print("== 源码 AST 静态扫描(零出网 / 零执行 / 无明文落库) ==")
    targets = [
        "app/enums/CiEnum.py",
        "app/models/ci.py",
        "app/schema/ci.py",
        "app/core/ci_runner.py",
        "app/crud/ci/CiIntegrationDao.py",
        "app/crud/ci/CiRunDao.py",
        "app/routers/ci/integration.py",
        "app/routers/ci/run.py",
    ]
    missing = [t for t in targets if not os.path.isfile(os.path.join(ROOT, t))]
    check("CI 模块文件齐全", not missing, str(missing))
    forbidden_imports = ("aiohttp", "httpx", "requests", "urllib.request", "http.client", "socket")
    forbidden_calls = ("eval", "exec")
    found = []
    for rel in targets:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name.startswith(forbidden_imports):
                        found.append(f"{rel}: import {n.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith(forbidden_imports):
                    found.append(f"{rel}: from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    found.append(f"{rel}: {node.func.id}()")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in forbidden_calls:
                    found.append(f"{rel}: {node.func.attr}()")
    check("CI 模块零出网 import/调用、零 eval/exec", not found, str(found))

    # 一期零出网(决定 Q5): callback_url 只存不发 —— 没有任何发送调用
    cb_found = []
    for rel in targets:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r"callback_url", text):
            line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end())]
            if re.search(r"(post|get|put|request|send|fetch|urlopen)\s*\(", line, re.I):
                cb_found.append(f"{rel}: {line.strip()}")
    check("callback_url 一期只存不发(无发送调用)", not cb_found, str(cb_found))

    # 明文凭据不得出现在任何落库赋值里: `token =` 后面直接跟列赋值
    leak = []
    for rel in targets:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r"\.token\s*=\s*", text):
            line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end())]
            # 允许 `token = cls.generate_token()` 这类局部变量, 禁止赋给 model 列
            if re.search(r"\bmodel\.\w*token\w*\s*=", line) or re.search(
                    r"data\.\w*token\w*\s*=", line):
                leak.append(f"{rel}: {line.strip()}")
    check("没有把明文 token 写进任何列", not leak, str(leak))

    # 日志语句里不得出现完整明文 token 的拼接
    log_leak = []
    for rel in targets:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if re.search(r"log\.(info|warning|error|debug|exception)\(", line) and \
                        re.search(r"token\b(?!\s*(=|hash|prefix|[:_]))", line) and \
                        not re.search(r"token_hash|token_prefix|prefix=|\{token\[|generate_token",
                                      line):
                    log_leak.append(f"{rel}:{i}: {line.strip()}")
    check("日志里没有完整凭据", not log_leak, str(log_leak))


def test_no_permission_mutation():
    print("== Permission() 未被改动(既有全站鉴权) ==")
    with open(os.path.join(ROOT, "app", "routers", "__init__.py"), encoding="utf-8") as f:
        src = f.read()
    perm_body = src.split("class Permission:")[1].split("class CIPermission")[0]
    check("Permission 仍校验角色", "self.role" in perm_body)
    check("Permission 仍查用户", "UserDao.query_user" in perm_body)
    check("Permission 不识别 pity_ci_ 前缀", TOKEN_PREFIX not in perm_body)


# ---------------------------------------------------------------------------
# 跨端常量
# ---------------------------------------------------------------------------


def test_cross_endpoint_constants():
    """constitution 原则 III: 前端镜像 consts/ci.ts 与后端权威定义一致"""
    print("== 跨端常量核对(前端镜像) ==")
    frontend_file = os.path.join(ROOT, "..", "frontend", "src", "consts", "ci.ts")
    check("前端镜像文件存在", os.path.isfile(frontend_file), frontend_file)
    if not os.path.isfile(frontend_file):
        return
    with open(frontend_file, encoding="utf-8") as f:
        text = f.read()
    check("前端指认后端权威", "backend/app/enums/CiEnum.py" in text)
    check("前端 NOT_PASSED = 111", f"NOT_PASSED: {CiErrorCode.NOT_PASSED}" in text)
    check("前端 WAIT_TIMEOUT = 112", f"WAIT_TIMEOUT: {CiErrorCode.WAIT_TIMEOUT}" in text)
    check("前端 TOKEN_PREFIX 一致", f"'{TOKEN_PREFIX}'" in text)
    check("前端超时上限一致", f"CI_WAIT_TIMEOUT_MAX_SEC = {1800}" in text)
    # 六态文案与颜色都存在, 且 3/5 文案不同(FR-015 的前端一半)
    check("前端六态文案齐全", all(f"{v}:" in text for v in (0, 1, 2, 3, 4, 5)))
    m = re.search(r"CI_RUN_STATUS_LABELS[\s\S]*?\};", text)
    check("前端 3 与 5 文案不同(测试未通过 vs 执行失败)",
          m is not None and "未通过" in m.group(0) and "执行失败" in m.group(0)
          and m.group(0).split("3:")[1].split("\n")[0] != m.group(0).split("5:")[1].split("\n")[0]
          if m else False)
    check("前端凭据占位符存在(示例片段不回显真凭据)", "YOUR_PITY_CI_TOKEN" in text)


def test_integration_model_constraints():
    print("== 表结构约束(data-model.md §2) ==")
    cols = PityCiIntegration.__table__.columns
    check("integration.token_hash 唯一", cols["token_hash"].unique)
    check("integration.token_hash NOT NULL", not cols["token_hash"].nullable)
    check("integration.name 上限 32", cols["name"].type.length == 32)
    check("integration.callback_url 上限 255", cols["callback_url"].type.length == 255)
    check("integration.project_id 有索引", cols["project_id"].index)
    rcols = PityCiRun.__table__.columns
    check("run.external_build_id 上限 64", rcols["external_build_id"].type.length == 64)
    check("run.error_msg 上限 500", rcols["error_msg"].type.length == 500)
    check("run.report_ids 是 TEXT(可存多条报告 id)", rcols["report_ids"].type.length is None)
    check("run.status NOT NULL 默认 0", not rcols["status"].nullable and rcols["status"].default
          is not None)
    idx_names = [i.name for i in PityCiRun.__table__.indexes]
    check("run 有 (project_id, created_at) 复合索引(SC-009)",
          any("project_created" in n for n in idx_names), str(idx_names))
    check("run 有 waited 列(区分两种等待语义)", "waited" in rcols)


def test_snippet_placeholders():
    """接入示例片段: 凭据必须是占位符, 绝不能回显真实明文(T039 / FR-027 / D10)"""
    print("== 接入示例片段(凭据占位符) ==")
    path = os.path.join(ROOT, "..", "frontend", "src", "pages", "ci", "SnippetsPanel.tsx")
    check("SnippetsPanel 存在", os.path.isfile(path), path)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    check("两段流水线示例都在", "jenkinsfile" in text and "ghActions" in text)
    check("Jenkins 用 httpRequest + token header",
          "httpRequest" in text and "name: 'token'" in text)
    check("GitHub Actions 用 curl + token header", "curl -sS" in text and '-H "token:' in text)
    check("凭据位置是占位符常量(引用 @/consts/ci)", "CI_TOKEN_PLACEHOLDER" in text)
    check("片段里带 plan_id", "plan_id" in text)
    check("片段里带 wait/timeout(等待语义示例)", '"wait": true' in text and "timeout_sec" in text)
    # **最关键的一条**: 源码里不得出现「pity_ci_ + 32 位 hex」的真实凭据形态
    check("源码里没有真实凭据形态",
          re.search(r"pity_ci_[0-9a-f]{32}", text) is None)
    # 也不能把占位符拼成 Groovy 插值(那会被当成变量名, 复制出去是坏片段)
    check("占位符没有被拼进 Groovy 插值 ${...}",
          "${YOUR_PITY_CI_TOKEN}" not in text and '"${CI_TOKEN_PLACEHOLDER}"' not in text)


def test_security_review_fixes():
    """安全审查 F1/F3/F4/F5 的回归断言 —— 修完必须留门禁, 否则会被改回去"""
    print("== 安全审查修复(F1 链接注入 / F3 脱敏 / F4 scheme / F5 误改) ==")
    from pydantic import ValidationError
    from app.schema.ci import CiIntegrationForm, CiRunForm, check_url_field

    def rejected(form_cls, **kw):
        try:
            form_cls(**kw)
            return None
        except ValidationError as e:
            return e.errors()[0]["msg"]

    # --- F1: external_url 是外部可控、会被渲染成链接的值 ---
    bad_urls = ["javascript:alert(1)", "data:text/html,<script>x</script>",
                "ftp://evil/x", "//evil.com/x", "vbscript:msgbox(1)"]
    for u in bad_urls:
        err = rejected(CiRunForm, external_url=u)
        check(f"F1 拒绝 external_url={u[:28]}", err is not None, str(err))
    check("F1 放行 http/https", rejected(CiRunForm, external_url="https://jenkins/job/1") is None)
    check("F1 放行空值", rejected(CiRunForm, external_url=None) is None)

    # --- F4: callback_url 一期不发, 但白名单现在就上 ---
    for u in ["javascript:alert(1)", "data:text/html,x"]:
        err = rejected(CiIntegrationForm, project_id=1, name="x", callback_url=u)
        check(f"F4 拒绝 callback_url={u[:24]}", err is not None, str(err))
    check("F4 放行 https 回调", rejected(CiIntegrationForm, project_id=1, name="x",
                                        callback_url="https://jenkins/hook") is None)
    check("F4 放行空回调", rejected(CiIntegrationForm, project_id=1, name="x",
                                   callback_url=None) is None)

    # --- F3: error_msg 脱敏(不只是截断) ---
    from app.crud.ci.CiRunDao import CiRunDao
    check("F3 URL query 被抹掉",
          "***" in CiRunDao.clip_error("timeout https://a.com/v1?access_token=abc&x=1") and
          "abc" not in CiRunDao.clip_error("timeout https://a.com/v1?access_token=abc&x=1"))
    scrubbed = CiRunDao.clip_error("auth failed Authorization: Bearer eyJhbGciOi.xxx")
    check("F3 Bearer JWT 被吃掉", "eyJ" not in scrubbed and "***" in scrubbed, scrubbed)
    check("F3 password= 被抹掉",
          "hunter2" not in CiRunDao.clip_error("连接失败 password=hunter2"))
    check("F3 token= 被抹掉",
          "pity_ci_" not in CiRunDao.clip_error("header token=pity_ci_9f2c4e8a1b7d0c3f"))
    plain = "查询用例失败: 用例id: 999 不存在"
    check("F3 普通文本不被误伤", CiRunDao.clip_error(plain) == plain)
    check("F3 截断到 500", len(CiRunDao.clip_error("x" * 999)) == 500)
    check("F3 None 保持 None", CiRunDao.clip_error(None) is None)

    # --- F5: token_hash 不进操作日志, 靠 __fields__ 过滤(隐性依赖) ---
    fields = [f.name for f in PityCiIntegration.__fields__]
    check("F5 __fields__ 不含 token_hash", "token_hash" not in fields, str(fields))
    check("F5 __fields__ 不含 token_prefix", "token_prefix" not in fields, str(fields))
    from app.crud import Mapper
    from app.models import async_session  # noqa: F401  (确保 model 已注册)
    check("F5 models 里有防误改注释",
          "不能加 `token_hash`" in open(os.path.join(ROOT, "app", "models", "ci.py"),
                                        encoding="utf-8").read())

    # --- 前端纵深: isSafeHttpUrl ---
    fe = os.path.join(ROOT, "..", "frontend", "src", "consts", "ci.ts")
    check("前端镜像有 scheme 白名单", "CI_ALLOWED_URL_SCHEMES" in open(fe, encoding="utf-8").read())
    panel = os.path.join(ROOT, "..", "frontend", "src", "pages", "ci", "RunHistoryPanel.tsx")
    panel_src = open(panel, encoding="utf-8").read()
    check("历史面板渲染链接前过 isSafeHttpUrl", "isSafeHttpUrl(r.external_url)" in panel_src)
    check("历史面板不再裸用 r.external_url 做 href判断",
          "return r.external_url ?" not in panel_src)
    check("scheme 白名单两端一致(都只 http/https)",
          "http" in open(fe, encoding="utf-8").read() and "https" in
          open(fe, encoding="utf-8").read() and ALLOWED_URL_SCHEMES == ("http", "https"))


def main():
    test_credential_chain()
    test_token_format()
    test_business_codes()
    test_run_status()
    test_wait_defaults()
    test_run_test_plan_signature()
    test_ci_runner_uses_asyncio_wait()
    test_lifespan_recovery()
    test_cipermission()
    test_no_permission_mutation()
    test_integration_model_constraints()
    test_static_source_scan()
    test_cross_endpoint_constants()
    test_snippet_placeholders()
    test_security_review_fixes()
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()
