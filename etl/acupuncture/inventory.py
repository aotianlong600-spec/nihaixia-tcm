"""Build the full-book TOC denominator and backmatter indexes for acupuncture.

Reads ``sources/acupuncture/pages.jsonl`` and writes:
- ``data/acupuncture/chapters.json``
- ``data/acupuncture/book_indexes.json``
"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = ROOT / "sources" / "acupuncture" / "pages.jsonl"
CHAPTERS_OUT = ROOT / "brain_data" / "acupuncture" / "chapters.json"
INDEXES_OUT = ROOT / "brain_data" / "acupuncture" / "book_indexes.json"
SOURCE_ID = "ni-acupuncture-v2-20100703"

TOC_LINE_RE = re.compile(r"^(?P<title>.+?)\s*[·…]+\s*(?P<page>\d+)\s*$")
CHAPTER_RE = re.compile(r"^第([一二三四五六])章\s+(.+)$")
CH_SECTION_RE = re.compile(r"^([一二三四五六七八九十]+)、(.+)$")
SUB_SECTION_RE = re.compile(r"^(\d+)[、\s]+(.+)$")
TIMESTAMP_RE = re.compile(r"[（(](\d{1,2}-\d{1,2}:\d{2}:\d{2})[）)]")

MERIDIAN_META = {
    "任脉与督脉": ("meridian:ren_du_intro", "任脉与督脉总论"),
    "任脉经穴": ("meridian:ren", "任脉"),
    "督脉经穴篇": ("meridian:du", "督脉"),
    "手太阴肺经": ("meridian:lu", "手太阴肺经"),
    "手阳明大肠经": ("meridian:li", "手阳明大肠经"),
    "足阳明胃经": ("meridian:st", "足阳明胃经"),
    "足太阴脾经": ("meridian:sp", "足太阴脾经"),
    "手少阴心经": ("meridian:ht", "手少阴心经"),
    "手太阳小肠经": ("meridian:si", "手太阳小肠经"),
    "足太阳膀胱经": ("meridian:bl", "足太阳膀胱经"),
    "足少阴肾经": ("meridian:ki", "足少阴肾经"),
    "手厥阴心包经": ("meridian:pc", "手厥阴心包经"),
    "手少阳三焦经": ("meridian:sj", "手少阳三焦经"),
    "足少阳胆经": ("meridian:gb", "足少阳胆经"),
    "足厥阴肝经": ("meridian:lv", "足厥阴肝经"),
}

PILOT_MERIDIAN_IDS = {"meridian:lu"}
PILOT_CONDITION_TITLES = {"头部与脑瘤治症", "治鼻病：鼻息肉 鼻炎"}


def load_pages() -> list[dict]:
    return [json.loads(line) for line in PAGES_PATH.open("r", encoding="utf-8") if line.strip()]


def strip_timestamp(title: str) -> tuple[str, str]:
    match = TIMESTAMP_RE.search(title)
    if not match:
        return title.strip(), ""
    clean = TIMESTAMP_RE.sub("", title).strip()
    return clean, match.group(1)


def norm_title(value: str) -> str:
    cleaned = re.sub(r"[①②③④⑤⑥⑦⑧⑨⑩]", "", value or "")
    return re.sub(r"[\s：:、，,。；;（）()·・-]+", "", cleaned)


def parse_toc(pages: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    raw_entries: list[dict] = []
    for pdf_page in range(3, 11):
        body = pages[pdf_page - 1]["body_text"]
        for line in body.splitlines():
            line = line.strip()
            if not line or line == "目录":
                continue
            match = TOC_LINE_RE.match(line)
            if not match:
                continue
            raw_title = match.group("title").strip()
            target_page = int(match.group("page"))
            clean_title, ts = strip_timestamp(raw_title)
            raw_entries.append(
                {
                    "raw_title": raw_title,
                    "title": clean_title,
                    "timestamp": ts,
                    "page_start": target_page,
                    "toc_pdf_page": pdf_page,
                }
            )

    frontmatter: list[dict] = []
    chapters: list[dict] = []
    appendices: list[dict] = []
    current_chapter: dict | None = None
    current_major: dict | None = None
    sec_counter = 0

    for entry in raw_entries:
        title = entry["title"]
        page_start = entry["page_start"]
        if title in {"校勘序", "目录"}:
            frontmatter.append(
                {
                    "id": "preface" if title == "校勘序" else "toc",
                    "title": title,
                    "page_start": page_start,
                    "page_end": 2 if title == "校勘序" else 10,
                }
            )
            continue
        if title in {"穴位拼音索引", "穴位笔画索引", "治症索引"}:
            app_id = (
                "index_pinyin"
                if "拼音" in title
                else "index_stroke"
                if "笔画" in title
                else "index_condition"
            )
            appendices.append(
                {
                    "id": app_id,
                    "title": title,
                    "page_start": page_start,
                    "page_end": page_start,
                }
            )
            continue

        ch_match = CHAPTER_RE.match(title)
        if ch_match:
            ch_num_cn = ch_match.group(1)
            ch_idx = "一二三四五六".index(ch_num_cn) + 1
            current_chapter = {
                "id": f"ch{ch_idx}",
                "chapter_number": ch_idx,
                "title": title,
                "timestamp": entry["timestamp"],
                "page_start": page_start,
                "page_end": page_start,
                "sections": [],
            }
            chapters.append(current_chapter)
            current_major = None
            continue

        if current_chapter is None:
            continue

        sec_counter += 1
        ch_sec_match = CH_SECTION_RE.match(title)
        sub_sec_match = SUB_SECTION_RE.match(title)
        if ch_sec_match:
            bare_name = ch_sec_match.group(2).strip()
            meridian_info = MERIDIAN_META.get(bare_name) if current_chapter["id"] == "ch4" else None
            section = {
                "id": f"{current_chapter['id']}:s{sec_counter:03d}",
                "title": title,
                "bare_title": bare_name,
                "level": "meridian" if meridian_info else "section",
                "meridian_id": meridian_info[0] if meridian_info else None,
                "timestamp": entry["timestamp"],
                "page_start": page_start,
                "page_end": page_start,
                "pilot_status": (
                    "approved"
                    if (meridian_info and meridian_info[0] in PILOT_MERIDIAN_IDS)
                    or bare_name in PILOT_CONDITION_TITLES
                    else "pending"
                ),
            }
            current_chapter["sections"].append(section)
            current_major = section
        else:
            bare_name = sub_sec_match.group(2).strip() if sub_sec_match else title
            parent_meridian = current_major.get("meridian_id") if current_major else None
            is_pilot = (
                (parent_meridian in PILOT_MERIDIAN_IDS)
                or (title in PILOT_CONDITION_TITLES)
                or (bare_name in PILOT_CONDITION_TITLES)
            )
            section = {
                "id": f"{current_chapter['id']}:s{sec_counter:03d}",
                "title": title,
                "bare_title": bare_name,
                "level": "subsection" if current_major else "section",
                "parent_section_id": current_major["id"] if current_major else None,
                "meridian_id": parent_meridian,
                "timestamp": entry["timestamp"],
                "page_start": page_start,
                "page_end": page_start,
                "pilot_status": "approved" if is_pilot else "pending",
            }
            current_chapter["sections"].append(section)

    # Compute exact page_end using heading line position on the next boundary page
    page_first_lines = {
        p["pdf_page"]: (p["body_text"].splitlines()[0].strip() if p["body_text"].splitlines() else "")
        for p in pages
    }

    for idx, app in enumerate(appendices):
        if idx + 1 < len(appendices):
            app["page_end"] = appendices[idx + 1]["page_start"] - 1
        else:
            app["page_end"] = 216

    for idx, ch in enumerate(chapters):
        next_start = chapters[idx + 1]["page_start"] if idx + 1 < len(chapters) else 201
        if next_start == 201:
            ch["page_end"] = 200
        else:
            next_norm = norm_title(chapters[idx + 1]["title"])
            first_norm = norm_title(page_first_lines.get(next_start, ""))
            ch["page_end"] = next_start - 1 if first_norm.startswith(next_norm[:6]) else next_start

        secs = ch["sections"]
        for s_idx, sec in enumerate(secs):
            if s_idx + 1 < len(secs):
                nxt = secs[s_idx + 1]
                n_start = nxt["page_start"]
                if n_start <= sec["page_start"]:
                    sec["page_end"] = sec["page_start"]
                else:
                    nxt_norm = norm_title(nxt["title"])
                    first_norm = norm_title(page_first_lines.get(n_start, ""))
                    sec["page_end"] = n_start - 1 if nxt_norm and first_norm.startswith(nxt_norm[:6]) else n_start
            else:
                sec["page_end"] = ch["page_end"]

        pilot_count = sum(1 for sec in secs if sec["pilot_status"] == "approved")
        ch["total_sections"] = len(secs)
        ch["approved_sections"] = pilot_count
        ch["review_status"] = "partial" if pilot_count > 0 else "pending"

    return frontmatter, chapters, appendices


def detect_unknown_sections(pages: list[dict], chapters: list[dict]) -> list[dict]:
    toc_norms = set()
    for ch in chapters:
        toc_norms.add(norm_title(ch["title"]))
        for sec in ch["sections"]:
            toc_norms.add(norm_title(sec["title"]))
            toc_norms.add(norm_title(sec["bare_title"]))

    unknowns: list[dict] = []
    for page in pages:
        pdf_page = page["pdf_page"]
        if pdf_page < 11 or pdf_page > 200:
            continue
        for line in page["body_text"].splitlines():
            s = line.strip()
            if not s:
                continue
            has_ts = bool(TIMESTAMP_RE.search(s))
            is_ch = bool(CHAPTER_RE.match(s))
            if not (has_ts or is_ch):
                continue
            # Ignore inline parenthetical collation notes or narrative sentences mentioning timestamps
            if "校对注" in s or len(s) > 48:
                continue
            clean, ts = strip_timestamp(s)
            n = norm_title(clean)
            if not n:
                continue
            matched = any(n in t or t in n for t in toc_norms if len(t) >= 2)
            if not matched:
                unknowns.append(
                    {
                        "page_id": page["page_id"],
                        "pdf_page": pdf_page,
                        "heading": clean,
                        "timestamp": ts,
                        "raw_line": s,
                    }
                )
    return unknowns


def parse_two_column_index(pages: list[dict], start_page: int, end_page: int, kind: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    for pdf_page in range(start_page, end_page + 1):
        body = pages[pdf_page - 1]["body_text"]
        for line in body.splitlines():
            s = line.strip()
            if not s or s in {"穴位拼音索引", "治症索引"}:
                continue
            if re.fullmatch(r"[Ａ-ＺA-Z]", s) or re.fullmatch(r"[一二三四五六七八九十]+划", s):
                continue
            if re.match(r"^\d+", s):
                # continuation of previous entry's page numbers
                if current is not None:
                    more = [int(n) for n in re.findall(r"\d+", s)]
                    current["pages"].extend(more)
                continue
            # Format: "名称, 12, 34, 56"
            if "," in s or "，" in s:
                parts = re.split(r"[,，]", s)
                name = parts[0].strip()
                nums = [int(n) for p in parts[1:] for n in re.findall(r"\d+", p)]
                current = {
                    "id": f"idx:{kind}:{name}",
                    "name": name,
                    "kind": kind,
                    "pages": nums,
                    "index_pdf_page": pdf_page,
                    "generation_status": "auto",
                    "evidence_status": "anchored",
                    "review_status": "pending",
                }
                entries.append(current)
    # Deduplicate pages preserving order
    for row in entries:
        seen = set()
        dedup = []
        for p in row["pages"]:
            if p not in seen:
                seen.add(p)
                dedup.append(p)
        row["pages"] = dedup
    return entries


def main() -> int:
    pages = load_pages()
    frontmatter, chapters, appendices = parse_toc(pages)
    unknown_sections = detect_unknown_sections(pages, chapters)

    chapters_payload = {
        "source_id": SOURCE_ID,
        "total_pages": len(pages),
        "frontmatter": frontmatter,
        "chapters": chapters,
        "appendices": appendices,
        "unknown_sections": unknown_sections,
        "stats": {
            "total_chapters": len(chapters),
            "total_sections": sum(ch["total_sections"] for ch in chapters),
            "approved_sections": sum(ch["approved_sections"] for ch in chapters),
            "unknown_section_count": len(unknown_sections),
        },
    }

    pinyin_acupoints = parse_two_column_index(pages, 201, 206, "acupoint")
    condition_index = parse_two_column_index(pages, 213, 216, "condition")
    indexes_payload = {
        "source_id": SOURCE_ID,
        "pinyin_acupoints": pinyin_acupoints,
        "condition_index": condition_index,
        "stats": {
            "indexed_acupoint_terms": len(pinyin_acupoints),
            "indexed_condition_terms": len(condition_index),
        },
    }

    CHAPTERS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CHAPTERS_OUT.write_text(
        json.dumps(chapters_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    INDEXES_OUT.write_text(
        json.dumps(indexes_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "chapters": chapters_payload["stats"],
                "indexes": indexes_payload["stats"],
                "unknown_sections_sample": unknown_sections[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
