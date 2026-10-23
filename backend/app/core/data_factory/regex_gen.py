"""
轻量正则生成器

不引入 exrex 这类额外依赖, 自己实现一个够用的正则 -> 匹配串生成器。
支持的正则语法:
    字面量        abc
    转义类        \\d \\D \\w \\W \\s \\S
    任意字符      .
    字符类        [0-9] [a-zA-Z] [^0-9]
    分组          (abc|def)
    或分支        abc|def
    量词          * + ? {n} {n,m} {n,}
    锚点          ^ $   (生成时忽略)

量词的重复次数上限受 MAX_REPEAT 约束, 避免 {0,1000000} 这种把内存打爆的规则。
"""
import random
import string

MAX_REPEAT = 20
MAX_DEPTH = 10

# 生成用的随机源, 由调用方注入(通常是 Faker.seed_instance 过的实例),
# 保证同样的 seed 能重放出一模一样的结果
_DEFAULT_RNG = random


class RegexError(Exception):
    """正则解析或生成失败"""


_ESCAPES = {
    'd': string.digits,
    'D': string.ascii_letters + string.punctuation,
    'w': string.ascii_letters + string.digits + '_',
    'W': string.punctuation.replace('_', ''),
    's': ' \t',
    'S': string.printable.replace(' \t', ''),
}


class _Node(object):
    """正则 AST 节点"""

    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.__dict__.update(kwargs)


def _parse_class(pattern, pos):
    """解析 [...] 字符类, 返回 (charset, new_pos)"""
    negate = False
    if pattern[pos] == '^':
        negate = True
        pos += 1
    chars = []
    while pos < len(pattern) and pattern[pos] != ']':
        ch = pattern[pos]
        if ch == '\\' and pos + 1 < len(pattern):
            pos += 1
            esc = pattern[pos]
            if esc in _ESCAPES:
                chars.extend(_ESCAPES[esc])
            else:
                chars.append(esc)
            pos += 1
            continue
        if pos + 2 < len(pattern) and pattern[pos + 1] == '-' and pattern[pos + 2] != ']':
            # a-z 这样的区间
            start, end = ch, pattern[pos + 2]
            if ord(start) > ord(end):
                raise RegexError(f"字符类区间非法: {start}-{end}")
            chars.extend(chr(c) for c in range(ord(start), ord(end) + 1))
            pos += 3
            continue
        chars.append(ch)
        pos += 1
    if pos >= len(pattern):
        raise RegexError("字符类缺少右方括号 ]")
    pos += 1  # 跳过 ]
    charset = ''.join(chars)
    if negate:
        excluded = set(charset)
        charset = ''.join(c for c in string.printable if c not in excluded)
    if not charset:
        raise RegexError("字符类为空")
    return charset, pos


def _parse_atom(pattern, pos, depth):
    ch = pattern[pos]
    if ch == '(':
        # 处理 (?: ...) 非捕获分组
        inner_start = pos + 1
        if pattern.startswith('(?', inner_start):
            if pattern.startswith('(?:', inner_start):
                inner_start += 2
            elif pattern.startswith('(?P<', inner_start):
                end = pattern.index('>', inner_start)
                inner_start = end + 1
            else:
                raise RegexError(f"暂不支持的分组语法: {pattern[pos:pos + 6]}")
        node, pos = _parse_alt(pattern, inner_start, depth + 1)
        if pos >= len(pattern) or pattern[pos] != ')':
            raise RegexError("分组缺少右括号 )")
        return node, pos + 1
    if ch == '[':
        charset, pos = _parse_class(pattern, pos + 1)
        return _Node('class', charset=charset), pos
    if ch == '.':
        return _Node('any'), pos + 1
    if ch == '\\':
        if pos + 1 >= len(pattern):
            raise RegexError("正则以孤立的反斜杠结尾")
        esc = pattern[pos + 1]
        if esc in _ESCAPES:
            return _Node('class', charset=_ESCAPES[esc]), pos + 2
        if esc == 'n':
            return _Node('literal', value='\n'), pos + 2
        if esc == 't':
            return _Node('literal', value='\t'), pos + 2
        return _Node('literal', value=esc), pos + 2
    if ch in '^$':
        # 锚点, 生成时无意义, 直接跳过
        return _Node('empty'), pos + 1
    if ch in '*+?':
        raise RegexError(f"量词 {ch} 前面缺少可重复的内容")
    return _Node('literal', value=ch), pos + 1


def _parse_term(pattern, pos, depth):
    node, pos = _parse_atom(pattern, pos, depth)
    if pos >= len(pattern):
        return node, pos
    ch = pattern[pos]
    if ch == '*':
        return _Node('repeat', child=node, low=0, high=3), pos + 1
    if ch == '+':
        return _Node('repeat', child=node, low=1, high=3), pos + 1
    if ch == '?':
        return _Node('repeat', child=node, low=0, high=1), pos + 1
    if ch == '{':
        end = pattern.find('}', pos)
        if end == -1:
            raise RegexError("量词缺少右花括号 }")
        body = pattern[pos + 1:end]
        try:
            if ',' in body:
                low_str, high_str = body.split(',', 1)
                low = int(low_str) if low_str else 0
                high = int(high_str) if high_str else MAX_REPEAT
            else:
                low = high = int(body)
        except ValueError:
            raise RegexError(f"量词格式非法: {{{body}}}")
        if high < low:
            raise RegexError(f"量词上下界非法: {{{body}}}")
        high = min(high, MAX_REPEAT)
        low = min(low, MAX_REPEAT)
        return _Node('repeat', child=node, low=low, high=high), end + 1
    return node, pos


def _parse_seq(pattern, pos, depth):
    terms = []
    while pos < len(pattern) and pattern[pos] not in '|)':
        node, pos = _parse_term(pattern, pos, depth)
        terms.append(node)
    return _Node('seq', terms=terms), pos


def _parse_alt(pattern, pos, depth):
    if depth > MAX_DEPTH:
        raise RegexError("正则嵌套层级过深")
    branches = []
    node, pos = _parse_seq(pattern, pos, depth)
    branches.append(node)
    while pos < len(pattern) and pattern[pos] == '|':
        node, pos = _parse_seq(pattern, pos + 1, depth)
        branches.append(node)
    return _Node('alt', branches=branches), pos


def _gen(node, rng=None):
    kind = node.kind
    if kind == 'literal':
        return node.value
    if kind == 'empty':
        return ''
    if kind == 'class':
        return rng.choice(node.charset)
    if kind == 'any':
        return rng.choice(string.ascii_letters + string.digits)
    if kind == 'seq':
        return ''.join(_gen(t, rng) for t in node.terms)
    if kind == 'alt':
        return _gen(rng.choice(node.branches), rng)
    if kind == 'repeat':
        times = rng.randint(node.low, node.high)
        return ''.join(_gen(node.child, rng) for _ in range(times))
    raise RegexError(f"未知的正则节点: {kind}")


def generate(pattern: str, rng=None) -> str:
    """
    生成一个匹配 pattern 的随机字符串

    :param pattern: 正则表达式
    :param rng:     随机源, 传入带种子的 random.Random 实例才能保证可重放
    :return: 匹配该正则的字符串
    """
    if not pattern:
        raise RegexError("正则不能为空")
    rng = rng or _DEFAULT_RNG
    node, pos = _parse_alt(pattern, 0, 0)
    if pos != len(pattern):
        raise RegexError(f"正则解析失败, 位置 {pos}: {pattern}")
    return _gen(node, rng)
