"""Extract all 216 pages of the acupuncture collated transcript PDF cleanly.

Separates running header, body text, collator footnotes (using the exact
geometric footnote divider rule), inline collation notes, video timestamps,
and footer/printed page numbers into ``sources/acupuncture/pages.jsonl``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium


ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = ROOT / "books" / "ni-haixia-medicine" / "倪海厦人纪系列之针灸教程.pdf"
OUTPUT_PATH = ROOT / "sources" / "acupuncture" / "pages.jsonl"
SOURCE_ID = "ni-acupuncture-v2-20100703"

TIMESTAMP_RE = re.compile(r"[（(](\d{1,2}-\d{1,2}:\d{2}:\d{2})[）)]")
COLLATION_NOTE_RE = re.compile(r"[（(](校对注[^）)]*)[）)]")
PRINTED_PAGE_RE = re.compile(r"(?:^|\s)(\d{1,3})\s*$")


def split_footnotes(text: str) -> list[str]:
    if not text.strip():
        return []
    collapsed = re.sub(r"\s*\n\s*", "", text.strip())
    parts = re.split(r"(?=[①②③④⑤⑥⑦⑧⑨⑩])", collapsed)
    return [part.strip() for part in parts if part.strip()]


def parse_printed_page(footer_text: str, pdf_page: int) -> int | None:
    if pdf_page == 1:
        return None
    for line in footer_text.splitlines():
        m = PRINTED_PAGE_RE.search(line.strip())
        if m:
            return int(m.group(1))
    return None


def extract_all_pages() -> list[dict]:
    records: list[dict] = []
    fium = pdfium.PdfDocument(str(PDF_PATH))
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for idx, page in enumerate(pdf.pages):
            pdf_page = idx + 1
            raw_text = fium[idx].get_textpage().get_text_range().replace("\r\n", "\n").strip()

            width = float(page.width)
            height = float(page.height)
            if pdf_page == 1:
                header_text = ""
                body_text = (page.extract_text() or "").strip()
                footnotes: list[str] = []
                footer_text = ""
                printed_page = None
            else:
                header_rules = [r for r in page.rects if r["top"] < 70 and (r["x1"] - r["x0"]) > 300]
                footer_rules = [r for r in page.rects if r["top"] > 760 and (r["x1"] - r["x0"]) > 300]
                fn_rules = [
                    r
                    for r in page.rects
                    if 500 <= r["top"] <= 775 and 100 <= (r["x1"] - r["x0"]) <= 220
                ]
                header_y = header_rules[0]["bottom"] + 1 if header_rules else 56.0
                footer_y = footer_rules[0]["top"] - 1 if footer_rules else 778.0
                body_bottom = fn_rules[0]["top"] - 1 if fn_rules else footer_y

                header_text = (page.crop((0, 0, width, header_y)).extract_text() or "").strip()
                if pdf_page >= 201:
                    left_text = (page.crop((0, header_y, width / 2, body_bottom)).extract_text() or "").strip()
                    right_text = (page.crop((width / 2, header_y, width, body_bottom)).extract_text() or "").strip()
                    body_text = "\n".join(part for part in (left_text, right_text) if part)
                else:
                    body_text = (page.crop((0, header_y, width, body_bottom)).extract_text() or "").strip()
                fn_text = (
                    page.crop((0, body_bottom, width, footer_y)).extract_text() or ""
                    if fn_rules
                    else ""
                )
                footnotes = split_footnotes(fn_text)
                footer_text = (page.crop((0, footer_y, width, height)).extract_text() or "").strip()
                printed_page = parse_printed_page(footer_text, pdf_page)

            timestamps = TIMESTAMP_RE.findall(body_text)
            collation_notes = COLLATION_NOTE_RE.findall(body_text)
            page_id = f"{SOURCE_ID}:p{pdf_page:03d}"
            records.append(
                {
                    "page_id": page_id,
                    "source_id": SOURCE_ID,
                    "pdf_page": pdf_page,
                    "printed_page": printed_page,
                    "header": header_text,
                    "body_text": body_text,
                    "footnotes": footnotes,
                    "collation_notes": collation_notes,
                    "timestamps": timestamps,
                    "footer": footer_text,
                    "raw_text": raw_text,
                    "text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    "extraction_method": "pdf_text_layout",
                    "ocr_status": "clean_digital",
                }
            )
    return records


def main() -> int:
    records = extract_all_pages()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Extracted {len(records)} pages to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
