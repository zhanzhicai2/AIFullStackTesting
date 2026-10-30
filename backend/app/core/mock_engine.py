"""
Mock 匹配引擎 —— 纯函数, 确定性(constitution 原则 I)

**确定性声明**: 本模块无任何随机源、无 IO。给定同一请求快照(method + path)与同一规则集,
`match_rule` 必然返回同一条规则(或 None)。匹配顺序全排序确定:

```
路径精确度(精确 0 > 参数化 1 > 通配 2) → priority(数字小优先) → id(创建早优先)
```

**安全边界**: 本模块只做字符串/列表比较, 不发起任何外部请求、不执行任何代码 ——
回归脚本 `mock_selftest.py` 对源码做 AST 静态扫描保证这一点(无出网调用、无 eval/exec)。
"""
from typing import List, Optional

from app.enums.MockEnum import PATH_TYPE_EXACT, PATH_TYPE_PARAM, PATH_TYPE_WILDCARD


def derive_path_type(path: str) -> int:
    """
    由 path 推导路径类型: 含 `*` → 通配; 含 `:`(无 `*`)→ 参数化; 否则精确。
    DAO 存储时用本函数固化 `path_type`, 匹配时直接用 —— 两者永不漂移
    (data-model.md §2.2 不变量)。
    """
    if "*" in path:
        return PATH_TYPE_WILDCARD
    if ":" in path:
        return PATH_TYPE_PARAM
    return PATH_TYPE_EXACT


def normalize_path(path: str) -> str:
    """
    清洗被测接口路径: 去掉 query、合并多余 `/`、去掉末尾 `/`。
    例: `/api/user/1?x=1` → `/api/user/1`; `/api/` → `/api`; `/` 保持 `/`。
    """
    path = path.split("?")[0]
    path = "/" + path.strip("/")
    if path != "/":
        path = path.rstrip("/")
    return path


def _segments_match(pattern_segs: List[str], actual_segs: List[str]) -> bool:
    """
    参数化路径段匹配: 含 `:` 前缀的段(`:xxx`)匹配任意单段(不含 `/`), 其余段逐段相等。
    段数必须一致 —— `/api/user/:id` 不匹配 `/api/user`(段数 2 vs 3)。
    """
    if len(pattern_segs) != len(actual_segs):
        return False
    for p, a in zip(pattern_segs, actual_segs):
        if p.startswith(":") and len(p) > 1:
            continue
        if p != a:
            return False
    return True


def _match_rule_path(rule_path: str, path_type: int, full_path: str) -> bool:
    """单条规则路径匹配(全路径已 normalize)。"""
    if path_type == PATH_TYPE_EXACT:
        return rule_path == full_path
    if path_type == PATH_TYPE_PARAM:
        return _segments_match(rule_path.split("/"), full_path.split("/"))
    # 通配: `*` 只允许在末尾, 匹配剩余任意内容(含空)
    prefix = rule_path[:-1] if rule_path.endswith("*") else rule_path
    return full_path.startswith(prefix)


def match_rule(method: str, full_path: str, rules: List[object]) -> Optional[object]:
    """
    从规则列表(已按项目过滤)中确定性地选出命中规则。

    :param method: 请求方法(如 GET), 规则 method == 该方法或 'ANY' 才参与匹配
    :param full_path: 被测接口路径(可带 query, 内部会清洗)
    :param rules: 候选规则, 元素须暴露 method / path / path_type / priority / status / id 属性
                  (PityMockRule ORM 对象或等价命名元组)
    :return: 命中的规则或 None
    """
    full_path = normalize_path(full_path)
    candidates = []
    for rule in rules:
        if getattr(rule, "status", 1) != 1:
            continue  # 停用规则不参与匹配(FR-012)
        if rule.method != "ANY" and rule.method != method:
            continue
        if not _match_rule_path(rule.path, rule.path_type, full_path):
            continue
        candidates.append(rule)
    if not candidates:
        return None
    # 全排序确定: 路径精确度 → 方法具体度(具体方法 0 优先于 ANY 1)→ priority → id
    candidates.sort(key=lambda r: (r.path_type, 0 if r.method == method else 1,
                                   r.priority, r.id))
    return candidates[0]
