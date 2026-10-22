"""
AI 厂商与预置模型模板

VENDORS  : 首次访问 /ai 接口时由 AIVendorDao.ensure_seed() 幂等写入 pity_ai_vendor
SYSTEM_MODELS: 「获取系统模型」按钮的数据源,平台维护的标准清单,不落库

Base URL 均为 OpenAI 兼容格式,便于统一用 GET {base_url}/models 拉取模型列表。
"""

# 预置厂商清单
# code / 中文名 / 英文名 / Base URL / 控制台地址 / 预置模型
VENDORS = [
    {
        "code": "siliconflow",
        "name": "硅基流动",
        "en_name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "console_url": "https://cloud.siliconflow.cn/account/ak",
    },
    {
        "code": "deepseek",
        "name": "DeepSeek",
        "en_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "console_url": "https://platform.deepseek.com",
    },
    {
        "code": "dashscope",
        "name": "阿里云百炼",
        "en_name": "Alibaba Cloud Bailian",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "console_url": "https://bailian.console.aliyun.com",
    },
    {
        "code": "doubao",
        "name": "豆包",
        "en_name": "Doubao",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "console_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/management/apiKey",
    },
    {
        "code": "moonshot",
        "name": "月之暗面",
        "en_name": "Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "console_url": "https://platform.moonshot.cn/console/api-keys",
    },
    {
        "code": "minimax",
        "name": "MiniMax",
        "en_name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "console_url": "https://platform.minimaxi.com",
    },
    {
        "code": "modelscope",
        "name": "魔搭社区",
        "en_name": "ModelScope",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "console_url": "https://modelscope.cn/my/myaccesstoken",
    },
    {
        "code": "xiaomi",
        "name": "小米",
        "en_name": "MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "console_url": "https://platform.xiaomimimo.com",
    },
    {
        "code": "zhipu",
        "name": "智谱AI",
        "en_name": "ZhipuAI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "console_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    {
        "code": "ollama",
        "name": "本地部署",
        "en_name": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "console_url": "",
    },
]

# 系统预置模型模板,按厂商 code 索引
# name / model_type 参见 app/enums/AIModelEnum.py
SYSTEM_MODELS = {
    "siliconflow": [
        {"name": "deepseek-ai/DeepSeek-V3", "model_type": "chat"},
        {"name": "deepseek-ai/DeepSeek-R1", "model_type": "chat"},
        {"name": "Qwen/Qwen3-235B-A22B", "model_type": "chat"},
        {"name": "THUDM/glm-4-9b-chat", "model_type": "chat"},
        {"name": "BAAI/bge-m3", "model_type": "embedding"},
        {"name": "BAAI/bge-reranker-v2-m3", "model_type": "rerank"},
    ],
    "deepseek": [
        {"name": "deepseek-chat", "model_type": "chat"},
        {"name": "deepseek-reasoner", "model_type": "chat"},
    ],
    "dashscope": [
        {"name": "qwen-max", "model_type": "chat"},
        {"name": "qwen-plus", "model_type": "chat"},
        {"name": "qwen-turbo", "model_type": "chat"},
        {"name": "text-embedding-v3", "model_type": "embedding"},
        {"name": "qwen3-rerank-0.6b", "model_type": "rerank"},
    ],
    "doubao": [
        {"name": "doubao-pro-32k", "model_type": "chat"},
        {"name": "doubao-lite-32k", "model_type": "chat"},
        {"name": "doubao-1.5-pro-32k", "model_type": "chat"},
        {"name": "doubao-embedding", "model_type": "embedding"},
    ],
    "moonshot": [
        {"name": "moonshot-v1-8k", "model_type": "chat"},
        {"name": "moonshot-v1-32k", "model_type": "chat"},
        {"name": "moonshot-v1-128k", "model_type": "chat"},
    ],
    "minimax": [
        {"name": "MiniMax-M3", "model_type": "chat"},
        {"name": "MiniMax-M2.7", "model_type": "chat"},
        {"name": "MiniMax-M2.7-highspeed", "model_type": "chat"},
    ],
    "modelscope": [
        {"name": "Qwen/Qwen3-235B-A22B-Instruct", "model_type": "chat"},
        {"name": "Qwen/Qwen3-32B", "model_type": "chat"},
        {"name": "deepseek-ai/DeepSeek-V3", "model_type": "chat"},
    ],
    "xiaomi": [
        {"name": "mimo-v2.6-pro", "model_type": "chat"},
        {"name": "mimo-v2.6-flash", "model_type": "chat"},
        {"name": "mimo-v2.6-pro-ultraspeed", "model_type": "chat"},
    ],
    "zhipu": [
        {"name": "glm-4-plus", "model_type": "chat"},
        {"name": "glm-4-air", "model_type": "chat"},
        {"name": "glm-4-flash", "model_type": "chat"},
        {"name": "embedding-3", "model_type": "embedding"},
        {"name": "rerank", "model_type": "rerank"},
    ],
    # 本地部署的模型取决于用户自己装了啥,不预置
    "ollama": [],
}


def list_system_models(vendor_code: str):
    """按厂商 code 取系统预置模型清单,未知厂商返回空列表"""
    return SYSTEM_MODELS.get(vendor_code, [])