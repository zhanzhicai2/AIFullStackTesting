import inspect
import os

from loguru import logger

from config import Config


# @SingletonDecorator
class Log(object):
    business = None

    def __init__(self, name='pity'):  # Logger标识默认为app
        """
        :param name: 业务名称
        """
        # 如果目录不存在则创建
        if not os.path.exists(Config.LOG_DIR):
            os.mkdir(Config.LOG_DIR)
        self.business = name

    def info(self, message: str):
        # 必须用 .info() —— info sink 的 level 是 INFO, 走 .debug() 会被整条过滤掉
        # (这就是 pity_info.log 曾经恒为 0 字节的原因)
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_INFO, func=func, line=line,
                    business=self.business, filename=file_name).info(message)

    def success(self, message: str):
        # SUCCESS(25) 低于 WARNING(30), 只有绑到 info 这一侧才落得进文件
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_INFO, func=func, line=line,
                    business=self.business, filename=file_name).success(message)

    def error(self, message: str):
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_ERROR, func=func, line=line,
                    business=self.business, filename=file_name).error(message)

    def warning(self, message: str):
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_ERROR, func=func, line=line,
                    business=self.business, filename=file_name).warning(message)

    def debug(self, message: str):
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_INFO, func=func, line=line,
                    business=self.business, filename=file_name).debug(message)

    def exception(self, message: str):
        file_name, line, func, _, _ = inspect.getframeinfo(inspect.currentframe().f_back)
        logger.bind(name=Config.PITY_ERROR, func=func, line=line,
                    business=self.business, filename=file_name).exception(message)
