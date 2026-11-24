from enum import Enum


class OssEnum(Enum):
    ALIYUN = "aliyun"
    QINIU = "qiniu"
    TENCENT = "cos"
    # 本地文件系统存储 —— 开发环境默认, 零外部依赖(见 middleware/oss/local.py)
    LOCAL = "local"
