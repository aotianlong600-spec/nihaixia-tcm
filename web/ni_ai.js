/* 倪师 AI 辩证论治与开方工作台（独立问诊人档案/历史 + 分类四诊采集 + 纯 Python SSE 流式 + 实证侧栏） */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const STORAGE_PATIENT_KEY = "ni_ai_active_patient_id";
  const STORAGE_SESSION_KEY = "ni_ai_active_session_id";
  const STORAGE_MODEL_CACHE_KEY = "ni_ai_cached_models_v1";

  const PRESET_CASES = [
    {
      label: "太阳中风表虚（桂枝汤）",
      query: "鼻鸣干呕 头项强痛",
      symptoms: ["发热", "恶风", "有汗"],
      pulses: ["浮", "缓"],
      tongues: ["舌淡红苔薄白"],
      abdomen: [],
      eye: [],
      tender: [],
      negations: [],
    },
    {
      label: "项背强几几（桂枝加葛根汤）",
      query: "项背强几几",
      symptoms: ["恶风", "有汗", "项背强"],
      pulses: ["浮"],
      tongues: ["舌淡红苔薄白"],
      abdomen: [],
      eye: [],
      tender: [],
      negations: [],
    },
    {
      label: "少阳往来寒热（小柴胡汤）",
      query: "胸胁苦满 默默不欲饮食 心烦喜呕 目眩",
      symptoms: ["往来寒热", "口苦", "咽干"],
      pulses: ["弦"],
      tongues: ["舌淡红苔薄白"],
      abdomen: [],
      eye: [],
      tender: [],
      negations: ["无大便干结"],
    },
    {
      label: "脾胃虚寒胃痛（理中/建中方向）",
      query: "体力差 长期乏力 心下胃痛 空腹痛 消化不良 胃胀气",
      symptoms: ["胃脘胀满", "食欲不振", "身冷"],
      pulses: ["沉", "人迎脉大"],
      tongues: ["舌苔白滑", "唇干"],
      abdomen: ["胸腹动悸"],
      eye: ["肝区白点"],
      tender: ["中枢穴压痛"],
      negations: [],
    },
    {
      label: "少阴里虚寒（四逆/真武方向）",
      query: "但欲寐 小便清长",
      symptoms: ["身冷", "脚冷", "下利清谷"],
      pulses: ["微弱"],
      tongues: ["舌淡胖齿痕"],
      abdomen: ["脐下悸"],
      eye: [],
      tender: ["关元穴压痛"],
      negations: ["无发热"],
    },
    {
      label: "危急重症预警演示",
      query: "胸痛彻背 呼吸困难 大汗淋漓",
      symptoms: ["胸痛", "大汗"],
      pulses: ["沉"],
      tongues: [],
      abdomen: [],
      eye: [],
      tender: [],
      negations: [],
    },
  ];

  const DIMENSION_DEFS = {
    symptoms: {
      groups: [
        { label: "表证寒热", items: ["恶寒", "恶风", "发热", "无汗", "有汗", "项背强", "身痛", "往来寒热"] },
        { label: "胸胁脾胃", items: ["胸胁苦满", "口苦", "咽干", "心烦喜呕", "胃脘胀满", "食欲不振", "大便干", "下利清谷"] },
        { label: "寒热津液与眠溺", items: ["口渴喜冷饮", "口渴不欲饮", "身冷", "脚冷", "失眠", "头晕目眩", "小便不利", "心悸"] },
      ],
    },
    tongue: {
      groups: [
        { label: "舌质与唇象", items: ["舌淡红苔薄白", "舌质红", "舌红少苔", "舌暗有瘀点", "舌淡胖齿痕", "唇干", "唇暗沉"] },
        { label: "舌苔特征", items: ["舌苔白滑", "苔黄腻", "苔黄燥", "苔少或剥"] },
      ],
    },
    pulse: {
      groups: [
        { label: "常见脉象", items: ["浮", "沉", "紧", "缓", "弦", "滑", "数", "迟", "细", "微弱", "结代", "人迎脉大"] },
      ],
    },
    abdomen: {
      groups: [
        { label: "经方腹诊要点", items: ["胸腹动悸", "心下痞硬", "心下急", "少腹急结", "腹满拒按", "腹痛喜按", "腹直肌拘急", "脐下悸"] },
      ],
    },
    eye: {
      groups: [
        { label: "倪师眼诊 · 小儿指诊", items: ["肝区白点", "目赤多眵", "眼睑浮肿", "白睛黄染", "小儿指纹浮红", "小儿指纹紫滞"] },
      ],
    },
    tender: {
      groups: [
        { label: "倪氏临床压痛点（针灸与辨证辅参）", items: ["天枢穴压痛", "中极穴压痛", "关元穴压痛", "胆石点压痛", "肾伤穴压痛", "脾经压痛", "灵台穴压痛", "神道穴压痛", "中枢穴压痛", "大杼穴压痛"] },
      ],
    },
    negations: {
      groups: [
        { label: "明确排空与禁忌确认（大脑自动屏蔽反向加分）", items: ["无发热", "不恶心", "未怀孕", "不在经期", "未做心脏手术", "无大便干结"] },
      ],
    },
  };

  function emptyIntake() {
    return {
      query: "",
      symptoms: [],
      tongues: [],
      pulses: [],
      abdomen: [],
      eye: [],
      tender: [],
      negations: [],
      notes: { present: "", past: "", allergy: "", exam: "" },
    };
  }

  function cloneIntake(raw) {
    const base = emptyIntake();
    if (!raw || typeof raw !== "object") return base;
    for (const k of ["symptoms", "tongues", "pulses", "abdomen", "eye", "tender", "negations"]) {
      if (Array.isArray(raw[k])) {
        base[k] = raw[k].map((v) => String(v || "").trim()).filter(Boolean);
      }
    }
    if (typeof raw.query === "string") base.query = raw.query;
    if (raw.notes && typeof raw.notes === "object") {
      base.notes = {
        present: String(raw.notes.present || ""),
        past: String(raw.notes.past || ""),
        allergy: String(raw.notes.allergy || ""),
        exam: String(raw.notes.exam || ""),
      };
    }
    return base;
  }

  const niState = {
    booted: false,
    config: null,
    style: "master_balanced",
    reasoningEffort: "auto",
    offlineOnly: false,
    activeDim: "symptoms",
    evTab: "rx",
    mobilePane: "consult",
    intakeCollapsed: false,
    historyCollapsed: false,

    patients: [],
    activePatientId: null,
    sessions: [],
    activeSessionId: null,

    intake: emptyIntake(),
    pendingImages: [],
    visionBusy: false,
    visionFeedback: null,
    pinnedEntity: null,
    turns: [],
    latestPacket: null,
    selectedPacketTurnId: null,

    modalDraftNew: false,
    codexPollTimer: null,
    codexPollingPending: false,
    abortController: null,
  };

  const MAX_PENDING_IMAGES = 3;

  function loadModelCacheMap() {
    try {
      const raw = localStorage.getItem(STORAGE_MODEL_CACHE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }

  function getCachedModelsForProfile(profileId, provider) {
    const map = loadModelCacheMap();
    const key = `${profileId || "default"}::${provider || ""}`;
    return Array.isArray(map[key]) ? map[key] : [];
  }

  function saveCachedModelsForProfile(profileId, provider, models) {
    if (!Array.isArray(models) || !models.length) return;
    try {
      const map = loadModelCacheMap();
      const key = `${profileId || "default"}::${provider || ""}`;
      map[key] = Array.from(new Set(models.map((m) => String(m || "").trim()).filter(Boolean))).slice(0, 120);
      localStorage.setItem(STORAGE_MODEL_CACHE_KEY, JSON.stringify(map));
    } catch {
      // ignore storage quota errors
    }
  }

  function evaluateReasoningProfile(provider, protocol, model) {
    const cfg = niState.config || {};
    const rules = Array.isArray(cfg.reasoning_rules) ? cfg.reasoning_rules : [];
    const prov = String(provider || cfg.provider || "").trim().toLowerCase();
    const proto = String(protocol || cfg.protocol || "openai_compat").trim().toLowerCase();
    const mod = String(model || "").trim().toLowerCase();
    for (const rule of rules) {
      if (Array.isArray(rule.protocols) && rule.protocols.length && !rule.protocols.includes(proto)) continue;
      try {
        const exclRx = rule.exclude_regex ? new RegExp(rule.exclude_regex, "i") : null;
        if (exclRx && mod && exclRx.test(mod)) continue;
        const modRx = rule.model_regex ? new RegExp(rule.model_regex, "i") : null;
        const provList = Array.isArray(rule.providers) ? rule.providers : [];
        if (rule.match_either_provider_or_model) {
          if (!(provList.includes(prov) || (modRx && mod && modRx.test(mod)))) continue;
        } else {
          if (provList.length && !provList.includes(prov)) continue;
          if (modRx && !(mod && modRx.test(mod))) continue;
        }
        return {
          id: rule.id,
          efforts: Array.isArray(rule.efforts) && rule.efforts.length ? rule.efforts : ["auto"],
          supports_reasoning: Boolean(rule.supports_reasoning),
          protocol_mode: rule.protocol_mode || "openai_reasoning",
          hint: rule.hint || "",
        };
      } catch {
        continue;
      }
    }
    return cfg.reasoning_profile || {
      id: "generic",
      efforts: ["auto", "none", "minimal", "low", "medium", "high", "xhigh"],
      supports_reasoning: true,
      protocol_mode: "openai_reasoning",
      hint: "选「自动」按模型默认；选具体档位将透传对应思考参数。",
    };
  }

  function getReasoningTierLabel(effortId) {
    const tiers = niState.config?.reasoning_tiers || [];
    const hit = tiers.find((t) => t.id === effortId);
    return hit ? hit.label : effortId;
  }

  function syncReasoningSelect(selectEl, hintEl, provider, protocol, model, desiredValue) {
    const profile = evaluateReasoningProfile(provider, protocol, model);
    const efforts = profile.efforts || ["auto"];
    if (selectEl) {
      selectEl.innerHTML = efforts
        .map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(getReasoningTierLabel(id))}</option>`)
        .join("");
      const nextVal = efforts.includes(desiredValue) ? desiredValue : "auto";
      selectEl.value = nextVal;
      selectEl.disabled = efforts.length <= 1;
    }
    if (hintEl) {
      hintEl.textContent = profile.hint || "";
    }
    return { profile, selected: efforts.includes(desiredValue) ? desiredValue : "auto" };
  }

  function escapeHtml(text) {
    return String(text ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function showNotice(msg) {
    const el = $("#notice");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    window.clearTimeout(el._aiTimer);
    el._aiTimer = window.setTimeout(() => el.classList.add("hidden"), 2800);
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await res.text();
    let body = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = { detail: text };
    }
    if (!res.ok) {
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return body;
  }

  function formatShortTime(isoStr) {
    if (!isoStr) return "";
    const m = String(isoStr).match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
    return m ? `${m[1]} ${m[2]}` : String(isoStr).slice(0, 16);
  }

  function renderInlineMarkdown(escapedLine) {
    let out = escapedLine;
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
    out = out.replace(/\[ref\s*[:：]\s*(\d+)\]/gi, (_, num) => {
      return `<button type="button" class="ai-ref-pill" data-ai-ref="${num}" title="查看第 ${num} 条原书实证">[ref:${num}]</button>`;
    });
    return out;
  }

  function renderMarkdownSafe(rawText) {
    const lines = String(rawText || "").replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let inUl = false;
    let inOl = false;
    let inQuote = false;

    const closeLists = () => {
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
    };
    const closeQuote = () => {
      if (inQuote) {
        html.push("</blockquote>");
        inQuote = false;
      }
    };

    for (const rawLine of lines) {
      const trimmed = rawLine.trim();
      if (!trimmed) {
        closeLists();
        closeQuote();
        continue;
      }
      if (/^---+$/.test(trimmed)) {
        closeLists();
        closeQuote();
        html.push('<hr class="ai-md-hr" />');
        continue;
      }
      const hMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
      if (hMatch) {
        closeLists();
        closeQuote();
        const lvl = Math.min(hMatch[1].length + 1, 5);
        html.push(`<h${lvl} class="ai-md-h">${renderInlineMarkdown(escapeHtml(hMatch[2]))}</h${lvl}>`);
        continue;
      }
      if (trimmed.startsWith(">")) {
        closeLists();
        if (!inQuote) {
          html.push('<blockquote class="ai-md-quote">');
          inQuote = true;
        }
        html.push(`<p>${renderInlineMarkdown(escapeHtml(trimmed.replace(/^>\s?/, "")))}</p>`);
        continue;
      }
      closeQuote();

      const ulMatch = trimmed.match(/^[-*•]\s+(.+)$/);
      if (ulMatch) {
        if (inOl) {
          html.push("</ol>");
          inOl = false;
        }
        if (!inUl) {
          html.push('<ul class="ai-md-list">');
          inUl = true;
        }
        html.push(`<li>${renderInlineMarkdown(escapeHtml(ulMatch[1]))}</li>`);
        continue;
      }

      const olMatch = trimmed.match(/^\d+[.)、]\s*(.+)$/);
      if (olMatch) {
        if (inUl) {
          html.push("</ul>");
          inUl = false;
        }
        if (!inOl) {
          html.push('<ol class="ai-md-list">');
          inOl = true;
        }
        html.push(`<li>${renderInlineMarkdown(escapeHtml(olMatch[1]))}</li>`);
        continue;
      }

      closeLists();
      html.push(`<p>${renderInlineMarkdown(escapeHtml(trimmed))}</p>`);
    }

    closeLists();
    closeQuote();
    return html.join("\n");
  }

  function currentPacket() {
    if (niState.selectedPacketTurnId) {
      const hit = niState.turns.find((t) => t.id === niState.selectedPacketTurnId && t.packet);
      if (hit) return hit.packet;
    }
    for (let i = niState.turns.length - 1; i >= 0; i -= 1) {
      if (niState.turns[i].packet) return niState.turns[i].packet;
    }
    return niState.latestPacket || null;
  }

  function renderHomepageProfileAndModelSelects(cfg) {
    if (!cfg) return;
    const profSel = $("#ai-profile-select");
    const profiles = Array.isArray(cfg.profiles) && cfg.profiles.length
      ? cfg.profiles
      : [cfg];
    if (profSel) {
      profSel.innerHTML = profiles
        .map((p) => {
          const mark = p.ready ? "● " : "○ ";
          const label = `${mark}${p.profile_name || p.model || p.provider}`;
          return `<option value="${escapeHtml(p.profile_id || "default")}">${escapeHtml(label)}</option>`;
        })
        .join("");
      profSel.value = cfg.active_profile_id || cfg.profile_id || profiles[0]?.profile_id || "default";
    }

    const modSel = $("#ai-model-select");
    if (modSel) {
      const preset = (cfg.presets || []).find((p) => p.id === cfg.provider);
      const cached = getCachedModelsForProfile(cfg.active_profile_id || cfg.profile_id, cfg.provider);
      const merged = [];
      for (const m of [cfg.model, ...(preset?.suggested_models || []), ...cached]) {
        const clean = String(m || "").trim();
        if (clean && !merged.includes(clean)) merged.push(clean);
      }
      if (!merged.length) merged.push(cfg.model || "deepseek-chat");
      modSel.innerHTML = merged
        .map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`)
        .join("");
      modSel.value = cfg.model || merged[0];
    }
  }

  function updateStatusHeader() {
    const pill = $("#ai-status-pill");
    const hdrBadge = $("#ai-header-badge");
    const cfg = niState.config;
    if (!cfg) return;

    const preset = (cfg.presets || []).find((p) => p.id === cfg.provider);
    const providerLabel = (preset?.label || cfg.provider || "").split("（")[0];
    let label = "";
    let modeClass = "offline";

    if (niState.offlineOnly) {
      label = "离线直出 · 本地中医大脑";
      modeClass = "offline";
    } else if (cfg.ready) {
      label = `在线推演 · ${providerLabel} (${cfg.model})`;
      modeClass = "ready";
    } else if (cfg.protocol === "codex_oauth" || cfg.provider === "codex") {
      label = "Codex 未登录 · 免 Key 离线就绪（点模型设置登录）";
      modeClass = "offline";
    } else {
      label = "免 Key 离线出方就绪（可点右侧配置大模型）";
      modeClass = "offline";
    }

    if (pill) {
      pill.textContent = label;
      pill.className = `ai-status-pill is-${modeClass}`;
    }
    if (hdrBadge) {
      hdrBadge.textContent = cfg.ready && !niState.offlineOnly ? `AI: ${cfg.model}` : "AI: 离线直出就绪";
    }
    renderHomepageProfileAndModelSelects(cfg);
    const synced = syncReasoningSelect(
      $("#ai-effort-select"),
      null,
      cfg.provider,
      cfg.protocol,
      cfg.model,
      niState.reasoningEffort || cfg.reasoning_effort || "auto"
    );
    niState.reasoningEffort = synced.selected;
    if ($("#ai-effort-select") && (niState.offlineOnly || !synced.profile.supports_reasoning)) {
      $("#ai-effort-select").title = niState.offlineOnly
        ? "离线直出模式下不调用大模型"
        : synced.profile.hint || "当前模型无需调整思考档位";
    }
  }

  function setMobilePane(pane) {
    const next = pane === "evidence" || pane === "history" ? pane : "consult";
    niState.mobilePane = next;
    $("#ai-workspace")?.setAttribute("data-mobile-pane", next);
    document.querySelectorAll("#ai-mobile-pane-tabs .ai-mpane-tab").forEach((btn) => {
      const on = btn.dataset.aiMpane === next;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });
  }

  function updateMobilePaneBadges(packet = null) {
    const pkt = packet || currentPacket();
    const topFormula = pkt?.case_packet?.matched_formulas?.[0]?.name || "";
    const rxBadge = $("#ai-mpane-rx-badge");
    if (rxBadge) {
      rxBadge.textContent = topFormula;
      rxBadge.classList.toggle("hidden", !topFormula);
    }
    const patBadge = $("#ai-mpane-pat-badge");
    if (patBadge) {
      const cnt = (niState.sessions || []).length;
      patBadge.textContent = String(cnt);
    }
  }

  // ── Patient & History Rendering ───────────────────────────────────────
  function renderPatientsAndSessions() {
    updateMobilePaneBadges();
    const activePat = niState.patients.find((p) => p.id === niState.activePatientId) || null;

    const pill = $("#ai-active-patient-pill");
    if (pill) {
      if (activePat) {
        const meta = [activePat.gender, activePat.age].filter(Boolean).join(" · ");
        pill.textContent = `问诊人：${activePat.name}${meta ? `（${meta}）` : ""}`;
      } else {
        pill.textContent = "未选择问诊人（点击新开自动建档）";
      }
    }

    const sesLabel = $("#ai-session-patient-label");
    if (sesLabel) {
      sesLabel.textContent = activePat ? `${activePat.name} · 历史问诊` : "历史问诊";
    }

    const patListEl = $("#ai-patient-list");
    if (patListEl) {
      if (!niState.patients.length) {
        patListEl.innerHTML = '<div class="ai-hist-empty">暂无问诊人，点击上方「+ 添加」新建独立档案。</div>';
      } else {
        patListEl.innerHTML = niState.patients
          .map((p) => {
            const active = p.id === niState.activePatientId;
            const meta = [p.gender, p.age, `${p.session_count || 0}次`].filter(Boolean).join(" · ");
            return `
              <div class="ai-pat-item ${active ? "active" : ""}" data-pat-select="${escapeHtml(p.id)}">
                <div class="ai-pat-main">
                  <strong>${escapeHtml(p.name)}</strong>
                  <small>${escapeHtml(meta)}</small>
                </div>
                <div class="ai-pat-ops">
                  <button type="button" class="ai-icon-btn" data-pat-edit="${escapeHtml(p.id)}" title="编辑档案">✎</button>
                  <button type="button" class="ai-icon-btn is-del" data-pat-del="${escapeHtml(p.id)}" title="删除问诊人及全部历史">×</button>
                </div>
              </div>`;
          })
          .join("");
      }
    }

    const sesListEl = $("#ai-session-list");
    if (sesListEl) {
      if (!niState.activePatientId) {
        sesListEl.innerHTML = '<div class="ai-hist-empty">先添加或选择一位问诊人。</div>';
      } else if (!niState.sessions.length) {
        sesListEl.innerHTML = '<div class="ai-hist-empty">该问诊人暂无历史，点击「+ 新开」开始记录。</div>';
      } else {
        sesListEl.innerHTML = niState.sessions
          .map((s) => {
            const active = s.id === niState.activeSessionId;
            return `
              <div class="ai-ses-item ${active ? "active" : ""}" data-ses-select="${escapeHtml(s.id)}">
                <div class="ai-ses-top">
                  <strong class="ai-ses-title">${escapeHtml(s.title)}</strong>
                  <button type="button" class="ai-icon-btn is-del" data-ses-del="${escapeHtml(s.id)}" title="删除此条问诊记录">×</button>
                </div>
                <div class="ai-ses-meta">
                  ${s.primary_formula ? `<span class="ai-ses-rx">${escapeHtml(s.primary_formula)}</span>` : ""}
                  <span>${escapeHtml(formatShortTime(s.updated_at || s.created_at))}</span>
                  ${s.turn_count ? `<span>${s.turn_count}问</span>` : ""}
                </div>
              </div>`;
          })
          .join("");
      }
    }
  }

  function openPatientForm(editPatient = null) {
    const form = $("#ai-patient-form");
    if (!form) return;
    form.classList.remove("hidden");
    if ($("#ai-pat-id")) $("#ai-pat-id").value = editPatient?.id || "";
    if ($("#ai-pat-name")) $("#ai-pat-name").value = editPatient?.name || "";
    if ($("#ai-pat-gender")) $("#ai-pat-gender").value = editPatient?.gender || "";
    if ($("#ai-pat-age")) $("#ai-pat-age").value = editPatient?.age || "";
    if ($("#ai-pat-notes")) $("#ai-pat-notes").value = editPatient?.notes || "";
    $("#ai-pat-name")?.focus();
  }

  function closePatientForm() {
    const form = $("#ai-patient-form");
    if (!form) return;
    form.classList.add("hidden");
    if ($("#ai-pat-id")) $("#ai-pat-id").value = "";
  }

  function applySessionToWorkspace(ses) {
    niState.activeSessionId = ses?.id || null;
    if (ses?.id) localStorage.setItem(STORAGE_SESSION_KEY, ses.id);
    else localStorage.removeItem(STORAGE_SESSION_KEY);

    niState.intake = cloneIntake(ses?.intake);
    niState.pendingImages = [];
    niState.visionFeedback = null;
    niState.pinnedEntity = ses?.pinned_entity || null;
    niState.turns = Array.isArray(ses?.turns) ? ses.turns : [];
    niState.latestPacket = ses?.latest_packet || null;
    niState.selectedPacketTurnId = null;

    const qInput = $("#ai-query-input");
    if (qInput) {
      qInput.value = !niState.turns.length ? niState.intake.query || "" : "";
    }

    renderPatientsAndSessions();
    renderDimSelector();
    renderSelectedBoard();
    renderPinnedEntity();
    renderVisionStrip();
    renderConversation();
  }

  async function selectPatient(patientId, preferredSessionId = null) {
    niState.activePatientId = patientId;
    if (patientId) localStorage.setItem(STORAGE_PATIENT_KEY, patientId);
    else localStorage.removeItem(STORAGE_PATIENT_KEY);

    if (!patientId) {
      niState.sessions = [];
      applySessionToWorkspace(null);
      return;
    }

    const res = await apiJson(`/api/ai/patients/${encodeURIComponent(patientId)}/sessions`);
    niState.sessions = res.sessions || [];
    const targetId =
      (preferredSessionId && niState.sessions.some((s) => s.id === preferredSessionId) ? preferredSessionId : null) ||
      (niState.sessions[0]?.id || null);

    if (targetId) {
      const detail = await apiJson(`/api/ai/sessions/${encodeURIComponent(targetId)}`);
      applySessionToWorkspace(detail.session);
    } else {
      applySessionToWorkspace(null);
    }
  }

  async function selectSession(sessionId) {
    const detail = await apiJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}`);
    applySessionToWorkspace(detail.session);
  }

  async function createNewSession({ clearPinned = true, intakeOverride = null } = {}) {
    if (niState.abortController) {
      showNotice("当前推演进行中，请先停止再新开问诊");
      return null;
    }

    // Ensure at least one patient exists cleanly
    if (!niState.activePatientId) {
      const created = await apiJson("/api/ai/patients", {
        method: "POST",
        body: JSON.stringify({ name: "默认问诊人" }),
      });
      niState.patients = created.patients || [];
      niState.activePatientId = created.patient.id;
      localStorage.setItem(STORAGE_PATIENT_KEY, niState.activePatientId);
      if (created.initial_session && !intakeOverride) {
        const res = await apiJson(`/api/ai/patients/${encodeURIComponent(niState.activePatientId)}/sessions`);
        niState.sessions = res.sessions || [];
        applySessionToWorkspace(created.initial_session);
        $("#ai-query-input")?.focus();
        return created.initial_session;
      }
    }

    const nextIntake = intakeOverride ? cloneIntake(intakeOverride) : emptyIntake();
    const res = await apiJson(`/api/ai/patients/${encodeURIComponent(niState.activePatientId)}/sessions`, {
      method: "POST",
      body: JSON.stringify({
        title: "新开问诊",
        intake: nextIntake,
        pinned_entity: clearPinned ? null : niState.pinnedEntity,
      }),
    });
    niState.sessions = res.sessions || [];
    // Refresh patient session counts in sidebar
    apiJson("/api/ai/patients")
      .then((pRes) => {
        niState.patients = pRes.patients || niState.patients;
        renderPatientsAndSessions();
      })
      .catch(() => {});

    applySessionToWorkspace(res.session);
    if (window.innerWidth < 1180) setMobilePane("consult");
    $("#ai-query-input")?.focus();
    return res.session;
  }

  async function persistCurrentSession({ updatePinned = true, updatePacket = false } = {}) {
    if (!niState.activeSessionId) return;
    try {
      const res = await apiJson(`/api/ai/sessions/${encodeURIComponent(niState.activeSessionId)}/save`, {
        method: "POST",
        body: JSON.stringify({
          intake: niState.intake,
          pinned_entity: niState.pinnedEntity,
          turns: niState.turns.map((t) => ({
            id: t.id,
            role: t.role,
            query: t.query,
            pulse: t.pulse,
            tongue: t.tongue,
            pinnedEntity: t.pinnedEntity,
            text: t.text,
            reasoning: t.reasoning,
            mode: t.mode,
            provider: t.provider,
            model: t.model,
            cited: t.cited,
            imagesMeta: Array.isArray(t.imagesMeta) ? t.imagesMeta : undefined,
            error: t.error,
          })),
          latest_packet: currentPacket(),
          update_pinned: updatePinned,
          update_packet: updatePacket,
        }),
      });
      niState.sessions = res.sessions || niState.sessions;
      renderPatientsAndSessions();
    } catch {
      // Non-blocking persistence failure never interrupts consultation
    }
  }

  // ── Structured Four-Diagnosis Intake & Collected Board ────────────────
  function renderDimSelector() {
    document.querySelectorAll("#ai-dim-tabs .ai-dim-tab").forEach((btn) => {
      const on = btn.dataset.aiDim === niState.activeDim;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });

    const body = $("#ai-dim-body");
    if (!body) return;
    if (niState.intakeCollapsed) {
      body.classList.add("hidden");
      return;
    }
    body.classList.remove("hidden");

    const dim = niState.activeDim;
    if (dim === "presets") {
      body.innerHTML = `<div class="ai-preset-grid">
        ${PRESET_CASES.map(
          (c, idx) => `<button type="button" class="ai-preset-btn" data-ai-preset="${idx}">
            <strong>${escapeHtml(c.label)}</strong>
            <small>${escapeHtml([...c.symptoms, c.query, c.pulses.length ? `脉${c.pulses.join("")}` : ""].filter(Boolean).join(" · "))}</small>
          </button>`
        ).join("")}
      </div>`;
      return;
    }

    if (dim === "notes") {
      const n = niState.intake.notes || {};
      const activePat = niState.patients.find((p) => p.id === niState.activePatientId);
      const patHint = activePat?.notes ? `问诊人档案备注：${activePat.notes}` : "";
      body.innerHTML = `
        <div class="ai-notes-grid">
          <label><span>现病史（起病时间、诱因、规律）</span><input type="text" data-ai-note="present" value="${escapeHtml(n.present || "")}" placeholder="如：受凉三天，午后寒热加重" /></label>
          <label><span>既往史与西药史（降压/降糖/抗凝等）</span><input type="text" data-ai-note="past" value="${escapeHtml(n.past || "")}" placeholder="如：高血压服氨氯地平，胃病多年" /></label>
          <label><span>过敏 / 经期妊娠说明</span><input type="text" data-ai-note="allergy" value="${escapeHtml(n.allergy || "")}" placeholder="如：未怀孕，不在经期，无药物过敏" /></label>
          <label><span>辅助检查与睡眠二便</span><input type="text" data-ai-note="exam" value="${escapeHtml(n.exam || "")}" placeholder="如：大便两日一行，小便黄，夜醒一次" /></label>
        </div>
        ${patHint ? `<div class="ai-pat-note-hint">${escapeHtml(patHint)}</div>` : ""}`;
      return;
    }

    const spec = DIMENSION_DEFS[dim];
    if (!spec) return;
    const fieldName = dim === "tongue" ? "tongues" : dim === "pulse" ? "pulses" : dim;
    const selected = niState.intake[fieldName] || [];
    body.innerHTML = spec.groups
      .map(
        (grp) => `
        <div class="ai-dim-group">
          <span class="ai-dim-group-label">${escapeHtml(grp.label)}</span>
          <div class="ai-chip-row">
            ${grp.items
              .map((val) => {
                const on = selected.includes(val);
                return `<button type="button" class="ai-chip ${on ? "active" : ""}" data-ai-toggle-cat="${escapeHtml(fieldName)}" data-ai-toggle-val="${escapeHtml(val)}">${escapeHtml(val)}</button>`;
              })
              .join("")}
          </div>
        </div>`
      )
      .join("");
  }

  function renderSelectedBoard() {
    const board = $("#ai-selected-board");
    if (!board) return;
    const rows = [
      { key: "symptoms", label: "症候", cls: "" },
      { key: "tongues", label: "舌诊", cls: "" },
      { key: "pulses", label: "脉诊", cls: "is-pulse" },
      { key: "abdomen", label: "腹诊", cls: "" },
      { key: "eye", label: "眼·指", cls: "" },
      { key: "tender", label: "压痛点", cls: "is-tender" },
      { key: "negations", label: "排空否定", cls: "is-neg" },
    ];
    const htmlRows = [];
    for (const row of rows) {
      const arr = niState.intake[row.key] || [];
      if (!arr.length) continue;
      htmlRows.push(`
        <div class="ai-sel-row">
          <span class="ai-sel-label">${row.label}</span>
          <div class="ai-sel-tags">
            ${arr
              .map(
                (v) =>
                  `<button type="button" class="ai-sel-pill ${row.cls}" data-ai-remove-cat="${row.key}" data-ai-remove-val="${escapeHtml(v)}">${escapeHtml(v)} <em>×</em></button>`
              )
              .join("")}
          </div>
        </div>`);
    }

    const n = niState.intake.notes || {};
    const noteItems = [n.present, n.past, n.allergy, n.exam].filter((x) => x && x.trim());
    if (noteItems.length) {
      htmlRows.push(`
        <div class="ai-sel-row">
          <span class="ai-sel-label">病历</span>
          <div class="ai-sel-tags"><span class="ai-sel-pill is-note">${escapeHtml(noteItems.join("；").slice(0, 90))}</span></div>
        </div>`);
    }

    if (!htmlRows.length) {
      board.innerHTML = '<div class="ai-sel-empty">可从上方「常见症状 / 舌诊 / 脉诊 / 腹诊 / 压痛点」点选四诊，或直接在下方输入症状。</div>';
    } else {
      board.innerHTML = htmlRows.join("");
    }
  }

  function renderPinnedEntity() {
    const box = $("#ai-pinned-box");
    if (!box) return;
    if (!niState.pinnedEntity) {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }
    const ent = niState.pinnedEntity;
    box.classList.remove("hidden");
    box.innerHTML = `
      <div class="ai-pinned-head">
        <span>已锁定精讲对象 · ${escapeHtml(ent.label || ent.kind)}</span>
        <button type="button" class="ai-link-btn" id="ai-unpin-btn">取消锁定 ×</button>
      </div>
      <strong>${escapeHtml(ent.name || ent.id || "当前条目")}</strong>
    `;
  }

  function renderSafetyBanner(packet) {
    const box = $("#ai-safety-banner");
    if (!box) return;
    const sb = packet?.safety_boundary;
    if (!sb || !sb.triggered) {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }
    const isEmergency = sb.mode === "emergency_triage" || sb.risk_level === "emergency";
    box.className = `ai-safety-banner ${isEmergency ? "is-emergency" : "is-caution"}`;
    box.innerHTML = `
      <strong>⚠️ ${escapeHtml(sb.title || "安全预警")}</strong>
      <p>${escapeHtml(sb.message || "")}</p>
    `;
  }

  // ── Evidence Right Sidebar (Tabbed: 主力方 / 配穴·汉唐 / 原典 [ref]) ──
  function renderEvidenceSidebar(packet) {
    updateMobilePaneBadges(packet);
    document.querySelectorAll("#ai-ev-tabs .ai-ev-tab").forEach((btn) => {
      const on = btn.dataset.aiEvTab === niState.evTab;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });

    const host = $("#ai-evidence-body");
    if (!host) return;
    renderSafetyBanner(packet);

    if (!packet) {
      host.innerHTML = `
        <div class="ai-ev-empty">
          <h3>中医大脑实证处方侧栏</h3>
          <p>提交症状后，将在此分三大页签实时展示：</p>
          <ul>
            <li><strong>主力方 · 合方</strong>：主方原典组成/剂量、煎服法、十八反拦截、排除误治方</li>
            <li><strong>配穴 · 汉唐</strong>：人纪针灸取穴（点击跳定位）、汉唐百方与督脉压痛提示</li>
            <li><strong>原典 [ref]</strong>：优先置顶《人纪》《伤寒》《金匮》《汉唐》，点击可对照原页</li>
          </ul>
        </div>`;
      return;
    }

    const cp = packet.case_packet || {};
    const formulas = cp.matched_formulas || [];
    const suppressed = cp.suppressed_formulas || [];
    const compounds = cp.compound_regimens || [];
    const acups = cp.matched_acupoints || [];
    const negations = cp.recognized_negations || [];
    const dSafety = cp.decoction_and_safety || [];
    const hantang = packet.hantang_clues || {};
    const htFormulas = hantang.hantang_formulas || [];
    const westernGuides = hantang.western_history_guidance || [];
    const duGuides = hantang.du_spine_guides || [];
    const citations = packet.citations || [];
    const syms = cp.extracted_symptoms || [];
    const diffs = cp.differential_points || [];

    if (niState.evTab === "acup") {
      const acupHtml = acups.length
        ? `<div class="ai-ev-section">
            <div class="ai-ev-title">人纪针灸配穴（点击看定位与补泻）</div>
            <div class="ai-acup-grid">
              ${acups
                .map(
                  (pt) => `
                  <button type="button" class="ai-acup-btn" data-ai-jump-kind="acupuncture" data-ai-jump-id="${encodeURIComponent(pt.id || "")}">
                    <strong>${escapeHtml(pt.name)}</strong>
                    <span>${escapeHtml(pt.role || "")}</span>
                    ${pt.reason ? `<small>${escapeHtml(pt.reason.slice(0, 48))}</small>` : ""}
                  </button>`
                )
                .join("")}
            </div>
          </div>`
        : '<div class="ai-ev-card"><p class="ai-ev-copy">当前输入暂未匹配专项配穴。</p></div>';

      const hantangHtml =
        htFormulas.length || duGuides.length || westernGuides.length
          ? `<div class="ai-ev-section">
              <div class="ai-ev-title">汉唐百方 · 督脉与西医史提示</div>
              <div class="ai-ev-card">
                ${htFormulas
                  .slice(0, 4)
                  .map(
                    (hf) => `
                    <div class="ai-ht-row">
                      <strong>${escapeHtml(hf.ht_number)} ${escapeHtml(hf.name)}</strong>
                      <p>${escapeHtml((hf.match_reasons || []).join("；") || hf.indications || "")}</p>
                    </div>`
                  )
                  .join("")}
                ${duGuides.slice(0, 3).map((d) => `<div class="ai-ev-note"><b>督脉诊察：</b>${escapeHtml(d.point || d.location || "")} — ${escapeHtml(d.meaning || d.clinical_sign || "")}</div>`).join("")}
                ${westernGuides.slice(0, 3).map((w) => `<div class="ai-ev-note"><b>西医介入史提示：</b>${escapeHtml(w.scenario || w.title || "")} — ${escapeHtml(w.guidance || w.summary || "")}</div>`).join("")}
              </div>
            </div>`
          : "";

      host.innerHTML = `${acupHtml}${hantangHtml}`;
      return;
    }

    if (niState.evTab === "refs") {
      host.innerHTML = citations.length
        ? `<div class="ai-ev-section">
            <div class="ai-ev-title">可核查经典依据（共 ${citations.length} 条，人纪/原典优先）</div>
            <div class="ai-ref-list">
              ${citations
                .map(
                  (cit) => `
                  <article class="ai-ref-card" data-ai-cit-id="${cit.ref_id}">
                    <div class="ai-ref-top">
                      <span class="ai-ref-idx">[ref:${cit.ref_id}]</span>
                      <strong>${escapeHtml(cit.book_title)}</strong>
                      <span>${escapeHtml(cit.unit_label || "")}</span>
                      <button type="button" class="ai-mini-btn" data-ai-open-cit="${cit.ref_id}">翻原页 ↗</button>
                    </div>
                    <p>${escapeHtml(String(cit.quote || "").slice(0, 170))}${String(cit.quote || "").length > 170 ? "…" : ""}</p>
                  </article>`
                )
                .join("")}
            </div>
          </div>`
        : '<div class="ai-ev-card"><p class="ai-ev-copy">当前查询暂无直接页码原文命中，请补充核心症状或方名再试。</p></div>';
      return;
    }

    // Default tab: "rx" (主力方 · 合方)
    const rxCardsHtml = formulas.length
      ? formulas
          .slice(0, 3)
          .map((f, idx) => {
            const ings = f.ingredients || [];
            const ingGrid = ings.length
              ? `<div class="ai-rx-ing-list">${ings
                  .map(
                    (ing) =>
                      `<span class="ai-ing-pill ${ing.risk_level === "high_risk" || ing.risk_level === "emergency" ? "is-risk" : ""}">${escapeHtml(ing.name)} <em>${escapeHtml(ing.dose || "")}${ing.processing ? `·${escapeHtml(ing.processing)}` : ""}</em></span>`
                  )
                  .join("")}</div>`
              : f.herbs?.length
              ? `<p class="ai-ev-copy">参考药味：${escapeHtml(f.herbs.join("、"))}</p>`
              : "";

            return `
              <article class="ai-rx-card ${idx === 0 ? "is-lead" : ""}">
                <div class="ai-rx-head">
                  <div>
                    <div class="ai-rx-badge-row">
                      <span class="ai-rx-badge ${idx === 0 ? "" : "is-alt"}">${idx === 0 ? "主力首选" : "备选相参"}</span>
                      ${f.match_pct ? `<span class="ai-rx-fit">实证匹配 ${f.match_pct}%</span>` : ""}
                      ${f.herb_count ? `<span class="ai-rx-fit">${f.herb_count} 味</span>` : ""}
                    </div>
                    <h4>${escapeHtml(f.name)}</h4>
                    <small>${escapeHtml(f.book || "经方典籍")} · ${escapeHtml(f.six_meridian || "")}</small>
                  </div>
                  ${
                    f.formula_id
                      ? `<button type="button" class="ai-mini-btn" data-ai-jump-kind="formulas" data-ai-jump-id="${encodeURIComponent(f.formula_id)}">详考 ↗</button>`
                      : ""
                  }
                </div>
                ${f.pathogenesis ? `<p class="ai-ev-copy"><strong>病机</strong>：${escapeHtml(f.pathogenesis)}</p>` : ""}
                ${f.composition_raw ? `<div class="ai-rx-raw"><strong>原方</strong>：${escapeHtml(f.composition_raw)}</div>` : ""}
                ${ingGrid}
                ${f.usage_plain ? `<div class="ai-rx-usage"><strong>煎服法</strong>：${escapeHtml(f.usage_plain)}</div>` : ""}
                ${
                  f.high_risk_herbs?.length
                    ? `<div class="ai-rx-warn">炮制红线：含 ${escapeHtml(f.high_risk_herbs.join("、"))}，须严守先煎/炮制并由医师核量。</div>`
                    : ""
                }
              </article>`;
          })
          .join("")
      : `<div class="ai-ev-card"><p class="ai-ev-copy">当前输入症状尚不足以锁定单一主方，可补充寒热、汗出、二便、舌脉线索。</p></div>`;

    const compoundHtml = compounds.length
      ? `<div class="ai-ev-section">
          <div class="ai-ev-title">合方协同与煎药安全（${compounds.length}）</div>
          ${compounds
            .slice(0, 2)
            .map(
              (reg) => `
              <div class="ai-ev-card">
                <strong>${escapeHtml(reg.title || "合方方案")}</strong>
                ${reg.overlap_note ? `<p class="ai-ev-copy">${escapeHtml(reg.overlap_note)}</p>` : ""}
                ${
                  (reg.formulas_detail || []).length
                    ? `<div class="ai-rx-sublist">${reg.formulas_detail
                        .map((sf) => `<div>· <b>${escapeHtml(sf.name)}</b>：${escapeHtml(sf.composition_raw || (sf.herbs || []).join("、"))}</div>`)
                        .join("")}</div>`
                    : ""
                }
              </div>`
            )
            .join("")}
          ${dSafety.length ? `<div class="ai-ev-card">${dSafety.slice(0, 3).map((line) => `<div class="ai-ev-note">${escapeHtml(line)}</div>`).join("")}</div>` : ""}
        </div>`
      : dSafety.length
      ? `<div class="ai-ev-section"><div class="ai-ev-title">煎煮与十八反/十九畏核查</div><div class="ai-ev-card">${dSafety.slice(0, 3).map((line) => `<div class="ai-ev-note">${escapeHtml(line)}</div>`).join("")}</div></div>`
      : "";

    const suppressedHtml = suppressed.length
      ? `<div class="ai-ev-section">
          <div class="ai-ev-title">已排除相反误方（防误汗误下）</div>
          <div class="ai-ev-card">
            ${suppressed
              .map((s) => `<div class="ai-supp-row"><s>${escapeHtml(s.name)}</s><span>${escapeHtml((s.reasons || []).join("；"))}</span></div>`)
              .join("")}
          </div>
        </div>`
      : "";

    host.innerHTML = `
      ${
        syms.length || negations.length || cp.primary_six_channel
          ? `<div class="ai-ev-summary">
              ${cp.primary_six_channel ? `<span class="ai-ev-tag is-primary">${escapeHtml(cp.primary_six_channel)}</span>` : ""}
              ${syms.map((s) => `<span class="ai-ev-tag">${escapeHtml(s)}</span>`).join("")}
              ${negations.map((n) => `<span class="ai-ev-tag is-neg">已排除：${escapeHtml(n)}</span>`).join("")}
            </div>`
          : ""
      }
      <div class="ai-ev-section">
        <div class="ai-ev-title">辨证处方（经典原方原量）</div>
        ${rxCardsHtml}
      </div>
      ${compoundHtml}
      ${
        diffs.length
          ? `<div class="ai-ev-section"><div class="ai-ev-title">临床鉴别要点</div><div class="ai-ev-card"><ul class="ai-diff-ul">${diffs
              .slice(0, 4)
              .map((d) => `<li>${escapeHtml(d)}</li>`)
              .join("")}</ul></div></div>`
          : ""
      }
      ${suppressedHtml}
    `;
  }

  function renderConversation() {
    const host = $("#ai-chat-thread");
    if (!host) return;

    if (!niState.turns.length) {
      const activePat = niState.patients.find((p) => p.id === niState.activePatientId);
      const patName = activePat ? activePat.name : "当前问诊人";
      host.innerHTML = `
        <div class="ai-welcome">
          <div class="ai-welcome-mark">倪</div>
          <h2>${escapeHtml(patName)} · 倪师辩证开方诊室</h2>
          <p>上方按维度点选<strong>症状、舌诊、脉诊、腹诊、眼诊、倪师压痛点</strong>或直接描述主诉，系统即刻结合 5 阶段辨证引擎与 17 册原典书库开出经方/合方。</p>
          <div class="ai-welcome-tips">
            <span>每位问诊人拥有独立历史档；左侧点「+ 新开」开启新病案，点「×」删除单条或整人档案；免 Key 亦可离线直出经方。</span>
          </div>
        </div>`;
      renderEvidenceSidebar(currentPacket());
      return;
    }

    host.innerHTML = niState.turns
      .map((t) => {
        if (t.role === "user") {
          const metaBits = [
            t.pulse ? `脉：${t.pulse}` : "",
            t.tongue ? `舌：${t.tongue}` : "",
            t.pinnedEntity ? `精讲：${t.pinnedEntity.name}` : "",
            Array.isArray(t.imagesMeta) && t.imagesMeta.length ? `附图：${t.imagesMeta.map((x) => x.name).join("、")}` : "",
          ].filter(Boolean);
          return `
            <article class="ai-turn is-user" data-turn-id="${escapeHtml(t.id)}">
              <div class="ai-turn-badge">主诉与四诊</div>
              <div class="ai-turn-user-text">${escapeHtml(t.query)}</div>
              ${metaBits.length ? `<div class="ai-turn-meta">${metaBits.map((b) => `<span>${escapeHtml(b)}</span>`).join("")}</div>` : ""}
            </article>`;
        }

        const modeText =
          t.mode === "offline" || t.mode === "offline_fallback"
            ? "离线中医大脑实证直出"
            : `倪师角色 · ${t.provider || "LLM"}${t.model ? ` (${t.model})` : ""}`;
        const reasoningHtml = t.reasoning
          ? `<details class="ai-reasoning" ${t.streaming && !t.text ? "open" : ""}>
              <summary>推演思考过程（${t.streaming && !t.text ? "思考中..." : "点击展开/收起"}）</summary>
              <div class="ai-reasoning-body">${escapeHtml(t.reasoning)}</div>
            </details>`
          : "";
        const bodyHtml = t.text
          ? renderMarkdownSafe(t.text)
          : t.streaming
          ? '<div class="ai-typing">正在查阅经方与十七册藏书实证并生成处方...</div>'
          : "";
        const errHtml = t.error ? `<div class="ai-turn-warn">大模型调用提示：${escapeHtml(t.error)}（已自动切换离线实证直出保障不断流）</div>` : "";
        const followupsHtml =
          !t.streaming && t.text
            ? `<div class="ai-followup-row">
                <button type="button" class="ai-followup-btn" data-ai-followup="请具体说明这付方的加减化裁和喝完后怎么判断药效好转（问睡眠胃口手脚温凉大便）？">问加减与服后反应</button>
                <button type="button" class="ai-followup-btn" data-ai-followup="如果病人平时在吃降压药、降糖药或阿司匹林等西药，这首方要注意什么禁忌？">问西药史与禁忌</button>
                <button type="button" class="ai-followup-btn" data-ai-followup="配合这首方，人纪针灸具体怎么下针、下哪些穴位、补泻手法如何？">问详细针灸手法</button>
                ${
                  t.packet
                    ? `<button type="button" class="ai-followup-btn is-packet" data-ai-select-packet="${escapeHtml(t.id)}">定位本轮实证包</button>`
                    : ""
                }
                <button type="button" class="ai-followup-btn ai-mobile-only-btn" data-ai-open-evidence="rx">查看处方笺与依据 →</button>
              </div>`
            : "";

        return `
          <article class="ai-turn is-assistant ${t.streaming ? "is-streaming" : ""}" data-turn-id="${escapeHtml(t.id)}">
            <div class="ai-turn-head">
              <span class="ai-master-tag">倪师辨证开方</span>
              <span class="ai-mode-tag">${escapeHtml(modeText)}</span>
            </div>
            ${errHtml}
            ${reasoningHtml}
            <div class="ai-turn-body">${bodyHtml}</div>
            ${followupsHtml}
          </article>`;
      })
      .join("");

    const scroller = $("#ai-chat-scroll");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
    renderEvidenceSidebar(currentPacket());
  }

  function buildCompositeQuery(typedText) {
    const k = niState.intake;
    const parts = [];
    if (k.symptoms.length) parts.push(k.symptoms.join(" "));
    if (k.abdomen.length) parts.push(`腹诊：${k.abdomen.join(" ")}`);
    if (k.eye.length) parts.push(`眼/指诊：${k.eye.join(" ")}`);
    if (k.tender.length) parts.push(`压痛点：${k.tender.join(" ")}`);
    if (k.negations.length) parts.push(k.negations.join(" "));
    const n = k.notes || {};
    const nBits = [
      n.present ? `现病史:${n.present}` : "",
      n.past ? `既往史:${n.past}` : "",
      n.allergy ? `过敏/孕经:${n.allergy}` : "",
      n.exam ? `检查/二便:${n.exam}` : "",
    ].filter(Boolean);
    if (nBits.length) parts.push(nBits.join("；"));
    if (typedText) parts.push(typedText);
    return parts.join(" ").trim();
  }

  function buildHistoryPayload() {
    const slice = [];
    for (const t of niState.turns) {
      if (t.role === "user") {
        slice.push({ role: "user", content: t.query });
      } else if (t.role === "assistant" && !t.streaming && t.text) {
        slice.push({ role: "assistant", content: t.text });
      }
    }
    return slice.slice(-10);
  }

  function updateStreamingControls(isStreaming) {
    const sendBtn = $("#ai-submit-btn");
    const stopBtn = $("#ai-stop-btn");
    if (sendBtn) {
      sendBtn.disabled = isStreaming;
      sendBtn.textContent = isStreaming ? "正在辩证开方..." : "倪师辩证出方";
    }
    if (stopBtn) {
      stopBtn.classList.toggle("hidden", !isStreaming);
    }
  }

  function parseSseFrames(chunkText, stateObj, onEvent) {
    stateObj.buf += chunkText.replace(/\r\n/g, "\n");
    const parts = stateObj.buf.split("\n\n");
    stateObj.buf = parts.pop() || "";
    for (const block of parts) {
      if (!block.trim()) continue;
      let evName = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          evName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!dataLines.length) continue;
      try {
        onEvent(evName, JSON.parse(dataLines.join("\n")));
      } catch {
        // Ignore partial chunk gracefully
      }
    }
  }

  function renderVisionStrip() {
    const listEl = $("#ai-image-preview-list");
    const extractBtn = $("#ai-ocr-extract-btn");
    const clearBtn = $("#ai-vision-clear-btn");
    const hintEl = $("#ai-vision-hint");
    const fbEl = $("#ai-vision-feedback");
    const imgs = niState.pendingImages || [];

    if (listEl) {
      if (!imgs.length) {
        listEl.classList.add("hidden");
        listEl.innerHTML = "";
      } else {
        listEl.classList.remove("hidden");
        listEl.innerHTML = imgs
          .map(
            (img) => `
            <div class="ai-img-thumb">
              <img src="${escapeHtml(img.data_url)}" alt="${escapeHtml(img.name)}" />
              <div class="ai-img-thumb-meta">
                <span>${escapeHtml(img.name)}</span>
                <small>${img.sizeKb} KB</small>
              </div>
              <button type="button" class="ai-img-rm" data-ai-rm-img="${escapeHtml(img.id)}" title="移除此图片">×</button>
            </div>`
          )
          .join("");
      }
    }
    if (extractBtn) {
      extractBtn.classList.toggle("hidden", !imgs.length);
      extractBtn.disabled = niState.visionBusy;
      extractBtn.textContent = niState.visionBusy ? "正在识图读取四诊..." : "✨ 识图填入四诊";
    }
    if (clearBtn) {
      clearBtn.classList.toggle("hidden", !imgs.length);
      clearBtn.disabled = niState.visionBusy;
    }
    if (hintEl) {
      hintEl.classList.toggle("hidden", imgs.length > 0);
    }
    if (fbEl) {
      if (!niState.visionFeedback) {
        fbEl.classList.add("hidden");
        fbEl.innerHTML = "";
      } else {
        fbEl.className = `ai-vision-feedback ${niState.visionFeedback.kind === "err" ? "is-err" : "is-ok"}`;
        fbEl.textContent = niState.visionFeedback.text;
      }
    }
  }

  async function compressImageFile(file) {
    if (!file || !String(file.type || "").startsWith("image/")) {
      throw new Error("请选择 JPG / PNG / WebP / GIF 格式的图片");
    }
    if (file.size > 20 * 1024 * 1024) {
      throw new Error(`图片「${file.name || "未命名"}」超过 20MB，请裁剪后再上传`);
    }
    const rawDataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("读取图片失败"));
      reader.readAsDataURL(file);
    });
    const imgObj = await new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = () => reject(new Error("图片解码失败，请更换常用 JPG / PNG 图片"));
      im.src = rawDataUrl;
    });
    const w = imgObj.naturalWidth || imgObj.width || 1;
    const h = imgObj.naturalHeight || imgObj.height || 1;
    const maxSide = 1400;
    const scale = Math.min(1, maxSide / Math.max(w, h));
    const dstW = Math.max(1, Math.round(w * scale));
    const dstH = Math.max(1, Math.round(h * scale));

    const canvas = document.createElement("canvas");
    canvas.width = dstW;
    canvas.height = dstH;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("浏览器画布压缩初始化失败");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, dstW, dstH);
    ctx.drawImage(imgObj, 0, 0, dstW, dstH);

    let mimeType = "image/jpeg";
    let dataUrl = canvas.toDataURL("image/jpeg", 0.84);
    if (file.type === "image/png" && rawDataUrl.length < 480 * 1024 && scale === 1) {
      mimeType = "image/png";
      dataUrl = rawDataUrl;
    }
    const approxBytes = Math.round((dataUrl.length * 3) / 4);
    return {
      id: `img-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: String(file.name || "粘贴图片").slice(0, 48),
      mime_type: mimeType,
      data_url: dataUrl,
      sizeKb: Math.max(1, Math.round(approxBytes / 1024)),
    };
  }

  async function addImageFiles(files) {
    if (!files.length) return;
    niState.visionFeedback = null;
    for (const file of files) {
      if ((niState.pendingImages || []).length >= MAX_PENDING_IMAGES) {
        showNotice(`每次最多附带 ${MAX_PENDING_IMAGES} 张图片`);
        break;
      }
      try {
        const compressed = await compressImageFile(file);
        niState.pendingImages.push(compressed);
      } catch (err) {
        niState.visionFeedback = { kind: "err", text: err.message || "图片处理失败" };
      }
    }
    renderVisionStrip();
  }

  function mergeExtractedIntake(extracted) {
    if (!extracted || typeof extracted !== "object") return 0;
    let addedCount = 0;
    const catKeys = ["symptoms", "negations", "pulses", "tongues", "abdomen", "eye", "tender"];
    for (const cat of catKeys) {
      const targetArr = niState.intake[cat];
      const incoming = Array.isArray(extracted[cat]) ? extracted[cat] : [];
      for (const rawItem of incoming) {
        const val = String(rawItem || "").trim();
        if (val && !targetArr.includes(val)) {
          targetArr.push(val);
          addedCount += 1;
        }
      }
    }
    const mNotes = extracted.medical_notes || {};
    for (const k of ["present", "past", "allergy", "exam"]) {
      const incoming = String(mNotes[k] || "").trim();
      if (!incoming) continue;
      const cur = String(niState.intake.notes[k] || "").trim();
      if (!cur) {
        niState.intake.notes[k] = incoming;
        addedCount += 1;
      } else if (!cur.includes(incoming)) {
        niState.intake.notes[k] = `${cur}；${incoming}`.slice(0, 260);
        addedCount += 1;
      }
    }
    const queryEl = $("#ai-query-input");
    const chief = String(extracted.chief_complaint || "").trim();
    if (queryEl && chief) {
      const curQ = queryEl.value.trim();
      if (!curQ) queryEl.value = chief;
      else if (!curQ.includes(chief)) queryEl.value = `${curQ} ${chief}`;
      niState.intake.query = queryEl.value.trim();
    }
    return addedCount;
  }

  async function extractIntakeFromImages() {
    if (niState.visionBusy) return;
    if (!niState.pendingImages.length) {
      showNotice("请先上传或粘贴病例/问诊表图片");
      return;
    }
    if (niState.offlineOnly || !niState.config?.ready) {
      niState.visionFeedback = {
        kind: "err",
        text: "识图填入四诊需要开启在线多模态模型（请关闭「离线直出」并在模型设置中选用支持看图的模型，如 GPT-4o / Gemini / Claude / Qwen-VL / DeepSeek 多模态版）。",
      };
      renderVisionStrip();
      return;
    }
    niState.visionBusy = true;
    niState.visionFeedback = null;
    renderVisionStrip();
    try {
      const res = await apiJson("/api/ai/vision-intake", {
        method: "POST",
        body: JSON.stringify({
          images: niState.pendingImages.map((img) => ({ name: img.name, data_url: img.data_url })),
          hint: $("#ai-query-input")?.value?.trim() || "",
        }),
      });
      const added = mergeExtractedIntake(res);
      renderDimSelector();
      renderSelectedBoard();
      const warnText = Array.isArray(res.warnings) && res.warnings.length ? ` 提示：${res.warnings.join("；")}` : "";
      const summaryPreview = res.chief_complaint || res.raw_text || "已完成图像读取";
      niState.visionFeedback = {
        kind: "ok",
        text: `已识图写入 ${added} 项四诊信息（模型：${res.model || niState.config?.model || ""}）。摘要：${String(summaryPreview).slice(0, 90)}。请核对上方四诊标签后点击「倪师辩证出方」。${warnText}`,
      };
      showNotice(`识图完成：已写入 ${added} 项四诊与主诉`);
    } catch (err) {
      niState.visionFeedback = { kind: "err", text: err.message || "识图失败，请核对模型是否支持视觉输入" };
    } finally {
      niState.visionBusy = false;
      renderVisionStrip();
    }
  }

  async function submitConsultation(customQuery = null) {
    if (niState.abortController) {
      showNotice("当前推演正在进行中，可点击停止后再发下一问");
      return;
    }

    const inputEl = $("#ai-query-input");
    const typedText = String(customQuery !== null ? customQuery : inputEl?.value || "").trim();
    if (customQuery === null) {
      niState.intake.query = typedText;
    }

    const attachedImgs = customQuery === null ? [...(niState.pendingImages || [])] : [];
    const isFollowUp = customQuery !== null || (niState.turns.length > 0 && Boolean(typedText));
    let query = isFollowUp ? typedText : buildCompositeQuery(typedText);
    if (!query && attachedImgs.length) {
      query = "请识读所附病例/问诊表图片中的四诊信息，并给出倪师经方辨证与参考处方。";
    }

    if (!query) {
      showNotice("请点选上方四诊标签、上传病历图片或输入症状主诉");
      inputEl?.focus();
      return;
    }

    // Ensure patient & active session exist in SQLite before first turn
    if (!niState.activePatientId || !niState.activeSessionId) {
      try {
        await createNewSession({ clearPinned: false, intakeOverride: niState.intake });
      } catch (err) {
        showNotice(err?.message || "创建问诊会话失败");
        return;
      }
    }

    const pulse = niState.intake.pulses.join(" ");
    const tongue = niState.intake.tongues.join(" ");
    const pinned = niState.pinnedEntity ? { ...niState.pinnedEntity } : null;
    const history = buildHistoryPayload();

    const userTurn = {
      id: `u-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      role: "user",
      query,
      pulse,
      tongue,
      pinnedEntity: pinned,
      imagesMeta: attachedImgs.length ? attachedImgs.map((x) => ({ name: x.name })) : undefined,
    };
    const asstTurn = {
      id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      role: "assistant",
      text: "",
      reasoning: "",
      packet: null,
      mode: niState.offlineOnly || !niState.config?.ready ? "offline" : "live",
      provider: niState.config?.provider || "",
      model: niState.config?.model || "",
      cited: null,
      error: "",
      streaming: true,
    };

    niState.turns.push(userTurn, asstTurn);
    niState.selectedPacketTurnId = asstTurn.id;
    if (customQuery === null && inputEl) {
      inputEl.value = "";
    }
    if (attachedImgs.length) {
      niState.pendingImages = [];
      niState.visionFeedback = null;
      renderVisionStrip();
    }

    renderConversation();
    const ac = new AbortController();
    niState.abortController = ac;
    updateStreamingControls(true);

    try {
      const res = await fetch("/api/ai/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ac.signal,
        body: JSON.stringify({
          query,
          pulse,
          tongue,
          style: niState.style,
          reasoning_effort: niState.reasoningEffort,
          offline: niState.offlineOnly,
          history,
          images: attachedImgs.map((x) => ({ name: x.name, data_url: x.data_url })),
          entity_focus: pinned
            ? {
                kind: pinned.kind,
                id: pinned.id || "",
                book_id: pinned.book_id || "",
                page_no: pinned.page_no || 0,
              }
            : null,
        }),
      });

      if (!res.ok) {
        throw new Error((await res.text()) || `HTTP ${res.status}`);
      }
      if (!res.body) {
        throw new Error("浏览器未返回可读流响应");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      const sseBuf = { buf: "" };
      let renderScheduled = false;
      const scheduleRender = () => {
        if (renderScheduled) return;
        renderScheduled = true;
        window.requestAnimationFrame(() => {
          renderScheduled = false;
          renderConversation();
        });
      };

      const handleEvent = (evName, data) => {
        if (evName === "context") {
          asstTurn.mode = data.mode || asstTurn.mode;
          asstTurn.provider = data.provider || asstTurn.provider;
          asstTurn.model = data.model || asstTurn.model;
          asstTurn.packet = data.packet || null;
          niState.latestPacket = asstTurn.packet;
          renderConversation();
        } else if (evName === "reasoning") {
          asstTurn.reasoning += data.text || "";
          scheduleRender();
        } else if (evName === "delta") {
          asstTurn.text += data.text || "";
          scheduleRender();
        } else if (evName === "error") {
          asstTurn.error = data.detail || "上游模型调用异常";
          if (!asstTurn.text && data.fallback_text) {
            asstTurn.text = data.fallback_text;
          }
          renderConversation();
        } else if (evName === "done") {
          asstTurn.streaming = false;
          asstTurn.mode = data.mode || asstTurn.mode;
          asstTurn.text = data.text || asstTurn.text;
          asstTurn.reasoning = data.reasoning || asstTurn.reasoning;
          asstTurn.cited = data.cited || null;
          if (data.error) asstTurn.error = data.error;
          renderConversation();
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          const tail = decoder.decode();
          if (tail) parseSseFrames(tail + "\n\n", sseBuf, handleEvent);
          else if (sseBuf.buf.trim()) parseSseFrames("\n\n", sseBuf, handleEvent);
          break;
        }
        parseSseFrames(decoder.decode(value, { stream: true }), sseBuf, handleEvent);
      }

      asstTurn.streaming = false;
      renderConversation();
      await persistCurrentSession({ updatePinned: true, updatePacket: true });
    } catch (err) {
      asstTurn.streaming = false;
      if (err.name === "AbortError") {
        asstTurn.error = asstTurn.text ? "已手动停止后续输出" : "已取消本次请求";
      } else {
        asstTurn.error = err.message || "流式连接中断";
      }
      renderConversation();
      await persistCurrentSession({ updatePinned: true, updatePacket: true });
    } finally {
      niState.abortController = null;
      updateStreamingControls(false);
    }
  }

  function openCitationByRef(refId) {
    const pkt = currentPacket();
    const cit = (pkt?.citations || []).find((c) => Number(c.ref_id) === Number(refId));
    if (!cit) {
      showNotice(`当前实证包中未找到 [ref:${refId}]`);
      return;
    }
    if (cit.source_scope === "curated_library" && typeof window.tcmOpenContextDrawer === "function") {
      window.tcmOpenContextDrawer({
        bookId: cit.book_id,
        pageNo: Number(cit.page_no || 1),
        q: String(cit.quote || "").slice(0, 18),
        bookHint: cit.book_title || "",
      });
      return;
    }
    showNotice(`${cit.book_title} (${cit.unit_label})：${String(cit.quote || "").slice(0, 80)}`);
  }

  // ── Configuration Modal & Codex OAuth Panel ───────────────────────────
  function stopCodexPolling() {
    if (niState.codexPollTimer) {
      window.clearTimeout(niState.codexPollTimer);
      niState.codexPollTimer = null;
    }
    niState.codexPollingPending = false;
  }

  function scheduleCodexPolling() {
    if (niState.codexPollTimer) window.clearTimeout(niState.codexPollTimer);
    const modal = $("#ai-config-modal");
    if (!modal || modal.classList.contains("hidden")) {
      stopCodexPolling();
      return;
    }
    niState.codexPollTimer = window.setTimeout(async () => {
      try {
        const prevActive = niState.config?.active_profile_id;
        const res = await apiJson("/api/ai/codex/status");
        if (res.config) {
          niState.config = res.config;
          if (res.config.active_profile_id && res.config.active_profile_id !== prevActive) {
            populateModalFromConfig(res.config);
          }
          updateStatusHeader();
        }
        renderCodexAuthPanel(res);
        if (res.logged_in && (!res.login || res.login.status !== "pending")) {
          if (niState.codexPollingPending) {
            showNotice(`OpenAI Codex 登录成功：${res.account_masked || "ChatGPT 已连接"}`);
            const out = $("#ai-cfg-test-result");
            if (out) {
              out.className = "ai-cfg-result is-ok";
              out.textContent = `Codex 已完成授权（${res.account_masked || "ChatGPT 订阅"}），已自动启用 OpenAI Codex 配置并正在同步订阅模型。`;
            }
            syncLiveCodexModels(res.config || niState.config, true);
          }
          stopCodexPolling();
          return;
        }
        if (res.login?.status === "pending") {
          scheduleCodexPolling();
        } else {
          stopCodexPolling();
        }
      } catch {
        stopCodexPolling();
      }
    }, 1600);
  }

  let codexModelsFetchInFlight = false;
  async function syncLiveCodexModels(cfg, force = false) {
    if (!cfg || codexModelsFetchInFlight) return;
    const isCodexActive = cfg.protocol === "codex_oauth" || cfg.provider === "codex";
    const hasOauth = Boolean(cfg.has_oauth || cfg.codex_auth?.logged_in);
    if (!hasOauth) return;
    const targetProf =
      (cfg.profiles || []).find((p) => p.protocol === "codex_oauth" || p.provider === "codex") || cfg;
    const pid = targetProf.profile_id || cfg.active_profile_id || "default";
    if (!force && getCachedModelsForProfile(pid, "codex").length > 0 && !isCodexActive) return;
    codexModelsFetchInFlight = true;
    try {
      const res = await apiJson("/api/ai/models", {
        method: "POST",
        body: JSON.stringify({
          provider: "codex",
          protocol: "codex_oauth",
          base_url: targetProf.base_url || "https://chatgpt.com/backend-api",
          model: targetProf.model || "gpt-5.6-sol",
          relay_url: targetProf.relay_url || "",
        }),
      });
      const models = Array.isArray(res?.models) ? res.models : [];
      if (models.length) {
        saveCachedModelsForProfile(pid, "codex", models);
        renderHomepageProfileAndModelSelects(niState.config);
        if ($("#ai-cfg-provider")?.value === "codex") {
          refreshSuggestedModelsList("codex", $("#ai-cfg-model")?.value || models[0]);
        }
      }
    } catch {
      // keep preset list cleanly if offline
    } finally {
      codexModelsFetchInFlight = false;
    }
  }

  function renderCodexAuthPanel(codexAuth) {
    const statusEl = $("#ai-cfg-codex-status");
    const logoutBtn = $("#ai-cfg-codex-logout-btn");
    const cancelBtn = $("#ai-cfg-codex-cancel-btn");
    const pendingEl = $("#ai-cfg-codex-pending");
    const cbWrap = $("#ai-cfg-codex-callback-wrap");
    if (!statusEl) return;

    const auth = codexAuth || {};
    if (auth.logged_in) {
      const plan = auth.plan_type ? `（${auth.plan_type} 订阅）` : "";
      const expMs = auth.expires_at ? (auth.expires_at > 1e12 ? auth.expires_at : auth.expires_at * 1000) : 0;
      const expStr = expMs ? ` · 有效期至 ${new Date(expMs).toLocaleString()}` : "";
      statusEl.textContent = `已登录：${auth.account_masked || "ChatGPT 账号"}${plan}${expStr}`;
      statusEl.className = "ai-form-note is-codex-ok";
    } else {
      statusEl.textContent = "尚未登录 ChatGPT / OpenAI Codex 账号（无需手动填写 API Key）";
      statusEl.className = "ai-form-note";
    }
    if (logoutBtn) logoutBtn.classList.toggle("hidden", !auth.logged_in);

    const login = auth.login || null;
    const isPending = login?.status === "pending";
    niState.codexPollingPending = isPending;
    if (cancelBtn) cancelBtn.classList.toggle("hidden", !isPending);

    if (pendingEl) {
      if (isPending && login.method === "device") {
        const verifyUrl = login.verification_uri || login.auth_url || "https://auth.openai.com/codex/device";
        pendingEl.classList.remove("hidden");
        pendingEl.innerHTML =
          `<div class="ai-codex-code-row">` +
          `<span>一次性设备码：</span>` +
          `<code class="ai-codex-user-code">${escapeHtml(login.user_code || "")}</code>` +
          `<button type="button" class="ai-mini-btn" data-copy-codex-code="${escapeHtml(login.user_code || "")}">复制</button>` +
          `</div>` +
          `<div class="ai-codex-link-row">请打开 <a href="${escapeHtml(verifyUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(verifyUrl)}</a> 并输入设备码，授权完成后此处将自动识别…</div>` +
          `<small class="ai-form-note">若打开链接显示乱码，多为本地代理/安全软件对 OpenAI 页面的 br/zstd 压缩或域名分流异常；请确保 <code>auth.openai.com</code> 与 <code>auth-cdn.oaistatic.com</code> 走同一节点、用无痕窗口打开，或改用「浏览器 OAuth 登录」。</small>`;
      } else if (isPending && login.method === "browser") {
        pendingEl.classList.remove("hidden");
        pendingEl.innerHTML =
          `<div class="ai-codex-link-row">若未自动弹出授权页，请点击：<a href="${escapeHtml(login.auth_url || "#")}" target="_blank" rel="noopener noreferrer">打开 OpenAI 官方登录页 ↗</a></div>`;
      } else if ((login?.status === "error" || login?.status === "failed") && login.error) {
        pendingEl.classList.remove("hidden");
        pendingEl.innerHTML = `<div class="ai-codex-err-msg">${escapeHtml(login.error)}</div>`;
      } else {
        pendingEl.classList.add("hidden");
        pendingEl.innerHTML = "";
      }
    }

    if (cbWrap) {
      cbWrap.classList.toggle("hidden", !(isPending && login?.method === "browser"));
    }

    if (isPending) {
      scheduleCodexPolling();
    } else {
      stopCodexPolling();
    }
  }

  function syncModalAuthVisibility() {
    const prov = $("#ai-cfg-provider")?.value || "deepseek";
    const proto = $("#ai-cfg-protocol")?.value || "openai_compat";
    const urlVal = String($("#ai-cfg-url")?.value || "").trim().toLowerCase();
    const isCodex = proto === "codex_oauth" || prov === "codex";
    const isCorsRestrictedHost =
      urlVal.includes("opencode.ai") ||
      urlVal.includes("moonshot.cn") ||
      urlVal.includes("bigmodel.cn");
    const needsRelayHint = isCodex || prov === "custom" || isCorsRestrictedHost;
    const relayVal = $("#ai-cfg-relay-url")?.value?.trim() || "";
    const localBridge = window.tcmLocalCodexBridge;
    $("#ai-cfg-local-bridge-row")?.classList.toggle("hidden", !(window.__TCM_STATIC_WEB__ && isCodex));
    const bridgeConnected = Boolean(localBridge?.status().connected);
    const bridgeButton = $("#ai-cfg-local-bridge-btn");
    if (bridgeButton) bridgeButton.textContent = bridgeConnected ? "断开本机中转" : "连接本机中转";
    const bridgeStatus = $("#ai-cfg-local-bridge-status");
    if (bridgeStatus) bridgeStatus.textContent = bridgeConnected
      ? "已连接本机：Codex 请求使用当前电脑的网络。请保持本机中转程序运行。"
      : "网页版默认使用云端服务，无需启动本机程序。本机中转为可选连接，仅当前电脑可用。";
    if (window.__TCM_STATIC_WEB__) {
      const browserBtn = $("#ai-cfg-codex-browser-btn");
      if (browserBtn) browserBtn.textContent = "浏览器登录（手动回调）";
      const callbackLabel = $('label[for="ai-cfg-codex-callback-input"]');
      if (callbackLabel) callbackLabel.textContent = "授权后若显示 localhost:1455 无法访问，请复制该页完整地址粘贴到这里，再点「提交回调链接」。保持本页打开，不要刷新。";
    }
    $("#ai-cfg-key-row")?.classList.toggle("hidden", isCodex);
    $("#ai-cfg-codex-box")?.classList.toggle("hidden", !isCodex);
    $("#ai-cfg-relay-row")?.classList.toggle("hidden", !(needsRelayHint && (window.__TCM_STATIC_WEB__ || relayVal)));

    const envNote = $("#ai-cfg-codex-env-note");
    if (envNote) {
      envNote.textContent = window.__TCM_STATIC_WEB__
        ? "网页版推荐设备码登录，每位用户使用自己的 ChatGPT 账号。授权令牌与模型请求经项目云端服务发送至 OpenAI，无需运行本机中转。浏览器授权需要手动粘贴回调链接。"
        : "本地 Python 服务版已直连 auth.openai.com 与 localhost:1455 回调监听，支持设备码或浏览器一键登录，凭证仅限权存本地 data/codex_oauth.json，对话由后端转发，无任何浏览器跨域限制。";
    }

    const provNote = $("#ai-cfg-provider-note");
    if (provNote) {
      if (window.__TCM_STATIC_WEB__ && urlVal.includes("opencode.ai") && !relayVal) {
        provNote.textContent =
          "⚠️ OpenCode 提示：opencode.ai 仅允许拉取模型列表，服务端未对 github.io 开放对话 POST 跨域权限（测试连通/发送对话会被浏览器拦截）。请改用本地版 (127.0.0.1:8767)、下方填入 CORS 中继地址，或切换为 DeepSeek / 硅基流动 / 阿里云百炼 / OpenRouter。";
      } else if (window.__TCM_STATIC_WEB__ && (urlVal.includes("moonshot.cn") || urlVal.includes("bigmodel.cn")) && !relayVal) {
        provNote.textContent =
          "⚠️ 跨域提示：该网关当前未对 github.io 开放浏览器 POST 跨域，测试或对话时会被浏览器拦截；建议改用本地版 (127.0.0.1:8767) 或切换 DeepSeek / 硅基流动 / 阿里云百炼 / OpenRouter。";
      } else {
        const preset = (niState.config?.presets || []).find((p) => p.id === prov);
        provNote.textContent = preset?.note || "";
      }
    }
  }

  function renderModalProfileSelect(cfg) {
    const sel = $("#ai-cfg-profile-select");
    const delBtn = $("#ai-cfg-del-profile-btn");
    const profiles = Array.isArray(cfg?.profiles) ? cfg.profiles : [];
    if (sel) {
      const opts = profiles.map((p) => {
        const mark = p.ready ? "● " : "○ ";
        return `<option value="${escapeHtml(p.profile_id)}">${escapeHtml(`${mark}${p.profile_name || p.model}`)}</option>`;
      });
      opts.push(`<option value="__new__">+ 准备新建配置组...</option>`);
      sel.innerHTML = opts.join("");
      sel.value = niState.modalDraftNew
        ? "__new__"
        : (cfg?.active_profile_id || cfg?.profile_id || profiles[0]?.profile_id || "default");
    }
    if (delBtn) {
      delBtn.disabled = niState.modalDraftNew || profiles.length <= 1;
    }
  }

  function populateModalFromConfig(cfg, { isNewDraft = false } = {}) {
    if (!cfg) return;
    niState.modalDraftNew = Boolean(isNewDraft);
    renderModalProfileSelect(cfg);
    if ($("#ai-cfg-profile-name")) {
      $("#ai-cfg-profile-name").value = isNewDraft ? "" : (cfg.profile_name || "");
    }
    if ($("#ai-cfg-provider")) $("#ai-cfg-provider").value = cfg.provider || "deepseek";
    if ($("#ai-cfg-protocol")) $("#ai-cfg-protocol").value = cfg.protocol || "openai_compat";
    if ($("#ai-cfg-url")) $("#ai-cfg-url").value = cfg.base_url || "";
    if ($("#ai-cfg-relay-url")) $("#ai-cfg-relay-url").value = cfg.relay_url || "";
    if ($("#ai-cfg-model")) $("#ai-cfg-model").value = cfg.model || "";
    const keyInput = $("#ai-cfg-key");
    if (keyInput) {
      keyInput.value = "";
      keyInput.placeholder = isNewDraft
        ? "输入新配置的 API Key（本地 Ollama 可留空）"
        : cfg.has_api_key
        ? `已保存密钥（${cfg.api_key_masked}），留空保留原密钥`
        : "输入 API Key（本地 Ollama 可留空）";
    }
    if ($("#ai-cfg-clear-key")) $("#ai-cfg-clear-key").checked = false;
    if ($("#ai-cfg-style")) $("#ai-cfg-style").value = cfg.persona_style || "master_balanced";
    if ($("#ai-cfg-temp")) $("#ai-cfg-temp").value = String(cfg.temperature ?? 0.45);
    if ($("#ai-cfg-tokens")) $("#ai-cfg-tokens").value = String(cfg.max_tokens ?? 0);
    if ($("#ai-cfg-timeout")) $("#ai-cfg-timeout").value = String(cfg.timeout_sec ?? 120);
    const keyHint = $("#ai-cfg-key-hint");
    if (keyHint) {
      keyHint.textContent = isNewDraft
        ? "新建配置将独立保存密钥与模型参数，不覆盖其他已存配置"
        : cfg.key_source === "env"
        ? `当前通过环境变量自动识别密钥（${cfg.api_key_masked}）`
        : cfg.key_source === "saved" || cfg.key_source === "browser"
        ? `当前配置已独立保存密钥（${cfg.api_key_masked}）`
        : "当前配置尚未设置 API Key（不配也可免 Key 离线出方）";
    }
    syncModalAuthVisibility();
    renderCodexAuthPanel(cfg.codex_auth);
    refreshSuggestedModelsList(cfg.provider, cfg.model);
    syncModalReasoningSelect(cfg.reasoning_effort || niState.reasoningEffort || "auto");
  }

  function syncModalReasoningSelect(desiredValue = null) {
    const prov = $("#ai-cfg-provider")?.value || "deepseek";
    const proto = $("#ai-cfg-protocol")?.value || "openai_compat";
    const model = $("#ai-cfg-model")?.value || "";
    const cur = desiredValue || $("#ai-cfg-reasoning")?.value || niState.config?.reasoning_effort || "auto";
    syncReasoningSelect($("#ai-cfg-reasoning"), $("#ai-cfg-reasoning-hint"), prov, proto, model, cur);
  }

  function refreshSuggestedModelsList(providerId, currentModel = "") {
    const preset = (niState.config?.presets || []).find((p) => p.id === providerId);
    const pid = $("#ai-cfg-profile-select")?.value;
    const cached = pid && pid !== "__new__" ? getCachedModelsForProfile(pid, providerId) : [];
    const models = [];
    for (const m of [...(preset?.suggested_models || []), ...cached, currentModel]) {
      const clean = String(m || "").trim();
      if (clean && !models.includes(clean)) models.push(clean);
    }
    if ($("#ai-cfg-model-options")) {
      $("#ai-cfg-model-options").innerHTML = models.map((m) => `<option value="${escapeHtml(m)}"></option>`).join("");
    }
    if ($("#ai-cfg-model-pills")) {
      $("#ai-cfg-model-pills").innerHTML = models
        .slice(0, 12)
        .map((m) => `<button type="button" class="ai-chip ${m === currentModel ? "active" : ""}" data-ai-pick-model="${escapeHtml(m)}">${escapeHtml(m)}</button>`)
        .join("");
    }
    if ($("#ai-cfg-provider-note")) {
      const presetUrl = String($("#ai-cfg-url")?.value || "").trim().toLowerCase();
      if (!(window.__TCM_STATIC_WEB__ && (presetUrl.includes("opencode.ai") || presetUrl.includes("moonshot.cn") || presetUrl.includes("bigmodel.cn")) && !$("#ai-cfg-relay-url")?.value?.trim())) {
        $("#ai-cfg-provider-note").textContent = preset?.note || "";
      }
    }
    syncModalReasoningSelect();
  }

  function collectModalPayload({ saveAsNew = false } = {}) {
    const rawTemp = $("#ai-cfg-temp")?.value;
    const rawTokens = $("#ai-cfg-tokens")?.value;
    const rawTimeout = $("#ai-cfg-timeout")?.value;
    const parsedTemp = rawTemp === "" || rawTemp === undefined ? 0.45 : Number(rawTemp);
    const parsedTokens = rawTokens === "" || rawTokens === undefined ? 0 : Math.trunc(Number(rawTokens));
    const parsedTimeout = rawTimeout === "" || rawTimeout === undefined ? 120 : Math.trunc(Number(rawTimeout));
    const selPid = $("#ai-cfg-profile-select")?.value || "";
    const creatingNew = Boolean(saveAsNew || niState.modalDraftNew || selPid === "__new__");
    const payload = {
      save_as_new: creatingNew,
      profile_name: $("#ai-cfg-profile-name")?.value?.trim() || "",
      provider: $("#ai-cfg-provider")?.value || "deepseek",
      protocol: $("#ai-cfg-protocol")?.value || "openai_compat",
      base_url: $("#ai-cfg-url")?.value?.trim() || "",
      relay_url: $("#ai-cfg-relay-url")?.value?.trim() || "",
      model: $("#ai-cfg-model")?.value?.trim() || "",
      persona_style: $("#ai-cfg-style")?.value || "master_balanced",
      reasoning_effort: $("#ai-cfg-reasoning")?.value || "auto",
      temperature: Number.isFinite(parsedTemp) ? parsedTemp : 0.45,
      max_tokens: Number.isFinite(parsedTokens) ? Math.max(0, Math.min(128000, parsedTokens)) : 0,
      timeout_sec: Number.isFinite(parsedTimeout) ? parsedTimeout : 120,
    };
    if (!creatingNew && selPid) {
      payload.profile_id = selPid;
    }
    const typedKey = $("#ai-cfg-key")?.value?.trim() || "";
    if (typedKey) payload.api_key = typedKey;
    if ($("#ai-cfg-clear-key")?.checked) payload.clear_api_key = true;
    return payload;
  }

  function openConfigModal() {
    const modal = $("#ai-config-modal");
    if (!modal) return;
    populateModalFromConfig(niState.config);
    const out = $("#ai-cfg-test-result");
    if (out) {
      out.className = "ai-cfg-result hidden";
      out.textContent = "";
    }
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    const prevActive = niState.config?.active_profile_id;
    apiJson("/api/ai/codex/status")
      .then((res) => {
        if (res.config) {
          niState.config = res.config;
          if (res.config.active_profile_id && res.config.active_profile_id !== prevActive) {
            populateModalFromConfig(res.config);
          }
          updateStatusHeader();
          syncLiveCodexModels(res.config, false);
        }
        renderCodexAuthPanel(res);
      })
      .catch(() => {});
  }

  function closeConfigModal() {
    stopCodexPolling();
    const modal = $("#ai-config-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  async function loadConfig() {
    const cfg = await apiJson("/api/ai/config");
    niState.config = cfg;
    niState.style = cfg.persona_style || "master_balanced";
    niState.reasoningEffort = cfg.reasoning_effort || "auto";

    const styleSel = $("#ai-style-select");
    if (styleSel && cfg.styles?.length) {
      styleSel.innerHTML = cfg.styles.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.label)}</option>`).join("");
      styleSel.value = niState.style;
    }
    if ($("#ai-cfg-style") && cfg.styles?.length) {
      $("#ai-cfg-style").innerHTML = cfg.styles.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.label)}</option>`).join("");
    }
    if ($("#ai-cfg-provider") && cfg.presets?.length) {
      $("#ai-cfg-provider").innerHTML = cfg.presets.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join("");
    }
    updateStatusHeader();
    syncLiveCodexModels(cfg, false);
  }

  function bindEvents() {
    // Mobile 3-pane switcher bar
    $("#ai-mobile-pane-tabs")?.addEventListener("click", (e) => {
      const tab = e.target.closest("[data-ai-mpane]");
      if (!tab) return;
      setMobilePane(tab.dataset.aiMpane);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    // History panel collapse toggle (desktop collapses column; mobile switches pane)
    $("#ai-toggle-history-btn")?.addEventListener("click", () => {
      if (window.innerWidth < 1180) {
        setMobilePane(niState.mobilePane === "history" ? "consult" : "history");
        return;
      }
      niState.historyCollapsed = !niState.historyCollapsed;
      $("#ai-workspace")?.classList.toggle("is-hist-collapsed", niState.historyCollapsed);
    });

    $("#ai-top-new-session-btn")?.addEventListener("click", () => createNewSession().catch((e) => showNotice(e.message)));
    $("#ai-new-session-btn")?.addEventListener("click", () => createNewSession().catch((e) => showNotice(e.message)));

    // Patient CRUD
    $("#ai-add-patient-btn")?.addEventListener("click", () => openPatientForm(null));
    $("#ai-pat-cancel-btn")?.addEventListener("click", closePatientForm);

    $("#ai-pat-save-btn")?.addEventListener("click", async () => {
      const patId = $("#ai-pat-id")?.value?.trim() || "";
      const payload = {
        name: $("#ai-pat-name")?.value?.trim() || "",
        gender: $("#ai-pat-gender")?.value || "",
        age: $("#ai-pat-age")?.value?.trim() || "",
        notes: $("#ai-pat-notes")?.value?.trim() || "",
      };
      if (!payload.name) {
        showNotice("请输入问诊人姓名或称呼");
        $("#ai-pat-name")?.focus();
        return;
      }
      try {
        if (patId) {
          const res = await apiJson(`/api/ai/patients/${encodeURIComponent(patId)}/update`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          niState.patients = res.patients || [];
          closePatientForm();
          renderPatientsAndSessions();
          showNotice("已更新问诊人档案");
        } else {
          const res = await apiJson("/api/ai/patients", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          niState.patients = res.patients || [];
          closePatientForm();
          await selectPatient(res.patient.id, res.initial_session?.id);
          if (window.innerWidth < 1180) setMobilePane("consult");
          showNotice(`已添加问诊人「${res.patient.name}」并开启独立诊室`);
        }
      } catch (err) {
        showNotice(err.message);
      }
    });

    $("#ai-patient-list")?.addEventListener("click", async (e) => {
      const editBtn = e.target.closest("[data-pat-edit]");
      if (editBtn) {
        e.stopPropagation();
        const pat = niState.patients.find((p) => p.id === editBtn.dataset.patEdit);
        if (pat) openPatientForm(pat);
        return;
      }
      const delBtn = e.target.closest("[data-pat-del]");
      if (delBtn) {
        e.stopPropagation();
        const pid = delBtn.dataset.patDel;
        const pat = niState.patients.find((p) => p.id === pid);
        if (!window.confirm(`确定删除问诊人「${pat?.name || ""}」及其全部问诊历史吗？`)) return;
        try {
          const res = await apiJson(`/api/ai/patients/${encodeURIComponent(pid)}/delete`, { method: "POST" });
          niState.patients = res.patients || [];
          if (niState.activePatientId === pid) {
            const nextId = niState.patients[0]?.id || null;
            await selectPatient(nextId);
          } else {
            renderPatientsAndSessions();
          }
          showNotice("已删除问诊人及历史记录");
        } catch (err) {
          showNotice(err.message);
        }
        return;
      }
      const card = e.target.closest("[data-pat-select]");
      if (card) {
        const pid = card.dataset.patSelect;
        if (pid !== niState.activePatientId) {
          await selectPatient(pid).catch((err) => showNotice(err.message));
        }
      }
    });

    $("#ai-session-list")?.addEventListener("click", async (e) => {
      const delBtn = e.target.closest("[data-ses-del]");
      if (delBtn) {
        e.stopPropagation();
        const sid = delBtn.dataset.sesDel;
        try {
          const res = await apiJson(`/api/ai/sessions/${encodeURIComponent(sid)}/delete`, { method: "POST" });
          niState.sessions = res.sessions || [];
          if (niState.activeSessionId === sid) {
            const nextSid = niState.sessions[0]?.id || null;
            if (nextSid) await selectSession(nextSid);
            else applySessionToWorkspace(null);
          } else {
            renderPatientsAndSessions();
          }
          apiJson("/api/ai/patients")
            .then((pRes) => {
              niState.patients = pRes.patients || niState.patients;
              renderPatientsAndSessions();
            })
            .catch(() => {});
          showNotice("已删除该条问诊历史");
        } catch (err) {
          showNotice(err.message);
        }
        return;
      }
      const row = e.target.closest("[data-ses-select]");
      if (row) {
        const sid = row.dataset.sesSelect;
        if (sid !== niState.activeSessionId) {
          await selectSession(sid).catch((err) => showNotice(err.message));
        }
        if (window.innerWidth < 1180) {
          setMobilePane("consult");
        }
      }
    });

    // Structured intake dimension tabs & toggles
    $("#ai-dim-tabs")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-ai-dim]");
      if (!btn) return;
      niState.activeDim = btn.dataset.aiDim;
      if (niState.intakeCollapsed) {
        niState.intakeCollapsed = false;
        if ($("#ai-intake-collapse-btn")) $("#ai-intake-collapse-btn").textContent = "收起四诊盘 ▲";
      }
      renderDimSelector();
    });

    $("#ai-intake-collapse-btn")?.addEventListener("click", () => {
      niState.intakeCollapsed = !niState.intakeCollapsed;
      if ($("#ai-intake-collapse-btn")) {
        $("#ai-intake-collapse-btn").textContent = niState.intakeCollapsed ? "展开四诊盘 ▼" : "收起四诊盘 ▲";
      }
      renderDimSelector();
    });

    $("#ai-clear-intake-btn")?.addEventListener("click", () => {
      niState.intake = emptyIntake();
      niState.pendingImages = [];
      niState.visionFeedback = null;
      if ($("#ai-query-input")) $("#ai-query-input").value = "";
      renderDimSelector();
      renderSelectedBoard();
      renderVisionStrip();
    });

    $("#ai-upload-image-btn")?.addEventListener("click", () => $("#ai-image-input")?.click());
    $("#ai-image-input")?.addEventListener("change", (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = "";
      addImageFiles(files);
    });
    $("#ai-query-input")?.addEventListener("paste", (e) => {
      const items = Array.from(e.clipboardData?.items || []);
      const imgFiles = items
        .filter((it) => it.kind === "file" && String(it.type || "").startsWith("image/"))
        .map((it) => it.getAsFile())
        .filter(Boolean);
      if (!imgFiles.length) return;
      e.preventDefault();
      addImageFiles(imgFiles);
    });
    $("#ai-image-preview-list")?.addEventListener("click", (e) => {
      const rmBtn = e.target.closest("[data-ai-rm-img]");
      if (!rmBtn) return;
      const rmId = rmBtn.dataset.aiRmImg;
      niState.pendingImages = (niState.pendingImages || []).filter((x) => x.id !== rmId);
      if (!niState.pendingImages.length) niState.visionFeedback = null;
      renderVisionStrip();
    });
    $("#ai-vision-clear-btn")?.addEventListener("click", () => {
      niState.pendingImages = [];
      niState.visionFeedback = null;
      renderVisionStrip();
    });
    $("#ai-ocr-extract-btn")?.addEventListener("click", extractIntakeFromImages);

    $("#ai-dim-body")?.addEventListener("click", (e) => {
      const presetBtn = e.target.closest("[data-ai-preset]");
      if (presetBtn) {
        const c = PRESET_CASES[Number(presetBtn.dataset.aiPreset)];
        if (!c) return;
        niState.intake = {
          ...emptyIntake(),
          query: c.query,
          symptoms: [...c.symptoms],
          pulses: [...c.pulses],
          tongues: [...c.tongues],
          abdomen: [...c.abdomen],
          eye: [...c.eye],
          tender: [...c.tender],
          negations: [...c.negations],
        };
        if ($("#ai-query-input")) $("#ai-query-input").value = c.query;
        renderDimSelector();
        renderSelectedBoard();
        submitConsultation();
        return;
      }

      const togBtn = e.target.closest("[data-ai-toggle-cat]");
      if (togBtn) {
        const cat = togBtn.dataset.aiToggleCat;
        const val = togBtn.dataset.aiToggleVal;
        const arr = niState.intake[cat];
        if (!Array.isArray(arr)) return;
        const idx = arr.indexOf(val);
        if (idx >= 0) arr.splice(idx, 1);
        else arr.push(val);
        renderDimSelector();
        renderSelectedBoard();
      }
    });

    $("#ai-dim-body")?.addEventListener("input", (e) => {
      const inp = e.target.closest("[data-ai-note]");
      if (!inp) return;
      niState.intake.notes[inp.dataset.aiNote] = inp.value;
      renderSelectedBoard();
    });

    $("#ai-selected-board")?.addEventListener("click", (e) => {
      const rmBtn = e.target.closest("[data-ai-remove-cat]");
      if (!rmBtn) return;
      const cat = rmBtn.dataset.aiRemoveCat;
      const val = rmBtn.dataset.aiRemoveVal;
      const arr = niState.intake[cat];
      if (!Array.isArray(arr)) return;
      const idx = arr.indexOf(val);
      if (idx >= 0) arr.splice(idx, 1);
      renderDimSelector();
      renderSelectedBoard();
    });

    $("#ai-query-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        submitConsultation();
      }
    });

    $("#ai-submit-btn")?.addEventListener("click", () => submitConsultation());
    $("#ai-stop-btn")?.addEventListener("click", () => {
      if (niState.abortController) niState.abortController.abort();
    });

    $("#ai-profile-select")?.addEventListener("change", async (e) => {
      const nextId = e.target.value;
      if (!nextId) return;
      try {
        const saved = await apiJson("/api/ai/profiles/select", {
          method: "POST",
          body: JSON.stringify({ profile_id: nextId }),
        });
        niState.config = saved;
        niState.style = saved.persona_style || niState.style;
        niState.reasoningEffort = saved.reasoning_effort || "auto";
        if ($("#ai-style-select")) $("#ai-style-select").value = niState.style;
        updateStatusHeader();
        showNotice(`已切换配置：${saved.profile_name || saved.model}`);
      } catch (err) {
        showNotice(err.message);
        updateStatusHeader();
      }
    });

    $("#ai-model-select")?.addEventListener("change", async (e) => {
      const nextModel = e.target.value;
      if (!nextModel) return;
      try {
        const pid = niState.config?.active_profile_id || niState.config?.profile_id || "default";
        const saved = await apiJson("/api/ai/config", {
          method: "POST",
          body: JSON.stringify({ profile_id: pid, model: nextModel }),
        });
        niState.config = saved;
        niState.reasoningEffort = saved.reasoning_effort || "auto";
        updateStatusHeader();
        showNotice(`已切换并保存模型：${saved.model}`);
      } catch (err) {
        showNotice(err.message);
        updateStatusHeader();
      }
    });

    $("#ai-style-select")?.addEventListener("change", (e) => {
      niState.style = e.target.value;
    });

    $("#ai-effort-select")?.addEventListener("change", (e) => {
      const nextEffort = e.target.value || "auto";
      niState.reasoningEffort = nextEffort;
      if (niState.config) niState.config.reasoning_effort = nextEffort;
      apiJson("/api/ai/config", {
        method: "POST",
        body: JSON.stringify({ reasoning_effort: nextEffort }),
      })
        .then((saved) => {
          niState.config = saved;
          niState.reasoningEffort = saved.reasoning_effort || nextEffort;
          updateStatusHeader();
        })
        .catch(() => {});
    });

    $("#ai-offline-toggle")?.addEventListener("change", (e) => {
      niState.offlineOnly = Boolean(e.target.checked);
      updateStatusHeader();
    });

    $("#ai-pinned-box")?.addEventListener("click", (e) => {
      if (e.target.closest("#ai-unpin-btn")) {
        niState.pinnedEntity = null;
        renderPinnedEntity();
      }
    });

    $("#ai-chat-thread")?.addEventListener("click", (e) => {
      const refBtn = e.target.closest("[data-ai-ref]");
      if (refBtn) {
        e.preventDefault();
        openCitationByRef(Number(refBtn.dataset.aiRef));
        return;
      }
      const fqBtn = e.target.closest("[data-ai-followup]");
      if (fqBtn) {
        e.preventDefault();
        submitConsultation(fqBtn.dataset.aiFollowup);
        return;
      }
      const pktBtn = e.target.closest("[data-ai-select-packet]");
      if (pktBtn) {
        niState.selectedPacketTurnId = pktBtn.dataset.aiSelectPacket;
        renderEvidenceSidebar(currentPacket());
        if (window.innerWidth < 1180) {
          setMobilePane("evidence");
        } else {
          showNotice("已切换到该轮辨证的实时实证包");
        }
        return;
      }
      const evJumpBtn = e.target.closest("[data-ai-open-evidence]");
      if (evJumpBtn) {
        niState.evTab = evJumpBtn.dataset.aiOpenEvidence || "rx";
        renderEvidenceSidebar(currentPacket());
        setMobilePane("evidence");
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });

    // Evidence panel tabs & jump/ref actions
    $("#ai-ev-tabs")?.addEventListener("click", (e) => {
      const tab = e.target.closest("[data-ai-ev-tab]");
      if (!tab) return;
      niState.evTab = tab.dataset.aiEvTab;
      renderEvidenceSidebar(currentPacket());
    });

    $("#ai-evidence-body")?.addEventListener("click", (e) => {
      const openCitBtn = e.target.closest("[data-ai-open-cit]");
      if (openCitBtn) {
        e.preventDefault();
        openCitationByRef(Number(openCitBtn.dataset.aiOpenCit));
        return;
      }
      const jumpBtn = e.target.closest("[data-ai-jump-kind]");
      if (jumpBtn) {
        e.preventDefault();
        const kind = jumpBtn.dataset.aiJumpKind;
        const eid = decodeURIComponent(jumpBtn.dataset.aiJumpId || "");
        if (window.libraryStage5?.jumpToEntity) {
          window.libraryStage5.jumpToEntity(kind, eid);
        }
      }
    });

    // Config Modal Events
    $("#ai-open-config-btn")?.addEventListener("click", openConfigModal);
    $("#ai-close-config-btn")?.addEventListener("click", closeConfigModal);
    $("#ai-config-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "ai-config-modal") closeConfigModal();
    });

    $("#ai-cfg-profile-select")?.addEventListener("change", async (e) => {
      const pid = e.target.value;
      if (pid === "__new__") {
        populateModalFromConfig(niState.config, { isNewDraft: true });
        return;
      }
      try {
        const saved = await apiJson("/api/ai/profiles/select", {
          method: "POST",
          body: JSON.stringify({ profile_id: pid }),
        });
        niState.config = saved;
        niState.style = saved.persona_style || niState.style;
        niState.reasoningEffort = saved.reasoning_effort || "auto";
        if ($("#ai-style-select")) $("#ai-style-select").value = niState.style;
        updateStatusHeader();
        populateModalFromConfig(saved);
      } catch (err) {
        showNotice(err.message);
      }
    });

    $("#ai-cfg-new-profile-btn")?.addEventListener("click", () => {
      populateModalFromConfig(niState.config, { isNewDraft: true });
      const out = $("#ai-cfg-test-result");
      if (out) {
        out.className = "ai-cfg-result";
        out.textContent = "已进入「新建配置」模式：选好服务商、填好密钥与模型后点「保存配置」即可独立存为新配置。";
      }
      $("#ai-cfg-profile-name")?.focus();
    });

    $("#ai-cfg-del-profile-btn")?.addEventListener("click", async () => {
      const pid = $("#ai-cfg-profile-select")?.value;
      if (!pid || pid === "__new__") return;
      const prof = (niState.config?.profiles || []).find((p) => p.profile_id === pid);
      if (!window.confirm(`确定删除已保存的模型配置「${prof?.profile_name || pid}」吗？`)) return;
      const out = $("#ai-cfg-test-result");
      try {
        const saved = await apiJson("/api/ai/profiles/delete", {
          method: "POST",
          body: JSON.stringify({ profile_id: pid }),
        });
        niState.config = saved;
        niState.style = saved.persona_style || niState.style;
        niState.reasoningEffort = saved.reasoning_effort || "auto";
        if ($("#ai-style-select")) $("#ai-style-select").value = niState.style;
        updateStatusHeader();
        populateModalFromConfig(saved);
        if (out) {
          out.className = "ai-cfg-result is-ok";
          out.textContent = "已删除该配置组";
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = `删除失败：${err.message}`;
        }
      }
    });

    $("#ai-cfg-provider")?.addEventListener("change", (e) => {
      const pid = e.target.value;
      const preset = (niState.config?.presets || []).find((p) => p.id === pid);
      if (preset) {
        if ($("#ai-cfg-protocol")) $("#ai-cfg-protocol").value = preset.protocol || "openai_compat";
        if ($("#ai-cfg-url")) $("#ai-cfg-url").value = preset.base_url || "";
        if ($("#ai-cfg-model")) $("#ai-cfg-model").value = preset.default_model || "";
        syncModalAuthVisibility();
        refreshSuggestedModelsList(pid, preset.default_model || "");
        if (pid === "codex" && niState.config?.codex_auth?.logged_in) {
          syncLiveCodexModels({ ...niState.config, provider: "codex", protocol: "codex_oauth", has_oauth: true }, true);
        }
      } else {
        syncModalAuthVisibility();
        syncModalReasoningSelect();
      }
    });

    $("#ai-cfg-protocol")?.addEventListener("change", () => {
      syncModalAuthVisibility();
      syncModalReasoningSelect();
    });
    $("#ai-cfg-url")?.addEventListener("input", () => syncModalAuthVisibility());
    $("#ai-cfg-url")?.addEventListener("change", () => syncModalAuthVisibility());
    $("#ai-cfg-relay-url")?.addEventListener("input", () => syncModalAuthVisibility());
    $("#ai-cfg-model")?.addEventListener("input", () => syncModalReasoningSelect());
    $("#ai-cfg-model")?.addEventListener("change", () => syncModalReasoningSelect());

    $("#ai-cfg-model-pills")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-ai-pick-model]");
      if (!btn) return;
      if ($("#ai-cfg-model")) $("#ai-cfg-model").value = btn.dataset.aiPickModel;
      refreshSuggestedModelsList($("#ai-cfg-provider")?.value || "", btn.dataset.aiPickModel);
    });

    $("#ai-cfg-codex-device-btn")?.addEventListener("click", async () => {
      const out = $("#ai-cfg-test-result");
      const btn = $("#ai-cfg-codex-device-btn");
      try {
        if (btn) btn.disabled = true;
        const res = await apiJson("/api/ai/codex/login", {
          method: "POST",
          body: JSON.stringify({
            method: "device",
            relay_url: $("#ai-cfg-relay-url")?.value?.trim() || "",
          }),
        });
        if (res.config) {
          niState.config = res.config;
          updateStatusHeader();
        }
        renderCodexAuthPanel(res);
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = err.message;
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    $("#ai-cfg-local-bridge-btn")?.addEventListener("click", async () => {
      const bridge = window.tcmLocalCodexBridge;
      const btn = $("#ai-cfg-local-bridge-btn");
      const out = $("#ai-cfg-test-result");
      if (!bridge) return;
      try {
        if (btn) btn.disabled = true;
        if (bridge.status().connected) {
          bridge.disconnect();
          showNotice("已断开本页的本机中转");
        } else {
          await bridge.connect();
          showNotice("已连接本机中转，可继续 Codex 授权或测试连通");
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = err.message;
        }
      } finally {
        syncModalAuthVisibility();
        if (btn) btn.disabled = false;
      }
    });

    $("#ai-cfg-codex-browser-btn")?.addEventListener("click", async () => {
      const out = $("#ai-cfg-test-result");
      const btn = $("#ai-cfg-codex-browser-btn");
      try {
        if (btn) btn.disabled = true;
        const res = await apiJson("/api/ai/codex/login", {
          method: "POST",
          body: JSON.stringify({
            method: "browser",
            relay_url: $("#ai-cfg-relay-url")?.value?.trim() || "",
          }),
        });
        if (res.config) {
          niState.config = res.config;
          updateStatusHeader();
        }
        renderCodexAuthPanel(res);
        if (res.login?.auth_url) {
          window.open(res.login.auth_url, "_blank", "noopener,noreferrer");
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = err.message;
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    $("#ai-cfg-codex-callback-btn")?.addEventListener("click", async () => {
      const out = $("#ai-cfg-test-result");
      const btn = $("#ai-cfg-codex-callback-btn");
      const rawUrl = $("#ai-cfg-codex-callback-input")?.value?.trim() || "";
      if (!rawUrl) {
        showNotice("请先粘贴授权完成后的回调 URL");
        return;
      }
      try {
        if (btn) btn.disabled = true;
        const res = await apiJson("/api/ai/codex/callback", {
          method: "POST",
          body: JSON.stringify({
            callback_url: rawUrl,
            relay_url: $("#ai-cfg-relay-url")?.value?.trim() || "",
          }),
        });
        if (res.config) {
          niState.config = res.config;
          populateModalFromConfig(res.config);
          updateStatusHeader();
        }
        if (Array.isArray(res.models) && res.models.length && res.config) {
          const codexProf = (res.config.profiles || []).find((p) => p.protocol === "codex_oauth") || res.config;
          saveCachedModelsForProfile(codexProf.profile_id || "default", "codex", res.models);
          renderHomepageProfileAndModelSelects(res.config);
          refreshSuggestedModelsList("codex", $("#ai-cfg-model")?.value || res.models[0]);
        }
        if ($("#ai-cfg-codex-callback-input")) $("#ai-cfg-codex-callback-input").value = "";
        renderCodexAuthPanel(res);
        syncLiveCodexModels(res.config || niState.config, true);
        if (out) {
          out.className = "ai-cfg-result is-ok";
          out.textContent = `OpenAI Codex 登录成功：${res.account_masked || "ChatGPT 已连接"}，已自动开启 OpenAI Codex 配置并同步可用模型。`;
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = err.message;
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    $("#ai-cfg-codex-cancel-btn")?.addEventListener("click", async () => {
      try {
        const res = await apiJson("/api/ai/codex/cancel", { method: "POST" });
        if (res.config) niState.config = res.config;
        renderCodexAuthPanel(res);
      } catch (err) {
        showNotice(err.message);
      }
    });

    $("#ai-cfg-codex-logout-btn")?.addEventListener("click", async () => {
      try {
        const res = await apiJson("/api/ai/codex/logout", { method: "POST" });
        if (res.config) {
          niState.config = res.config;
          updateStatusHeader();
        }
        renderCodexAuthPanel(res);
        showNotice("已退出 OpenAI Codex 登录");
      } catch (err) {
        showNotice(err.message);
      }
    });

    $("#ai-cfg-codex-pending")?.addEventListener("click", async (e) => {
      const copyBtn = e.target.closest("[data-copy-codex-code]");
      if (!copyBtn) return;
      const code = copyBtn.dataset.copyCodexCode || "";
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        showNotice(`已复制设备码：${code}`);
      } catch {
        showNotice(`请手动复制设备码：${code}`);
      }
    });

    $("#ai-cfg-fetch-models")?.addEventListener("click", async () => {
      const out = $("#ai-cfg-test-result");
      const btn = $("#ai-cfg-fetch-models");
      try {
        if (btn) btn.disabled = true;
        const payload = collectModalPayload();
        const res = await apiJson("/api/ai/models", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const models = res.models || [];
        const activePid = payload.profile_id || niState.config?.active_profile_id || "default";
        saveCachedModelsForProfile(activePid, payload.provider, models);
        if ($("#ai-cfg-model-options")) $("#ai-cfg-model-options").innerHTML = models.map((m) => `<option value="${escapeHtml(m)}"></option>`).join("");
        if ($("#ai-cfg-model-pills")) {
          $("#ai-cfg-model-pills").innerHTML = models
            .slice(0, 12)
            .map((m) => `<button type="button" class="ai-chip" data-ai-pick-model="${escapeHtml(m)}">${escapeHtml(m)}</button>`)
            .join("");
        }
        if (models.length && $("#ai-cfg-model") && !$("#ai-cfg-model").value.trim()) {
          $("#ai-cfg-model").value = models[0];
        }
        renderHomepageProfileAndModelSelects(niState.config);
        if (out) {
          out.className = "ai-cfg-result is-ok";
          out.textContent = `已获取到 ${models.length} 个模型（来源：${res.source === "live" ? "接口实时拉取" : "内置预设"}）`;
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = `获取模型失败：${err.message}`;
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    $("#ai-cfg-test-btn")?.addEventListener("click", async () => {
      const out = $("#ai-cfg-test-result");
      const btn = $("#ai-cfg-test-btn");
      try {
        if (btn) btn.disabled = true;
        if (out) {
          out.className = "ai-cfg-result";
          out.textContent = "正在连通验证模型...";
        }
        const res = await apiJson("/api/ai/test", {
          method: "POST",
          body: JSON.stringify(collectModalPayload()),
        });
        if (out) {
          out.className = "ai-cfg-result is-ok";
          out.textContent = `连接成功 · ${res.model} · 延迟 ${res.latency_ms} ms · 返回：“${res.reply_preview}”（请点击右下角「保存配置」使配置生效）`;
        }
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = `连接测试失败：${err.message}`;
        }
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    const saveFromModal = async (saveAsNew = false) => {
      const out = $("#ai-cfg-test-result");
      try {
        const saved = await apiJson("/api/ai/config", {
          method: "POST",
          body: JSON.stringify(collectModalPayload({ saveAsNew })),
        });
        niState.config = saved;
        niState.modalDraftNew = false;
        niState.style = saved.persona_style || niState.style;
        niState.reasoningEffort = saved.reasoning_effort || "auto";
        if ($("#ai-style-select")) $("#ai-style-select").value = niState.style;
        const pillModels = Array.from(
          document.querySelectorAll("#ai-cfg-model-pills [data-ai-pick-model]")
        )
          .map((btn) => String(btn.dataset.aiPickModel || "").trim())
          .filter(Boolean);
        if (pillModels.length) {
          saveCachedModelsForProfile(
            saved.active_profile_id || saved.profile_id || "default",
            saved.provider,
            pillModels
          );
        }
        updateStatusHeader();
        closeConfigModal();
        showNotice(saveAsNew ? `已另存为新配置：${saved.profile_name || saved.model}` : `已保存配置：${saved.profile_name || saved.model}`);
      } catch (err) {
        if (out) {
          out.className = "ai-cfg-result is-err";
          out.textContent = `保存失败：${err.message}`;
        }
      }
    };

    $("#ai-cfg-save-btn")?.addEventListener("click", () => saveFromModal(false));
    $("#ai-cfg-save-as-btn")?.addEventListener("click", () => saveFromModal(true));

    // Cross-tab "请倪师精讲 ↗" buttons open a dedicated new consultation for current patient cleanly
    document.addEventListener("click", (e) => {
      const askBtn = e.target.closest("[data-ask-ni-kind]");
      if (!askBtn) return;
      e.preventDefault();
      askEntity({
        kind: askBtn.dataset.askNiKind,
        id: decodeURIComponent(askBtn.dataset.askNiId || ""),
        name: decodeURIComponent(askBtn.dataset.askNiName || ""),
        book_id: decodeURIComponent(askBtn.dataset.askNiBookId || ""),
        page_no: Number(askBtn.dataset.askNiPage || 0),
        prompt: decodeURIComponent(askBtn.dataset.askNiPrompt || ""),
      });
    });
  }

  async function activate() {
    if (niState.booted) return;
    niState.booted = true;
    bindEvents();
    renderDimSelector();
    renderSelectedBoard();
    renderPinnedEntity();
    renderVisionStrip();
    renderConversation();

    try {
      const [_, patRes] = await Promise.all([loadConfig(), apiJson("/api/ai/patients")]);
      niState.patients = patRes.patients || [];
      const savedPatId = localStorage.getItem(STORAGE_PATIENT_KEY);
      const savedSesId = localStorage.getItem(STORAGE_SESSION_KEY);
      const initialPatId =
        (savedPatId && niState.patients.some((p) => p.id === savedPatId) ? savedPatId : null) ||
        (niState.patients[0]?.id || null);

      await selectPatient(initialPatId, savedSesId);
    } catch {
      showNotice("工作台初始化异常，仍可本地离线出方");
    }
  }

  async function askEntity(opts = {}) {
    await activate();
    if (typeof window.__tcmSetView === "function") {
      window.__tcmSetView("ai");
    } else {
      document.querySelector('.module-tab[data-view="ai"]')?.click();
    }
    const pinned = {
      kind: opts.kind || "formula",
      id: opts.id || "",
      name: opts.name || opts.id || "当前条目",
      label: opts.label || opts.kind || "经典条目",
      book_id: opts.book_id || "",
      page_no: opts.page_no || 0,
    };
    await createNewSession({ clearPinned: false });
    niState.pinnedEntity = pinned;
    renderPinnedEntity();
    const prompt = opts.prompt || `请倪师结合原典与临床经验，详细讲解「${pinned.name}」的病机、原方用量、煎服法、随症加减与使用禁忌。`;
    await submitConsultation(prompt);
  }

  window.niAI = {
    activate,
    askEntity,
    openConfigModal,
    submitConsultation,
    createNewSession,
  };
})();
