"""
数据工厂生成内核

职责: 把一份「字段规则集」变成 N 行数据。

三条硬约束:
1. 确定性 —— 同样的 rules + seed 必须产出完全一样的数据, 所以用 Faker.seed_instance 而不是全局 seed
2. 变量复用平台既有的 ${...} 语法 (Jinja2, app/core/render.py), 不另造一套
3. 不引入 exrex 之类的额外依赖, 正则生成走自研的 regex_gen
"""
import json
import re
import string
import uuid as uuid_lib
from datetime import datetime, timedelta
from itertools import count as iter_count
from typing import Any, Dict, List

from faker import Faker

from app.core.data_factory.regex_gen import RegexError
from app.core.data_factory.regex_gen import generate as regex_generate
from app.core.functions import PityFunction
from app.core.render import Render

# 允许使用的 faker provider, 避免 AI 翻译出不存在的名字
FAKER_PROVIDERS = {
    'name', 'first_name', 'last_name', 'user_name', 'phone_number', 'email', 'company',
    'job', 'ssn', 'address', 'city', 'country', 'street_name', 'building_number',
    'password', 'word', 'sentence', 'text', 'paragraph', 'uuid4', 'url', 'uri', 'domain_name',
    'ipv4', 'ipv6', 'mac_address', 'user_agent', 'mime_type', 'file_name', 'file_path',
    'boolean', 'pyint', 'pyfloat', 'pybool', 'random_int', 'random_element', 'random_elements',
    'date_between', 'date_this_century', 'date_this_decade', 'date_this_year', 'future_date',
    'past_date', 'timezone', 'credit_card_number', 'credit_card_expire', 'currency_name',
    'currency_code', 'ean', 'isbn13', 'hex_color', 'color_name', 'rgb_color', 'language_code',
    'sha1', 'md5', 'uuid1',
}

# 字段名约束: 要能作为 Jinja2 变量名被 ${field} 引用
FIELD_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# ${字段名} 占位符, 不带括号的是字段引用, 带括号的是函数调用
FIELD_REF_PATTERN = re.compile(r'\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}')

MAX_UNIQUE_ATTEMPT = 100
# 支持的生成方式, 与前端 consts/datafactory.ts 的 RULE_KINDS 保持一致
DATA_FACTORY_KINDS = ('fixed', 'random', 'enum', 'sequence', 'uuid', 'template', 'regex',
                      'reference', 'faker', 'func', 'date')


class DataFactoryError(Exception):
    """数据工厂业务异常"""


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


class DataGenerator(object):
    """
    字段规则集 -> 数据行
    """

    def __init__(self, rules: Any, seed: int = None, locale: str = "zh_CN"):
        self.rules = self._normalize(rules)
        self.locale = locale
        self.faker = Faker(locale)
        if seed is not None:
            # seed_instance 只影响这个实例, 不会污染其他并发请求
            self.faker.seed_instance(seed)
        # 所有随机都走这个实例, Faker 的 seed_instance 会一并给它设种子,
        # 这样 random kind / 正则生成的随机数也能跟着 seed 一起重放
        self.rng = self.faker.random
        # 遮蔽 PityFunction 里依赖 OS 熵 / 全局 random 的两个函数。
        # Jinja2 解析变量时上下文优先于 globals, 所以同名会取这里带种子的版本,
        # 保证 ${uuid()} / ${random_int(1,100)} 也能跟着 seed 重放。
        # 注意 PityFunction.now() 这类时间函数仍然取真实时间, 无法重放。
        self._render_globals = {
            'uuid': self._next_uuid,
            'random_int': self._random_int,
        }
        self._sequences: Dict[str, Any] = {}
        self._enum_index: Dict[str, int] = {}
        self._seen: Dict[str, set] = {}
        self._order = self._resolve_order()

    # ---------------- 规则解析 ----------------

    @staticmethod
    def _normalize(rules: Any) -> List[dict]:
        """接受 [{"name":..}, ..] 或 {"columns": [...]}"""
        if isinstance(rules, str):
            try:
                rules = json.loads(rules)
            except Exception:
                raise DataFactoryError("字段规则不是合法的 JSON")
        if isinstance(rules, dict):
            rules = rules.get("columns") or []
        if not isinstance(rules, list) or not rules:
            raise DataFactoryError("字段规则不能为空")
        result = []
        names = set()
        for item in rules:
            if not isinstance(item, dict):
                raise DataFactoryError("字段规则格式非法")
            name = str(item.get("name") or "").strip()
            if not name:
                raise DataFactoryError("字段名不能为空")
            if not FIELD_NAME_PATTERN.match(name):
                raise DataFactoryError(f"字段名 {name} 非法, 只能包含字母/数字/下划线且不能以数字开头")
            if name in names:
                raise DataFactoryError(f"字段名 {name} 重复")
            names.add(name)
            rule = item.get("rule") or {}
            if not isinstance(rule, dict):
                raise DataFactoryError(f"字段 {name} 的生成规则格式非法")
            kind = rule.get("kind") or "fixed"
            if kind not in DATA_FACTORY_KINDS:
                raise DataFactoryError(f"字段 {name} 的生成方式 {kind} 不支持")
            result.append({
                "name": name,
                "type": item.get("type") or "string",
                "rule": rule,
                "unique": bool(item.get("unique")),
                "nullable": bool(item.get("nullable")),
                "default": item.get("default"),
                "comment": item.get("comment") or "",
            })
        return result

    @staticmethod
    def _rule_sources(rule: dict) -> List[str]:
        """取出规则里所有可能带 ${} 占位符的字符串"""
        sources = []
        for key in ('value', 'template', 'pattern', 'expr', 'from'):
            value = rule.get(key)
            if isinstance(value, str):
                sources.append(value)
        return sources

    def _dependencies(self, column: dict) -> List[str]:
        """该字段依赖了哪些其他字段"""
        deps = set()
        rule = column['rule']
        if rule.get('kind') == 'reference':
            source = rule.get('from')
            if isinstance(source, str) and source:
                deps.add(source)
        for text in self._rule_sources(rule):
            for match in FIELD_REF_PATTERN.finditer(text):
                name = match.group(1)
                # 带括号的是函数调用, 这里只匹配不带括号的形式, 所以命中的都是字段引用
                if name in PityFunction.__dict__:
                    continue
                deps.add(name)
        deps.discard(column['name'])
        return list(deps)

    def _resolve_order(self) -> List[dict]:
        """按依赖做拓扑排序, 有环直接报错"""
        by_name = {c['name']: c for c in self.rules}
        for column in self.rules:
            for dep in self._dependencies(column):
                if dep not in by_name:
                    raise DataFactoryError(f"字段 {column['name']} 引用了不存在的字段 {dep}")
        # Kahn 算法
        indegree = {c['name']: len(self._dependencies(c)) for c in self.rules}
        children: Dict[str, List[str]] = {c['name']: [] for c in self.rules}
        for column in self.rules:
            for dep in self._dependencies(column):
                children[dep].append(column['name'])
        ready = [n for n, d in indegree.items() if d == 0]
        ordered = []
        while ready:
            name = ready.pop()
            ordered.append(by_name[name])
            for child in children[name]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(ordered) != len(self.rules):
            stuck = [n for n, d in indegree.items() if d > 0]
            raise DataFactoryError(f"字段引用存在循环依赖: {', '.join(stuck)}")
        return ordered

    def _next_uuid(self) -> str:
        """带种子的 uuid, 格式与 PityFunction.uuid() 一致(32位无横线)"""
        return uuid_lib.UUID(int=self.rng.getrandbits(128), version=4).hex

    def _random_int(self, a, b):
        """带种子的随机整数, 替代 PityFunction.random_int 的全局 random"""
        return self.rng.randint(int(a), int(b))

    # ---------------- 单个字段生成 ----------------

    def _produce(self, column: dict, context: dict, index: int):
        rule = column['rule']
        kind = rule.get('kind')
        if kind == 'fixed':
            return rule.get('value')
        if kind == 'random':
            return self._random(column, rule)
        if kind == 'enum':
            return self._enum(column, rule)
        if kind == 'sequence':
            return self._sequence(column, rule)
        if kind == 'uuid':
            prefix = rule.get('prefix') or ""
            # 用带种子的 uuid, 保证整个数据集都能重放
            return f"{prefix}{self._next_uuid()}"
        if kind == 'template':
            return self._fill_template(str(rule.get('template') or ""))
        if kind == 'regex':
            return self._regex(rule)
        if kind == 'reference':
            source = rule.get('from')
            if source not in context:
                raise DataFactoryError(f"字段 {column['name']} 引用的字段 {source} 尚未生成")
            return context[source]
        if kind == 'faker':
            return self._faker(rule)
        if kind == 'func':
            return rule.get('expr')
        if kind == 'date':
            return self._date(rule)
        raise DataFactoryError(f"字段 {column['name']} 的生成方式 {kind} 不支持")

    def _random(self, column: dict, rule: dict):
        type_name = column['type']
        if type_name == 'float':
            low = float(rule.get('min') or 0)
            high = float(rule.get('max') or 100)
            decimals = int(rule.get('decimals') or 2)
            return round(self.rng.uniform(low, high), decimals)
        low = int(rule.get('min') or 0)
        high = int(rule.get('max') or 100)
        if high < low:
            low, high = high, low
        return self.rng.randint(low, high)

    def _fill_template(self, text: str) -> str:
        """
        字符模板填充: # 数字, ? 字母, * 数字或字母, 其余字符原样保留。

        不用 Faker.bothify —— 它的 numerify 会把 @ 和 % 也当成数字占位符,
        "${mobile}@qq.com" 这种模板会被填成 "1{mobile}2qq.com"。
        """
        chars = []
        for ch in text:
            if ch == '#':
                chars.append(self.rng.choice(string.digits))
            elif ch == '?':
                chars.append(self.rng.choice(string.ascii_letters))
            elif ch == '*':
                chars.append(self.rng.choice(string.ascii_letters + string.digits))
            else:
                chars.append(ch)
        return ''.join(chars)

    def _enum(self, column: dict, rule: dict):
        values = rule.get('values') or []
        if not isinstance(values, list) or not values:
            raise DataFactoryError(f"字段 {column['name']} 的枚举值为空")
        name = column['name']
        position = self._enum_index.get(name, 0)
        self._enum_index[name] = position + 1
        return values[position % len(values)]

    def _sequence(self, column: dict, rule: dict):
        name = column['name']
        if name not in self._sequences:
            start = int(rule.get('start') or 1)
            step = int(rule.get('step') or 1)
            self._sequences[name] = iter_count(start, step)
        return next(self._sequences[name])

    def _regex(self, rule: dict):
        pattern = str(rule.get('pattern') or "")
        try:
            return regex_generate(pattern, self.rng)
        except RegexError as e:
            raise DataFactoryError(f"正则生成失败: {e}")

    def _faker(self, rule: dict):
        provider = str(rule.get("provider") or "").strip()
        if provider not in FAKER_PROVIDERS:
            raise DataFactoryError(f"不支持的 faker provider: {provider}")
        args = rule.get("args") or {}
        if not isinstance(args, dict):
            raise DataFactoryError(f"faker 参数格式非法: {provider}")
        try:
            return getattr(self.faker, provider)(**args)
        except TypeError as e:
            raise DataFactoryError(f"faker provider {provider} 参数错误: {e}")

    def _date(self, rule: dict):
        fmt = rule.get("format") or "%Y-%m-%d %H:%M:%S"
        start = self._parse_time(rule.get("start"), -30)
        end = self._parse_time(rule.get("end"), 0)
        if start > end:
            start, end = end, start
        seconds = int((end - start).total_seconds())
        offset = self.rng.randint(0, max(seconds, 0))
        return (start + timedelta(seconds=offset)).strftime(fmt)

    @staticmethod
    def _parse_time(value, default_delta_days: int = 0) -> datetime:
        """
        解析时间表达式:
            now            当前时间
            -30d / +2h     相对当前时间的偏移
            2024-01-01     绝对时间(支持到秒)
        """
        if not value:
            return datetime.now() + timedelta(days=default_delta_days)
        text = str(value).strip()
        if text == "now":
            return datetime.now()
        matched = re.match(r'^([+-])(\d+)([dhm])$', text)
        if matched:
            sign = -1 if matched.group(1) == '-' else 1
            amount = int(matched.group(2))
            unit = matched.group(3)
            delta = {'d': timedelta(days=amount),
                     'h': timedelta(hours=amount),
                     'm': timedelta(minutes=amount)}[unit]
            return datetime.now() + sign * delta
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise DataFactoryError(f"无法解析的时间表达式: {text}")

    # ---------------- 变量解析 ----------------

    def _render_context(self, context: dict) -> dict:
        """渲染上下文 = 本行已生成字段 + 带种子的内置函数(字段同名时以字段为准)"""
        merged = dict(context)
        for key, func in self._render_globals.items():
            if key not in merged:
                merged[key] = func
        return merged

    @staticmethod
    def _resolve_vars(value: Any, context: dict, column_name: str):
        """把 ${字段} 替换成实际值, ${函数()} 交给 Jinja2 渲染"""
        if value is None:
            return None
        text = _stringify(value)
        if '${' not in text:
            return text
        # 先校验引用的字段确实存在, 否则 Jinja2 会静默渲染成空字符串, 很难排查
        for match in FIELD_REF_PATTERN.finditer(text):
            name = match.group(1)
            if name in PityFunction.__dict__:
                continue
            if name not in context:
                raise DataFactoryError(f"字段 {column_name} 引用了未定义的变量 {name}")
        try:
            return Render.render(context, text)
        except Exception as e:
            raise DataFactoryError(f"字段 {column_name} 变量解析失败: {e}")

    @staticmethod
    def _coerce(value: Any, type_name: str):
        if value is None:
            return None
        try:
            if type_name == 'int':
                if isinstance(value, bool):
                    return int(value)
                return int(value)
            if type_name == 'float':
                return float(value)
            if type_name == 'bool':
                if isinstance(value, str):
                    return value.strip().lower() in ('1', 'true', 'yes', 'y')
                return bool(value)
            if type_name == 'string':
                return value if isinstance(value, str) else _stringify(value)
        except (TypeError, ValueError):
            # 转换不了就保留原值, 交给数据库层报错, 错误信息更贴近真实原因
            return value
        return value

    # ---------------- 对外入口 ----------------

    def generate(self, count: int) -> List[dict]:
        """
        生成 count 行数据
        """
        if count <= 0:
            raise DataFactoryError("生成条数必须大于 0")
        rows = []
        for index in range(count):
            context: Dict[str, Any] = {}
            values: Dict[str, Any] = {}
            # 按依赖顺序计算, 保证被引用的字段先生成出来
            for column in self._order:
                value = self._generate_value(column, context, index)
                context[column['name']] = value
                values[column['name']] = value
            # 输出按用户声明的字段顺序, 而不是拓扑排序的顺序
            rows.append({column['name']: values[column['name']] for column in self.rules})
        return rows

    def _finalize(self, column: dict, context: dict, index: int):
        """
        单个字段的完整产出: 生成 -> 解析 ${} -> 类型转换 -> 兜底值
        """
        raw = self._produce(column, context, index)
        name = column['name']
        value = self._resolve_vars(raw, self._render_context(context), name)
        value = self._coerce(value, column['type'])
        if value is None:
            if column.get('default') is not None:
                value = column['default']
            elif not column.get('nullable'):
                value = "" if column['type'] == 'string' else None
        return value

    def _generate_value(self, column: dict, context: dict, index: int):
        """
        带唯一性约束的字段产出。

        去重必须做在**解析完 ${} 之后的最终值**上:
        否则 "email = ${mobile}@qq.com" 这类规则, 每行产出的都是同一个字面量
        "${mobile}@qq.com", 第 2 行就会判重失败且重试永远一样。
        """
        name = column['name']
        if not column.get('unique'):
            return self._finalize(column, context, index)
        seen = self._seen.setdefault(name, set())
        retryable = self._can_retry(column)
        for attempt in range(MAX_UNIQUE_ATTEMPT if retryable else 1):
            value = self._finalize(column, context, index)
            key = _stringify(value)
            if key not in seen:
                seen.add(key)
                return value
        if retryable:
            raise DataFactoryError(
                f"字段 {name} 生成唯一值失败(已尝试 {MAX_UNIQUE_ATTEMPT} 次), 请放宽取值范围")
        raise DataFactoryError(
            f"字段 {name} 的生成方式在本行内是确定的, 无法换新值去满足唯一约束, "
            f"且当前值与已生成的数据重复, 请让被引用的字段唯一或给它加上随机部分")

    @staticmethod
    def _can_retry(column: dict) -> bool:
        """
        该字段重试能否换出新值。
        - fixed / reference: 每次都一样
        - template / func: 如果里面引用了本行已固定字段, 重试也没用
        其余(random / faker / regex / uuid / date / sequence / enum)重试可以换值
        """
        kind = column['rule'].get('kind')
        if kind in ('fixed', 'reference'):
            return False
        if kind in ('template', 'func'):
            for text in DataGenerator._rule_sources(column['rule']):
                for match in FIELD_REF_PATTERN.finditer(text):
                    if match.group(1) not in PityFunction.__dict__:
                        return False
        return True
