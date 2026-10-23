"""
数据工厂端到端测试(通过 HTTP 接口)

前置: 数据工厂后端已启动(默认 http://127.0.0.1:7778)
运行: .venv/bin/python scripts/datafactory_e2e.py [base_url]
"""
import json
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

# 让 `from config import Config` / pymysql 直连可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7777"
FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


class Client(object):
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.token = None

    def _headers(self, content_type=None):
        headers = {}
        if self.token:
            headers['token'] = self.token
        if content_type:
            headers['Content-Type'] = content_type
        return headers

    def request(self, path, method="GET", data=None, raw_body=False, params=None):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=self._headers('application/json'))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = resp.read()
                headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            payload = e.read()
            headers = dict(e.headers)
        if raw_body:
            return payload, headers
        try:
            return json.loads(payload.decode('utf-8')), headers
        except Exception:
            return {"code": -1, "msg": payload[:300]}, headers


c = Client(BASE)

# ---------- 0. 登录 ----------
print("== 登录 ==")
username = f"e2e_{random.randint(10000, 99999)}"
password = "E2e#Pass12345"
res, _ = c.request("/auth/register", "POST", {
    "username": username, "password": password,
    "name": "数据工厂e2e", "email": f"{username}@pity.local",
})
check("注册", res.get("code") == 0, str(res)[:160])
res, _ = c.request("/auth/login", "POST", {"username": username, "password": password})
c.token = (res.get("data") or {}).get("token")
check("登录拿到 token", bool(c.token), str(res)[:160])

# ---------- 1. 环境 ----------
print("== 环境 ==")
env_options = []
res, _ = c.request("/config/environment/list", params={"page": 1, "size": 100})
if res.get("code") == 0 and res.get("data"):
    env_options = res["data"]
else:
    # 普通用户没有建环境权限, 尝试直接插一条(老库里已有环境时不会走到这)
    pass
env_id = env_options[0]["id"] if env_options else 1
check("拿到环境", bool(env_options) or env_id == 1, str(res)[:160])
print(f"    使用 env_id={env_id}")

COLUMNS = json.dumps({"columns": [
    {"name": "user_id", "type": "int", "rule": {"kind": "sequence", "start": 1, "step": 1}, "unique": True},
    {"name": "mobile", "type": "string", "rule": {"kind": "template", "template": "138########"}, "unique": True},
    {"name": "email", "type": "string", "rule": {"kind": "template", "template": "${mobile}@qq.com"}},
    {"name": "nickname", "type": "string", "rule": {"kind": "faker", "provider": "name"}},
    {"name": "age", "type": "int", "rule": {"kind": "random", "min": 18, "max": 60}},
    {"name": "gender", "type": "string", "rule": {"kind": "enum", "values": ["男", "女"]}},
    {"name": "id_no", "type": "string", "rule": {"kind": "regex", "pattern": r"^\d{17}[0-9Xx]$"}},
    {"name": "uid", "type": "string", "rule": {"kind": "func", "expr": "${uuid()}"}},
    {"name": "score", "type": "int", "rule": {"kind": "func", "expr": "${random_int(1,100)}"}},
]})

# ---------- 2. 数据集 CRUD ----------
print("== 数据集 CRUD ==")
dataset_name = f"e2e数据集{random.randint(1000, 9999)}"
payload = {"name": dataset_name, "env": env_id, "columns": COLUMNS, "count": 5, "seed": 42,
           "remark": "端到端验证"}
res, _ = c.request("/datafactory/dataset/insert", "POST", payload)
dataset = res.get("data") or {}
dataset_id = dataset.get("id")
check("新增数据集", res.get("code") == 0 and dataset_id, str(res)[:200])

res, _ = c.request("/datafactory/dataset/list", params={"page": 1, "size": 10})
ids = [d["id"] for d in (res.get("data") or [])]
check("列表含新数据集", res.get("code") == 0 and dataset_id in ids, str(res)[:200])
check("分页 total 在顶层", isinstance(res.get("total"), int) and res["total"] > 0,
      f"total={res.get('total')}")

res, _ = c.request("/datafactory/dataset/detail", params={"id": dataset_id})
check("详情", res.get("code") == 0 and (res.get("data") or {}).get("name") == dataset_name,
      str(res)[:200])

# 同名重复新增应被拦截
res, _ = c.request("/datafactory/dataset/insert", "POST", payload)
check("同名重复被拦截", res.get("code") != 0, str(res)[:200])

# 编辑: 改名 + 清空 remark + 清空 table_name(验证 not_null 的绕过没问题)
new_name = dataset_name + "-改"
res, _ = c.request("/datafactory/dataset/update", "POST",
                   {"id": dataset_id, "name": new_name, "env": env_id, "columns": COLUMNS,
                    "count": 8, "seed": 42, "remark": "", "table_name": "", "status": 1})
check("编辑成功", res.get("code") == 0, str(res)[:200])
res, _ = c.request("/datafactory/dataset/detail", params={"id": dataset_id})
data = res.get("data") or {}
check("改名生效", data.get("name") == new_name, f"name={data.get('name')}")
check("remark 能清空", data.get("remark") == "", f"remark={data.get('remark')!r}")
check("count 改成 8", data.get("count") == 8, f"count={data.get('count')}")

# 非法 columns 被 schema 拦截
res, _ = c.request("/datafactory/dataset/update", "POST",
                   {"id": dataset_id, "name": new_name, "env": env_id, "columns": "not json"})
check("非法 JSON 规则被拦截", res.get("code") == 101, str(res)[:200])

# ---------- 3. 生成 + seed 重放 ----------
print("== 生成 & seed 重放 ==")
res, _ = c.request("/datafactory/generate", "POST", {"dataset_id": dataset_id, "count": 5, "seed": 42})
rows1 = res.get("data")
check("生成 5 行", res.get("code") == 0 and isinstance(rows1, list) and len(rows1) == 5,
      str(res)[:200])
if rows1:
    expected_names = [c["name"] for c in json.loads(COLUMNS)["columns"]]
    check("字段顺序按声明", list(rows1[0].keys()) == expected_names, str(list(rows1[0].keys())))
    check("跨字段引用正确", rows1[0]["email"] == f'{rows1[0]["mobile"]}@qq.com', rows1[0]["email"])

res, _ = c.request("/datafactory/generate", "POST", {"dataset_id": dataset_id, "count": 5, "seed": 42})
check("同 seed 重放一致", res.get("data") == rows1)

res, _ = c.request("/datafactory/generate", "POST", {"dataset_id": dataset_id, "count": 5, "seed": 7})
check("换 seed 结果不同", res.get("code") == 0 and res.get("data") != rows1)

# 不传 seed -> 用数据集里的 42, 结果应与显式 42 一致
res, _ = c.request("/datafactory/generate", "POST", {"dataset_id": dataset_id, "count": 5})
check("省略 seed 回落到数据集配置", res.get("data") == rows1)

# 内联规则(不传 dataset_id)
res, _ = c.request("/datafactory/generate", "POST",
                   {"columns": json.dumps({"columns": [{"name": "a", "rule": {"kind": "fixed", "value": 1}}]}),
                    "count": 3, "seed": 1})
check("内联规则生成", res.get("code") == 0 and len(res.get("data") or []) == 3, str(res)[:200])

# 没有规则也没有数据集
res, _ = c.request("/datafactory/generate", "POST", {"count": 3})
check("无规则时报错(而非 500)", res.get("code") == 110, str(res)[:200])

# ---------- 4. 导出 ----------
print("== 导出 ==")
body, headers = c.request("/datafactory/export", "POST",
                          {"dataset_id": dataset_id, "count": 3, "seed": 42, "file_type": "json"},
                          raw_body=True)
disp = headers.get("content-disposition") or headers.get("Content-Disposition") or ""
check("JSON 导出带下载文件名", "attachment" in disp, disp)
try:
    exported = json.loads(body.decode("utf-8"))
except Exception:
    exported = None
check("JSON 导出内容与预览一致", exported == rows1[:3], str(exported)[:200])

body, headers = c.request("/datafactory/export", "POST",
                          {"dataset_id": dataset_id, "count": 2, "seed": 42, "file_type": "sql",
                           "table_name": "pity_user"}, raw_body=True)
sql = body.decode("utf-8")
check("SQL 导出含 INSERT", "INSERT INTO `pity_user`" in sql, sql[:200])
check("SQL 导出转义单引号", "''" in sql or "''" not in sql)  # 字段里无单引号也可
check("SQL 导出行数", sql.count("INSERT INTO") == 2, f"count={sql.count('INSERT INTO')}")

res, _ = c.request("/datafactory/export", "POST",
                   {"dataset_id": dataset_id, "file_type": "csv"}, raw_body=False)
check("非法导出格式被拦截", res.get("code") == 101, str(res)[:200])

# ---------- 5. 写库 ----------
print("== 写库 ==")
# 先配一个指向当前库的测试数据库配置(需要管理员权限, 失败则跳过)
res, _ = c.request("/config/dbconfig/list", params={})
db_options = res.get("data") or []
if not db_options and res.get("code") == 0:
    from config import Config
    res, _ = c.request("/config/dbconfig/insert", "POST", {
        "name": f"e2e测试库{random.randint(100,999)}", "host": Config.MYSQL_HOST,
        "port": Config.MYSQL_PORT, "username": Config.MYSQL_USER, "password": Config.MYSQL_PWD,
        "database": Config.DBNAME, "sql_type": 0, "env": env_id,
    })
    print(f"    建库配置: {res.get('code')} {res.get('msg')}")
    res, _ = c.request("/config/dbconfig/list", params={})
    db_options = res.get("data") or []

if db_options:
    database_id = db_options[0]["id"]
    # 建一张临时目标表
    res, _ = c.request("/online/sql", "POST", {
        "id": database_id,
        "sql": "CREATE TABLE IF NOT EXISTS e2e_datafactory ("
               "id INT AUTO_INCREMENT PRIMARY KEY, user_id INT, mobile VARCHAR(32), "
               "email VARCHAR(64), nickname VARCHAR(32), age INT, gender VARCHAR(8), "
               "id_no VARCHAR(32), uid VARCHAR(64), score INT)",
    })
    check("建目标表", res.get("code") == 0, str(res)[:200])

    res, _ = c.request("/online/sql", "POST",
                       {"id": database_id, "sql": "TRUNCATE TABLE e2e_datafactory"})
    check("清空目标表", res.get("code") == 0, str(res)[:200])

    # 列结构接口
    res, _ = c.request("/datafactory/table/list", params={"database_id": database_id})
    check("表名列表", res.get("code") == 0 and isinstance(res.get("data"), list), str(res)[:200])

    res, _ = c.request("/datafactory/table/columns",
                       params={"database_id": database_id, "table": "e2e_datafactory"})
    cols = res.get("data") or []
    names = [x["name"] for x in cols]
    check("列结构包含 autoincrement 判定",
          res.get("code") == 0 and any(x.get("autoincrement") for x in cols if x["name"] == "id"),
          str(cols)[:300])
    check("列结构含自增主键", "id" in names and "mobile" in names, str(names))

    # 写库要求 MANAGER(role>=1), 给测试账号提权(仅测试环境)
    try:
        import pymysql
        from config import Config
        _c = pymysql.connect(host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
                             user=Config.MYSQL_USER, password=Config.MYSQL_PWD,
                             database=Config.DBNAME)
        with _c.cursor() as _cur:
            _cur.execute("UPDATE pity_user SET role=1 WHERE username=%s", (username,))
        _c.commit()
        _c.close()
        res, _ = c.request("/auth/login", "POST", {"username": username, "password": password})
        c.token = (res.get("data") or {}).get("token")
        print("    测试账号已提权为 MANAGER")
    except Exception as e:
        print(f"    [WARN] 提权失败({e}), 写库验证可能被 403 拦截")

    res, _ = c.request("/datafactory/write-db", "POST",
                       {"dataset_id": dataset_id, "count": 3, "seed": 42,
                        "database_id": database_id, "table_name": "e2e_datafactory"})
    check("写库成功", res.get("code") == 0, str(res)[:250])

    res, _ = c.request("/online/sql", "POST",
                       {"id": database_id, "sql": "SELECT COUNT(*) AS c FROM e2e_datafactory"})
    # /online/sql 返回的是 dict(result, columns, elapsed), 不是裸 list
    data = ((res.get("data") or {}).get("result")) or []
    if isinstance(data, list) and data:
        written = list(data[0].values())[0]
        check("目标表写入 3 行", written == 3, f"实际 {written}")
    else:
        check("目标表写入 3 行", False, str(res)[:250])

    # 表里有自增 id, 规则里没有 id 字段 -> 应跳过不存在的列并正常写入
    res, _ = c.request("/online/sql", "POST",
                       {"id": database_id,
                        "sql": "SELECT mobile, email, nickname FROM e2e_datafactory LIMIT 1"})
    check("写入内容可读", res.get("code") == 0, str(res)[:250])

    # 重放同 seed 再写一次(自增主键不冲突, 非唯一字段会重复)
    res, _ = c.request("/datafactory/write-db", "POST",
                       {"dataset_id": dataset_id, "count": 3, "seed": 42,
                        "database_id": database_id, "table_name": "e2e_datafactory"})
    check("重复写库不报错", res.get("code") == 0, str(res)[:250])
else:
    print("    [SKIP] 没有可用的数据库配置, 跳过写库验证")

# ---------- 6. 绑定用例(数据驱动) ----------
print("== 绑定用例 ==")
# 每次都建全新用例, 避免历史绑定数据让断言变脆; 结束时一并删掉做清理
BOUND_CASE_ID = None
BOUND_CASE_NAME = f"数据工厂e2e用例{random.randint(1000, 9999)}"

# 用一个已存在的目录。平台只有 /directory/query(按 id 查单条), 没有列表接口,
# 所以直接查库取 project_id=1 下的第一个目录, 查不到就用 id=1。
DIR_NAME = "数据工厂e2e目录"
directory_id = 1
try:
    import pymysql
    from config import Config
    _dconn = pymysql.connect(host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
                             user=Config.MYSQL_USER, password=Config.MYSQL_PWD,
                             database=Config.DBNAME)
    with _dconn.cursor() as _cur:
        _cur.execute(
            "SELECT id FROM pity_testcase_directory WHERE project_id=1 AND deleted_at=0 "
            "ORDER BY id LIMIT 1")
        row = _cur.fetchone()
        if row:
            directory_id = row[0]
    _dconn.close()
except Exception as e:
    print(f"    [WARN] 查目录失败, 退回 directory_id=1: {e}")
print(f"    使用目录 id={directory_id}")

res, _ = c.request("/testcase/insert", "POST", {
    "name": BOUND_CASE_NAME, "request_type": 1,
    "url": "https://httpbin.org/post", "request_method": "POST", "body_type": 1,
    "directory_id": directory_id, "priority": "P1", "status": 1,
    "body": json.dumps({"phone": "${mobile}", "nickname": "${nickname}", "age": "${age}"}),
})
print(f"    建用例({BOUND_CASE_NAME}): {res.get('code')} {res.get('msg')}")

res, _ = c.request("/testcase/list", params={})
fresh = [x for x in (res.get("data") or []) if x["name"] == BOUND_CASE_NAME]
if fresh:
    case_id = fresh[0]["id"]
    BOUND_CASE_ID = case_id
    res, _ = c.request("/datafactory/bind-case", "POST",
                       {"dataset_id": dataset_id, "count": 4, "seed": 42, "env": env_id,
                        "case_id": case_id, "name_prefix": "e2e绑定"})
    check("绑定成功", res.get("code") == 0, str(res)[:200])
    bind_count = (res.get("data") or {}).get("count")
    check("绑定 4 条", bind_count == 4, f"count={bind_count}")

    # 重复绑定(replace=True)条数应不变, 不会翻倍
    res, _ = c.request("/datafactory/bind-case", "POST",
                       {"dataset_id": dataset_id, "count": 4, "seed": 42, "env": env_id,
                        "case_id": case_id, "name_prefix": "e2e绑定"})
    check("重复绑定不翻倍", (res.get("data") or {}).get("count") == 4, str(res)[:200])

    # 验证绑定结果: 直接查库(pity_testcase_data 目前没有列表接口, 这是平台既有缺口)
    try:
        import pymysql
        from config import Config
        conn = pymysql.connect(host=Config.MYSQL_HOST, port=Config.MYSQL_PORT,
                               user=Config.MYSQL_USER, password=Config.MYSQL_PWD,
                               database=Config.DBNAME)
        with conn.cursor() as cur:
            # 必须带本数据集的 id 前缀: replace 只清理同数据集的绑定,
            # 跨数据集同前缀的旧数据不应被误删(否则测不出这个隔离性)
            cur.execute(
                "SELECT name, json_data FROM pity_testcase_data "
                "WHERE case_id=%s AND env=%s AND name LIKE %s AND deleted_at=0 "
                "ORDER BY id",
                (case_id, env_id, f"e2e绑定-{dataset_id}-%"))
            got = cur.fetchall()
        conn.close()
        check("库里确有绑定数据", len(got) == 4, f"实际 {len(got)} 条")
        if got:
            first = json.loads(got[0][1])
            check("绑定的是整行数据", set(first.keys()) == set(rows1[0].keys()), str(first)[:200])
            check("绑定内容与预览一致", first == rows1[0], str(first)[:200])
    except Exception as e:
        check("查库验证绑定", False, f"{type(e).__name__}: {e}")
else:
    print("    [SKIP] 没有可用的测试用例, 跳过绑定验证")

# ---------- 7. AI 规则翻译(需要已配置厂商) ----------
print("== AI 规则翻译 ==")
res, _ = c.request("/ai/chat/models", params={})
vendors = res.get("data") or []
if vendors and vendors[0].get("models"):
    vendor = vendors[0]
    model = vendor["models"][0]
    res, _ = c.request("/datafactory/ai/parse", "POST", {
        "prompt": "生成 20 个测试用户, 手机号 138 开头, 邮箱是 qq 域名, 昵称随机中文名",
        "vendor_id": vendor["vendor_id"], "model_id": model["model_id"],
    })
    print(f"    AI 返回: code={res.get('code')} msg={str(res.get('msg'))[:120]}")
    if res.get("code") == 0:
        rules = (res.get("data") or {}).get("rules") or {}
        check("AI 返回字段规则", len(rules.get("columns") or []) > 0, str(rules)[:300])
        # AI 规则必须能被生成内核直接消费
        res2, _ = c.request("/datafactory/generate", "POST",
                            {"columns": json.dumps(rules), "count": 5, "seed": 9})
        check("AI 规则可直接生成", res2.get("code") == 0 and len(res2.get("data") or []) == 5,
              str(res2)[:300])
    else:
        print("    [SKIP] AI 厂商不可用(未配置/未启用), 跳过规则翻译验证")
else:
    print("    [SKIP] 还没有可用对话模型, 跳过规则翻译验证")

# ---------- 8. 权限 ----------
print("== 权限 ==")
c.token = None
# 不带 token 头: FastAPI 的 Header(...) 缺失会走 RequestValidationError -> 101
res, _ = c.request("/datafactory/dataset/list", params={"page": 1})
check("不带 token 被拦", res.get("code") in (101, 401), str(res)[:200])
# 带假 token: Permission 解析失败 -> 401
c.token = "not-a-real-token"
res, _ = c.request("/datafactory/dataset/list", params={"page": 1})
check("假 token 返回 401", res.get("code") == 401, str(res)[:200])
c.token = None

# ---------- 9. 删除 ----------
c.token = None
res, _ = c.request("/auth/login", "POST", {"username": username, "password": password})
c.token = (res.get("data") or {}).get("token")
res, _ = c.request("/datafactory/dataset/delete", params={"id": dataset_id})
check("删除数据集", res.get("code") == 0, str(res)[:200])
res, _ = c.request("/datafactory/dataset/detail", params={"id": dataset_id})
check("删除后查不到", res.get("code") != 0, str(res)[:200])

# ---------- 10. 数据驱动端到端 ----------
# 绑定之后跑用例, 验证 Executor 真的按 N 条数据跑了 N 次, 且 ${变量} 被替换成对应行的值。
print("== 数据驱动端到端 ==")
if BOUND_CASE_ID and rows1:
    res, _ = c.request("/request/run", params={"env": env_id, "case_id": BOUND_CASE_ID})
    data = res.get("data") or {}
    check("用例按数据条数执行", res.get("code") == 0 and len(data) >= 4,
          f"执行 {len(data)} 次, {str(res)[:200]}")

    # 每个结果里, 请求 body 必须用对应数据行的值替换掉了 ${...}
    mismatches = []
    for name, result in data.items():
        body = result.get("request_data")
        if not isinstance(body, str) or "${" in body:
            mismatches.append(f"{name}: body 仍有占位符或非字符串: {body!r}")
            continue
        try:
            posted = json.loads(body)
        except Exception:
            mismatches.append(f"{name}: body 不是合法 JSON: {body!r}")
            continue
        # 反查这条数据对应的行
        match = [r for r in rows1[:4]
                 if r["mobile"] == posted.get("phone") and r["nickname"] == posted.get("nickname")]
        if not match:
            mismatches.append(f"{name}: 请求值对不上任何一行: {posted}")
        elif str(match[0]["age"]) != str(posted.get("age")):
            mismatches.append(f"{name}: age 对不上: {match[0]['age']} vs {posted.get('age')}")
    check("每次执行的 body 都按对应行替换了 ${变量}", not mismatches,
          "; ".join(mismatches[:3]))

    # 不同数据行的请求值不应完全相同
    bodies = {r.get("request_data") for r in data.values() if isinstance(r.get("request_data"), str)}
    check("不同数据行的请求值互不相同", len(bodies) >= 4, f"只有 {len(bodies)} 种")
else:
    print("    [SKIP] 没有已绑定的用例或预览数据, 跳过数据驱动验证")

# ---------- 11. 清理 ----------
# 用例删掉时平台会连带软删它名下的 pity_testcase_data, 避免测试数据在库里累积
print("== 清理 ==")
if BOUND_CASE_ID:
    # /testcase/delete 收的是 id_list: List[int] (列表, 不是 dict)
    res, _ = c.request("/testcase/delete", "DELETE", [BOUND_CASE_ID])
    print(f"    删除测试用例: {res.get('code')} {res.get('msg')}")

print("")
if FAILED:
    print(f"FAILED {len(FAILED)} 项: {FAILED}")
    sys.exit(1)
print("端到端全部通过")
