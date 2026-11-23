"""
持续集成(CI)的跨端常量 —— **后端是权威定义**

constitution 原则 III 要求"前后端共享的常量、枚举、规则表 MUST 有唯一权威定义,
MUST NOT 两端各写一份再靠约定保持一致"。

本文件是以下常量的**唯一权威定义**:
- `CI_NOT_PASSED` / `CI_WAIT_TIMEOUT`  业务结果码(111 测试未通过 / 112 等待超时)
- `RunStatus.*`                        触发记录的六态(0 pending … 5 error)
- `TOKEN_PREFIX` / `TOKEN_EXPIRE_DAYS` 接入凭据的前缀与默认有效期
- `WAIT_TIMEOUT_*`                     等待语义的默认/上限秒数

**前端镜像**: `frontend/src/consts/ci.ts`
⚠️ **改一处必须同时改另一处** —— 契约见 `specs/004-ci/contracts/api.md` §0、§4。
前端只是镜像, 不是第二份定义; 后端是最终裁决者。

**业务码说明**(CLAUDE.md「响应格式」): 沿用平台既有 `0 / 101 / 110 / 401 / 403` 区段
递增新增两档, **不混入 200/300/500 这类 HTTP 段**; 所有 HTTP 响应仍恒为 200,
判定看 body 的 `code`。
"""


class CiErrorCode:
    """CI 相关业务码 —— 增量落在既有同区段, 见 CLAUDE.md 响应码表"""

    # 测试未通过(决定 Q2) —— 与「平台执行失败」必须可区分(spec FR-015 / SC-006)
    NOT_PASSED = 111
    # 等待超时, 执行仍在后台继续(spec FR-011) —— 与 111/110 可区分, CI 据此决定
    # 「再轮询一次」还是「按自身策略判失败」
    WAIT_TIMEOUT = 112


class RunStatus:
    """`pity_ci_run.status` 六态 —— data-model.md §3.1 状态机"""

    PENDING = 0     # 已受理, 未开始
    RUNNING = 1     # 执行中
    SUCCESS = 2     # 测试通过
    FAILED = 3      # 测试未通过(测试红了)
    TIMEOUT = 4     # 等待超时(可能仍在跑, 终态由回填步骤写)
    ERROR = 5       # 平台执行失败 / 重启中断(平台坏了)

    ALL = (PENDING, RUNNING, SUCCESS, FAILED, TIMEOUT, ERROR)
    # 「可能仍在跑」的中间态 —— 重启时必须收敛到 ERROR(data-model.md §3.2)
    IN_FLIGHT = (PENDING, RUNNING)
    # 终态(不再变化)
    TERMINAL = (SUCCESS, FAILED, TIMEOUT, ERROR)


# 接入凭据明文前缀 —— `pity_ci_` + secrets.token_hex(16) = 40 字符
# 明文只在签发响应里出现一次, 之后任何读路径都拿不到(spec FR-002)
TOKEN_PREFIX = "pity_ci_"
TOKEN_RANDOM_HEX_LEN = 32      # token_hex(16) 的十六进制长度
TOKEN_PREFIX_LEN = 12          # 仅供界面辨识, **校验不使用它**
TOKEN_DEFAULT_EXPIRE_DAYS = 365  # 决定 Q4: 默认 1 年; 显式传 null = 长期有效

# 等待语义(spec FR-011 / 决定 Q3: 默认不等待)
WAIT_DEFAULT = False
WAIT_TIMEOUT_DEFAULT_SEC = 300
WAIT_TIMEOUT_MIN_SEC = 1
WAIT_TIMEOUT_MAX_SEC = 1800

# 触发记录 error_msg 上限 —— 避免异常堆栈把 TEXT 撑爆(data-model.md §5)
ERROR_MSG_MAX_LEN = 500

# 集成配置字段上限(schema 层校验, 契约 contracts/api.md §2)
INTEGRATION_NAME_MAX_LEN = 32
CALLBACK_URL_MAX_LEN = 255
EXTERNAL_BUILD_ID_MAX_LEN = 64
EXTERNAL_URL_MAX_LEN = 255
