from enum import IntEnum


class AIModelTypeEnum(object):
    """AI模型类型,对应前端展示的标签"""

    chat = "chat"
    embedding = "embedding"
    rerank = "rerank"
    image = "image"

    @classmethod
    def types(cls):
        return [
            {"name": "对话", "value": cls.chat},
            {"name": "向量", "value": cls.embedding},
            {"name": "重排序", "value": cls.rerank},
            {"name": "图像", "value": cls.image},
        ]

    @classmethod
    def labels(cls):
        """前端模型列表里直接展示的标签文案"""
        return {
            cls.chat: "对话chat",
            cls.embedding: "向量embedding",
            cls.rerank: "重排序rerank",
            cls.image: "图像image",
        }

    @classmethod
    def name(cls, value):
        """操作日志里展示的中文名"""
        for item in cls.types():
            if item["value"] == value:
                return item["name"]
        return value


class AIModelSourceEnum(IntEnum):
    """模型来源"""

    custom = 3      # 自定义添加
    remote = 2      # 厂商接口拉取
    system = 1      # 系统预置模板