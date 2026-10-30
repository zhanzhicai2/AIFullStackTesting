"""
Mock 配置的跨端常量 —— **后端是权威定义**

constitution 原则 III 要求"前后端共享的常量、枚举、规则表 MUST 有唯一权威定义,
MUST NOT 两端各写一份再靠约定保持一致"。

本文件是以下常量的**唯一权威定义**:
- `METHODS`         请求方法白名单(GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS/ANY)
- `PATH_TYPE_*`     路径类型(0 精确 / 1 参数化 / 2 通配)
- `MAX_DELAY`       模拟延迟上限(毫秒)
- `MIN/MAX_STATUS_CODE` 响应状态码上下限

**前端镜像**: `frontend/src/consts/mock.ts`
⚠️ **改一处必须同时改另一处** —— 契约见 `specs/003-mock-config/contracts/api.md` §4。
前端只是镜像, 不是第二份定义; 后端是最终裁决者(不在白名单内的字段被拒绝)。
"""
from typing import List

# 请求方法白名单。ANY = 匹配任意方法(对外服务按请求 method 过滤时视为通配)。
METHODS: List[str] = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "ANY"]

# 路径类型(存储时由 path 推导并固化, 见 app/core/mock_engine.py 的 derive_path_type)
PATH_TYPE_EXACT = 0      # 精确: 路径完全相等
PATH_TYPE_PARAM = 1      # 参数化: 含 :xxx, 匹配一个路径段
PATH_TYPE_WILDCARD = 2   # 通配: 含末尾 *, 匹配剩余任意内容

# 模拟延迟上限(毫秒) —— 超过即拦, 防止把 mock 服务变成慢速放大器
MAX_DELAY = 5000
# 响应状态码范围(HTTP 语义)
MIN_STATUS_CODE = 100
MAX_STATUS_CODE = 599

# 规则路径上限(字符)
MAX_PATH_LENGTH = 255
