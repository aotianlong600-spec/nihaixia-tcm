"""Stage 0 source inventory builder.

Scans local book files in ``books/ni-haixia-medicine`` and structured source
snapshots in ``sources/`` (plus ``data/herbs.json``) and writes:
- ``data/source_catalog.json``
- ``docs/SOURCE_REGISTRY.md``

Existing ``data/source_manifest.json`` and formula/herb files are never modified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pypdfium2 as pdfium


ROOT = Path(__file__).resolve().parents[1]
BOOKS_DIR = ROOT / "books" / "ni-haixia-medicine"
SOURCES_DIR = ROOT / "sources"
CATALOG_PATH = ROOT / "brain_data" / "source_catalog.json"
REGISTRY_DOC_PATH = ROOT / "docs" / "SOURCE_REGISTRY.md"


KNOWN_SOURCES = {
    "books/ni-haixia-medicine/倪海厦人纪系列之针灸教程.pdf": {
        "source_id": "ni-acupuncture-v2-20100703",
        "title": "倪海厦人纪系列之针灸教程（校勘转录版）",
        "authors_and_collators": ["倪海厦（讲授）", "民间中医爱好者（校勘整理）"],
        "edition": "V2-20100703（第四次修改）",
        "source_type": "collated_transcript",
        "page_mapping_note": "第 1 页为封面；第 2–216 页 PDF 页码与印刷页码一致",
        "known_issues": [
            "校勘序明示其基于网络流传授课扫描件校勘整理，属校勘转录版，非原始出版原书。",
            "页底带编号脚注（①②③）由校勘者补充，不代表原讲授者原意。",
            "目录含六章正文与三份索引（穴位拼音、穴位笔画、治症索引）。",
        ],
    },
    "books/ni-haixia-medicine/【倪海厦注解版】倪海厦注神农本草经(清晰版).pdf": {
        "source_id": "ni-bencao-pdf",
        "title": "倪海厦注神农本草经",
        "authors_and_collators": ["倪海厦（注解）"],
        "edition": "清晰版电子版",
        "source_type": "collated_transcript",
        "page_mapping_note": "共 154 页 PDF；尚待阶段 2 逐页建立 PDF 页码与原书药物目录映射",
        "known_issues": ["部分首页或扉页无文本层，具体文本分布待阶段 2 全页清点。"],
    },
    "books/ni-haixia-medicine/倪海厦人纪系列之伤寒论.pdf": {
        "source_id": "ni-shanghan-pdf",
        "title": "倪海厦人纪系列之伤寒论",
        "authors_and_collators": ["倪海厦（讲授）", "民间校排整理"],
        "edition": "2010-05-09 定稿",
        "source_type": "collated_transcript",
        "page_mapping_note": "共 209 页；已抽取页文本见 sources/ni_shanghan_pages.jsonl",
        "known_issues": ["部分古文传本与《伤寒论辑义》存在剂量或字句差异，见方剂校注。"],
    },
    "books/ni-haixia-medicine/【倪海厦注释 】倪海厦人纪系列之金匮要略.pdf": {
        "source_id": "ni-jinkui-pdf",
        "title": "倪海厦人纪系列之金匮要略",
        "authors_and_collators": ["倪海厦（注释）", "小桂枝·群龙无首（校排）"],
        "edition": "10.10.10 校排版",
        "source_type": "collated_transcript",
        "page_mapping_note": "共 419 页；已抽取页文本见 sources/ni_jinkui_pages.jsonl",
        "known_issues": ["待阶段 4 与目录前 186 条方剂逐页对照。"],
    },
    "books/ni-haixia-medicine/【视频同步文稿】《金匮要略》——倪海厦人纪教程简体整理稿.pdf": {
        "source_id": "ni-jinkui-video-pdf",
        "title": "《金匮要略》——倪海厦人纪教程简体整理稿（视频同步文稿）",
        "authors_and_collators": ["倪海厦（讲授）", "视频同步整理者"],
        "edition": "简体整理稿",
        "source_type": "video_sync_transcript",
        "page_mapping_note": "共 377 页；已抽取页文本见 sources/ni_jinkui_transcript.jsonl",
        "known_issues": ["视频口语转录稿可能与印刷注本存在同音字差异。"],
    },
    "books/ni-haixia-medicine/【视频同步文稿】倪海厦人纪系列书籍之《皇帝内经上册》 .pdf": {
        "source_id": "ni-neijing-vol1-pdf",
        "title": "倪海厦人纪系列《黄帝内经》上册（视频同步文稿）",
        "authors_and_collators": ["倪海厦（讲授）", "视频同步文稿整理"],
        "edition": "视频同步文稿上册",
        "source_type": "video_sync_transcript",
        "page_mapping_note": "共 152 页；需在阶段 3 核对《素问》《灵枢》实际收录篇章分母",
        "known_issues": ["文件名写作“皇帝内经上册”；属于视频同步讲义稿，非经典独立校勘本。"],
    },
    "books/ni-haixia-medicine/【视频同步文稿】倪海厦人纪系列书籍之《黄帝内经下册》.pdf": {
        "source_id": "ni-neijing-vol2-pdf",
        "title": "倪海厦人纪系列《黄帝内经》下册（视频同步文稿）",
        "authors_and_collators": ["倪海厦（讲授）", "视频同步文稿整理"],
        "edition": "视频同步文稿下册",
        "source_type": "video_sync_transcript",
        "page_mapping_note": "共 154 页；与上册合计 306 页，待阶段 3 清点篇章目录",
        "known_issues": ["属于视频同步讲义稿，经典原文与讲解需在阶段 3 严格分源。"],
    },
    "books/ni-haixia-medicine/伤寒论辑义--.txt": {
        "source_id": "shanghan-juyi-book-txt",
        "title": "伤寒论辑义（本地原始文本）",
        "authors_and_collators": ["（日）丹波元简（辑义）"],
        "edition": "GB18030 纯文本",
        "source_type": "classical_edition",
        "page_mapping_note": "纯文本按原始行号定位，与 sources/shanghan_juyi.txt 同源",
        "known_issues": [],
    },
    "sources/shanghan_juyi.txt": {
        "source_id": "shanghan-juyi-snapshot",
        "title": "伤寒论辑义（仓库抽取底本）",
        "authors_and_collators": ["（日）丹波元简（辑义）"],
        "edition": "GB18030 仓库底本",
        "source_type": "classical_edition",
        "page_mapping_note": "纯文本按行号定位，供 etl/extract_shanghan.py 读取",
        "known_issues": [],
    },
    "sources/ni_shanghan_pages.jsonl": {
        "source_id": "ni-shanghan-pages-jsonl",
        "title": "倪海厦人纪系列之伤寒论 PDF 页级文本快照",
        "authors_and_collators": ["仓库 ETL 抽取"],
        "edition": "JSONL 页级快照",
        "source_type": "structured_snapshot",
        "page_mapping_note": "按 JSONL 内 page 字段对应原 PDF 页码",
        "known_issues": [],
    },
    "sources/ni_jinkui_pages.jsonl": {
        "source_id": "ni-jinkui-pages-jsonl",
        "title": "倪海厦注金匮要略 PDF 页级文本快照",
        "authors_and_collators": ["仓库 ETL 抽取"],
        "edition": "JSONL 页级快照",
        "source_type": "structured_snapshot",
        "page_mapping_note": "按 JSONL 内 page 字段对应原 PDF 页码",
        "known_issues": [],
    },
    "sources/ni_jinkui_transcript.jsonl": {
        "source_id": "ni-jinkui-video-jsonl",
        "title": "《金匮要略》视频同步文稿页级文本快照",
        "authors_and_collators": ["仓库 ETL 抽取"],
        "edition": "JSONL 页级快照",
        "source_type": "structured_snapshot",
        "page_mapping_note": "按 JSONL 内 page 字段对应视频文稿 PDF 页码",
        "known_issues": [],
    },
    "sources/jinkui_recipes_source.json": {
        "source_id": "jinkui-recipes-snapshot",
        "title": "金匮要略 186 条方剂抽取快照",
        "authors_and_collators": ["仓库 ETL 抽取"],
        "edition": "JSON 结构化快照",
        "source_type": "structured_snapshot",
        "page_mapping_note": "含每首方剂在金匮注本中的起始页码",
        "known_issues": [],
    },
    "data/herbs.json": {
        "source_id": "ni-bencao-351-snapshot",
        "title": "倪海厦注神农本草经 351 味药结构化快照",
        "authors_and_collators": ["倪海厦（注）", "仓库 V1 抽取"],
        "edition": "351 味基线快照",
        "source_type": "structured_snapshot",
        "page_mapping_note": "每味药含 page_start 与 page_end 对应神农本草经 PDF 页码",
        "known_issues": ["尚待阶段 2 核对原书完整总目分母与版本差异。"],
    },
    "books/ni-haixia-medicine/【汉唐中医内容】倪海厦传统中医跟诊过程.pdf": {
        "source_id": "ni-hantang-clinic-notes-pdf",
        "title": "倪海厦传统中医跟诊过程（心得）",
        "authors_and_collators": ["跟诊弟子（整理）"],
        "edition": "汉唐中医跟诊电子稿",
        "source_type": "lecture_transcript",
        "page_mapping_note": "共 35 页 PDF；待后续专题参考",
        "known_issues": ["属弟子跟诊心得整理，不可替代原典。"],
    },
    "books/ni-haixia-medicine/【汉唐中医内容】倪海厦汉唐中医经典文章医案集.pdf": {
        "source_id": "ni-hantang-articles-cases-pdf",
        "title": "倪海厦汉唐中医经典文章医案集",
        "authors_and_collators": ["倪海厦（撰）", "汉唐中医整理"],
        "edition": "电子汇编本",
        "source_type": "collated_transcript",
        "page_mapping_note": "共 383 页 PDF；待后续医案对照",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/倪海夏-汉唐中医方剂讲解.pdf": {
        "source_id": "ni-hantang-formulas-pdf",
        "title": "汉唐中医方剂讲解",
        "authors_and_collators": ["倪海厦（讲授）", "紫极书院整理"],
        "edition": "电子整理稿",
        "source_type": "lecture_transcript",
        "page_mapping_note": "共 235 页 PDF；含 HT 系列汉唐方讲解",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/大冢敬节伤寒论解说(1).docx": {
        "source_id": "otsuka-shanghan-docx",
        "title": "大冢敬节《伤寒论解说》摘录",
        "authors_and_collators": ["大冢敬节（著）"],
        "edition": "DOCX 电子摘录",
        "source_type": "collated_transcript",
        "page_mapping_note": "DOCX 文本；供他家伤寒注释参考",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/明清名医全书大成(徐灵胎医学全书 ).pdf": {
        "source_id": "xu-lingtai-collection-pdf",
        "title": "明清名医全书大成·徐灵胎医学全书",
        "authors_and_collators": ["（清）徐大椿（灵胎）"],
        "edition": "WinRT OCR 校理双栏版 + 原版影印 PDF",
        "source_type": "classical_edition",
        "page_mapping_note": "共 434 页（412 页本地 Windows zh-Hans-CN OCR 全文 + 22 页空白背面如实留空），原书 p.1–420 对照（含1999现代导言/学术研究边界标注与王孟英「雄按」）",
        "known_issues": ["偶见繁简/异体及古籍版面识别差异，阅读器同步附原页扫描图像供核对。"],
    },
    "books/ni-haixia-medicine/石室秘录-清-陈士铎.txt": {
        "source_id": "chen-shiduo-shishimilu-txt",
        "title": "石室秘录",
        "authors_and_collators": ["（清）陈士铎"],
        "edition": "纯文本电子版",
        "source_type": "classical_edition",
        "page_mapping_note": "纯文本按行定位",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/血证论-唐容川.pdf": {
        "source_id": "tang-rongchuan-xuezhenglun-pdf",
        "title": "血证论",
        "authors_and_collators": ["（清）唐容川"],
        "edition": "电子版 PDF",
        "source_type": "classical_edition",
        "page_mapping_note": "共 170 页 PDF；第 1 页封面无文本",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/证因方论集要-汪汝麟.doc": {
        "source_id": "wang-rulin-zhengyinfanglun-doc",
        "title": "证因方论集要",
        "authors_and_collators": ["汪汝麟"],
        "edition": "DOC 电子版",
        "source_type": "classical_edition",
        "page_mapping_note": "旧版 DOC 格式，未抽取文本",
        "known_issues": [],
    },
    "books/ni-haixia-medicine/黄帝外经.pdf": {
        "source_id": "huangdi-waijing-pdf",
        "title": "黄帝外经",
        "authors_and_collators": ["托名岐伯/陈士铎述"],
        "edition": "WinRT OCR 数字化版 + 原版影印 PDF",
        "source_type": "classical_edition",
        "page_mapping_note": "共 85 页本地 Windows zh-Hans-CN OCR 全文（p.1–4 卷首概述 + 现存《外经微言》80 篇，含「凌波按」）",
        "known_issues": ["底本楷体偶见「耒/汨/順/炅」等异形识别字，检索已兼顾归一化，阅读器并附原页图像核对。"],
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_pdf(path: Path) -> tuple[int, str]:
    doc = pdfium.PdfDocument(str(path))
    total = len(doc)
    sample_indices = sorted({0, min(1, total - 1), min(10, total - 1), total // 2, total - 1})
    non_empty = 0
    bad_chars = 0
    total_chars = 0
    for idx in sample_indices:
        text = doc[idx].get_textpage().get_text_range().strip()
        if len(text) >= 20:
            non_empty += 1
        total_chars += len(text)
        bad_chars += sum(1 for ch in text if ch == "\ufffd" or (0xE000 <= ord(ch) <= 0xF8FF))
    if total_chars == 0 or non_empty == 0:
        return total, "image_only"
    if bad_chars / max(1, total_chars) > 0.05:
        return total, "garbled"
    if non_empty < len(sample_indices):
        return total, "mixed"
    return total, "clean_digital"


def slug_source_id(rel_path: str) -> str:
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:8]
    stem = Path(rel_path).stem
    ascii_part = "".join(ch.lower() if ch.isascii() and ch.isalnum() else "-" for ch in stem)
    ascii_part = "-".join(part for part in ascii_part.split("-") if part)
    return f"src-{ascii_part or 'doc'}-{digest}"


def build_entry(path: Path) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    meta = KNOWN_SOURCES.get(rel, {})
    suffix = path.suffix.lower().lstrip(".")
    total_pages = None
    if suffix == "pdf":
        total_pages, text_status = inspect_pdf(path)
    elif suffix in {"json", "jsonl"}:
        text_status = "structured_data"
    elif suffix == "txt":
        text_status = "plain_text"
    else:
        text_status = "uninspected"

    default_type = (
        "structured_snapshot"
        if rel.startswith(("sources/", "data/")) and suffix in {"json", "jsonl"}
        else "collated_transcript"
    )
    return {
        "source_id": meta.get("source_id") or slug_source_id(rel),
        "title": meta.get("title") or path.stem,
        "authors_and_collators": meta.get("authors_and_collators") or ["待清点登记"],
        "edition": meta.get("edition") or "本地原始文件",
        "source_type": meta.get("source_type") or default_type,
        "file_format": suffix,
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "total_pages": total_pages,
        "page_mapping_note": meta.get("page_mapping_note") or "尚未建立逐页映射",
        "relative_path": rel,
        "text_layer_status": text_status,
        "known_issues": meta.get("known_issues") or [],
    }


def build_catalog() -> dict:
    files: list[Path] = []
    if BOOKS_DIR.is_dir():
        files.extend(sorted(p for p in BOOKS_DIR.rglob("*") if p.is_file()))
    if SOURCES_DIR.is_dir():
        for path in sorted(SOURCES_DIR.iterdir()):
            if path.is_file() and path.name != "README.md":
                files.append(path)
    herbs_path = ROOT / "brain_data" / "herbs.json"
    if herbs_path.is_file():
        files.append(herbs_path)

    entries = [build_entry(path) for path in files]
    return {
        "schema_version": "2.0",
        "total_sources": len(entries),
        "sources": entries,
    }


def render_registry_markdown(catalog: dict) -> str:
    lines = [
        "# V2 统一来源目录（docs/SOURCE_REGISTRY.md）",
        "",
        "本文件由 `python -m etl.source_inventory` 自动生成，对应 `data/source_catalog.json`。",
        "",
        "| `source_id` | 名称 | 来源类型 | 格式 | 页数 | 文本层状态 | 相对路径 | SHA-256（前12位） |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for item in catalog["sources"]:
        pages = str(item["total_pages"]) if item["total_pages"] is not None else "—"
        lines.append(
            f"| `{item['source_id']}` | {item['title']} | `{item['source_type']}` | "
            f"`{item['file_format']}` | {pages} | `{item['text_layer_status']}` | "
            f"`{item['relative_path']}` | `{item['sha256'][:12]}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    catalog = build_catalog()
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    REGISTRY_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_DOC_PATH.write_text(
        render_registry_markdown(catalog),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {catalog['total_sources']} source records to {CATALOG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
