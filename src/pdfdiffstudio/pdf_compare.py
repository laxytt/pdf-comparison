from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
from itertools import zip_longest
from pathlib import Path
import hashlib
import re
import tempfile
from typing import Callable


ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class PdfPage:
    index: int
    text: str
    width: float
    height: float


@dataclass(frozen=True)
class PageDiff:
    page_number: int
    left_text: str
    right_text: str
    left_html: str
    right_html: str
    added_lines: int
    removed_lines: int
    changed_lines: int
    similarity: float

    @property
    def is_changed(self) -> bool:
        return self.added_lines > 0 or self.removed_lines > 0 or self.changed_lines > 0

    @property
    def status(self) -> str:
        if not self.left_text.strip() and self.right_text.strip():
            return "Added"
        if self.left_text.strip() and not self.right_text.strip():
            return "Removed"
        if self.is_changed:
            return "Changed"
        return "Unchanged"


@dataclass(frozen=True)
class PdfComparisonResult:
    left_path: Path
    right_path: Path
    left_page_count: int
    right_page_count: int
    pages: tuple[PageDiff, ...]

    @property
    def changed_pages(self) -> int:
        return sum(1 for page in self.pages if page.is_changed)

    @property
    def added_lines(self) -> int:
        return sum(page.added_lines for page in self.pages)

    @property
    def removed_lines(self) -> int:
        return sum(page.removed_lines for page in self.pages)

    @property
    def changed_lines(self) -> int:
        return sum(page.changed_lines for page in self.pages)


@dataclass(frozen=True)
class VisualDiffResult:
    left_image: Path
    right_image: Path
    changed_ratio: float


def compare_pdfs(left_path: str | Path, right_path: str | Path, progress: ProgressCallback | None = None) -> PdfComparisonResult:
    left = Path(left_path)
    right = Path(right_path)
    _require_pdf(left)
    _require_pdf(right)

    _emit(progress, "Reading first PDF", 5)
    left_pages = extract_pdf_pages(left)
    _emit(progress, "Reading second PDF", 25)
    right_pages = extract_pdf_pages(right)

    page_count = max(len(left_pages), len(right_pages))
    diffs: list[PageDiff] = []
    for index in range(page_count):
        percent = 35 + int((index / max(page_count, 1)) * 60)
        _emit(progress, f"Comparing page {index + 1} of {page_count}", percent)
        left_text = left_pages[index].text if index < len(left_pages) else ""
        right_text = right_pages[index].text if index < len(right_pages) else ""
        diffs.append(build_page_diff(index + 1, left_text, right_text))

    _emit(progress, "Comparison complete", 100)
    return PdfComparisonResult(
        left_path=left,
        right_path=right,
        left_page_count=len(left_pages),
        right_page_count=len(right_pages),
        pages=tuple(diffs),
    )


def extract_pdf_pages(path: str | Path) -> list[PdfPage]:
    fitz = _load_fitz()
    pdf_path = Path(path)
    _require_pdf(pdf_path)

    pages: list[PdfPage] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            rect = page.rect
            text = page.get_text("text", sort=True) or ""
            pages.append(PdfPage(index=index, text=text, width=float(rect.width), height=float(rect.height)))
    return pages


def build_page_diff(page_number: int, left_text: str, right_text: str) -> PageDiff:
    left_lines = _split_lines(left_text)
    right_lines = _split_lines(right_text)
    matcher = SequenceMatcher(None, left_lines, right_lines, autojunk=False)

    left_rendered: list[str] = []
    right_rendered: list[str] = []
    added = 0
    removed = 0
    changed = 0
    left_line_number = 1
    right_line_number = 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_chunk = left_lines[i1:i2]
        right_chunk = right_lines[j1:j2]

        if tag == "equal":
            for left_line, right_line in zip(left_chunk, right_chunk):
                left_rendered.append(_line_html(left_line_number, "equal", escape(left_line)))
                right_rendered.append(_line_html(right_line_number, "equal", escape(right_line)))
                left_line_number += 1
                right_line_number += 1
            continue

        if tag == "delete":
            for left_line in left_chunk:
                removed += 1
                left_rendered.append(_line_html(left_line_number, "removed", escape(left_line)))
                right_rendered.append(_line_html(None, "placeholder", "&nbsp;"))
                left_line_number += 1
            continue

        if tag == "insert":
            for right_line in right_chunk:
                added += 1
                left_rendered.append(_line_html(None, "placeholder", "&nbsp;"))
                right_rendered.append(_line_html(right_line_number, "added", escape(right_line)))
                right_line_number += 1
            continue

        for left_line, right_line in zip_longest(left_chunk, right_chunk):
            if left_line is not None and right_line is not None:
                changed += 1
                left_markup, right_markup = _word_diff_markup(left_line, right_line)
                left_rendered.append(_line_html(left_line_number, "changed", left_markup))
                right_rendered.append(_line_html(right_line_number, "changed", right_markup))
                left_line_number += 1
                right_line_number += 1
            elif left_line is not None:
                removed += 1
                left_rendered.append(_line_html(left_line_number, "removed", escape(left_line)))
                right_rendered.append(_line_html(None, "placeholder", "&nbsp;"))
                left_line_number += 1
            elif right_line is not None:
                added += 1
                left_rendered.append(_line_html(None, "placeholder", "&nbsp;"))
                right_rendered.append(_line_html(right_line_number, "added", escape(right_line)))
                right_line_number += 1

    similarity = matcher.ratio()
    return PageDiff(
        page_number=page_number,
        left_text=left_text,
        right_text=right_text,
        left_html=_document_html(left_rendered),
        right_html=_document_html(right_rendered),
        added_lines=added,
        removed_lines=removed,
        changed_lines=changed,
        similarity=similarity,
    )


def render_visual_diff(
    left_path: str | Path,
    right_path: str | Path,
    page_index: int,
    dpi: int = 120,
    threshold: int = 22,
    output_dir: str | Path | None = None,
) -> VisualDiffResult:
    fitz = _load_fitz()
    Image, ImageChops, ImageFilter = _load_pillow()

    left_pdf = Path(left_path)
    right_pdf = Path(right_path)
    _require_pdf(left_pdf)
    _require_pdf(right_pdf)

    out_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "pdfdiffstudio"
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_key = _visual_cache_key(left_pdf, right_pdf, page_index, dpi, threshold)
    left_output = out_dir / f"{cache_key}_left_marked.png"
    right_output = out_dir / f"{cache_key}_right_marked.png"
    ratio_output = out_dir / f"{cache_key}_ratio.txt"
    if left_output.exists() and right_output.exists() and ratio_output.exists():
        try:
            changed_ratio = float(ratio_output.read_text(encoding="utf-8"))
        except ValueError:
            changed_ratio = 0.0
        return VisualDiffResult(left_output, right_output, changed_ratio=changed_ratio)

    left_image = _render_page_image(fitz, Image, left_pdf, page_index, dpi)
    right_image = _render_page_image(fitz, Image, right_pdf, page_index, dpi)
    if left_image is None and right_image is None:
        blank = Image.new("RGB", (1000, 1300), "white")
        left_image = blank.copy()
        right_image = blank.copy()
    elif left_image is None:
        left_image = Image.new("RGB", right_image.size, "white")
    elif right_image is None:
        right_image = Image.new("RGB", left_image.size, "white")

    target_size = (max(left_image.width, right_image.width), max(left_image.height, right_image.height))
    left_canvas = _pad_image(Image, left_image, target_size)
    right_canvas = _pad_image(Image, right_image, target_size)

    difference = ImageChops.difference(left_canvas, right_canvas).convert("L")
    mask = difference.point(lambda value: 255 if value > threshold else 0)
    mask = mask.filter(ImageFilter.MaxFilter(7))
    mask_data = mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
    changed_pixels = sum(1 for value in mask_data if value)
    changed_ratio = changed_pixels / float(target_size[0] * target_size[1])

    left_marked = _highlight_image(Image, left_canvas, mask, (220, 38, 38, 95))
    right_marked = _highlight_image(Image, right_canvas, mask, (22, 163, 74, 95))

    left_marked.save(left_output)
    right_marked.save(right_output)
    ratio_output.write_text(str(changed_ratio), encoding="utf-8")
    return VisualDiffResult(left_output, right_output, changed_ratio=changed_ratio)


def _split_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _line_html(line_number: int | None, kind: str, content: str) -> str:
    label = "" if line_number is None else str(line_number)
    return (
        f'<div class="line {kind}">'
        f'<span class="line-number">{label}</span>'
        f'<span class="line-content">{content or "&nbsp;"}</span>'
        "</div>"
    )


def _document_html(lines: list[str]) -> str:
    body = "\n".join(lines) if lines else '<div class="empty">No extracted text on this page.</div>'
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    margin: 0;
    background: #fbfbf8;
    color: #202124;
    font-family: Consolas, Menlo, Monaco, monospace;
    font-size: 12px;
}}
.line {{
    display: block;
    min-height: 18px;
    padding: 2px 8px 2px 0;
    border-left: 4px solid transparent;
    white-space: pre-wrap;
}}
.line-number {{
    display: inline-block;
    width: 44px;
    padding-right: 8px;
    color: #7a7f87;
    text-align: right;
    user-select: none;
}}
.line-content {{
    white-space: pre-wrap;
}}
.equal {{
    background: #fbfbf8;
}}
.changed {{
    background: #fff5cf;
    border-left-color: #b7791f;
}}
.added {{
    background: #e7f6ea;
    border-left-color: #2f855a;
}}
.removed {{
    background: #ffe7e4;
    border-left-color: #c53030;
}}
.placeholder {{
    background: #f0f1f2;
    color: #9aa0a6;
}}
.word-added {{
    background: #a7f3bf;
    border-radius: 2px;
}}
.word-removed {{
    background: #ffb4ae;
    border-radius: 2px;
}}
.empty {{
    padding: 18px;
    color: #6b7280;
    font-family: Arial, sans-serif;
}}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _word_diff_markup(left_line: str, right_line: str) -> tuple[str, str]:
    left_tokens = _tokenize(left_line)
    right_tokens = _tokenize(right_line)
    matcher = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False)
    left_parts: list[str] = []
    right_parts: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_segment = "".join(left_tokens[i1:i2])
        right_segment = "".join(right_tokens[j1:j2])
        if tag == "equal":
            left_parts.append(escape(left_segment))
            right_parts.append(escape(right_segment))
        elif tag == "delete":
            left_parts.append(f'<span class="word-removed">{escape(left_segment)}</span>')
        elif tag == "insert":
            right_parts.append(f'<span class="word-added">{escape(right_segment)}</span>')
        else:
            if left_segment:
                left_parts.append(f'<span class="word-removed">{escape(left_segment)}</span>')
            if right_segment:
                right_parts.append(f'<span class="word-added">{escape(right_segment)}</span>')

    return "".join(left_parts), "".join(right_parts)


def _tokenize(value: str) -> list[str]:
    return re.findall(r"\w+|\s+|[^\w\s]", value, flags=re.UNICODE)


def _require_pdf(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {path}")


def _visual_cache_key(left_pdf: Path, right_pdf: Path, page_index: int, dpi: int, threshold: int) -> str:
    parts = [
        "split-visual-v2",
        str(left_pdf.resolve()),
        str(left_pdf.stat().st_mtime_ns),
        str(right_pdf.resolve()),
        str(right_pdf.stat().st_mtime_ns),
        str(page_index),
        str(dpi),
        str(threshold),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:18]


def _render_page_image(fitz, Image, path: Path, page_index: int, dpi: int):
    zoom = dpi / 72.0
    with fitz.open(path) as doc:
        if page_index < 0 or page_index >= len(doc):
            return None
        page = doc.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _pad_image(Image, image, size: tuple[int, int]):
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, (0, 0))
    return canvas


def _highlight_image(Image, base_image, mask, color: tuple[int, int, int, int]):
    base_rgba = base_image.convert("RGBA")
    highlight = Image.new("RGBA", base_image.size, color)
    highlighted = Image.alpha_composite(base_rgba, highlight)
    return Image.composite(highlighted, base_rgba, mask).convert("RGB")


def _load_fitz():
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install dependencies with: python -m pip install -r requirements.txt") from exc
    return fitz


def _load_pillow():
    try:
        from PIL import Image, ImageChops, ImageFilter
    except ImportError as exc:
        raise RuntimeError("Pillow is required. Install dependencies with: python -m pip install -r requirements.txt") from exc
    return Image, ImageChops, ImageFilter


def _emit(progress: ProgressCallback | None, message: str, percent: int) -> None:
    if progress is not None:
        progress(message, percent)
