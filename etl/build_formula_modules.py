"""Build one navigable module for every source-indexed formula.

The generated modules are source-indexed, not human-reviewed. Curated modules
already present in formula_evidence.json are preserved.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "brain_data"
OUTPUT = DATA / "formula_modules.json"

SYMPTOM_TERMS = """
发热 恶寒 恶风 汗出 无汗 自汗 盗汗 头痛 头重 眩晕 目眩 口苦 咽干 口渴 消渴
咳嗽 喘 短气 胸满 胸痛 心悸 心烦 烦躁 失眠 多眠 但欲寐 谵语 发狂 抽搐 拘急
腹满 腹痛 少腹痛 心下痞 呕吐 干呕 呕逆 下利 便秘 大便硬 小便不利 小便数
身重 身痛 骨节疼痛 四肢厥冷 手足冷 手足温 水肿 黄疸 衄血 下血 瘀血 带下
痛经 月经不调 阴痒 疮疡 脓血 痰多 黄痰 白痰 食不下 不能食 能食 嗳气
""".split()

CHANNEL_IDS = {
    "太阳": "taiyang",
    "阳明": "yangming",
    "少阳": "shaoyang",
    "太阴": "taiyin",
    "少阴": "shaoyin",
    "厥阴": "jueyin",
}


def read_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clean(text: str) -> str:
    text = (text or "").replace("\r", "")
    text = re.sub(r"(.)\1{3,}", r"\1", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"第\s*\d+\s*页", line):
            continue
        if line in {"觀", "其", "脈", "證", "知", "犯", "何", "逆", "隨", "證", "治", "之"}:
            continue
        lines.append(line)
    value = "\n".join(lines)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def source_text(formula: dict) -> str:
    parts = [
        formula.get("composition_raw", ""),
        formula.get("decoction", ""),
        formula.get("notes", ""),
        formula.get("source", {}).get("excerpt", ""),
    ]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def usage_text(formula: dict) -> str:
    return (formula.get("decoction") or formula.get("source", {}).get("excerpt") or "").strip()


def split_sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。；])", text)
        if part.strip()
    ]


def usage_steps(text: str) -> list[str]:
    sentences = split_sentences(text)
    picked = [
        sentence
        for sentence in sentences
        if any(term in sentence for term in ("以水", "煮取", "煎", "去滓", "温服", "啜", "温覆", "服一升", "分温", "顿服"))
    ]
    return picked[:8] or sentences[:4]


def cautions(text: str) -> list[str]:
    return [
        sentence
        for sentence in split_sentences(text)
        if any(term in sentence for term in ("禁", "不可", "勿", "不得", "有毒", "不当"))
    ][:8]


def symptoms_for(formula: dict, evidence: dict) -> list[dict]:
    text = " ".join(
        [
            formula.get("indication", ""),
            formula.get("notes", ""),
            formula.get("source", {}).get("excerpt", ""),
            " ".join(row.get("text", "") for row in evidence.get("candidate_sources", {}).get("book", [])[:2]),
        ]
    )
    found = []
    for term in SYMPTOM_TERMS:
        if term in text and term not in {row["name"] for row in found}:
            pages = [
                row["page"]
                for row in evidence.get("candidate_sources", {}).get("book", [])
                if term in row.get("text", "") or term in row.get("excerpt", "")
            ]
            found.append({"name": term, "source": "原文页", "page": pages[0] if pages else None})
    return found[:14]


def page_reading(formula: dict, evidence: dict) -> list[dict]:
    rows = []
    seen = set()
    for candidate in evidence.get("candidate_sources", {}).get("book", []):
        page = candidate.get("page")
        text = clean(candidate.get("excerpt", ""))
        if not text or page in seen:
            continue
        seen.add(page)
        rows.append(
            {
                "page": page,
                "title": f"{formula['name']}相关原文",
                "kind": "方名命中页",
                "text": text[:3600],
                "annotation": "按本地原文页命中的相关段；逐方人工复核状态见校对标记。",
            }
        )
    if not rows:
        excerpt = clean(formula.get("source", {}).get("excerpt", ""))
        if excerpt:
            rows.append(
                {
                    "page": formula.get("source", {}).get("page"),
                    "title": f"{formula['name']}原文位置",
                    "kind": "原文摘录",
                    "text": excerpt[:3600],
                    "annotation": "当前以本地原文行号/页定位，尚未建立完整页图。",
                }
            )
    return rows


def six_channel_for(formula: dict, six_by_id: dict[str, dict]) -> dict:
    meridian = formula.get("six_meridian") or ""
    channel_id = CHANNEL_IDS.get(meridian, "")
    if channel_id and channel_id in six_by_id:
        item = deepcopy(six_by_id[channel_id])
        return {
            "id": item["id"],
            "name": item["name"],
            "summary": item["summary"],
            "original": item.get("original", []),
            "annotation_original": item.get("annotations", []),
            "source_pages": item.get("source_pages", []),
            "proof_note": item.get("proof_note", ""),
        }
    chapter = formula.get("chapter") or formula.get("six_meridian") or "方证条目"
    return {
        "id": "",
        "name": chapter,
        "summary": f"本条属于{chapter}范围，具体六经层级需结合完整条文继续判定。",
        "original": [],
        "annotation_original": [],
        "source_pages": [],
        "proof_note": "",
    }


def build_module(formula: dict, evidence: dict, six_by_id: dict[str, dict]) -> dict:
    if evidence.get("overview") and evidence.get("page_reading"):
        curated = deepcopy(evidence)
        curated["module_status"] = "curated"
        curated["review_level"] = evidence.get("review_level", "完整")
        return curated
    pages = page_reading(formula, evidence)
    source = source_text(formula)
    usage = usage_text(formula)
    symptom_rows = symptoms_for(formula, evidence)
    source_pages = [row["page"] for row in pages if row.get("page")]
    indication = (formula.get("indication") or formula.get("notes") or "").strip()
    composition = "、".join(
        f"{row['name']}{row.get('dose', '')}" for row in formula.get("ingredients", [])
    )
    page_labels = "、".join(str(page) for page in source_pages) or "原文行号"
    chapter = formula.get("chapter") or formula.get("six_meridian") or "方证"
    overview = {
        "title": f"{formula['name']}方证摘要",
        "paragraphs": [
            f"本条属于{chapter}。现依据本地原文建立独立模块，原文定位为第{page_labels}页。先看原方组成与煎服法，再看对应页的正文和注解。",
            f"原文所列证候：{indication or '本条以方名和组成为主，证候文字待从对应页继续整理。'}",
            f"方剂组成：{composition or '组成待补'}。剂量按来源原样保留，不换算为现代克数。",
            f"煎服法：{usage[:260] if usage else '原文未载明煎服法'}。完整古文、现代资料整理和逐页原文分别进入独立二级页。",
        ],
        "key_points": [
            chapter,
            f"{len(formula.get('ingredients', []))}味",
            f"原文{page_labels}",
            "模块已建立",
        ],
    }
    modern_source = "\n\n".join(
        row["text"]
        for row in pages
        if any(term in row["text"] for term in ("水", "煮", "煎", "服", "温覆"))
    )[:5000]
    return {
        "module_status": "source_indexed",
        "review_level": "原文页索引",
        "overview": overview,
        "symptoms": symptom_rows,
        "six_channel": six_channel_for(formula, six_by_id),
        "formula_original": {
            "title": f"{formula['name']}方",
            "text": source or "原文未提供可用组成。",
            "source_pages": source_pages,
            "note": f"本地原文定位：{formula.get('source', {}).get('path', '')}；页码/行号见校对依据。",
        },
        "usage_original": {
            "title": "古文用法",
            "summary": usage[:220] if usage else "原文未载明煎服法。",
            "text": usage or "原文未载明煎服法。",
            "source_pages": source_pages,
        },
        "usage_modern": {
            "summary": "本模块以原文页为底稿，二级页先给出整理步骤，再附可见的现代资料原文。",
            "source_text": modern_source or "当前可见本地原文未提供单独的现代煎药说明。",
            "steps": usage_steps(usage),
            "cautions": cautions(usage),
            "source_pages": source_pages,
        },
        "page_reading": pages,
        "rationale": {
            "summary": indication[:280] or f"本条已按{chapter}建立原文索引，方义与注解尚待逐页复核。",
            "full_text": "\n\n".join(row["text"] for row in pages)[:10000]
            or f"当前原文摘录：{source[:2000]}",
        },
        "annotations": [
            {
                "heading": f"第{row.get('page') or '未标'}页相关段",
                "text": row["text"][:2500],
                "source_page": row.get("page"),
            }
            for row in pages[:4]
        ],
        "proofreading": [
            {
                "kind": "本地原文",
                "title": formula.get("source", {}).get("title", "方剂来源"),
                "pages": page_labels,
                "note": "模块按本地页文本自动拆分；人工逐方复核仍以校对状态为准。",
            }
        ],
        "editorial_note": "本页由本地原文自动编页生成，用于逐方逐页复核；不把自动整理标记为人工定稿。",
    }


def main() -> int:
    formulas = read_json("formulas.json") + read_json("jinkui_formulas.json")
    evidence = read_json("formula_evidence.json")
    six_items = read_json("six_channels.json")["items"]
    six_by_id = {item["id"]: item for item in six_items}
    modules = {
        formula["id"]: build_module(formula, evidence.get(formula["id"], {}), six_by_id)
        for formula in formulas
    }
    modules = {key: value for key, value in modules.items() if value}
    write_json(OUTPUT, modules)
    print(f"modules={len(modules)} output={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
