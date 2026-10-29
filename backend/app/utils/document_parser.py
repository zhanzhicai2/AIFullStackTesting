"""
文档解析 —— 需求文档(PDF / Word / Markdown / 纯文本) → 纯文本

**边界(research.md §3.7)**:
- 只接受四种类型, 其余直接拒绝并说明支持哪些类型
- 单文件 ≤ 20MB
- 解析失败**降级为纯文本读取**, 并明确建议改用文本输入 ——
  用户上传了文档但平台解析不了时, 最有用的响应是"我读到了 X 字节但没解析出正文",
  而不是一句"格式不支持"。静默用空内容生成更糟: 模型会拿到空输入, 产出凭空编造的用例。
- 超长按**头尾截断**, 并在结果里标注 `truncated`

⚠️ 解析结果会进 prompt → 会出网到第三方厂商。调用方必须用
`app/core/ai_prompts/base.py` 的 `wrap_document` 包裹后再送进模型。
"""
import io
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.ai_prompts.base import MAX_DOCUMENT_CHARS, truncate

# 单文件大小上限 —— 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# 类型白名单 —— 扩展名 -> 中文名
SUPPORTED_EXTENSIONS = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".txt": "纯文本",
}

# 报错文案里用到的类型清单
SUPPORTED_HINT = "PDF / Word(.docx) / Markdown / 纯文本"


class DocumentError(Exception):
    """文档解析失败 —— 路由层转成 PityResponse.failed()"""


@dataclass
class ParsedDocument:
    """解析结果"""
    filename: str = ""
    content: str = ""
    chars: int = 0
    truncated: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "content": self.content,
            "chars": self.chars,
            "truncated": self.truncated,
            "warnings": list(self.warnings),
        }


def get_extension(filename: str) -> str:
    """取小写扩展名(含点)"""
    name = (filename or "").strip()
    index = name.rfind(".")
    if index == -1:
        return ""
    return name[index:].lower()


def check_type(filename: str) -> str:
    """
    校验文件类型 —— 不在白名单里直接拒绝。

    :return: 文件类型的中文名
    :raise DocumentError: 类型不支持
    """
    extension = get_extension(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError(f"不支持的文件类型, 当前支持 {SUPPORTED_HINT}")
    return SUPPORTED_EXTENSIONS[extension]


def check_size(size: int) -> None:
    """
    校验文件大小 —— 超过 20MB 直接拒绝。

    :raise DocumentError: 超过上限
    """
    if size and size > MAX_FILE_SIZE:
        raise DocumentError("文件超过 20MB 上限")


def _decode_text(data: bytes) -> Optional[str]:
    """
    把字节流当纯文本读 —— utf-8 优先, 失败试 gbk(中文旧文件常见)。

    解出来的东西如果大部分是不可打印字符, 说明这压根不是文本, 返回 None。
    """
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if not text:
            continue
        printable = sum(1 for ch in text[:4096] if ch.isprintable() or ch in "\r\n\t")
        if printable / max(1, len(text[:4096])) > 0.85:
            return text
    return None


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise DocumentError("服务器未安装 pypdf, 无法解析 PDF, 请改用文本输入")
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    except DocumentError:
        raise
    except Exception as e:
        raise DocumentError(f"PDF 解析失败: {e}")


def _parse_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        raise DocumentError("服务器未安装 python-docx, 无法解析 Word, 请改用文本输入")
    try:
        document = docx.Document(io.BytesIO(data))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        return "\n".join(paragraphs)
    except DocumentError:
        raise
    except Exception as e:
        raise DocumentError(f"Word 解析失败: {e}")


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """
    解析文档 —— 主入口。

    :param filename: 上传的文件名(用于判定类型)
    :param data:     文件字节
    :return:         ParsedDocument
    :raise DocumentError: 类型不支持 / 超过上限 / 解析彻底失败
    """
    kind = check_type(filename)
    check_size(len(data or b""))

    warnings: List[str] = []
    content = ""
    try:
        if kind == "PDF":
            content = _parse_pdf(data)
        elif kind == "Word":
            content = _parse_docx(data)
        else:
            text = _decode_text(data or b"")
            if text is None:
                raise DocumentError(f"{kind} 文件无法解码, 请改用文本输入")
            content = text
    except DocumentError as e:
        # 降级(research.md §3.7): 解析失败**不阻断整个生成任务** ——
        # 尝试把文件当纯文本读。仍然读不出正文才报错, 并建议改用文本输入。
        fallback = _decode_text(data or b"")
        if fallback and fallback.strip():
            warnings.append(f"按文档格式解析失败({e}), 已降级为纯文本读取")
            content = fallback
        else:
            raise DocumentError(f"{e}; 且无法按纯文本读取, 请改用文本输入")

    if not content.strip():
        # 解析成功但正文为空 —— 多半是扫描件 PDF 或纯图片 Word
        fallback = _decode_text(data or b"")
        if fallback and fallback.strip():
            warnings.append("未能按文档格式提取到正文, 已降级为纯文本读取")
            content = fallback
        else:
            warnings.append("未能提取到正文(可能是扫描件或纯图片文档), 建议改用文本输入")
            content = ""

    truncated = False
    if len(content) > MAX_DOCUMENT_CHARS:
        content, truncated, note = truncate(content, MAX_DOCUMENT_CHARS)
        if note:
            warnings.append(note)

    return ParsedDocument(filename=filename, content=content, chars=len(content),
                          truncated=truncated, warnings=warnings)
