"""Optimized Ni Haixia ('倪师角色') persona & grounded prompting for TCM Study Brain."""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any


STYLE_SPECS: dict[str, dict[str, str]] = {
    "master_balanced": {
        "id": "master_balanced",
        "label": "倪师亲授·处方实战版（推荐）",
        "summary": "输入症状直接出经方/合方处方、原方剂量与煎服法，并带倪师口述辨证、鉴别要点与原文溯源。",
        "voice_rules": (
            "1. 说话口吻：以倪海厦师父诊室带教口吻开讲。先亮明六经/脏腑辨证结论，再顺手用日常物象类比（太阳火气、冷水浇胃、卫气御外、水道水饮）讲清“为什么开这个方”。短句明快，适度穿插自然问答推进（“你想想看”、“对不对”、“很简单嘛”，全篇偶用一两处“嚎”）。\n"
            "2. 核心目标（输入症状必出清晰处方方案）：必须紧扣上下文给出的经方实证，输出清晰、不推诿的处方参考框架，依次包含：\n"
            "   - `**辨证焦点**：{六经或脏腑病位}（{病机要点} · 主方方向：{方名}）`\n"
            "   - `**建议经方处方**：`\n"
            "     - 若宜合方则写出主方+辅方；逐味列出**药物组成与原典经方用量/炮制**（优先采用上下文提供的 `composition_raw`/`ingredients`，有“先煎/后下/去皮/炙”等务必写明；仅在必要时用括号标明参考换算说明并区分“原典汉制”与“参考说明”，绝不捏造无据克数）。\n"
            "     - `**煎煮与服法**`：明确给出上下文中的 `usage_plain`（如先煮去沫、啜热稀粥、温覆微汗、中病即止等）。\n"
            "     - `**随症加减提示**`：结合病人可能兼夹证点明如何加味/转方。\n"
            "   - `**还需核对的四诊细节**`（提醒开药抓方前最后确认的 2~4 个问诊要点：有汗无汗、喜冷饮热饮、手足温凉、二便、西药史）\n"
            "   - `**鉴别要点（X vs Y）**`（对比容易误开的相反证型，防误汗误下）\n"
            "   - `**针灸配穴、触诊与饮食忌口**`（顺带点明配合穴位与忌冰冷生冷）\n"
            "   - `> 📜 **经典原文与实证出处**`（标注 `[ref:N]`）。"
        ),
    },
    "colloquial_lecture": {
        "id": "colloquial_lecture",
        "label": "原汁课堂·口述版",
        "summary": "接近人纪教学视频与汉唐跟诊口吻，一问一答推进后亮出经方处方与煎服法，文末附依据。",
        "voice_rules": (
            "1. 说话口吻：高度还原人纪课堂与跟诊实战对答，语气笃定直白、热情护阳气，先定经方，再讲透“为什么一剂能解”。\n"
            "2. 处方落地：用师父口述方式把【用哪张方、每味药原方几两怎么煮、喝完注意什么反应、配合扎哪几针、避开什么坑】交代明白，并带出 `[ref:N]` 经典依据。"
        ),
    },
    "academic_strict": {
        "id": "academic_strict",
        "label": "严谨考据·五层溯源版",
        "summary": "按五层隔离标准拆解辨证、经典原文原方原量、倪师阐释、跨书互参、AI推演与安全边界。",
        "voice_rules": (
            "1. 表达基调：保持临床处方与文献考据并重，输出清晰分节：\n"
            "   `【辨证与处方方案（经方原量+煎服法+针灸配穴）】`、`【经典原文层】`、`【倪师阐释层】`、`【鉴别与加减推演】`、`【安全边界与待核疑点】`，并准确标注 `[ref:N]`。"
        ),
    },
}

_SAFETY_AND_EPISTEMIC_FLOOR = """
【安全边界与实证处方纪律（务必遵守，但不推诿正常辨证出方）】
1. 急症与毒药红线：
   - 若上下文触发 `emergency_triage`（胸背剧痛、呼吸困难、神昏谵语、大出血/吐血黑便、高热惊厥等），**必须在回复最开头第一段**先警示立即前往急诊抢救/线下面诊，随后再做经典病机与文献参考分析。
   - 若主方含生附子、乌头、生半夏、巴豆、细辛、甘遂等峻猛毒药，或用户诉服药后**发麻、头晕昏沉、心悸大汗、剧吐泻**，必须明确警示**炮制/先煎要求及中毒即停医治红线**——绝不允许把毒副反应当成“瞑眩反应继续硬扛”。
   - 若用户明确表示信息过少、且缺核心寒热虚实依据（如只输入“肚子疼”三个字），先给出最可能分路与试探追问，避免盲目锁定单一峻下或大热之方；信息充分时则果断给出对应经方处方与煎服法，并附一句诚实提示（方药组成与用量依据经典与倪师教学整理供参考，抓药煎服前请结合当面脉舌或由执业中医师复核剂量与炮制）。
2. 零编造与严格溯源：
   - 处方药味、汉制原量、炮制方法与煎服法必须优先取自下方注入的「中医大脑实证上下文」，**严禁自行篡改方名或凭空捏造书中没有的药味**；若某味药原典未载具体用量，如实说明并提示须复核原方。
   - 引用文献请用 `[ref:N]` 格式，区分【经典原方/原文】【倪师讲解】【AI 辨证整理】。
""".strip()


def list_persona_styles() -> list[dict[str, str]]:
    return [
        {"id": spec["id"], "label": spec["label"], "summary": spec["summary"]}
        for spec in STYLE_SPECS.values()
    ]


def build_system_prompt(style: str = "master_balanced") -> str:
    spec = STYLE_SPECS.get(style) or STYLE_SPECS["master_balanced"]
    return (
        "你是“倪氏经方 × 中医大脑”工作台的经方助教（倪师角色）。\n"
        "你的使命是结合张仲景《伤寒论》《金匮要略》、《神农本草经》、《黄帝内经》与倪海厦人纪/汉唐诊疗体系，"
        "把后端中医大脑已经检索出的真实验证资料，转化为有临床神韵、脉络分明、且可点击溯源的教学解答。\n\n"
        f"{_SAFETY_AND_EPISTEMIC_FLOOR}\n\n"
        f"【当前回复模式：{spec['label']}】\n"
        f"{spec['voice_rules']}"
    )


def format_grounded_context(packet: dict[str, Any], *, max_refs: int = 8) -> str:
    """Serialize pre-retrieved Stage 1-5 evidence into a compact, high-signal prompt context."""
    sections: list[str] = []

    safety = packet.get("safety_boundary") or {}
    if safety.get("triggered") or safety.get("is_high_risk") or safety.get("risk_level") not in ("", "low", "standard", None):
        sections.append(
            "【安全熔断预警】\n"
            + json.dumps(
                {
                    "risk_level": safety.get("risk_level"),
                    "title": safety.get("title", ""),
                    "triggers": safety.get("matched_triggers") or safety.get("triggers") or [],
                    "notice": safety.get("banner") or safety.get("message") or "",
                },
                ensure_ascii=False,
            )
        )

    pinned = packet.get("pinned_entity")
    if pinned:
        sections.append("【用户当前点选精讲对象】\n" + json.dumps(pinned, ensure_ascii=False)[:1800])

    case_pkt = packet.get("case_packet") or {}
    if case_pkt:
        compact_case = {
            "primary_six_channel": case_pkt.get("primary_six_channel"),
            "extracted_symptoms": case_pkt.get("extracted_symptoms"),
            "recognized_negations": case_pkt.get("recognized_negations"),
            "extracted_pulses": case_pkt.get("extracted_pulses"),
            "extracted_tongues": case_pkt.get("extracted_tongues"),
            "contradiction_notes": case_pkt.get("contradiction_notes"),
            "matched_formulas": (case_pkt.get("matched_formulas") or [])[:4],
            "compound_regimens": (case_pkt.get("compound_regimens") or [])[:2],
            "matched_acupoints": (case_pkt.get("matched_acupoints") or [])[:4],
            "matched_herbs": (case_pkt.get("matched_herbs") or [])[:5],
            "differential_points": (case_pkt.get("differential_points") or [])[:4],
            "missing_inquiry": (case_pkt.get("missing_inquiry") or [])[:5],
        }
        sections.append("【中医大脑五阶辨证与四诊推演包】\n" + json.dumps(compact_case, ensure_ascii=False))

    hantang = packet.get("hantang_clues") or {}
    if any(hantang.get(k) for k in ("hantang_formulas", "du_spine_guides", "special_palpations", "western_history_guidance", "ht_redlines")):
        sections.append(
            "【汉唐经方、督脉压痛与西药介入提示】\n"
            + json.dumps(
                {
                    "formulas": (hantang.get("hantang_formulas") or [])[:3],
                    "du_spine": (hantang.get("du_spine_guides") or [])[:3],
                    "palpations": (hantang.get("special_palpations") or [])[:3],
                    "western_rules": (hantang.get("western_history_guidance") or [])[:2],
                    "redlines": (hantang.get("ht_redlines") or [])[:2],
                },
                ensure_ascii=False,
            )
        )

    citations = (packet.get("citations") or [])[:max_refs]
    if citations:
        lines = ["【可引用实证文献列表（引用时请写 [ref:编号]）】"]
        for c in citations:
            page_label = c.get("unit_label") or f"第 {c.get('page_no')} 页"
            loc = f"{c.get('book_title', '')} · {page_label}"
            quote = str(c.get("quote") or "").strip().replace("\n", " ")[:240]
            sha_short = str(c.get("text_sha256") or "")[:12]
            src_tag = "本机导入原文" if c.get("source_scope") == "local_sqlite" else "中医大脑原典"
            lines.append(f"[ref:{c['ref_id']}] ({src_tag} | {loc} | sha:{sha_short}) {quote}")
        sections.append("\n".join(lines))
    else:
        sections.append("【可引用实证文献列表】\n本次检索暂无直接页码原文命中；严禁自编条文号或页码，需明确告知“当前资料库暂无直接原文命中，仅做框架推演”。")

    return "\n\n".join(sections)


_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
_MAX_IMAGE_COUNT = 3
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)


def normalize_image_inputs(images: list[Any] | None, *, max_count: int = _MAX_IMAGE_COUNT) -> list[dict[str, str]]:
    """Validate and normalize up to max_count compressed image data URLs (PNG/JPEG/WebP/GIF)."""
    cleaned: list[dict[str, str]] = []
    for idx, item in enumerate(images or []):
        if len(cleaned) >= max_count:
            break
        raw_url = item.get("data_url") if isinstance(item, dict) else item
        raw_name = item.get("name") if isinstance(item, dict) else f"病例图 {idx + 1}"
        text = str(raw_url or "").strip()
        if not text:
            continue
        m = _DATA_URL_RE.match(text)
        if not m:
            continue
        mime = m.group(1).lower()
        if mime not in _ALLOWED_IMAGE_MIMES:
            continue
        if mime == "image/jpg":
            mime = "image/jpeg"
        b64 = re.sub(r"\s+", "", m.group(2))
        if not b64:
            continue
        try:
            decoded = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not decoded or len(decoded) > _MAX_IMAGE_BYTES:
            continue
        safe_name = str(raw_name or f"病例图 {len(cleaned) + 1}").strip()[:80]
        cleaned.append(
            {
                "name": safe_name,
                "mime_type": mime,
                "b64": b64,
                "data_url": f"data:{mime};base64,{b64}",
            }
        )
    return cleaned


def build_vision_intake_prompt(hint: str = "") -> tuple[str, str]:
    """Return (system_prompt, user_prompt) to extract structured TCM four-diagnosis findings from images."""
    sys_prompt = (
        "你是专业的中医问诊病历与四诊图片结构化助手。"
        "请仔细识读用户上传的问诊表、病历单、化验单、处方照片或舌象照片，只提取图片中真实可见的信息，严禁臆造。\n"
        "请严格仅输出一个 JSON 对象（不要包含额外前后缀说明），字段 schema 如下：\n"
        "{\n"
        '  "chief_complaint": "用简短一句概括主诉与核心症状（适合直接填入问诊输入框）",\n'
        '  "symptoms": ["尽量精炼的症状词条，如：发热、恶寒、恶风、有汗、无汗、往来寒热、口苦、咽干、胸胁苦满、胃脘胀满、食欲不振、大便干、下利清谷、口渴喜冷饮、身冷、脚冷、失眠、头晕目眩、心悸"],\n'
        '  "negations": ["明确写明的否定项，如：不恶寒、无大便干结、无发热"],\n'
        '  "pulses": ["脉象词，如：浮、沉、紧、缓、弦、滑、数、迟、细、微弱、结代"],\n'
        '  "tongues": ["舌象/唇象，如：舌淡红苔薄白、舌质红、舌红少苔、舌暗有瘀点、舌淡胖齿痕、舌苔白滑、苔黄腻、唇干"],\n'
        '  "abdomen": ["腹诊所见，如：胸腹动悸、心下痞硬、腹痛喜按"],\n'
        '  "eye": ["眼诊或小儿指纹所见"],\n'
        '  "tender": ["压痛点，如：关元穴压痛"],\n'
        '  "medical_notes": {\n'
        '    "present": "起病时间、诱因、加重缓解规律等现病史",\n'
        '    "past": "既往史、正在服用的西药（降压/降糖/抗凝等）",\n'
        '    "allergy": "过敏史、经期或妊娠说明",\n'
        '    "exam": "辅助检查结果、二便睡眠概括"\n'
        "  },\n"
        '  "raw_text": "逐条摘录图片中的关键文字或客观所见（如实写明不清楚/遮挡处）",\n'
        '  "warnings": ["如有反光/白平衡偏色（特别是舌象照片）或字迹模糊，在此简短提示人工复核"]\n'
        "}"
    )
    user_hint = (hint or "").strip()
    user_text = "请识别以上图片中的中医四诊信息、主诉症状、否定排除项与病历补充，严格返回 JSON。"
    if user_hint:
        user_text += f"\n用户补充说明：{user_hint[:400]}"
    return sys_prompt, user_text


def _dedupe_str_list(items: Any, *, max_items: int = 16, max_len: int = 36) -> list[str]:
    if isinstance(items, str):
        items = [s for s in re.split(r"[,，、;；\n]+", items) if s.strip()]
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x or "").strip()[:max_len]
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def parse_vision_intake_response(raw_reply: str, *, image_count: int = 1) -> dict[str, Any]:
    """Extract normalized intake JSON object from multimodal model output with plain-text fallback."""
    text = str(raw_reply or "").strip()
    parsed: dict[str, Any] | None = None

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                parsed = obj
                break
        except json.JSONDecodeError:
            continue

    if not parsed:
        clean_plain = text[:800].strip()
        return {
            "symptoms": [],
            "negations": [],
            "pulses": [],
            "tongues": [],
            "abdomen": [],
            "eye": [],
            "tender": [],
            "medical_notes": {"present": clean_plain[:240], "past": "", "allergy": "", "exam": ""},
            "chief_complaint": clean_plain[:180],
            "raw_text": clean_plain,
            "warnings": ["模型未返回标准 JSON，已将识读全文填入主诉/病历补充，请核对后补充标签。"],
            "image_count": image_count,
        }

    notes_raw = parsed.get("medical_notes") if isinstance(parsed.get("medical_notes"), dict) else {}
    medical_notes = {
        "present": str(notes_raw.get("present") or "").strip()[:240],
        "past": str(notes_raw.get("past") or "").strip()[:240],
        "allergy": str(notes_raw.get("allergy") or "").strip()[:200],
        "exam": str(notes_raw.get("exam") or "").strip()[:240],
    }
    symptoms = _dedupe_str_list(parsed.get("symptoms"))
    negations = _dedupe_str_list(parsed.get("negations"))
    pulses = _dedupe_str_list(parsed.get("pulses"))
    tongues = _dedupe_str_list(parsed.get("tongues"))
    abdomen = _dedupe_str_list(parsed.get("abdomen"))
    eye = _dedupe_str_list(parsed.get("eye"))
    tender = _dedupe_str_list(parsed.get("tender"))
    chief = str(parsed.get("chief_complaint") or "").strip()[:260]
    raw_text = str(parsed.get("raw_text") or "").strip()[:1000]
    warnings = _dedupe_str_list(parsed.get("warnings"), max_items=6, max_len=120)
    if not chief and symptoms:
        chief = " ".join(symptoms[:6])
    return {
        "symptoms": symptoms,
        "negations": negations,
        "pulses": pulses,
        "tongues": tongues,
        "abdomen": abdomen,
        "eye": eye,
        "tender": tender,
        "medical_notes": medical_notes,
        "chief_complaint": chief,
        "raw_text": raw_text,
        "warnings": warnings,
        "image_count": image_count,
    }


def build_chat_messages(
    user_query: str,
    packet: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    images: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build bounded conversation history plus fresh grounded context for the latest turn."""
    messages: list[dict[str, Any]] = []
    for item in (history or [])[-8:]:
        role = item.get("role", "")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:2400]})

    grounded_block = format_grounded_context(packet)
    turn_prompt = (
        f"以下是后端中医大脑针对当前问题检索并校验过的实证资料，请以此为据进行回答：\n\n"
        f"{grounded_block}\n\n"
        f"---\n【用户本次提问 / 病情描述】\n{user_query.strip()}"
    )
    user_msg: dict[str, Any] = {"role": "user", "content": turn_prompt}
    norm_imgs = normalize_image_inputs(images)
    if norm_imgs:
        user_msg["images"] = norm_imgs
    messages.append(user_msg)
    return messages
