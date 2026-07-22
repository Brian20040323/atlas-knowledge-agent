"""Extract text from uploaded files (Office / PDF / images / text)."""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from pathlib import Path

from app.config import ROOT_DIR

UPLOAD_DIR = ROOT_DIR / "data" / "uploads"

ALLOWED_EXT = {
    # text
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".rtf",
    # documents
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
    # archives (expanded on upload)
    ".zip",
    # images
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json"}
ARCHIVE_INNER_EXT = ALLOWED_EXT - {".zip"}


class IngestLimitError(ValueError):
    """Raised when upload size or document length exceeds configured budget."""


def validate_upload_size(data: bytes, max_mb: int) -> None:
    """Reject oversize uploads with a readable message (P1)."""
    limit = max(1, int(max_mb)) * 1024 * 1024
    if len(data) > limit:
        raise IngestLimitError(f"文件过大（上限 {max(1, int(max_mb))}MB，当前 {len(data)} 字节）")


def validate_content_length(content: str, max_chars: int) -> None:
    """Reject overlong document text before write."""
    limit = max(1, int(max_chars))
    n = len(content or "")
    if n > limit:
        raise IngestLimitError(f"文档过长（上限 {limit} 字符，当前 {n} 字符）")


def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\u4e00-\u9fff-]+", "_", base).strip("._")
    return cleaned[:120] or "upload.bin"


def detect_source_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".docx", ".doc"}:
        return "word"
    if ext == ".pptx":
        return "pptx"
    if ext == ".xlsx":
        return "xlsx"
    if ext == ".zip":
        return "zip"
    if ext in IMAGE_EXT:
        return "image"
    if ext in {".md", ".markdown"}:
        return "markdown"
    if ext in {".html", ".htm"}:
        return "html"
    if ext == ".rtf":
        return "rtf"
    if ext in TEXT_EXT:
        return "text"
    return "file"


_FAIL_MARKERS = (
    "未能提取到文本",
    "解析失败",
    "暂不完整支持",
    "未提取到可见正文",
    "未提取到文本",
    "未提取到单元格",
    "未能提取有效文本",
    "未识别到文字",
)


def is_weak_extraction(text: str) -> bool:
    """True when extract is empty, placeholder, or too thin to answer questions."""
    body = (text or "").strip()
    if len(body) < 12:
        return True
    if body.startswith("（") and any(m in body for m in _FAIL_MARKERS):
        return True
    # OCR/meta-only stubs without real body
    if body.startswith("图片文件：") and "OCR 识别结果：" not in body:
        return True
    if "未识别到文字" in body:
        return True
    return False


def extract_zip_members(
    data: bytes,
    *,
    max_files: int = 40,
    max_member_bytes: int = 25 * 1024 * 1024,
) -> list[tuple[str, bytes]]:
    """Return (basename, bytes) for supported files inside a zip."""
    import zipfile

    out: list[tuple[str, bytes]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IngestLimitError(f"无法打开 zip：{exc}") from exc

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            base = Path(name).name
            if not base or base.startswith("."):
                continue
            if "__MACOSX" in name.split("/"):
                continue
            ext = Path(base).suffix.lower()
            if ext not in ARCHIVE_INNER_EXT:
                continue
            if info.file_size > max_member_bytes:
                continue
            try:
                payload = zf.read(info)
            except Exception:  # noqa: BLE001
                continue
            if not payload:
                continue
            out.append((base, payload))
            if len(out) >= max_files:
                break
    return out


def extract_text_from_zip(data: bytes) -> str:
    """Flatten zip members into one searchable text block."""
    members = extract_zip_members(data)
    if not members:
        return (
            "（zip 内没有可解析的文件。"
            "请放入 PDF / Word / txt / md / 图片等支持的类型后重试。）"
        )
    parts: list[str] = [f"压缩包共解析 {len(members)} 个文件："]
    for name, payload in members:
        body = extract_text_from_bytes(name, payload).strip()
        parts.append(f"## 文件：{name}\n{body or '（无文本）'}")
    return "\n\n".join(parts)


def extract_text_from_bytes(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".zip":
        return extract_text_from_zip(data)
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext == ".docx":
        return _extract_docx(data)
    if ext == ".doc":
        return _extract_doc(data)
    if ext == ".pptx":
        return _extract_pptx(data)
    if ext == ".xlsx":
        return _extract_xlsx(data)
    if ext in IMAGE_EXT:
        return _extract_image_note(filename, data)
    if ext in {".html", ".htm"}:
        return _extract_html(data)
    if ext == ".rtf":
        return _extract_rtf(data)
    return _decode_text(data)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for i, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(f"[第{i}页]\n{text}")
        if parts:
            return "\n\n".join(parts)

        # 扫描件：尝试逐页渲染 + OCR（依赖可选）
        ocr_parts = _ocr_pdf_pages(data, max_pages=24)
        if ocr_parts:
            return "\n\n".join(ocr_parts)
        return (
            "（PDF 未能提取到文本，可能是扫描件。"
            "可安装 Tesseract 启用 OCR，或改用可复制文本的 PDF / Word。）"
        )
    except Exception as exc:  # noqa: BLE001
        return f"（PDF 解析失败：{exc}）"


def _ocr_pdf_pages(data: bytes, max_pages: int = 24) -> list[str]:
    """Best-effort OCR for scanned PDFs via pypdfium2 + pytesseract."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return []

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001
        return []

    out: list[str] = []
    n = min(len(pdf), max_pages)
    for i in range(n):
        try:
            page = pdf[i]
            pil = page.render(scale=2).to_pil()
            text = _ocr_pil(pil)
            if text:
                out.append(f"[第{i + 1}页 OCR]\n{text}")
        except Exception:  # noqa: BLE001
            continue
    return out


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts: list[str] = []
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                parts.append(t)
        for ti, table in enumerate(doc.tables, 1):
            rows: list[str] = []
            for row in table.rows:
                cells = [(c.text or "").strip() for c in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"[表格{ti}]\n" + "\n".join(rows))
        if not parts:
            return "（Word 文档未提取到可见正文，可能主要为图片。可另存图片后上传做 OCR。）"
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return f"（Word .docx 解析失败：{exc}。请确认文件未损坏。）"


def _extract_doc(data: bytes) -> str:
    """Legacy .doc: try LibreOffice-less heuristics; otherwise guide to .docx."""
    # Some .doc are actually OLE-wrapped HTML / RTF
    head = data[:64]
    if head.startswith(b"{\\rtf"):
        return _extract_rtf(data)
    if b"<html" in data[:2000].lower() or b"<!doctype html" in data[:2000].lower():
        return _extract_html(data)

    # Naive UTF-16LE / ascii scrapes (best-effort; not a full Word parser)
    scraps: list[str] = []
    try:
        as_utf16 = data.decode("utf-16-le", errors="ignore")
        chunks = re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。；：、？！\s]{8,}", as_utf16)
        scraps.extend(c.strip() for c in chunks if c.strip())
    except Exception:  # noqa: BLE001
        pass
    if scraps:
        text = "\n".join(scraps[:200])
        return (
            "（已从旧版 .doc 尽力提取文本；完整兼容请另存为 .docx 再上传）\n\n" + text
        )
    return (
        "（暂不完整支持旧版 Word .doc。请在 Word / WPS 中「另存为 .docx」后重新上传。）"
    )


def _extract_pptx(data: bytes) -> str:
    try:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        parts: list[str] = []
        for i, slide in enumerate(prs.slides, 1):
            bits: list[str] = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    t = (shape.text or "").strip()
                    if t:
                        bits.append(t)
            if bits:
                parts.append(f"[幻灯片{i}]\n" + "\n".join(bits))
        if not parts:
            return "（PPT 未提取到文本。）"
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return f"（PPT 解析失败：{exc}）"


def _extract_xlsx(data: bytes) -> str:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in wb.worksheets:
            rows: list[str] = []
            for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
                if i > 500:
                    rows.append("…（已截断，单表最多 500 行）")
                    break
                cells = ["" if c is None else str(c).strip() for c in row]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"[工作表 {sheet.title}]\n" + "\n".join(rows))
        wb.close()
        if not parts:
            return "（Excel 未提取到单元格内容。）"
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return f"（Excel 解析失败：{exc}）"


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            t = data.strip()
            if t:
                self._chunks.append(t)

    def text(self) -> str:
        raw = " ".join(self._chunks)
        return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", raw)).strip()


def _extract_html(data: bytes) -> str:
    html = _decode_text(data)
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        text = parser.text()
        return text or "（HTML 未提取到正文。）"
    except Exception as exc:  # noqa: BLE001
        return f"（HTML 解析失败：{exc}）"


def _extract_rtf(data: bytes) -> str:
    raw = _decode_text(data)
    # Strip common RTF control words / groups — best-effort, not a full RTF engine
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    text = re.sub(r"\\[a-zA-Z]+\d* ?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 8:
        return "（RTF 未能提取有效文本，请另存为 .docx / .txt。）"
    return text


def _extract_image_note(filename: str, data: bytes) -> str:
    note = [
        f"图片文件：{filename}",
        f"大小：{len(data)} 字节",
    ]
    ocr_text = _try_ocr(data)
    if ocr_text:
        note.append("OCR 识别结果：")
        note.append(ocr_text)
    else:
        note.append(
            "未识别到文字（需安装 Tesseract OCR，并确保 `chi_sim` 语言包可用）。"
            "当前已入库文件元信息；请在说明里补充图片内容以便检索。"
        )
    return "\n".join(note)


def _configure_tesseract() -> bool:
    """Locate Tesseract on Windows even if PATH was not refreshed."""
    try:
        import pytesseract
    except ImportError:
        return False

    import os
    import shutil

    candidates = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    cmd = next((c for c in candidates if c and Path(c).is_file()), None)
    if not cmd:
        return False
    pytesseract.pytesseract.tesseract_cmd = str(cmd)
    # UB-Mannheim Windows build expects TESSDATA_PREFIX = .../tessdata
    tessdata = Path(cmd).parent / "tessdata"
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return True


def _ocr_pil(image) -> str:  # noqa: ANN001
    if not _configure_tesseract():
        return ""
    try:
        import pytesseract
        from PIL import ImageEnhance, ImageOps

        # 轻度增强：提升扫描件/截图对比度
        work = image.convert("L") if image.mode != "L" else image
        work = ImageOps.autocontrast(work)
        work = ImageEnhance.Contrast(work).enhance(1.4)
        # 小图放大，利于细字
        if max(work.size) < 1200:
            scale = 1200 / max(work.size)
            work = work.resize(
                (max(1, int(work.size[0] * scale)), max(1, int(work.size[1] * scale)))
            )
        for lang in ("chi_sim+eng", "eng"):
            try:
                text = pytesseract.image_to_string(work, lang=lang, config="--psm 6")
                text = (text or "").strip()
                if len(text) >= 8:
                    return text
            except Exception:
                continue
        return ""
    except Exception:
        return ""


def _try_ocr(data: bytes) -> str:
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        return _ocr_pil(image)
    except Exception:
        return ""
