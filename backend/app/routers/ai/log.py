"""
日志分析路由 —— AI 工作台的 US3

前缀 `/ai`。契约见 `specs/001-ai-workbench/contracts/api.md` §4.2 / §4.4。

**`/ai/log/cluster` 不调用模型** —— 纯确定性处理(归一化 + 指纹分组 + p95 突增检测)。
模型只在 `/ai/log/analyze` 里出现, 而且只解读**一个错误簇**。

**平台自身日志要 ADMIN**(spec FR-041) —— 它是服务端运行日志, 可能带内部路径与堆栈。
"""
import json
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from app.core import ai_service
from app.core.ai_client import ChatError
from app.core.ai_prompts import clustering, log
from app.crud.ai.AIAnalysisDao import AIAnalysisDao
from app.exception.request import PermissionException
from app.handler.fatcory import PityResponse
from app.routers import Permission
from app.routers.ai.base import router
from app.schema.ai_workbench import LogAnalyzeForm, LogClusterForm
from app.utils.ui_security import is_blocked_ip, resolve_host
from config import Config

# 日志正文的上限 —— 10MB(research.md §3.5)
MAX_LOG_BYTES = 10 * 1024 * 1024


class LogSourceError(Exception):
    """日志来源不可用"""


def _read_platform_log() -> str:
    """平台自身日志 —— `backend/logs/pity_error.log`"""
    path = os.path.join(Config.LOG_DIR, "pity_error.log")
    if not os.path.exists(path):
        raise LogSourceError("平台运行日志不存在")
    size = os.path.getsize(path)
    if size > MAX_LOG_BYTES:
        # 超了只读尾部 —— 错误日志最有价值的是最近的
        with open(path, "rb") as handle:
            handle.seek(-MAX_LOG_BYTES, os.SEEK_END)
            return handle.read().decode("utf-8", errors="ignore")
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


async def _read_oss_file(file_id: int) -> str:
    """
    取已上传的日志文件 —— 按 `pity_oss_file.view_url` 下载。

    ⚠️ 这是**出网**请求, 复用 UI 子系统的 SSRF 兜底(002 的 `is_blocked_ip` /
    `resolve_host`): 只允许 http/https, 且**解析后不许落在私网/环回/链路本地**。
    `view_url` 是平台自己上传时写进去的, 但仍按外部输入对待 —— 宁可误杀。
    """
    import aiohttp

    from app.crud.oss.PityOssDao import PityOssDao

    record = await PityOssDao.query_file(file_id)
    if record is None:
        raise LogSourceError("日志文件不存在")
    url = record.view_url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise LogSourceError("日志文件地址不合法")
    host = parsed.hostname or ""
    for ip in resolve_host(host):
        if is_blocked_ip(ip):
            raise LogSourceError("日志文件地址指向内网, 已拒绝")
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise LogSourceError(f"取日志文件失败(HTTP {resp.status})")
                data = await resp.content.read(MAX_LOG_BYTES + 1)
    except LogSourceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LogSourceError(f"取日志文件失败: {e}")
    if len(data) > MAX_LOG_BYTES:
        data = data[-MAX_LOG_BYTES:]
    return data.decode("utf-8", errors="ignore")


@router.post("/log/cluster", description="日志聚类(不调用模型)")
async def cluster_logs(form: LogClusterForm, user_info=Depends(Permission())):
    """
    日志聚类 —— **纯确定性, 不产生任何模型调用**。

    三种来源:
    - `platform` 平台自身运行日志 —— **需要 ADMIN**(FR-041)
    - `file`     已上传的日志文件(`file_id`)
    - `text`     粘贴的文本
    """
    try:
        if form.source == "platform":
            # 平台自身日志是服务端运行日志 —— 收紧到 ADMIN(FR-041)
            await _require_admin(user_info)
            text = _read_platform_log()
        elif form.source == "file":
            if not form.file_id:
                return PityResponse.failed("请指定日志文件")
            text = await _read_oss_file(form.file_id)
        else:
            text = form.text or ""
            if not text.strip():
                return PityResponse.failed("请粘贴日志内容")

        result = clustering.cluster_logs(text, max_lines=form.max_lines or clustering.DEFAULT_MAX_LINES)
        return PityResponse.success(result, msg="聚类完成")
    except LogSourceError as e:
        return PityResponse.failed(str(e))
    except PermissionException:
        # 交给全局异常处理器 → code 403(契约 api.md §5)
        raise
    except Exception as e:
        return PityResponse.failed(e)


@router.post("/log/analyze", description="错误簇归因")
async def analyze_cluster(form: LogAnalyzeForm, user_info=Depends(Permission())):
    """
    对一个错误簇归因 —— 模型只解读这一个簇。

    `evidence` 逐条做**簇内日志行**的子串匹配, 对不上的移入 `unsupported`。
    结论落 `pity_ai_analysis`(每次一行, 永不覆盖)。
    """
    user_id = user_info['id']
    try:
        samples = [str(item) for item in (form.samples or [])][:log.MAX_SAMPLE_LINES]
        sample = samples[0] if samples else ""
        messages = log.build_messages(form.fingerprint, sample, form.count or 0, samples)

        def parser(text: str):
            return log.parse_result(text, samples)

        result = await ai_service.invoke(messages, form.vendor_id, form.model_id,
                                         scene="log", parser=parser, user_id=user_id)
        conclusion = result.data or {}

        analysis = await AIAnalysisDao.insert_analysis(
            title=f"错误簇 {form.fingerprint}", user_id=user_id, scene="log",
            result=json.dumps(conclusion, ensure_ascii=False),
            ref_type="log_cluster", vendor_id=result.vendor_id,
            model_name=result.model_name, tokens=result.tokens)
        payload = dict(conclusion)
        payload["analysis_id"] = analysis.id
        return PityResponse.success(payload, msg="归因完成")
    except ChatError as e:
        return PityResponse.failed(str(e))
    except ai_service.AIJsonError as e:
        return PityResponse.failed(f"模型返回的内容无法解析为合法结构: {e}, 请重试")
    except Exception as e:
        return PityResponse.failed(e)


async def _require_admin(user_info):
    """平台自身日志的权限校验 —— 必须是管理员"""
    role = user_info.get("role", 0)
    if role < Config.ADMIN:
        raise PermissionException(200, "无权访问平台运行日志")
