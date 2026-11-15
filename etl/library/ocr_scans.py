"""Deterministic WinRT OCR extraction and scholarly layout post-processing
for the two scanned library books:
  - xu-lingtai-collection-pdf (434 pages, 《明清名医全书大成·徐灵胎医学全书》)
  - huangdi-waijing-pdf (85 pages, 《黄帝外经》/《外经微言》)

Rules enforced here:
1. Genuine local OCR only (Windows.Media.Ocr zh-Hans-CN on pypdfium2 renders);
   intentionally blank verso/divider pages stay body_text="" with ocr_status="blank_page".
2. Clean CJK spacing and two-column reading order (left column then right column),
   stripping repeated running page headers/ornaments from body_text while extracting
   printed_page numbers cleanly.
3. Explicit scholarly boundaries: modern editorial prefaces/academic study/bibliographies
   and Wang Mengying's 《洄溪医案》「雄按」 notes are labeled clearly in section_title/headings.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
OCR_CACHE_DIR = ROOT / ".tmp" / "ocr_cache"
OCR_WORK_DIR = ROOT / ".tmp" / "ocr_work"
WINRT_PS1 = Path(__file__).resolve().parent / "winrt_ocr.ps1"


# Clean spaces adjacent to CJK chars/punctuation while keeping spaces between two ASCII tokens
_CJK_SPAN_L_RE = re.compile(
    r"([\u4e00-\u9fff\u3400-\u4dbf，。、；：？！“”‘’（）《》〈〉【】·—…．0-9])\s+(?=[\u4e00-\u9fff\u3400-\u4dbf，。、；：？！“”‘’（）《》〈〉【】·—…．])"
)
_CJK_SPAN_R_RE = re.compile(
    r"([\u4e00-\u9fff\u3400-\u4dbf，。、；：？！“”‘’（）《》〈〉【】·—…．])\s+(?=[0-9A-Za-z])"
)


def clean_ocr_line(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        s = _CJK_SPAN_L_RE.sub(r"\1", s)
        s = _CJK_SPAN_R_RE.sub(r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def load_or_run_winrt_ocr(book_id: str, pdf_rel_path: str) -> list[dict[str, Any]]:
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OCR_CACHE_DIR / f"{book_id}.raw.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data.get("pages", data) if isinstance(data, dict) else data

    import pypdfium2 as pdfium  # type: ignore

    pdf_path = ROOT / pdf_rel_path
    work_dir = OCR_WORK_DIR / book_id
    work_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for idx in range(len(doc)):
            img_path = work_dir / f"p{idx + 1:04d}.png"
            if not img_path.exists():
                doc[idx].render(scale=2.5).to_pil().save(img_path)
    finally:
        doc.close()

    subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINRT_PS1),
            "-ImageDir",
            str(work_dir),
            "-OutJson",
            str(cache_path),
        ],
        check=True,
    )
    shutil.rmtree(work_dir, ignore_errors=True)
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    return data.get("pages", data) if isinstance(data, dict) else data


def _merge_row_fragments(lines: list[dict[str, Any]], *, y_tol: float = 15.0, gap_space: float = 160.0) -> list[str]:
    if not lines:
        return []
    ordered = sorted(lines, key=lambda ln: (float(ln["y"]), float(ln["x"])))
    rows: list[list[dict[str, Any]]] = []
    for ln in ordered:
        y_mid = (float(ln["y"]) + float(ln["y2"])) * 0.5
        if rows:
            prev_mid = sum((float(x["y"]) + float(x["y2"])) * 0.5 for x in rows[-1]) / len(rows[-1])
            if abs(y_mid - prev_mid) <= y_tol:
                rows[-1].append(ln)
                continue
        rows.append([ln])

    out: list[str] = []
    for row in rows:
        row.sort(key=lambda x: float(x["x"]))
        buf = ""
        prev_x2 = None
        for frag in row:
            txt = clean_ocr_line(frag.get("text", ""))
            if not txt:
                continue
            if prev_x2 is None:
                buf = txt
            else:
                gap = float(frag["x"]) - prev_x2
                sep = " " if gap > gap_space else ""
                buf = f"{buf}{sep}{txt}".strip()
            prev_x2 = float(frag["x2"])
        if buf:
            out.append(buf)
    return out


# ---------------------------------------------------------------------------
# Book 1: 《黄帝外经》 (85 pages, single-column scan + 4-page 概述 + 80 essays)
# ---------------------------------------------------------------------------

_WJ_ESSAY_FIXUPS = {
    "六气分门第": "六气分门篇",
    "补泻阴汨篇": "补泻阴阳篇",
    "亡汨亡阴篇": "亡阳亡阴篇",
}


def _wj_search_variants(text: str) -> str:
    """Append common archaic-OCR character disambiguations strictly to search_text."""
    if not text:
        return ""
    extra = text
    for src, dst in (
        ("汨", "阳"),
        ("順", "阳"),
        ("耒", "未"),
        ("炅活", "灵活"),
        ("六气分门第", "六气分门篇"),
    ):
        extra = extra.replace(src, dst)
    return f"{text}\n{extra}" if extra != text else text


def extract_huangdi_waijing_ocr(
    pdf_rel_path: str,
    *,
    normalize_fn: Callable[[str], str],
    sha_fn: Callable[[str], str],
) -> list[dict[str, Any]]:
    raw_pages = load_or_run_winrt_ocr("huangdi-waijing-pdf", pdf_rel_path)
    out: list[dict[str, Any]] = []
    current_section = "【卷首概述】《外经微言》整理考略"

    for idx, pg in enumerate(raw_pages):
        pno = idx + 1
        lines = pg.get("lines") or []
        printed_page: str | None = str(pno) if pno >= 5 else None
        body_lines: list[dict[str, Any]] = []

        for ln in lines:
            t_raw = clean_ocr_line(ln.get("text", ""))
            if not t_raw:
                continue
            if float(ln["y"]) >= 2965 and re.fullmatch(r"\d{1,2}", t_raw):
                printed_page = t_raw
                continue
            body_lines.append(ln)

        merged_rows = _merge_row_fragments(body_lines, y_tol=22.0, gap_space=220.0)
        body_text = "\n".join(merged_rows).strip()

        page_headings: list[str] = []
        if pno == 1:
            page_headings.append("【卷首概述】《外经微言》整理考略")
        for ln in sorted(body_lines, key=lambda x: float(x["y"])):
            t_clean = clean_ocr_line(ln.get("text", ""))
            t_comp = t_clean.replace(" ", "")
            if (
                float(ln["x"]) < 450
                and len(t_comp) <= 12
                and not any(c in t_comp for c in "。，、：；？！“”（）")
                and (t_comp.endswith("篇") or t_comp == "六气分门第")
            ):
                canon = _WJ_ESSAY_FIXUPS.get(t_comp, t_comp)
                if canon not in page_headings:
                    page_headings.append(canon)
                current_section = canon

        section_title = page_headings[-1] if (page_headings and page_headings[-1].endswith("篇")) else current_section
        if pno == 4 and "阴阳颠倒篇" in page_headings:
            section_title = "阴阳颠倒篇（卷首概述终）"

        ocr_status = "winrt_zh_hans_ocr" if body_text else "blank_page"
        out.append(
            {
                "book_id": "huangdi-waijing-pdf",
                "source_id": "huangdi-waijing-pdf",
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页" + (f"（原书 p.{printed_page}）" if printed_page else ""),
                "printed_page": printed_page,
                "section_title": section_title,
                "headings": page_headings[:6],
                "body_text": body_text,
                "search_text": normalize_fn(_wj_search_variants(body_text + " " + " ".join(page_headings))),
                "text_sha256": sha_fn(body_text),
                "extraction_method": "pypdfium2_winrt_ocr",
                "ocr_status": ocr_status,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Book 2: 《明清名医全书大成·徐灵胎医学全书》 (434 pages, 8 books + modern study)
# ---------------------------------------------------------------------------

_XU_MILESTONES: dict[int, tuple[str, str | None]] = {
    1: ("【现代编注】《明清名医全书大成·徐灵胎医学全书》封面与编注总序", "【现代编注】总序·校注说明"),
    11: ("【现代编注】徐灵胎小传与校注说明", "校注说明（1999年整理本）"),
    13: ("【现代编注】全书总目", "全书总目"),
    14: ("《难经经释》扉页", "《难经经释》（清·徐灵胎）"),
    16: ("《难经经释》序", "《难经经释》序·凡例"),
    18: ("《难经经释》目录", "《难经经释》目录"),
    20: ("《难经经释》卷上", "《难经经释》卷上"),
    37: ("《难经经释》卷下", "《难经经释》卷下"),
    61: ("《难经经释》书后", "《难经经释》书后"),
    62: ("《神农本草经百种录》扉页", "《神农本草经百种录》（清·徐灵胎）"),
    64: ("《神农本草经百种录》序·凡例", "《神农本草经百种录》序"),
    66: ("《神农本草经百种录》目录", "《神农本草经百种录》目录"),
    68: ("《神农本草经百种录》正文", "《神农本草经百种录》上品起"),
    86: ("《医贯砭》扉页", "《医贯砭》（清·徐灵胎）"),
    88: ("《医贯砭》序", "《医贯砭》序"),
    90: ("《医贯砭》目录", "《医贯砭》目录"),
    92: ("《医贯砭》卷上", "《医贯砭》卷上"),
    108: ("《医贯砭》卷下", "《医贯砭》卷下"),
    126: ("《医学源流论》扉页", "《医学源流论》（清·徐灵胎）"),
    128: ("《医学源流论》自叙", "《医学源流论》自叙"),
    130: ("《医学源流论》目录", "《医学源流论》目录"),
    132: ("《医学源流论》卷上", "《医学源流论》卷上"),
    152: ("《医学源流论》卷下", "《医学源流论》卷下"),
    174: ("《伤寒类方》扉页", "《伤寒类方》（清·徐灵胎）"),
    176: ("《伤寒类方》序", "《伤寒类方》序"),
    178: ("《伤寒类方》目录", "《伤寒类方》目录"),
    182: ("《伤寒类方》正文（十二类方）", "《伤寒类方》正文 · 桂枝汤类起"),
    220: ("《兰台轨范》扉页", "《兰台轨范》（清·徐灵胎）"),
    222: ("《兰台轨范》序·凡例", "《兰台轨范》序·凡例"),
    224: ("《兰台轨范》目录", "《兰台轨范》目录"),
    238: ("《兰台轨范》卷一（通治方）", "《兰台轨范》卷一 · 通治方"),
    251: ("《兰台轨范》卷二", "《兰台轨范》卷二"),
    272: ("《兰台轨范》卷三", "《兰台轨范》卷三"),
    284: ("《兰台轨范》卷四", "《兰台轨范》卷四"),
    302: ("《兰台轨范》卷五", "《兰台轨范》卷五"),
    317: ("《兰台轨范》卷六", "《兰台轨范》卷六"),
    332: ("《兰台轨范》卷七", "《兰台轨范》卷七"),
    349: ("《兰台轨范》卷八（妇人·小儿·外科）", "《兰台轨范》卷八"),
    368: ("《慎疾刍言》扉页", "《慎疾刍言》（清·徐灵胎）"),
    370: ("《慎疾刍言》序", "《慎疾刍言》序"),
    372: ("《慎疾刍言》目录", "《慎疾刍言》目录"),
    374: ("《慎疾刍言》正文", "《慎疾刍言》正文 · 补剂起"),
    384: ("《洄溪医案》扉页〔清·王孟英编〕", "《洄溪医案》（徐灵胎著 · 王孟英编）"),
    386: ("《洄溪医案》王孟英序", "《洄溪医案》王孟英序"),
    388: ("《洄溪医案》目录", "《洄溪医案》目录"),
    390: ("《洄溪医案》正文〔含王孟英「雄按」〕", "《洄溪医案》正文（含「雄按」）"),
    414: ("【现代附编】出版尾页", None),
    416: ("【现代学术研究】徐灵胎医学学术思想研究", "【现代附编】徐灵胎医学学术思想研究"),
    423: ("【现代学术研究】徐灵胎著作辨考（含伪托考）", "【现代附编】徐灵胎著作辨考"),
    432: ("【现代研究题录】1950～1997年研究论文题录", "【现代附编】徐灵胎研究论文题录（1950～1997）"),
}


def _is_xu_running_header(ln: dict[str, Any], pno: int) -> bool:
    if pno <= 13:
        return False
    y = float(ln["y"])
    y2 = float(ln["y2"])
    txt = clean_ocr_line(ln.get("text", "")).replace(" ", "")
    if not txt:
        return True
    # Decorative column-divider dot above center line
    if y < 260 and 700 <= float(ln["x"]) <= 825 and txt in ("0", "o", "O", ".", "·", "。", "一"):
        return True
    # Physical running headers on p.14..434 sit strictly in y < 222 (0 body lines exist in y=[222,250))
    if y < 222 and y2 <= 242:
        return True
    return False


def _xu_order_body_lines(lines: list[dict[str, Any]], width: float) -> list[str]:
    if not lines:
        return []
    mid = width * 0.5
    wide_lines = [ln for ln in lines if float(ln["x"]) < mid - 85 and float(ln["x2"]) > mid + 65]

    # Single-column pages (prefaces, frontmatter, postface, thesis titles, bibliography lists)
    if len(wide_lines) >= 4 or (wide_lines and len(wide_lines) / len(lines) >= 0.35):
        return _merge_row_fragments(lines, y_tol=15.0, gap_space=140.0)

    # Multi-column bibliography tables (p.423-430) where rows hold 3+ horizontally distinct cells
    row_buckets: dict[int, int] = {}
    for ln in lines:
        yb = int(round((float(ln["y"]) + float(ln["y2"])) * 0.5 / 14.0))
        row_buckets[yb] = row_buckets.get(yb, 0) + 1
    if sum(1 for c in row_buckets.values() if c >= 3) >= 3:
        return _merge_row_fragments(lines, y_tol=12.0, gap_space=100.0)

    # Standard 2-column academic page: top banners -> left column -> right column
    banners: list[dict[str, Any]] = []
    left_col: list[dict[str, Any]] = []
    right_col: list[dict[str, Any]] = []

    for ln in lines:
        x = float(ln["x"])
        x2 = float(ln["x2"])
        y = float(ln["y"])
        cx = (x + x2) * 0.5
        if y < 510 and (x < mid - 55 and x2 > mid + 45 or (x >= 440 and x2 <= 1080 and len(clean_ocr_line(ln.get("text", ""))) <= 14)):
            banners.append(ln)
        elif cx < mid:
            left_col.append(ln)
        else:
            right_col.append(ln)

    out = _merge_row_fragments(banners, y_tol=18.0, gap_space=120.0)
    out.extend(_merge_row_fragments(left_col, y_tol=14.0, gap_space=140.0))
    out.extend(_merge_row_fragments(right_col, y_tol=14.0, gap_space=140.0))
    return out


def _detect_xu_subheadings(lines: list[dict[str, Any]], width: float, pno: int) -> list[str]:
    """Detect within-column centered standalone essay/category headings inside Xu's prose."""
    if pno < 68 or pno >= 414:
        return []
    # Skip directory index pages
    if 178 <= pno <= 180 or 224 <= pno <= 237 or pno in (90, 130, 131, 372, 388):
        return []
    mid = width * 0.5
    col_buckets: dict[int, list[dict[str, Any]]] = {0: [], 1: []}
    for ln in lines:
        col = 0 if (float(ln["x"]) + float(ln["x2"])) * 0.5 < mid else 1
        col_buckets[col].append(ln)

    found: list[str] = []
    for col in (0, 1):
        col_lines = sorted(col_buckets[col], key=lambda item: float(item["y"]))
        for idx, ln in enumerate(col_lines):
            y = float(ln["y"])
            if y < 530 and pno in _XU_MILESTONES:
                continue
            txt = clean_ocr_line(ln.get("text", "")).replace(" ", "")
            if not (2 <= len(txt) <= 9):
                continue
            if any(c in txt for c in "。，、；：？！“”（）()《》〈〉0123456789"):
                continue
            x = float(ln["x"])
            x2 = float(ln["x2"])
            # Centered horizontally inside left (mid~470) or right (mid~1040) column
            col_center = 470.0 if col == 0 else 1040.0
            ln_center = (x + x2) * 0.5
            if abs(ln_center - col_center) > 95.0:
                continue
            if x < (310.0 if col == 0 else 880.0):
                continue
            # Must have extra vertical spacing or follow sentence end
            gap_prev = y - float(col_lines[idx - 1]["y2"]) if idx > 0 else 999.0
            gap_next = float(col_lines[idx + 1]["y"]) - float(ln["y2"]) if idx + 1 < len(col_lines) else 999.0
            if gap_prev >= 22.0 or gap_next >= 22.0 or txt.endswith("论"):
                if txt not in ("上品", "中品", "下品", "卷上", "卷下") and txt not in found:
                    found.append(txt)
    return found[:6]


def extract_xu_lingtai_ocr(
    pdf_rel_path: str,
    *,
    normalize_fn: Callable[[str], str],
    sha_fn: Callable[[str], str],
) -> list[dict[str, Any]]:
    raw_pages = load_or_run_winrt_ocr("xu-lingtai-collection-pdf", pdf_rel_path)
    out: list[dict[str, Any]] = []
    current_section = _XU_MILESTONES[1][0]

    for idx, pg in enumerate(raw_pages):
        pno = idx + 1
        width = float(pg.get("width") or 1530.0)
        raw_lines = pg.get("lines") or []

        if pno in _XU_MILESTONES:
            current_section = _XU_MILESTONES[pno][0]

        body_lines = [ln for ln in raw_lines if not _is_xu_running_header(ln, pno)]
        ordered_rows = _xu_order_body_lines(body_lines, width)
        body_text = "\n".join(ordered_rows).strip()

        if not body_text:
            out.append(
                {
                    "book_id": "xu-lingtai-collection-pdf",
                    "source_id": "xu-lingtai-collection-pdf",
                    "page_no": pno,
                    "unit_type": "pdf_page",
                    "unit_label": f"PDF 第 {pno} 页",
                    "printed_page": None,
                    "section_title": "",
                    "headings": [],
                    "body_text": "",
                    "search_text": "",
                    "text_sha256": sha_fn(""),
                    "extraction_method": "pypdfium2_winrt_ocr",
                    "ocr_status": "blank_page",
                }
            )
            continue

        # Original book pagination starts at pdf p.14 (= p.1 title page), p.16 = p.3 .. p.433 = p.420, p.434 = dup p.420
        printed_page: str | None = None
        if 16 <= pno <= 433:
            printed_page = str(pno - 13)
        elif pno == 434:
            printed_page = "420（重页）"

        page_headings: list[str] = []
        if pno in _XU_MILESTONES and _XU_MILESTONES[pno][1]:
            page_headings.append(_XU_MILESTONES[pno][1] or "")
        for sub in _detect_xu_subheadings(body_lines, width, pno):
            if sub not in page_headings:
                page_headings.append(sub)

        section_title = current_section
        sub_prefix = current_section.split("（", 1)[0].split("扉页", 1)[0].strip()
        if page_headings and pno >= 68 and pno < 414:
            subs = [h for h in page_headings if h != (_XU_MILESTONES.get(pno, ("", None))[1] or "")]
            if subs:
                section_title = f"{sub_prefix} · {subs[0]}"
        if pno == 434:
            section_title = "【现代研究题录】1950～1997年研究论文题录（末页重印 p.420）"

        out.append(
            {
                "book_id": "xu-lingtai-collection-pdf",
                "source_id": "xu-lingtai-collection-pdf",
                "page_no": pno,
                "unit_type": "pdf_page",
                "unit_label": f"PDF 第 {pno} 页" + (f"（原书 p.{printed_page}）" if printed_page else ""),
                "printed_page": printed_page,
                "section_title": section_title,
                "headings": page_headings[:6],
                "body_text": body_text,
                "search_text": normalize_fn(body_text + " " + section_title + " " + " ".join(page_headings)),
                "text_sha256": sha_fn(body_text),
                "extraction_method": "pypdfium2_winrt_ocr",
                "ocr_status": "winrt_zh_hans_ocr",
            }
        )
    return out
