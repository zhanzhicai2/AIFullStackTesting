from app.core.configuration import SystemConfiguration
from app.enums.OssEnum import OssEnum
from app.middleware.oss.aliyun import AliyunOss
from app.middleware.oss.files import OssFile
from app.middleware.oss.local import LocalOss
from app.middleware.oss.qiniu import QiniuOss
from app.middleware.oss.tencent import TencentCos


class OssClient(object):
    _client = None

    @classmethod
    def get_oss_client(cls) -> OssFile:
        """
        通过oss配置拿到oss客户端
        :return:
        """
        if cls._client is None:
            cfg = SystemConfiguration.get_config()
            oss_config = cfg.get("oss")
            if oss_config is None:
                raise Exception("服务器未配置oss信息, 请在configuration.json中添加")
            oss_type = oss_config.get("oss_type")
            if oss_type is None:
                raise Exception("服务器oss信息缺少oss_type字段, 请在configuration.json中检查")
            access_key_id = oss_config.get("access_key_id")
            access_key_secret = oss_config.get("access_key_secret")
            bucket = oss_config.get("bucket")
            endpoint = oss_config.get("endpoint")
            oss_type = oss_type.lower()
            if oss_type == OssEnum.ALIYUN.value:
                cls._client = AliyunOss(access_key_id, access_key_secret, endpoint, bucket)
            elif oss_type == OssEnum.QINIU.value:
                # 桶的访问域名从配置读(oss.endpoint); 没配就回退到七云默认域名。
                # ⚠️ 以前这里用的是硬编码的 QINIU_URL, 而那个域名(static.pity.fun)已失效 ——
                # 上传能成功(走七牛 API), 但返回的链接打不开、后端自己下载也失败。
                domain = endpoint or f"http://{bucket}.hdslb.com"
                cls._client = QiniuOss(access_key_id, access_key_secret, bucket, domain)
            elif oss_type == OssEnum.TENCENT.value:
                cls._client = TencentCos(access_key_id, access_key_secret, endpoint, bucket)
            elif oss_type == OssEnum.LOCAL.value:
                cls._client = LocalOss()
            else:
                raise Exception(f"不支持的oss类型: {oss_type}")
        return cls._client
