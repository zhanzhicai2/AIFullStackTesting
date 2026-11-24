import os
import shutil

from awaits.awaitable import awaitable

from app.middleware.oss.files import OssFile
from config import Config


class LocalOss(OssFile):
    """
    本地文件系统存储 —— **开发环境默认**(`configuration_dev.json` 的 `oss_type = "local"`)。

    为什么要它: 原先 dev 配的 `oss_type = "gitee"` 不在 `OssEnum` 里, 调 OSS 接口直接抛
    「不支持的oss类型」, 而 Gitee 的对象存储服务早已下线 —— dev 环境等于没有存储可用。
    本地实现零外部依赖, 头像/附件上传在开发环境能真正跑通。

    文件落盘位置: `Config.OSS_LOCAL_DIR`(默认 `backend/data/oss/`), 结构与云厂商的
    key 一致(`get_real_path` 决定), 所以换成云厂商时同一批 filepath 语义不变。

    对外 URL: `{Config.OSS_LOCAL_URL_PREFIX}/{key}` = `/oss/files/{key}`。
    该前缀已被 nginx(`location ~ ^/(api|auth|...|oss|...)/`)与前端 dev proxy
    (`'/oss/'`)代理到后端, 所以浏览器可直接拿这个 URL 当 `<img src>` 用。
    """

    _base_path = "pity"

    def __init__(self, root: str = None, url_prefix: str = None):
        self.root = root or Config.OSS_LOCAL_DIR
        self.url_prefix = url_prefix or Config.OSS_LOCAL_URL_PREFIX
        os.makedirs(self.root, exist_ok=True)

    def _abs_path(self, key: str) -> str:
        """把 key 拼成绝对路径 —— 顺带挡掉 `../` 目录穿越"""
        safe = os.path.normpath(key).lstrip("/")
        if safe.startswith("..") or os.path.isabs(safe):
            raise Exception(f"非法文件路径: {key}")
        return os.path.join(self.root, safe)

    @awaitable
    def create_file(self, filepath: str, content: bytes, base_path: str = None):
        key = self.get_real_path(filepath, base_path)
        path = self._abs_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return f"{self.url_prefix}/{key}", len(content)

    @awaitable
    def delete_file(self, filepath: str, base_path: str = None):
        key = self.get_real_path(filepath, base_path)
        path = self._abs_path(key)
        if os.path.exists(path):
            os.remove(path)

    @awaitable
    def download_file(self, filepath, base_path: str = None):
        key = self.get_real_path(filepath, base_path)
        path = self._abs_path(key)
        if not os.path.exists(path):
            raise Exception(f"文件不存在: {filepath}")
        filename = key.split("/")[-1]
        # 复制一份临时文件 —— PityResponse.file 用 FileResponse + BackgroundTask
        # 在响应结束后把它删掉, 不能直接返回原文件
        tmp = rf'./{self.get_random_filename(filename)}'
        shutil.copyfile(path, tmp)
        return tmp, filename

    @awaitable
    def get_file_object(self, filepath):
        key = self.get_real_path(filepath)
        path = self._abs_path(key)
        if not os.path.exists(path):
            raise Exception(f"文件不存在: {filepath}")
        with open(path, "rb") as f:
            return f.read()
