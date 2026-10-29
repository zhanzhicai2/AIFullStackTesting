"""
日志异常聚类 —— **纯 Python, 不调用模型**

日志分析场景的第一层是确定性的, 第二层(逐簇归因)才交给模型:

```
原始日志
  ↓ ① 纯 Python 预处理(零 AI 调用)
  │   抽取异常栈 → 归一化(时间戳/行号/对象ID/十六进制地址/内存地址 → 占位符)
  │   → fingerprint → 按指纹分组计数
  ↓ ② 纯统计(零 AI 调用)
  │   按分钟计数 → 超过 p95 判为"异常突增"
  ↓ ③ AI 只解读 Top-N 簇(research.md §3.12)
```

**为什么要先聚类**: 让模型逐行判断, 成本与日志行数成正比, 10MB 日志不可行,
而且结果不稳定(同一类错误可能被拆成多簇)。归一化后指纹相同即判为同一簇 ——
纯字符串处理, 可以处理 MB 级日志且**零 token 成本**。

归一化的规则来自 research.md §3.12: 同一类错误在不同时间/不同请求下,
只有「时间戳 / UUID / 十六进制地址 / 内存地址 / 行号 / 对象 ID」这些片段不同。
"""
import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 行判定
# ---------------------------------------------------------------------------
# 错误行: 含异常关键字, 或带 loguru 的级别标记
ERROR_PATTERN = re.compile(r"(Exception|Error|ERROR|WARNING|Traceback|FATAL|CRITICAL|panic:)")
# 栈帧行: Java 的 `at com.foo.Bar.baz(Bar.java:42)` 或 Python 的 `File "x.py", line 42`
FRAME_PATTERN = re.compile(r'^\s*(?:at\s+[\w.$<>\[\]]+\s*\([^)]*\)|File\s+"[^"]*",\s+line\s+\d+)')

# 日志行里的时间戳(loguru 格式: 2026-10-26 03:12:44 | ERROR | ...)
TIMESTAMP_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")

# ---------------------------------------------------------------------------
# 归一化规则 —— 顺序敏感, 先具体后笼统
# ---------------------------------------------------------------------------
# 平台的日志格式是:
#   2026-10-12 21:41:26.222 | ERROR | 文件: .../UserDao.py | 模块: UserDao | 方法: login | 行数: 168 | - 消息
# 所以「行号」「对象 ID」有中英文两种写法, 都要归一化。
NORMALIZERS = [
    # 完整时间戳
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"), "<TS>"),
    # 纯时刻
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"), "<TS>"),
    # UUID —— 必须排在 HEX 前面, 否则 12 位的十六进制段会先被吃掉
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
     "<UUID>"),
    # 内存地址
    (re.compile(r"0x[0-9a-fA-F]+"), "<ADDR>"),
    # 长十六进制串
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "<HEX>"),
    # 英文对象 ID: case_id=101 / user_id: 5 / id=99
    (re.compile(r"(?i)\b([a-z][a-z0-9_]*_id|id)\s*[=:：]\s*\"?\d+"), r"\1=<ID>"),
    # 中文对象 ID: 用户ID: 5 / 用例编号: 12
    (re.compile(r"((?:用户|用例|请求|任务|订单)ID|用户编号|用例编号)\s*[=:：]\s*\d+"), r"\1=<ID>"),
    # 中文行号: 行数: 168
    (re.compile(r"(行数|行号)\s*[=:：]\s*\d+"), r"\1=<LINE>"),
    # 源文件行号: app/api/user.py:42
    (re.compile(r"([\w./\\-]+\.(?:py|java|js|jsx|ts|tsx|go|rb|php|cs|kt|swift)):(\d+)"), r"\1:<LINE>"),
    # 英文行号: line 42
    (re.compile(r"(?i)\bline\s+\d+\b"), "line <LINE>"),
    # 中文消息里夹的编号: 用户23登录失败
    (re.compile(r"(用户|用例|请求|订单|任务)\s*\d+"), r"\1<ID>"),
    # 长数字(对象 ID)
    (re.compile(r"\b\d{6,}\b"), "<ID>"),
]

# 影响面统计: 从日志行里提取 case_id / user_id
CASE_ID_PATTERN = re.compile(r"\b(?:case_id|caseId|case)\s*[=:：]\s*(\d+)", re.IGNORECASE)
USER_ID_PATTERN = re.compile(r"\b(?:user_id|userId|uid)\s*[=:：]\s*(\d+)", re.IGNORECASE)

# 单个样例保留的最大字符数(样例是要送进模型的, 不能无限长)
MAX_SAMPLE_CHARS = 2000

# 默认最多处理的行数
DEFAULT_MAX_LINES = 20000


def normalize(text: str) -> str:
    """
    归一化一行(或一段)文本 —— 把每次都不同的片段替换成占位符。

    归一化后完全相同的文本 → 指纹相同 → 判为同一簇。
    """
    content = text if text is not None else ""
    for pattern, replacement in NORMALIZERS:
        content = pattern.sub(replacement, content)
    return content


def fingerprint(text: str) -> str:
    """
    取归一化后文本的指纹(8 位十六进制)。

    用 sha256 而不是 md5: 一是避免个别环境禁用 md5, 二是 sha256 同样快。
    """
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def parse_timestamp(line: str) -> Optional[datetime]:
    """从一行日志里解析出时间戳; 解析不出来返回 None"""
    if not line:
        return None
    matched = TIMESTAMP_PATTERN.search(line)
    if not matched:
        return None
    raw = matched.group(1).replace("T", " ").replace(",", ".")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def is_error_line(line: str) -> bool:
    """是否是一条错误行"""
    return bool(ERROR_PATTERN.search(line or ""))


def is_frame_line(line: str) -> bool:
    """是否是栈帧行"""
    return bool(FRAME_PATTERN.match(line or ""))


def extract_events(lines: List[str]) -> List[Tuple[int, List[str]]]:
    """
    把日志行切成**错误事件**: 一条错误行 + 其后连续的栈帧行。

    :param lines: 日志行
    :return:     [(起始行下标, [错误行, 栈帧行...]), ...]
    """
    events = []
    index, total = 0, len(lines)
    while index < total:
        line = lines[index]
        if is_error_line(line):
            frames = []
            cursor = index + 1
            while cursor < total and is_frame_line(lines[cursor]):
                frames.append(lines[cursor])
                cursor += 1
            events.append((index, [line] + frames))
            index = cursor
        else:
            index += 1
    return events


def _percentile(values: List[int], percent: int) -> float:
    """
    百分位 —— **线性插值法**(与 numpy 默认的 'linear' 一致)。

    为什么不用最近秩法: 最近秩在样本数 ≤ 20 时, p95 恰好等于最大值
    (rank = ceil(0.95*N)-1 = N-1), 于是"count > p95"永远不成立 ——
    日志只有十几个分钟时**一个突增都检不出来**。线性插值在样本少时会把
    阈值压到最大值以下(如 [1,1,1,30] → 28.95), 突增能被检出;
    样本多时两者结果基本一致, 不改变既有语义。

    :param values:  样本(不要求有序)
    :param percent: 百分位(0-100)
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (percent / 100) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def detect_spikes(events: List[Tuple[int, List[str]]]) -> List[dict]:
    """
    异常突增检测 —— 按分钟计数, 超过 p95 判为突增。

    `baseline` 取的是 p95 阈值本身(即"正常分钟的计数上界"),
    突增分钟的计数要明显高于它 —— 契约里的例子是 count=342 / baseline=12。

    :param events: extract_events 的产物
    :return:       [{"start_at", "end_at", "count", "baseline"}, ...]
    """
    per_minute = Counter()
    for _, block in events:
        stamp = parse_timestamp(block[0])
        if stamp is None:
            continue
        per_minute[stamp.strftime("%Y-%m-%d %H:%M")] += 1
    if not per_minute:
        return []

    threshold = _percentile(list(per_minute.values()), 95)
    spike_minutes = sorted(k for k, v in per_minute.items() if v > threshold)
    if not spike_minutes:
        return []

    spikes = []
    bucket = [spike_minutes[0]]
    for item in spike_minutes[1:]:
        previous = datetime.strptime(bucket[-1], "%Y-%m-%d %H:%M")
        current = datetime.strptime(item, "%Y-%m-%d %H:%M")
        if current - previous == timedelta(minutes=1):
            bucket.append(item)
        else:
            spikes.append(_build_spike(bucket, per_minute, threshold))
            bucket = [item]
    spikes.append(_build_spike(bucket, per_minute, threshold))
    return spikes


def _build_spike(bucket: List[str], per_minute: Counter, threshold: float) -> dict:
    start = datetime.strptime(bucket[0], "%Y-%m-%d %H:%M")
    end = datetime.strptime(bucket[-1], "%Y-%m-%d %H:%M")
    count = sum(per_minute.get(key, 0) for key in bucket)
    return {
        "start_at": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_at": end.strftime("%Y-%m-%d %H:%M:%S"),
        "count": count,
        "baseline": int(threshold),
    }


def cluster_logs(text: str, max_lines: int = DEFAULT_MAX_LINES) -> dict:
    """
    日志聚类主入口 —— **纯确定性, 不调模型**。

    :param text:     日志正文
    :param max_lines: 最多处理的行数, 超出则按头尾截断
    :return: {"total_lines", "error_clusters", "spikes", "truncated"}
    """
    content = text if text is not None else ""
    lines = content.splitlines()
    total_lines = len(lines)
    truncated = False
    if max_lines and total_lines > max_lines:
        head = int(max_lines * 0.75)
        tail = max_lines - head
        lines = lines[:head] + lines[-tail:]
        truncated = True

    events = extract_events(lines)
    buckets: Dict[str, dict] = {}
    order: List[str] = []
    for _, block in events:
        normalized = normalize("\n".join(block))
        key = fingerprint(normalized)
        if key not in buckets:
            buckets[key] = {
                "fingerprint": key,
                "sample": "\n".join(block)[:MAX_SAMPLE_CHARS],
                "count": 0,
                "first_at": "",
                "last_at": "",
                "scope": {"cases": 0, "users": 0},
                "_cases": set(),
                "_users": set(),
            }
            order.append(key)
        bucket = buckets[key]
        bucket["count"] += 1
        stamp = parse_timestamp(block[0])
        if stamp is not None:
            formatted = stamp.strftime("%Y-%m-%d %H:%M:%S")
            if not bucket["first_at"] or formatted < bucket["first_at"]:
                bucket["first_at"] = formatted
            if not bucket["last_at"] or formatted > bucket["last_at"]:
                bucket["last_at"] = formatted
        for line in block:
            for matched in CASE_ID_PATTERN.finditer(line):
                bucket["_cases"].add(matched.group(1))
            for matched in USER_ID_PATTERN.finditer(line):
                bucket["_users"].add(matched.group(1))

    clusters = []
    for key in order:
        bucket = buckets[key]
        clusters.append({
            "fingerprint": bucket["fingerprint"],
            "sample": bucket["sample"],
            "count": bucket["count"],
            "first_at": bucket["first_at"],
            "last_at": bucket["last_at"],
            "scope": {"cases": len(bucket["_cases"]), "users": len(bucket["_users"])},
        })
    # 出现次数多的排前面, 便于前端只解读 Top-N
    clusters.sort(key=lambda item: (-item["count"], item["fingerprint"]))

    return {
        "total_lines": total_lines,
        "error_clusters": clusters,
        "spikes": detect_spikes(events),
        "truncated": truncated,
    }
