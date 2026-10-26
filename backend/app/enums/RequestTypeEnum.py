from enum import IntEnum


class RequestType(IntEnum):
    http = 1
    grpc = 2
    dubbo = 3
    # 4 原本被 websocket 占位, 但 websocket 从未真正落地(前端只提供 1/2/3,
    # 新建用例的表单只允许 HTTP), 而 UI 自动化子系统的契约明确要求 4 = web_ui,
    # 所以这里把 websocket 挪到 5, 让 4 归 web_ui。存量数据里不存在 request_type=4 的用例。
    web_ui = 4
    websocket = 5
