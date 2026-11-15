"""Attach per-formula usage and Ni Haixia evidence to the catalog.

The generated evidence file intentionally leaves `why` empty until a formula
has been reviewed. A name hit in a page is a candidate, not proof that the
surrounding paragraph explains the formula.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "brain_data"
SOURCES = ROOT / "sources"
OUTPUT = DATA / "formula_evidence.json"
REPORT = DATA / "evidence_report.json"
CURATED = DATA / "curated_formulas.json"
CURATED_BATCHES = DATA / "curated_batches"
CURATED_BATCH_MANIFEST = DATA / "curated_batch_manifest.json"

SHANGHAN_BOOK = "sources/ni_shanghan_pages.jsonl"
JINKUI_BOOK = "sources/ni_jinkui_pages.jsonl"
JINKUI_VIDEO = "sources/ni_jinkui_transcript.jsonl"

SEARCH_ALIASES = {
    "茯苓桂枝白术甘草汤": ["茯苓桂枝白朮甘草汤"],
    "栀子厚朴汤": ["栀子厚朴"],
    "栀子干姜汤": ["栀子干姜"],
    "桂枝甘草龙骨牡蛎汤": ["桂苓甘草龙骨牡蛎汤"],
    "麻黄连轺赤小豆汤": ["麻黄连翘赤小豆汤"],
    "烧裈散": ["烧裩散"],
}


def read_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def read_pages(path: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / path).open(encoding="utf-8")]


def load_curated() -> dict:
    merged = json.loads(CURATED.read_text(encoding="utf-8"))
    manifest = json.loads(CURATED_BATCH_MANIFEST.read_text(encoding="utf-8"))
    accepted = manifest.get("accepted", [])
    if not isinstance(accepted, list) or not all(isinstance(name, str) for name in accepted):
        raise ValueError("curated_batch_manifest.json must contain an accepted string list")
    for name in accepted:
        path = CURATED_BATCHES / name
        if not path.is_file():
            raise ValueError(f"accepted curated batch is missing: {name}")
        batch = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(batch, dict):
            raise ValueError(f"{path.name} must contain an object keyed by formula id")
        duplicate = sorted(set(merged) & set(batch))
        if duplicate:
            raise ValueError(f"{path.name} duplicates curated formulas: {', '.join(duplicate)}")
        merged.update(batch)
    return merged


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def normalize(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"(.)\1{3,}", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def candidates(pages: list[dict], terms: list[str], limit: int = 4) -> list[dict]:
    found = []
    seen = set()
    for page in pages:
        if page.get("page", 0) <= 2:
            continue
        text = normalize(page.get("text", ""))
        for term in terms:
            at = text.find(term)
            if at < 0:
                continue
            excerpt = text[max(0, at - 420) : at + 1000]
            key = (page["page"], excerpt[:100])
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "page": page["page"],
                    "term": term,
                    "excerpt": excerpt,
                }
            )
            break
        if len(found) >= limit:
            break
    return found


def reviewed_overrides():
    """The first Jinkui formula reviewed manually from local source pages."""
    return {
        "jinkui:四逆加人参汤": {
            "review_status": "reviewed",
            "usage_status": "reviewed",
            "usage_plain": "四逆汤内加人参一两，余依四逆汤服法；原文并载：以水三升，煮取一升二合，去滓，分温再服。",
            "why": "倪注抓住“利止、恶寒、脉微、复利”这一组亡阳亡血表现：此时不是单纯贫血，而是血寒、津液将脱，所以用四逆汤回阳救逆，再加人参补津液与中气。",
            "usage_note": "用法来自《金匮要略》页11，并与页10视频同步文稿对照。",
            "review_sources": [
                {
                    "kind": "倪海厦金匮要略",
                    "title": "倪海厦注金匮要略",
                    "page": 11,
                    "excerpt": "利止，恶寒脉微，而复利，亡血也，四逆加人参汤主之。四逆汤内加人参一两，余依四逆汤服法。",
                },
                {
                    "kind": "视频同步文稿",
                    "title": "《金匮要略》——倪海厦人纪教程简体整理稿",
                    "page": 10,
                    "excerpt": "这个条辨呢，后面“利止，恶寒脉微，而复利，亡血也，四逆加人参汤主之。”……四逆汤症。……病人恶寒脉微心脏力量不够了。",
                },
            ],
            "video_status": "reviewed",
            "video_note": "已核对《金匮要略》视频同步文稿页10。",
        },
    }


def main() -> int:
    formulas = read_json("formulas.json") + read_json("jinkui_formulas.json")
    shanghan_pages = read_pages(SHANGHAN_BOOK)
    jinkui_pages = read_pages(JINKUI_BOOK)
    video_pages = read_pages(JINKUI_VIDEO)
    overrides = reviewed_overrides()
    curated = load_curated()
    evidence = {}

    for formula in formulas:
        book = formula.get("book")
        if book == "伤寒论":
            book_candidates = candidates(
                shanghan_pages,
                [
                    formula["name"],
                    *formula.get("aliases", []),
                    *SEARCH_ALIASES.get(formula["name"], []),
                ],
            )
            if not book_candidates:
                book_candidates = candidates(
                    jinkui_pages,
                    [
                        formula["name"],
                        *formula.get("aliases", []),
                        *SEARCH_ALIASES.get(formula["name"], []),
                    ],
                )
            video_candidates = []
            video_status = "not_available"
            video_note = ""
        else:
            book_candidates = candidates(
                jinkui_pages,
                [formula["name"], *formula.get("aliases", [])],
            )
            video_candidates = candidates(
                video_pages,
                [formula["name"], *formula.get("aliases", [])],
            )
            video_status = "candidates" if video_candidates else "no_local_hit"
            video_note = ""

        usage = formula.get("decoction", "").strip()
        entry = {
            "usage_status": "source_text" if usage else "missing",
            "usage_plain": usage,
            "usage_note": "",
            "why": "",
            "review_status": "pending",
            "candidate_sources": {
                "book": book_candidates,
                "video": video_candidates,
            },
            "review_sources": [],
            "video_status": video_status,
            "video_note": video_note,
        }
        if formula["id"] in overrides:
            entry.update(deepcopy(overrides[formula["id"]]))
        if formula["id"] in curated:
            entry.update(deepcopy(curated[formula["id"]]))
        evidence[formula["id"]] = entry

    write_json(OUTPUT, evidence)
    review_counts = {}
    usage_counts = {}
    for entry in evidence.values():
        review_counts[entry["review_status"]] = review_counts.get(entry["review_status"], 0) + 1
        usage_counts[entry["usage_status"]] = usage_counts.get(entry["usage_status"], 0) + 1
    write_json(
        REPORT,
        {
            "formulas": len(formulas),
            "review_status": review_counts,
            "usage_status": usage_counts,
            "reviewed_ids": [key for key, value in evidence.items() if value["review_status"] == "reviewed"],
        },
    )
    print(f"evidence={len(evidence)} review={review_counts} usage={usage_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
