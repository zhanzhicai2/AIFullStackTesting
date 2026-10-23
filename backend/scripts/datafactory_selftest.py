"""
数据工厂自测脚本

不依赖 pytest(后端目前没有测试框架), 直接 python scripts/datafactory_selftest.py 即可跑。
覆盖: 生成内核 / seed 重放 / 错误处理 / 导出器 / AI 规则解析。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.data_factory import ai_parser, exporter  # noqa: E402
from app.core.data_factory.generator import DataFactoryError, DataGenerator  # noqa: E402

FAILED = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILED.append(label)


RULES = {
    "columns": [
        {"name": "user_id", "type": "int", "rule": {"kind": "sequence", "start": 1, "step": 1}, "unique": True},
        {"name": "mobile", "type": "string", "rule": {"kind": "template", "template": "138########"}, "unique": True},
        {"name": "email", "type": "string", "rule": {"kind": "template", "template": "${mobile}@qq.com"}},
        {"name": "nickname", "type": "string", "rule": {"kind": "faker", "provider": "name"}},
        {"name": "age", "type": "int", "rule": {"kind": "random", "min": 18, "max": 60}},
        {"name": "gender", "type": "string", "rule": {"kind": "enum", "values": ["男", "女"]}},
        {"name": "id_no", "type": "string", "rule": {"kind": "regex", "pattern": r"^\d{17}[0-9Xx]$"}},
        {"name": "uid", "type": "string", "rule": {"kind": "func", "expr": "${uuid()}"}},
        {"name": "score", "type": "int", "rule": {"kind": "func", "expr": "${random_int(1,100)}"}},
        {"name": "ref_user", "type": "int", "rule": {"kind": "reference", "from": "user_id"}},
        {"name": "created", "type": "string", "rule": {"kind": "date", "start": "-30d", "end": "now"}},
        {"name": "biz_id", "type": "string", "rule": {"kind": "uuid", "prefix": "u_"}},
    ]
}


def _replayable(rows):
    """
    去掉 date 类字段再比较。
    date / now() 依赖墙钟, 天生不可重放(生成器文档里已说明),
    两次调用跨秒边界会让断言偶发失败。
    """
    date_cols = [c["name"] for c in RULES["columns"]
                 if (c.get("rule") or {}).get("kind") == "date"]
    return [{k: v for k, v in r.items() if k not in date_cols} for r in rows]


def test_generator():
    print("== 生成内核 ==")
    rows = DataGenerator(RULES, seed=42).generate(3)
    for row in rows:
        print("   ", json.dumps(row, ensure_ascii=False))

    check("seed 重放一致", _replayable(rows) == _replayable(DataGenerator(RULES, seed=42).generate(3)))
    check("不同 seed 结果不同", _replayable(DataGenerator(RULES, seed=7).generate(3)) != _replayable(rows))
    check("字段顺序按声明顺序",
          list(rows[0].keys()) == [c["name"] for c in RULES["columns"]],
          f"实际 {list(rows[0].keys())}")
    check("跨字段引用 ${mobile}", rows[0]["email"] == f'{rows[0]["mobile"]}@qq.com')
    check("reference kind", rows[0]["ref_user"] == rows[0]["user_id"])
    check("模板 # 填充", all(len(r["mobile"]) == 11 and r["mobile"].startswith("138") for r in rows))
    check("模板不误伤 @ %", "@" in rows[0]["email"] and "%" not in rows[0]["email"])
    check("枚举轮转", all(r["gender"] in ("男", "女") for r in rows))
    check("随机区间", all(18 <= r["age"] <= 60 for r in rows))
    check("uuid 前缀", all(r["biz_id"].startswith("u_") for r in rows))
    check("func uuid 长度", all(len(r["uid"]) == 32 for r in rows))
    check("func random_int 区间", all(1 <= r["score"] <= 100 for r in rows))
    check("date 相对时间", all(r["created"][:4].isdigit() for r in rows))
    check("sequence 递增", [r["user_id"] for r in rows] == [1, 2, 3])
    check("regex 匹配", all(len(r["id_no"]) == 18 and r["id_no"][:17].isdigit() for r in rows))
    check("唯一约束不重复", len({r["mobile"] for r in rows}) == 3)
    check("faker 中文名", all(len(r["nickname"]) >= 2 for r in rows))


def test_errors():
    print("== 错误处理 ==")
    cases = [
        ("引用不存在的字段", {"columns": [{"name": "a", "rule": {"kind": "template", "template": "${nope}"}}]}),
        ("循环依赖", {"columns": [{"name": "a", "rule": {"kind": "reference", "from": "b"}},
                                  {"name": "b", "rule": {"kind": "reference", "from": "a"}}]}),
        ("非法字段名", {"columns": [{"name": "user-name", "rule": {"kind": "fixed", "value": 1}}]}),
        ("未知 kind", {"columns": [{"name": "a", "rule": {"kind": "magic"}}]}),
        ("未知 faker provider", {"columns": [{"name": "a", "rule": {"kind": "faker", "provider": "rm -rf"}}]}),
        ("重复字段名", {"columns": [{"name": "a", "rule": {"kind": "fixed", "value": 1}},
                                    {"name": "a", "rule": {"kind": "fixed", "value": 2}}]}),
        ("非法正则", {"columns": [{"name": "a", "rule": {"kind": "regex", "pattern": "[a-"}}]}),
        ("空枚举", {"columns": [{"name": "a", "rule": {"kind": "enum", "values": []}}]}),
        ("空规则集", {"columns": []}),
    ]
    for label, bad in cases:
        try:
            DataGenerator(bad, seed=1).generate(1)
            check(f"{label} 应报错", False, "但没有抛异常")
        except DataFactoryError:
            check(f"{label} 报错", True)
        except Exception as e:
            check(f"{label} 报错", False, f"抛的是非预期异常 {type(e).__name__}: {e}")


def test_exporter():
    print("== 导出器 ==")
    rows = [{"id": 1, "name": "O'Brien", "note": None, "score": 9.5, "ok": True, "raw": {"a": 1}}]
    sql = exporter.build_sql(rows, "pity_user")
    print("   ", sql)
    check("单引号转义", "O''Brien" in sql)
    check("None -> NULL", "NULL" in sql)
    check("浮点数", "9.5" in sql)
    check("布尔", ", 1," in sql or " 1," in sql)
    check("JSON 字段", '{"a": 1}' in sql or '"{\\"a\\": 1}"' in sql)
    check("JSON 导出", "O'Brien" in exporter.build_json(rows))
    check("空数据", exporter.build_sql([], "t") == "")


def test_ai_parser():
    print("== AI 规则解析 ==")
    ok = '''```json
{"count": 100, "columns": [
 {"name": "user_id", "type": "int", "rule": {"kind": "sequence", "start": 1, "step": 1}, "unique": true},
 {"name": "mobile", "type": "string", "rule": {"kind": "template", "template": "138########"}},
 {"name": "email", "type": "string", "rule": {"kind": "template", "template": "${mobile}@qq.com"}}
]}
```'''
    rules, warnings = ai_parser.parse_rules(ok)
    check("剥 markdown 代码块", len(rules["columns"]) == 3, str(rules))
    check("取 count", rules["count"] == 100)
    check("无警告", warnings == [], str(warnings))

    bad = '''{"count": 5, "columns": [
 {"name": "ok_field", "rule": {"kind": "fixed", "value": 1}},
 {"name": "bad-name", "rule": {"kind": "fixed", "value": 1}},
 {"name": "bad_kind", "rule": {"kind": "magic"}},
 {"name": "bad_faker", "rule": {"kind": "faker", "provider": "rm -rf"}}
]}'''
    rules, warnings = ai_parser.parse_rules(bad)
    check("非法字段被丢弃", len(rules["columns"]) == 1, str(rules))
    check("非法字段有 warning", len(warnings) == 3, str(warnings))

    try:
        ai_parser.parse_rules("完全不是 JSON")
        check("非 JSON 应报错", False)
    except DataFactoryError:
        check("非 JSON 报错", True)

    # 解析出来的规则必须能被生成内核直接消费
    rules, _ = ai_parser.parse_rules(ok)
    rows = DataGenerator({"columns": rules["columns"]}, seed=1).generate(2)
    check("AI 规则可直接生成", len(rows) == 2 and rows[0]["email"].endswith("@qq.com"))


def test_unique():
    """
    唯一性必须做在**解析 ${} 之后的最终值**上。
    曾经的 bug: 去重发生在解析前, "email = ${mobile}@qq.com" 每行产出的
    都是同一个字面量, 第 2 行就判重失败且重试永远一样。
    """
    print("== 唯一性约束 ==")
    derived = {"columns": [
        {"name": "mobile", "rule": {"kind": "template", "template": "138#######"}, "unique": True},
        {"name": "email", "rule": {"kind": "template", "template": "${mobile}@qq.com"}, "unique": True},
    ]}
    rows = DataGenerator(derived, seed=1).generate(20)
    check("引用已唯一字段时 email 能去重", len({r["email"] for r in rows}) == 20,
          str({r["email"] for r in rows})[:200])
    check("email 已被解析", rows[0]["email"].endswith("@qq.com") and "${" not in rows[0]["email"],
          rows[0]["email"])

    ref = {"columns": [
        {"name": "b", "rule": {"kind": "random", "min": 1, "max": 100000}, "unique": True},
        {"name": "c", "rule": {"kind": "reference", "from": "b"}, "unique": True},
    ]}
    rows = DataGenerator(ref, seed=2).generate(20)
    check("reference 字段随源字段唯一", len({r["c"] for r in rows}) == 20, str(rows[:3]))

    # 确定性字段没法换新值, 必须立刻给出可操作的报错, 而不是空跑 100 次
    fixed = {"columns": [{"name": "a", "rule": {"kind": "fixed", "value": "x"}, "unique": True}]}
    try:
        DataGenerator(fixed, seed=1).generate(3)
        check("fixed + unique 应报错", False, "没有抛异常")
    except DataFactoryError as e:
        check("fixed + unique 报可操作的错误", "确定的" in str(e), str(e))
        check("fixed + unique 不空跑 100 次", "100" not in str(e), str(e))


def test_autoincrement():
    """
    SQLAlchemy 的 column.autoincrement 是三态 True / False / 'auto'。
    'auto' 表示"交给 SQLAlchemy 自己判", 不是"是自增"。
    曾经的 bug: 写成 `in (True, 'auto')`, 导致 VARCHAR/TIMESTAMP 全被判成自增,
    从表结构导入时默认勾选的恰好是最没用的 4 列, 把 username/name/email 排除掉了。
    """
    print("== 自增列判定 ==")
    from sqlalchemy import Column, Integer, MetaData, String, Table
    from app.core.data_factory.writer import is_autoincrement

    table = Table('demo', MetaData(),
                  Column('id', Integer, primary_key=True),
                  Column('username', String(16)),
                  Column('age', Integer),
                  Column('created_at', Integer))
    checks = [
        ('单列整数主键', table.c.id, True),
        ('字符串列', table.c.username, False),
        ('非主键整数列', table.c.age, False),
        ('非主键时间类列', table.c.created_at, False),
    ]
    for label, col, expect in checks:
        got = is_autoincrement(col)
        check(f"{label}(autoincrement={col.autoincrement!r})", got is expect, f"得到 {got}")


def main():
    test_generator()
    test_unique()
    test_errors()
    test_exporter()
    test_ai_parser()
    test_autoincrement()
    print("")
    if FAILED:
        print(f"FAILED {len(FAILED)} 项: {FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == '__main__':
    main()
