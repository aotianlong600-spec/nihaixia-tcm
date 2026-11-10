"""Rebuild PDF page reading order into corrected_text without changing raw_text."""
import argparse
from contextlib import closing
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pdfplumber
import pypdfium2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import knowledge, offline_pack

ORDER_WARNINGS = (
    "审计抽查发现文本顺序错乱或句子碎裂；未订正",
    "审计抽查发现粗体条文重复提取；未去重或订正",
    "审计抽查发现原文与解说顺序错乱；未订正",
)
LAYOUT_NOTE = "阅读顺序已按版面坐标重建；未逐字医学校订"
LAYOUT_METHOD = "pdfplumber coordinate crop; raw_text retained; reading order rebuilt"


def _warning(value):
    for warning in ORDER_WARNINGS:
        value = value.replace(warning, "")
    parts = [part for part in value.split("；") if part and part != LAYOUT_NOTE]
    return "；".join([*parts, LAYOUT_NOTE])


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _order_score(textpage, width, height):
    chars = []
    for index in range(textpage.count_chars()):
        try:
            text, box = textpage.get_text_range(index, 1), textpage.get_charbox(index)
        except Exception:
            continue
        if text.strip() and box[0] >= width * 0.14 and box[1] >= height * 0.083 and box[3] <= height * 0.902:
            chars.append((index, text, box))
    stream = [char[0] for char in chars]
    lines = []
    for char in sorted(chars, key=lambda item: (-(item[2][1] + item[2][3]) / 2, item[2][0])):
        center = (char[2][1] + char[2][3]) / 2
        if not lines or abs(lines[-1][0] - center) > 4.2:
            lines.append([center, [char]])
        else:
            lines[-1][1].append(char)
            lines[-1][0] = sum((item[2][1] + item[2][3]) / 2 for item in lines[-1][1]) / len(lines[-1][1])
    reading = [char[0] for _, line in lines for char in sorted(line, key=lambda item: item[2][0])]
    return SequenceMatcher(None, stream, reading, autojunk=False).ratio() if stream else 1.0


def rebuild(source, destination):
    source = offline_pack._root(source)
    destination = Path(destination).absolute()
    offline_pack.verify_pack(source)
    if destination.exists():
        raise ValueError("输出知识包已存在，拒绝覆盖")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)

    database = destination / "knowledge.sqlite3"
    stats = {}
    with closing(sqlite3.connect(database)) as conn:
        with conn:
            documents = conn.execute(
                "SELECT id,title,physical_pages FROM documents ORDER BY title"
            ).fetchall()
            for sha, title, page_count in documents:
                source_pdf = destination / "originals" / f"{sha}.pdf"
                if not source_pdf.is_file():
                    continue
                rebuilt = skipped = 0
                with pypdfium2.PdfDocument(source_pdf) as source_doc, pdfplumber.open(source_pdf) as pdf:
                    if len(pdf.pages) != page_count:
                        raise ValueError(f"PDF页数不一致：{title}")
                    for number, page in enumerate(pdf.pages, 1):
                        pdfium_page = source_doc[number - 1]
                        if _order_score(pdfium_page.get_textpage(), pdfium_page.get_width(), pdfium_page.get_height()) >= 0.8:
                            skipped += 1
                            continue
                        row = conn.execute(
                            "SELECT raw_text,corrected_text,warning,extraction_method "
                            "FROM pages WHERE document_id=? AND physical_page=?",
                            (sha, number),
                        ).fetchone()
                        if row is None:
                            raise ValueError(f"知识包缺页：{title} 第{number}页")
                        raw, corrected, warning, method = row
                        if corrected is not None or not raw.strip():
                            skipped += 1
                            continue
                        text = knowledge.extract_pdf_page_text(page, force_layout=True)
                        retention = len(knowledge._normalize(text)) / max(1, len(knowledge._normalize(raw)))
                        if not 0.85 <= retention <= 1.15:
                            skipped += 1
                            continue
                        if knowledge._normalize(text) == knowledge._normalize(raw):
                            skipped += 1
                            continue
                        conn.execute(
                            "UPDATE pages SET corrected_text=?,search_text=?,warning=?,extraction_method=? "
                            "WHERE document_id=? AND physical_page=?",
                            (
                                text,
                                knowledge._normalize(text),
                                _warning(warning),
                                method if LAYOUT_METHOD in method else f"{method}；{LAYOUT_METHOD}",
                                sha,
                                number,
                            ),
                        )
                        rebuilt += 1
                stats[title] = {"rebuilt": rebuilt, "skipped": skipped}
        conn.execute("VACUUM")

    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["knowledge.sqlite3"] = {
        "bytes": database.stat().st_size,
        "sha256": _digest(database),
    }
    manifest_path.write_bytes(offline_pack._json_bytes(manifest))
    offline_pack.verify_pack(destination)
    return {"documents": stats, "rebuilt": sum(item["rebuilt"] for item in stats.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pack", type=Path, required=True)
    parser.add_argument("--output-pack", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.source_pack, args.output_pack), ensure_ascii=False))
