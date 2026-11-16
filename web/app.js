const state = {
  view: "ai",
  formulaQuery: "",
  formulaType: "",
  formulaMeridian: "",
  formulaBook: "",
  formulaStatus: "",
  formulaReview: "",
  formulaPage: 1,
  formulaTotal: 0,
  formulaItems: [],
  selectedFormula: null,
  herbQuery: "",
  herbCategory: "",
  herbPage: 1,
  herbTotal: 0,
  herbItems: [],
  selectedHerb: null,
  sixItems: [],
  selectedSix: null,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

if (!window.tcmImgAttrs) {
  window.tcmImgAttrs = function (apiUrl) {
    return `src="${escapeHtml(apiUrl)}"`;
  };
}

async function request(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error("本地数据读取失败");
  return response.json();
}

function showNotice(message) {
  const node = $("#notice");
  node.textContent = message;
  node.classList.remove("hidden");
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => node.classList.add("hidden"), 2800);
}

function setView(view, skipAutoLoad = false) {
  state.view = view;
  const activeTabView = view === "six" ? "formulas" : view;
  document.querySelectorAll(".module-tab").forEach((button) => {
    const active = button.dataset.view === activeTabView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".top-utility-tab").forEach((button) => {
    button.classList.remove("active");
    button.setAttribute("aria-selected", "false");
  });
  document.querySelectorAll(".module-view").forEach((node) => {
    node.classList.toggle("active", node.id === `${view}-view`);
  });
  if (skipAutoLoad) return;
  if (view === "ai" && window.niAI) window.niAI.activate().catch(() => {});
  if (view === "formulas" && !state.formulaItems.length) loadFormulas(true);
  if (view === "herbs") {
    if (window.bencaoUI) window.bencaoUI.activate().catch(() => showNotice("神农本草读取失败"));
    else if (!state.herbItems.length) loadHerbs(true);
  }
  if (view === "six" && !state.sixItems.length) loadSixChannels(true);
  if (view === "acupuncture" && window.acupunctureUI) window.acupunctureUI.activate().catch(() => {});
  if (view === "neijing" && window.neijingUI) window.neijingUI.activate().catch(() => {});
}
window.__tcmSetView = setView;

function listItem(formula, selected, kind) {
  const { id, name, type, six_meridian, chapter, ingredient_count, locator, page, book, status, status_label, review_status } = formula;
  const selectedClass = selected ? " selected" : "";
  const meta = kind === "herb"
    ? `<span>本经 ${escapeHtml(page)} 页</span>`
    : `<span class="status-pill status-${escapeHtml(status || "complete")}">${escapeHtml(status_label || "味数已核")}</span><span class="status-pill ${review_status === "reviewed" ? "status-reviewed" : "status-pending"}">${review_status === "reviewed" ? "已逐方校" : "待逐方校"}</span><span>${escapeHtml(book)}</span><span>${escapeHtml(type)}</span><span>${escapeHtml(chapter || six_meridian || "未分篇")}</span><span>${escapeHtml(ingredient_count)} 味</span><span>${book === "伤寒论" ? "行" : "页"} ${escapeHtml(locator)}</span>`;
  return `<button class="entity-item${selectedClass}" data-kind="${kind}" data-id="${encodeURIComponent(id)}">
    <span class="entity-name"><strong>${escapeHtml(name)}</strong><em>${kind === "herb" ? "本经" : escapeHtml(book)}</em></span>
    <span class="entity-meta">${meta}</span>
  </button>`;
}

function renderFormulaList() {
  const selectedId = state.selectedFormula?.id;
  $("#formula-list").innerHTML = state.formulaItems.map((item) =>
    listItem(item, selectedId === item.id, "formula")
  ).join("") || `<div class="loading">没有匹配的方剂。</div>`;
  $("#formula-count").textContent = `${state.formulaTotal} 条`;
  $("#formula-more").classList.toggle("hidden", state.formulaItems.length >= state.formulaTotal);
}

function renderHerbList() {
  const listEl = $("#herb-list");
  if (!listEl) return;
  const selectedId = state.selectedHerb?.id;
  listEl.innerHTML = state.herbItems.map((item) =>
    listItem(item, selectedId === item.id, "herb")
  ).join("") || `<div class="loading">没有匹配的中药。</div>`;
  if ($("#herb-count")) $("#herb-count").textContent = `${state.herbTotal} 味`;
  $("#herb-more")?.classList.toggle("hidden", state.herbItems.length >= state.herbTotal);
}

function ctxButtonHtml(label, opts = {}) {
  const attrs = ['type="button"', 'class="text-button ctx-ref-btn"', 'data-ctx-loc="1"'];
  if (opts.bookId) attrs.push(`data-ctx-book="${escapeHtml(opts.bookId)}"`);
  if (opts.pageNo) attrs.push(`data-ctx-page="${escapeHtml(opts.pageNo)}"`);
  if (opts.line) attrs.push(`data-ctx-line="${escapeHtml(opts.line)}"`);
  if (opts.bookHint) attrs.push(`data-ctx-hint="${escapeHtml(opts.bookHint)}"`);
  if (opts.q) attrs.push(`data-ctx-q="${escapeHtml(String(opts.q).slice(0, 24))}"`);
  return `<button ${attrs.join(" ")}>${escapeHtml(label)}</button>`;
}

function parseFirstPageNum(val) {
  const s = String(val || "");
  if (/行/.test(s) && !/页/.test(s)) return { pageNo: 0, line: Number((s.match(/(\d+)/) || [])[1] || 0) };
  return { pageNo: Number((s.match(/(\d+)/) || [])[1] || 0), line: 0 };
}

function renderNeijingRelations(items) {
  if (!items?.length) {
    return `<div class="section-copy">暂无直接对应的《黄帝内经》篇目或专题锚点。</div>`;
  }
  return `<div class="nj-link-grid">${items.map((rel) => {
    const attr = rel.target_kind === "chapter"
      ? `data-nj-jump-chapter="${encodeURIComponent(rel.target_nav_id)}"`
      : `data-nj-jump-concept="${encodeURIComponent(rel.target_nav_id)}"`;
    return `<button type="button" class="nj-rel-btn" ${attr}>
      <div class="nj-link-head">
        <strong>${escapeHtml(rel.canonical_name)}</strong>
        <em>${escapeHtml(rel.submodule_label || rel.chapter_title || "内经")} · ↗</em>
      </div>
      <p>${escapeHtml(rel.rationale || rel.label || "查看《黄帝内经·素问》原文与倪注")}</p>
    </button>`;
  }).join("")}</div>`;
}

function renderModificationsSection(item) {
  const mods = item.modifications || {};
  const asBase = mods.as_base || [];
  const asTarget = mods.as_target || [];
  if (!asBase.length && !asTarget.length) {
    return `<div class="section-block"><div class="section-title">经方加减变化规则</div><div class="section-copy">本方暂无收录结构化原书加减规则条目。</div></div>`;
  }
  const renderModList = (rows, direction) => rows.map((row) => {
    const peerId = direction === "base" ? row.target_formula_id : row.base_formula_id;
    const peerName = direction === "base" ? row.target_formula_name : row.base_formula_name;
    const peerLabel = direction === "base" ? "变化后方" : "出自原方";
    const diffSummary = row.changes?.summary || "";
    return `<div class="s4-mod-card">
      <div class="s4-mod-head">
        <span class="s4-mod-badge">${direction === "base" ? "本方加减化裁" : "由他方化裁而来"}</span>
        <strong>${escapeHtml(row.condition || "条文加减条件见原文")}</strong>
        ${peerId && peerName ? `<button type="button" class="text-button" data-formula-id="${encodeURIComponent(peerId)}">${peerLabel}：${escapeHtml(peerName)} ↗</button>` : ""}
      </div>
      ${diffSummary ? `<div class="s4-mod-diff">变化内容：${escapeHtml(diffSummary)}</div>` : ""}
      ${row.rationale ? `<div class="s4-mod-rationale">原书/倪注理由：${escapeHtml(row.rationale)}</div>` : ""}
      <div class="s4-mod-meta">
        ${row.boundary ? `<span>适用边界：${escapeHtml(row.boundary)}</span>` : ""}
        ${row.source ? `<span>出处：${escapeHtml(typeof row.source === "string" ? row.source : `${row.source.book || ""} ${row.source.ref || ""}`.trim())}</span>` : ""}
        ${ctxButtonHtml("对照原书上下文 ↗", { bookHint: item.book || "伤寒", q: peerName || row.condition || item.name })}
      </div>
    </div>`;
  }).join("");
  return `<div class="section-block">
    <div class="section-heading-row"><div class="section-title">经方加减变化规则（${asBase.length + asTarget.length}）</div></div>
    <div class="s4-mod-list">${renderModList(asBase, "base")}${renderModList(asTarget, "target")}</div>
  </div>`;
}

function renderCrossBookVariantSection(item) {
  const variant = item.cross_book_variant;
  if (!variant) return "";
  const peer = variant.peer_formula || {};
  const exactSame = Boolean(variant.same_composition_and_dose);
  const herbDiff = variant.herb_diff && (variant.herb_diff.only_in_shanghan?.length || variant.herb_diff.only_in_jinkui?.length);
  const diffs = [];
  if (herbDiff) diffs.push("组药不同");
  if ((variant.dose_or_processing_diffs || []).length) diffs.push(`剂量/炮制有 ${variant.dose_or_processing_diffs.length} 处差异`);
  const diffLabel = exactSame ? "两书组成与剂量基本一致" : (diffs.join(" · ") || "两书细节有异，分别保留");
  return `<div class="section-block s4-variant-box">
    <div class="section-heading-row">
      <div class="section-title">《伤寒论》↔《金匮要略》同名方对照</div>
      ${peer.id ? `<button type="button" class="text-button" data-formula-id="${encodeURIComponent(peer.id)}">查看${escapeHtml(peer.book || "另一书")}同名方：${escapeHtml(peer.name || item.name)} ↗</button>` : ""}
    </div>
    <div class="tag-row">
      <span class="status-pill ${exactSame ? "status-reviewed" : "status-variant"}">${escapeHtml(diffLabel)}</span>
    </div>
    ${variant.summary ? `<div class="section-copy">${escapeHtml(variant.summary)}</div>` : ""}
    ${(variant.dose_or_processing_diffs || []).length ? `<ul class="s4-diff-list">${variant.dose_or_processing_diffs.map((d) => `<li>${escapeHtml(typeof d === "string" ? d : `${d.herb || ""}：伤寒【${d.shanghan || "—"}】 vs 金匮【${d.jinkui || "—"}】`)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function renderAcupunctureLinksBlock(item) {
  const links = item.acupuncture_relations || [];
  if (!links.length) return "";
  const KIND_SEG = { acupoint: "points", meridian: "meridians", condition: "conditions", technique: "techniques" };
  return `<div class="section-block">
    <div class="section-title">针灸 / 穴诊 / 误治救治关联（${links.length}）</div>
    <div class="nj-link-grid">${links.map((rel) => {
      const seg = KIND_SEG[rel.target_kind] || "points";
      const highRisk = rel.risk_level === "high_risk" || rel.risk_level === "emergency";
      return `<button type="button" class="nj-rel-btn${highRisk ? " s4-risk-card" : ""}" data-s4-acup-seg="${escapeHtml(seg)}" data-s4-acup-id="${encodeURIComponent(rel.target_id)}">
        <div class="nj-link-head">
          <strong>${escapeHtml(rel.target_name || rel.target_id)}</strong>
          <em>${escapeHtml(rel.relation_kind || "针药关联")} · 赴针灸板块 ↗</em>
        </div>
        ${rel.quote ? `<p>原书引文：${escapeHtml(rel.quote)}</p>` : ""}
        ${rel.note ? `<p>${escapeHtml(rel.note)}</p>` : ""}
      </button>`;
    }).join("")}</div>
  </div>`;
}

function renderChapterAndChannelRef(item) {
  const blocks = [];
  if (item.jinkui_chapter) {
    const ch = item.jinkui_chapter;
    blocks.push(`<button type="button" class="nj-rel-btn" data-s4-jinkui-chapter="${encodeURIComponent(ch.id)}">
      <div class="nj-link-head">
        <strong>《金匮要略》${escapeHtml(ch.name || ch.title || ch.id)}</strong>
        <em>第 ${escapeHtml(ch.order || "")} 篇 · ${escapeHtml(ch.disease_category || "脉证篇目")} ↗</em>
      </div>
      <p>${escapeHtml(ch.summary || "按《金匮要略》原书篇目浏览脉证、治法与同篇方剂")}</p>
    </button>`);
  }
  if (item.six_channel_ref) {
    const sc = item.six_channel_ref;
    blocks.push(`<button type="button" class="nj-rel-btn" data-open-six-dossier="${encodeURIComponent(sc.id)}">
      <div class="nj-link-head">
        <strong>《伤寒论》${escapeHtml(sc.name || sc.id)}</strong>
        <em>含 ${sc.formula_count || ""} 方 · 六经辨证 ↗</em>
      </div>
      <p>${escapeHtml(sc.summary || "查看该经提纲条文、辨证要点与诸方衔接")}</p>
    </button>`);
  }
  if (!blocks.length) return "";
  return `<div class="section-block">
    <div class="section-title">所属原书篇目与辨证纲领</div>
    <div class="nj-link-grid">${blocks.join("")}</div>
  </div>`;
}

function ingredientHtml(item) {
  const name = item.herb_id
    ? `<button class="ingredient-link" data-herb-id="${encodeURIComponent(item.herb_id)}">${escapeHtml(item.name)}</button>`
    : escapeHtml(item.name);
  const processing = String(item.processing || "").trim();
  const processingHtml = processing
    ? `<div class="ingredient-processing">${escapeHtml(processing)}</div>`
    : "";
  const badges = [];
  if (item.herb_risk_level === "emergency") {
    badges.push(`<span class="bc-ing-risk" title="含剧毒或急危偏性，点入查看炮制与禁忌红线">剧毒/慎</span>`);
  }
  if (item.herb_controversy) {
    badges.push(`<span class="bc-ing-cont" title="${escapeHtml(item.herb_controversy)}">基原辨异</span>`);
  }
  const badgeHtml = badges.length ? `<div class="bc-ing-badges">${badges.join("")}</div>` : "";
  return `<div class="ingredient">
    <div class="ingredient-name">${name}</div>
    <div class="ingredient-dose">${escapeHtml(item.dose || "剂量见原文")}</div>
    ${processingHtml}
    ${badgeHtml}
  </div>`;
}

function renderCuratedFormulaDetail(item) {
  const evidence = item.evidence;
  const symptoms = evidence.symptoms || [];
  const overview = evidence.overview || {};
  const reviewLevel = evidence.review_level || (evidence.review_status === "reviewed" ? "完整" : "原文页索引");
  const reviewed = evidence.review_status === "reviewed";
  const related = item.related_herbs?.length
    ? `<div class="tag-row">${item.related_herbs.map((herb) =>
        `<button class="tag" data-herb-id="${encodeURIComponent(herb.id)}">${escapeHtml(herb.name)}</button>`
      ).join("")}</div>`
    : `<div class="section-copy">暂无已建立的本经条目链接。</div>`;
  const proof = evidence.proofreading?.length
    ? evidence.proofreading.map((row) => {
        const parsed = parseFirstPageNum(row.pages || "");
        const hasLoc = parsed.pageNo > 0 || parsed.line > 0;
        const hint = [row.title, row.kind, item.book].filter(Boolean).join(" ");
        return hasLoc
          ? `<button type="button" class="proof-chip is-clickable" data-ctx-loc="1" data-ctx-hint="${escapeHtml(hint)}" ${parsed.pageNo ? `data-ctx-page="${parsed.pageNo}"` : ""} ${parsed.line ? `data-ctx-line="${parsed.line}"` : ""} data-ctx-q="${escapeHtml(item.name)}" title="点击滑动对照原文上下页">${escapeHtml(row.title)} · ${escapeHtml(row.pages || "")} ↗</button>`
          : `<span class="proof-chip">${escapeHtml(row.title)} · ${escapeHtml(row.pages || "")}</span>`;
      }).join("")
    : `<span class="proof-chip">校对依据待补</span>`;
  const origPage0 = (evidence.formula_original?.source_pages || [])[0] || 0;
  const modPage0 = (evidence.usage_modern?.source_pages || [])[0] || origPage0;
  const sixAction = evidence.six_channel?.id
    ? `<button class="text-button" data-open-six-dossier="${encodeURIComponent(evidence.six_channel.id)}">原文与倪注</button>`
    : "";
  const adjunctsHtml = item.adjuncts?.length
    ? `<div class="topic-row"><div class="topic-copy"><div class="section-title">煎服辅料与合煎载体</div><div class="composition-grid">${item.adjuncts.map((adj) =>
        `<div class="ingredient"><div class="ingredient-name">${escapeHtml(adj.name)}</div><div class="ingredient-dose">${escapeHtml(adj.dose || "")}</div>${adj.role ? `<div class="ingredient-processing">${escapeHtml(adj.role)}</div>` : ""}</div>`
      ).join("")}</div></div></div>`
    : "";
  return `<div class="detail-inner curated-detail">
    <div class="detail-kicker">${escapeHtml(item.book)} · ${escapeHtml(reviewLevel)} ${ctxButtonHtml("滑动对照原书上下文 ↗", { bookHint: item.book, pageNo: origPage0, q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)}</h2>
    <p class="detail-subtitle">${escapeHtml(evidence.rationale.summary)}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.book)}</span><span class="status-pill ${reviewed ? "status-reviewed" : "status-pending"}">${reviewed ? "已逐方校" : "原文页索引"}</span><span class="tag">${escapeHtml(item.type)}</span><span class="tag">${escapeHtml(evidence.six_channel.name)}</span><span class="tag">${item.ingredients.length} 味</span></div>

    <div class="section-block top-composition">
      <div class="section-heading-row"><div class="section-title">1. 药物与剂量</div><div class="inline-actions">${ctxButtonHtml("原书上下页对照 ↗", { bookHint: item.book, pageNo: origPage0, q: item.name })}<button class="text-button" data-formula-page="source" data-formula-id="${encodeURIComponent(item.id)}">原方原文</button></div></div>
      <div class="composition-grid">${item.ingredients.map(ingredientHtml).join("")}</div>
    </div>

    <div class="section-block topic-stack s4-decoction-block">
      <div class="section-heading-row"><div class="section-title">2. 熬煮法与煎服规范</div></div>
      ${adjunctsHtml}
      <div class="topic-row">
        <div class="topic-copy"><div class="section-title">古法煎煮与服法</div><div class="section-copy">${escapeHtml(evidence.usage_original.summary)}</div></div>
        <button class="text-button topic-action" data-open-decoction="${encodeURIComponent(item.id)}" data-decoction-mode="ancient">完整古文煎药</button>
      </div>
      <div class="topic-row">
        <div class="topic-copy"><div class="section-title">现代煎药 · 书内原文</div><div class="curated-quote modern-source-quote">${escapeHtml(evidence.usage_modern.source_text)}</div></div>
        <div class="inline-actions">${ctxButtonHtml("书内原文上下文 ↗", { bookHint: item.book, pageNo: modPage0, q: (evidence.usage_modern.source_text || item.name).slice(0, 18) })}<button class="text-button topic-action" data-open-decoction="${encodeURIComponent(item.id)}" data-decoction-mode="modern">整理步骤</button></div>
      </div>
      <div class="warning-box">古籍剂量和煎服法按原文保留，仅供学习核对；不是个人处方。含附子、乌头、巴豆、半夏、甘遂、大戟等剧毒或峻下药味时，必须严守炮制与煎煮时长要求并由专业医师处理。</div>
    </div>

    <div class="section-block">
      <div class="section-title">3. 相关症状与辨证线索</div>
      <div class="symptom-row">${symptoms.map((row) => {
        const sp = parseFirstPageNum(row.page || "");
        const symHint = [item.book, row.source].filter(Boolean).join(" ");
        return sp.pageNo || sp.line
          ? `<button type="button" class="symptom-chip is-clickable" data-ctx-loc="1" data-ctx-hint="${escapeHtml(symHint)}" ${sp.pageNo ? `data-ctx-page="${sp.pageNo}"` : ""} ${sp.line ? `data-ctx-line="${sp.line}"` : ""} data-ctx-q="${escapeHtml(row.name)}" title="点击查看 ${escapeHtml(row.source || item.book)} · 第 ${escapeHtml(row.page)} 页上下文">${escapeHtml(row.name)} <small>p.${escapeHtml(row.page)} ↗</small></button>`
          : `<span class="symptom-chip" title="${escapeHtml(row.source || item.book)} · 第 ${escapeHtml(row.page)} 页">${escapeHtml(row.name)}</span>`;
      }).join("")}</div>
    </div>

    <div class="section-block overview-block">
      <div class="section-title">${escapeHtml(overview.title || "4. 方证摘要与辨证要点")}</div>
      <div class="overview-copy">${(overview.paragraphs || [evidence.rationale.summary]).map((row) => `<p>${escapeHtml(row)}</p>`).join("")}</div>
      <div class="symptom-row overview-keypoints">${(overview.key_points || []).map((row) => `<span class="symptom-chip">${escapeHtml(row)}</span>`).join("")}</div>
    </div>

    <div class="section-block">
      <div class="section-heading-row"><div class="section-title">为什么用 · 方义摘要</div><button class="text-button" data-formula-page="rationale" data-formula-id="${encodeURIComponent(item.id)}">完整倪注</button></div>
      <div class="section-copy">${escapeHtml(evidence.rationale.summary)}</div>
    </div>

    <div class="section-block curated-summary">
      <div class="section-heading-row"><div class="section-title">辨证纲领 · ${escapeHtml(evidence.six_channel.name)}</div>${sixAction}</div>
      <div class="section-copy">${escapeHtml(evidence.six_channel.summary)}</div>
    </div>

    ${renderModificationsSection(item)}
    ${renderCrossBookVariantSection(item)}
    ${renderChapterAndChannelRef(item)}
    ${renderAcupunctureLinksBlock(item)}

    <div class="section-block">
      <div class="section-title">关联《神农本草经》药物</div>
      ${related}
    </div>

    <div class="section-block">
      <div class="section-title">《黄帝内经·素问》理论渊源（${item.neijing_relations?.length || 0}）</div>
      ${renderNeijingRelations(item.neijing_relations)}
    </div>

    <div class="section-block">
      <div class="section-heading-row"><div class="section-title">校对依据</div><button class="text-button" data-formula-page="proof" data-formula-id="${encodeURIComponent(item.id)}">核对记录</button></div>
      <div class="proof-row">${proof}</div>
    </div>
  </div>`;
}

function renderDossier(item) {
  const evidence = item.evidence;
  const original = evidence.six_channel;
  const annotations = original.annotation_original || [];
  const annotationNotes = original.annotations || [];
  const formula = evidence.formula_original;
  const usage = evidence.usage_modern;
  const rationale = evidence.rationale;
  const sources = evidence.proofreading || [];
  const pageReading = evidence.page_reading || [];
  const paragraphs = (rows) => rows.map((row) => `<p>${escapeHtml(row)}</p>`).join("");
  const sourceLabel = (row) => row.pages ? `第 ${escapeHtml(row.pages)} 页` : "";
  const html = `<div class="detail-inner dossier-page">
    <button class="back-to-formula dossier-back" data-close-dossier="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker">逐方校 · 完整证据卡</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · 完整考证</h2>
    <p class="detail-subtitle">${escapeHtml(evidence.editorial_note)}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.book)}</span><span class="status-pill status-reviewed">已逐方校</span><span class="tag">${escapeHtml(original.name)}</span><span class="tag">${item.ingredients.length} 味</span></div>
    <div class="warning-box">原文、倪注、现代解释分栏陈列；现代解释不是原文，也不是面向个人的处方。</div>

    <nav class="dossier-nav" aria-label="完整考证章节">
      <button data-scroll-section="dossier-six">六经辨证</button>
      <button data-scroll-section="dossier-pages">逐页原文</button>
      <button data-scroll-section="dossier-formula">原方与用法</button>
      <button data-scroll-section="dossier-modern">现代解释</button>
      <button data-scroll-section="dossier-notes">倪注与方义</button>
      <button data-scroll-section="dossier-proof">校对依据</button>
    </nav>

    <section id="dossier-six" class="dossier-section">
      <div class="dossier-section-number">01</div>
      <div class="section-heading-row"><h3>六经辨证 · ${escapeHtml(original.name)}</h3><button class="text-button" data-six-id="${encodeURIComponent(original.id)}">打开独立板块</button></div>
      <p class="dossier-lead">${escapeHtml(original.summary)}</p>
      <h4>原文</h4>
      <div class="dossier-quote">${paragraphs(original.original)}</div>
      <h4>原文注解</h4>
      <div class="dossier-notes">${annotations.map((row) =>
        `<article><div class="source-locator"><span>倪海厦伤寒论 · 第 ${escapeHtml(row.page)} 页</span> ${ctxButtonHtml("滑动对照上下页 ↗", { bookId: "ni-shanghan-pdf", pageNo: Number(row.page || 0), q: (row.text || "").slice(0, 18) })}</div><p>${escapeHtml(row.text)}</p></article>`
      ).join("")}</div>
      <h4>理解</h4>
      <div class="dossier-notes">${annotationNotes.map((row) =>
        `<article><h5>${escapeHtml(row.heading)}</h5><p>${escapeHtml(row.text)}</p></article>`
      ).join("")}</div>
    </section>

    <section id="dossier-pages" class="dossier-section">
      <div class="dossier-section-number">02</div>
      <h3>逐页原文与注解</h3>
      <div class="page-reading-list">${pageReading.map((row) =>
        `<article class="page-reading"><div class="page-number"><div>第 ${escapeHtml(row.page)} 页</div>${ctxButtonHtml("上下文滑读 ↗", { bookHint: item.book, pageNo: Number(row.page || 0), q: (row.text || item.name).slice(0, 18) })}</div><div class="page-reading-body"><div class="page-kind">${escapeHtml(row.kind)}</div><h4>${escapeHtml(row.title)}</h4><div class="dossier-quote">${escapeHtml(row.text)}</div><div class="review-note">${escapeHtml(row.annotation)}</div></div></article>`
      ).join("")}</div>
    </section>

    <section id="dossier-formula" class="dossier-section">
      <div class="dossier-section-number">03</div>
      <div class="section-heading-row"><h3>${escapeHtml(formula.title)} · 古文原方</h3>${ctxButtonHtml("原书上下页对照 ↗", { bookHint: item.book, pageNo: (formula.source_pages || [])[0] || 0, q: item.name })}</div>
      <div class="dossier-quote source-quote">${escapeHtml(formula.text)}</div>
      <div class="source-note">${escapeHtml(formula.note)}</div>
      <h4>古文用法</h4>
      <div class="dossier-quote">${escapeHtml(evidence.usage_original.text)}</div>
    </section>

    <section id="dossier-modern" class="dossier-section">
      <div class="dossier-section-number">04</div>
      <h3>现代解释 · 煎服步骤</h3>
      <p class="dossier-lead">${escapeHtml(usage.summary)}</p>
      <ol class="dossier-steps">${usage.steps.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ol>
      <h4>注意</h4>
      <ul class="dossier-warnings">${usage.cautions.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ul>
      <h4>方义整理</h4>
      <div class="dossier-quote">${escapeHtml(rationale.full_text)}</div>
    </section>

    <section id="dossier-notes" class="dossier-section">
      <div class="dossier-section-number">05</div>
      <h3>倪注与方义</h3>
      <div class="dossier-notes">${(evidence.annotations || []).map((row) =>
        `<article><h5>${escapeHtml(row.heading)}</h5><p>${escapeHtml(row.text)}</p></article>`
      ).join("")}</div>
    </section>

    <section id="dossier-proof" class="dossier-section">
      <div class="dossier-section-number">06</div>
      <h3>校对依据</h3>
      <div class="proof-list">${sources.map((row) => {
        const sp = parseFirstPageNum(row.pages || "");
        return `<article><strong>${escapeHtml(row.kind)} · ${escapeHtml(row.title)}</strong><span>${escapeHtml(row.pages || "")}</span><p>${escapeHtml(row.note || "")}</p>${(sp.pageNo || sp.line) ? ctxButtonHtml("原书上下文 ↗", { bookHint: [row.title, row.kind, item.book].filter(Boolean).join(" "), pageNo: sp.pageNo, line: sp.line, q: item.name }) : ""}</article>`;
      }).join("")}</div>
    </section>
  </div>`;
  $("#formula-detail").innerHTML = html;
  return html;
}

function renderDecoctionPage(item, mode) {
  const evidence = item.evidence;
  const isAncient = mode === "ancient";
  const title = isAncient ? "完整古文煎药法" : "现代煎药整理步骤";
  const summary = isAncient ? evidence.usage_original.summary : "本页先列整理步骤，再附书内现代煎药原文。";
  const targetPages = isAncient ? evidence.formula_original.source_pages : evidence.usage_modern.source_pages;
  const body = isAncient
    ? `<div class="dossier-quote source-quote">${escapeHtml(evidence.usage_original.text)}</div><div class="source-note">${escapeHtml(evidence.formula_original.note)}</div>`
    : `<h4>整理步骤</h4><ol class="dossier-steps">${evidence.usage_modern.steps.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ol><h4>注意</h4><ul class="dossier-warnings">${evidence.usage_modern.cautions.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ul><h4>书内现代原文</h4><div class="dossier-quote source-quote">${escapeHtml(evidence.usage_modern.source_text)}</div>`;
  $("#formula-detail").innerHTML = `<div class="detail-inner dossier-page decoction-page">
    <button class="back-to-formula dossier-back" data-close-decoction="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker">煎药法 · ${isAncient ? "古文" : "书内现代解释"} ${ctxButtonHtml("滑动对照原书上下页 ↗", { bookHint: item.book, pageNo: (targetPages || [])[0] || 0, q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · ${title}</h2>
    <p class="detail-subtitle">${escapeHtml(summary)}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.book)}</span><span class="tag">${isAncient ? "古文原文" : "现代解释"}</span><span class="tag">第 ${escapeHtml(targetPages.join("、"))} 页</span></div>
    <div class="warning-box">古籍原文和现代解释分开陈列，不作为个人处方或自行煎服依据。</div>
    ${body}
    <div class="section-block inline-actions">
      <button class="text-button" data-open-decoction="${encodeURIComponent(item.id)}" data-decoction-mode="${isAncient ? "modern" : "ancient"}">${isAncient ? "查看现代煎药整理步骤" : "查看完整古文煎药法"}</button>
    </div>
  </div>`;
}

function renderFormulaSourcePage(item) {
  const evidence = item.evidence;
  const origP = (evidence.formula_original?.source_pages || [])[0] || 0;
  $("#formula-detail").innerHTML = `<div class="detail-inner dossier-page">
    <button class="back-to-formula dossier-back" data-close-formula-page="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker">原方 · 古文原文 ${ctxButtonHtml("滑动对照原书上下页 ↗", { bookHint: item.book, pageNo: origP, q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · 原方原文</h2>
    <div class="tag-row"><span class="tag">${escapeHtml(item.book)}</span><span class="tag">${item.ingredients.length} 味</span></div>
    <div class="warning-box">原文剂量仅供学习核对，不是个人处方。</div>
    <section class="dossier-section"><div class="dossier-section-number">01</div><h3>${escapeHtml(evidence.formula_original.title)}</h3><div class="dossier-quote source-quote">${escapeHtml(evidence.formula_original.text)}</div><div class="source-note">${escapeHtml(evidence.formula_original.note)}</div></section>
    <section class="dossier-section"><div class="dossier-section-number">02</div><h3>原始组成记录</h3><div class="dossier-quote">${escapeHtml(item.composition_raw)}</div></section>
  </div>`;
}

function renderFormulaRationalePage(item) {
  const evidence = item.evidence;
  const annotations = evidence.annotations || [];
  $("#formula-detail").innerHTML = `<div class="detail-inner dossier-page">
    <button class="back-to-formula dossier-back" data-close-formula-page="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker">为什么用 · 倪注与方义 ${ctxButtonHtml("滑动对照原书上下页 ↗", { bookHint: item.book, pageNo: annotations[0]?.source_page || 0, q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · 方义原文</h2>
    <p class="detail-subtitle">${escapeHtml(evidence.rationale.summary)}</p>
    <div class="warning-box">现代整理用于学习，不替代原文和专业辨证。</div>
    <section class="dossier-section"><div class="dossier-section-number">01</div><h3>方义整理</h3><div class="dossier-quote">${escapeHtml(evidence.rationale.full_text)}</div></section>
    <section class="dossier-section"><div class="dossier-section-number">02</div><h3>分项说明</h3><div class="dossier-notes">${annotations.map((row) => `<article><h5>${escapeHtml(row.heading)}</h5><p>${escapeHtml(row.text)}</p><div class="source-locator"><span>第 ${escapeHtml(row.source_page || "")} 页</span> ${row.source_page ? ctxButtonHtml("原书上下文 ↗", { bookHint: item.book, pageNo: Number(row.source_page || 0), q: (row.text || item.name).slice(0, 18) }) : ""}</div></article>`).join("")}</div></section>
  </div>`;
}

function renderFormulaProofPage(item) {
  const evidence = item.evidence;
  const sources = evidence.proofreading || [];
  $("#formula-detail").innerHTML = `<div class="detail-inner dossier-page">
    <button class="back-to-formula dossier-back" data-close-formula-page="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker">校对记录</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · 校对依据</h2>
    <p class="detail-subtitle">${escapeHtml(evidence.editorial_note)}</p>
    <section class="dossier-section"><div class="dossier-section-number">01</div><h3>已核对来源</h3><div class="proof-list">${sources.map((row) => {
      const sp = parseFirstPageNum(row.pages || "");
      return `<article><strong>${escapeHtml(row.kind)} · ${escapeHtml(row.title)}</strong><span>${escapeHtml(row.pages || "")}</span><p>${escapeHtml(row.note || "")}</p>${(sp.pageNo || sp.line) ? ctxButtonHtml("原书上下文 ↗", { bookHint: [row.title, row.kind, item.book].filter(Boolean).join(" "), pageNo: sp.pageNo, line: sp.line, q: item.name }) : ""}</article>`;
    }).join("")}</div></section>
  </div>`;
}

function renderFormulaDetail(item) {
  if (item.evidence?.six_channel && item.evidence?.usage_modern) {
    $("#formula-detail").innerHTML = renderCuratedFormulaDetail(item);
    return;
  }
  const source = item.source || {};
  const evidence = item.evidence || {};
  const status = item.status || "complete";
  const statusLabel = item.status_label || "味数已核";
  const reviewStatus = evidence.review_status || "pending";
  const reviewLabel = reviewStatus === "reviewed" ? "已逐方校" : "待逐方校";
  const context = item.chapter || item.six_meridian || "未分篇";
  const mismatch = item.source_expected_count !== item.source_ingredients.length || status === "variant" || status === "manual";
  const issues = item.quality?.issues || [];
  const issueBox = status !== "complete"
    ? `<div class="warning-box"><strong>${escapeHtml(statusLabel)}</strong>${issues.length ? `<br>${issues.map(escapeHtml).join("；")}` : ""}</div>`
    : "";
  const notes = item.notes
    ? `<div class="section-block"><div class="section-title">条文 / 倪注</div><div class="section-copy">${escapeHtml(item.notes)}</div></div>`
    : "";
  const usage = evidence.usage_plain || item.decoction || "";
  const usageLabel = evidence.usage_status === "reviewed" ? "已校用法" : evidence.usage_status === "missing" ? "原文缺" : "原文摘录";
  const reviewedSources = evidence.review_sources || [];
  const candidateSources = (evidence.candidate_sources?.book || []).map((row) => ({ ...row, kind: "书本候选" }));
  const why = evidence.why
    ? `<div class="section-copy">${escapeHtml(evidence.why)}</div>`
    : `<div class="missing-composition">待逐方校；候选出处暂列于下方。</div>`;
  const bookLocArgs = (row) => {
    const p = parseFirstPageNum(row?.page);
    return {
      bookHint: source.title || item.book || "",
      pageNo: p.pageNo,
      line: p.line,
      q: row?.excerpt ? String(row.excerpt).slice(0, 18) : item.name,
    };
  };
  const reviewedHtml = reviewedSources.length
    ? `<details open><summary>已采用的校对原文（${reviewedSources.length} 条）</summary><div class="evidence-list">${reviewedSources.map((row) =>
        `<article><div class="source-locator"><span>${escapeHtml(row.kind)} · ${escapeHtml(row.title)} · 第 ${escapeHtml(row.page)} 页</span>${ctxButtonHtml("滑动读原文上下文 ↗", bookLocArgs(row))}</div><p>${escapeHtml(row.excerpt)}</p></article>`
      ).join("")}</div></details>`
    : "";
  const candidateHtml = candidateSources.length
    ? `<details><summary>候选原文（未判定，${candidateSources.length} 条）</summary><div class="evidence-list">${candidateSources.map((row) =>
        `<article><div class="source-locator"><span>${escapeHtml(row.kind)} · 第 ${escapeHtml(row.page)} 页</span>${ctxButtonHtml("滑动读原文上下文 ↗", bookLocArgs(row))}</div><p>${escapeHtml(row.excerpt)}</p></article>`
      ).join("")}</div></details>`
    : "";
  const derivative = item.derivative
    ? `<div class="warning-box">加味方：基础方 ${escapeHtml(item.derivative.base)}；加 ${escapeHtml((item.derivative.additions || []).map((row) => row.name).join("、"))}</div>`
    : "";
  const related = item.related_herbs?.length
    ? `<div class="tag-row">${item.related_herbs.map((herb) =>
        `<button class="tag" data-herb-id="${encodeURIComponent(herb.id)}">${escapeHtml(herb.name)}</button>`
      ).join("")}</div>`
    : "";
  const adjuncts = item.adjuncts?.length
    ? `<div class="topic-row"><div class="topic-copy"><div class="section-title">煎服辅料与合煎载体</div><div class="composition-grid">${item.adjuncts.map((adj) =>
        `<div class="ingredient"><div class="ingredient-name">${escapeHtml(adj.name)}</div><div class="ingredient-dose">${escapeHtml(adj.dose)}</div>${adj.role ? `<div class="ingredient-processing">${escapeHtml(adj.role)}</div>` : ""}</div>`
      ).join("")}</div></div></div>`
    : "";
  const variant = mismatch
    ? `<details><summary>查看原文记录（${item.source_ingredients.length} 味）</summary>
       <ul class="variant-list">${item.source_ingredients.map((row) =>
         `<li>${escapeHtml(row.name)} ${escapeHtml(row.dose || "剂量未注")} ${escapeHtml(row.processing || "")}</li>`
       ).join("")}</ul></details>`
    : "";
  const composition = item.ingredients.length
    ? `<div class="composition-grid">${item.ingredients.map(ingredientHtml).join("")}</div>`
    : `<div class="missing-composition">本条目在原始资料中没有可用的组成行。没有用后世人卫资料补写。</div>`;
  const mainSrcOpts = {
    bookHint: source.title || item.book || "",
    pageNo: source.line ? 0 : Number(source.page || 0),
    line: Number(source.line || 0),
    q: item.name,
  };
  $("#formula-detail").innerHTML = `<div class="detail-inner">
    <div class="detail-kicker detail-kicker-row"><span>${escapeHtml(source.title)} · ${source.line ? `第 ${escapeHtml(source.line)} 行` : `第 ${escapeHtml(source.page)} 页`}</span><div class="detail-kicker-actions">${ctxButtonHtml("滑动查原书上下文 ↗", mainSrcOpts)}<button type="button" class="dossier-button ai-ask-btn" data-ask-ni-kind="formula" data-ask-ni-id="${encodeURIComponent(item.id)}" data-ask-ni-name="${encodeURIComponent(item.name)}">请倪师精讲此方 ↗</button></div></div>
    <h2 class="detail-title">${escapeHtml(item.name)}</h2>
    <p class="detail-subtitle">${escapeHtml(item.indication || "条目原文见下方")}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.book || "方剂")}</span><span class="status-pill status-${escapeHtml(status)}">${escapeHtml(statusLabel)}</span><span class="status-pill ${reviewStatus === "reviewed" ? "status-reviewed" : "status-pending"}">${escapeHtml(reviewLabel)}</span><span class="tag">${escapeHtml(item.type)}</span><span class="tag">${escapeHtml(context)}</span><span class="tag">${item.ingredients.length} 味</span></div>
    ${issueBox}
    ${derivative}
    <div class="section-block top-composition">
      <div class="section-title">1. 药物与剂量 · 原文组成</div>
      ${composition}
      ${variant}
    </div>
    <div class="section-block topic-stack s4-decoction-block">
      <div class="section-title">2. 熬煮法与煎服 · ${escapeHtml(usageLabel)}</div>
      ${adjuncts}
      <div class="section-copy">${escapeHtml(usage || "原文未提供可用用法")}</div>
      ${evidence.usage_note ? `<div class="review-note">${escapeHtml(evidence.usage_note)}</div>` : ""}
      <div class="warning-box">古籍剂量与煎服法按原文保留，仅供学习核对；含附子、乌头、巴豆、半夏、甘遂、大戟等剧毒或峻下药味时，须由专业医师按炮制与煎煮规范处理。</div>
    </div>
    <div class="section-block">
      <div class="section-title">3. 为什么用 · 方义与主治（${escapeHtml(reviewLabel)}）</div>
      ${why}
      ${reviewedHtml}
      ${candidateHtml}
    </div>
    ${renderModificationsSection(item)}
    ${renderCrossBookVariantSection(item)}
    ${renderChapterAndChannelRef(item)}
    ${renderAcupunctureLinksBlock(item)}
    <div class="section-block">
      <div class="section-title">关联《神农本草经》药物</div>
      ${related || `<div class="section-copy">暂无已建立的本经条目链接。</div>`}
    </div>
    <div class="section-block">
      <div class="section-title">《黄帝内经·素问》理论渊源（${item.neijing_relations?.length || 0}）</div>
      ${renderNeijingRelations(item.neijing_relations)}
    </div>
    ${notes}
    <div class="section-block">
      <div class="section-title">原文定位</div>
      <div class="source-box"><div class="source-locator"><span>${escapeHtml(source.title)} · ${escapeHtml(source.path)} · ${source.line ? `第 ${escapeHtml(source.line)} 行` : `第 ${escapeHtml(source.page)} 页`}${source.chapter ? ` · ${escapeHtml(source.chapter)}` : ""}</span>${ctxButtonHtml("定位原文上下文 ↗", { ...mainSrcOpts, q: (source.excerpt || item.name || "").slice(0, 18) })}</div><p>${escapeHtml(source.excerpt || source.note || "原文片段未提供")}</p></div>
    </div>
  </div>`;
}

window.__tcmRenderFormulaDetail = renderFormulaDetail;

function renderHerbDetail(item) {
  const detailEl = $("#herb-detail");
  if (!detailEl) return;
  const sections = Object.entries(item.sections || {}).filter(([, value]) => String(value || "").trim());
  const formulas = item.formulas?.length
    ? item.formulas.map((formula) =>
        `<button class="herb-formula-link" data-formula-id="${encodeURIComponent(formula.id)}">${escapeHtml(formula.name)}<small>${escapeHtml(formula.book || "")} · ${escapeHtml(formula.status_label || "")}</small></button>`
      ).join("")
    : `<span class="section-copy">暂无关联方剂。</span>`;
  detailEl.innerHTML = `<div class="detail-inner">
    <div class="detail-kicker detail-kicker-row"><span>倪海厦注神农本草经 · 第 ${escapeHtml(item.page_start)} 页</span>${ctxButtonHtml("滑动查原书上下文 ↗", { bookId: "ni-bencao-pdf", pageNo: Number(item.page_start || 1), q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)}</h2>
    <p class="detail-subtitle">${escapeHtml(item.names?.filter((name) => name !== item.name).join(" · ") || "本经条目")}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.source || "本经")}</span><span class="tag">${formulas ? "有方剂关联" : "暂无方剂关联"}</span></div>
    ${sections.map(([label, value]) => `<div class="section-block"><div class="section-title">${escapeHtml(label)}</div><div class="section-copy">${escapeHtml(value)}</div></div>`).join("")}
    <div class="section-block herb-list-section"><div class="section-title">相关方剂</div><div class="herb-formulas">${formulas}</div></div>
    <div class="section-block"><div class="section-title">《黄帝内经·素问》理论渊源（${item.neijing_relations?.length || 0}）</div>${renderNeijingRelations(item.neijing_relations)}</div>
  </div>`;
}

function renderSixList() {
  const selected = state.selectedSix?.id;
  $("#six-list").innerHTML = state.sixItems.map((item) => `
    <button class="entity-item${selected === item.id ? " selected" : ""}" data-six-id="${encodeURIComponent(item.id)}">
      <span class="entity-name"><strong>${escapeHtml(item.name)}</strong><em>${escapeHtml(item.order)}</em></span>
      <span class="entity-meta"><span class="status-pill ${item.status === "reviewed" ? "status-reviewed" : "status-pending"}">${escapeHtml(item.status_label)}</span><span>${item.annotations.length} 条注解</span><span>${item.related_formula_ids.length} 首关联方</span></span>
    </button>
  `).join("");
  $("#six-count").textContent = `${state.sixItems.length} 经`;
}

function renderSixDetail(item) {
  const symptoms = item.symptoms || [];
  const understanding = item.understanding || [];
  const related = item.related_formula_ids || [];
  const sixPage = Number(item.source_pages?.[0] || 1);
  $("#six-detail").innerHTML = `<div class="detail-inner">
    <div class="detail-kicker detail-kicker-row"><span>六经辨证 · ${escapeHtml(item.name)} · 倪注伤寒第 ${escapeHtml(sixPage)} 页</span>${ctxButtonHtml("滑动读原书上下文 ↗", { bookId: "ni-shanghan-pdf", pageNo: sixPage, q: item.name })}</div>
    <div class="dossier-title-row">
      <div><h2 class="detail-title">${escapeHtml(item.name)}</h2><p class="detail-subtitle">${escapeHtml(item.summary)}</p></div>
      <span class="status-pill ${item.status === "reviewed" ? "status-reviewed" : "status-pending"}">${escapeHtml(item.status_label)}</span>
    </div>
    <div class="warning-box">这是六经辨证学习条目，不替代面诊、脉诊和个体化辨证。</div>
    <div class="section-block">
      <div class="section-heading-row"><div class="section-title">相关症状</div><button class="text-button" data-open-six-dossier="${encodeURIComponent(item.id)}">展开原文与注解</button></div>
      <div class="symptom-row">${symptoms.length ? symptoms.map((row) => `<button type="button" class="symptom-chip is-clickable" data-ctx-loc="1" data-ctx-book="ni-shanghan-pdf" data-ctx-page="${escapeHtml(sixPage)}" data-ctx-q="${escapeHtml(row)}" title="在原书上下文中查找「${escapeHtml(row)}」">${escapeHtml(row)} ↗</button>`).join("") : `<span class="section-copy">待整理。</span>`}</div>
    </div>
    <div class="section-block">
      <div class="section-title">理解总结</div>
      ${understanding.length ? understanding.map((row) => `<article class="six-understanding"><h4>${escapeHtml(row.heading)}</h4><p>${escapeHtml(row.text)}</p></article>`).join("") : `<div class="missing-composition">原文已列，注解与总结待补。</div>`}
    </div>
    <div class="section-block">
      <div class="section-title">关联方剂</div>
      ${related.length ? `<div class="herb-formulas">${related.map((id) => `<button class="herb-formula-link" data-formula-id="${encodeURIComponent(id)}">${escapeHtml(id.split(":").slice(1).join(":"))}</button>`).join("")}</div>` : `<div class="section-copy">关系待接。</div>`}
    </div>
    <div class="section-block">
      <div class="section-title">《黄帝内经·素问》理论渊源（${item.neijing_relations?.length || 0}）</div>
      ${renderNeijingRelations(item.neijing_relations)}
    </div>
    <div class="section-block link-line"><div class="review-note">${escapeHtml(item.review_note || "")}</div></div>
  </div>`;
}

function renderSixDossier(item) {
  const original = item.original || [];
  const annotations = item.annotations || [];
  const understanding = item.understanding || [];
  const related = item.related_formula_ids || [];
  const source = item.source_pages?.length ? `第 ${item.source_pages.join("、")} 页` : "页码待补";
  const sixFirstPage = Number(item.source_pages?.[0] || 1);
  $("#six-detail").innerHTML = `<div class="detail-inner dossier-page">
    <button class="back-to-formula dossier-back" data-close-six-dossier="${encodeURIComponent(item.id)}">← 返回${escapeHtml(item.name)}</button>
    <div class="detail-kicker detail-kicker-row"><span>六经辨证 · 完整原文卡 · 倪注伤寒第 ${escapeHtml(sixFirstPage)} 页</span>${ctxButtonHtml("打开可滑动原书上下文 ↗", { bookId: "ni-shanghan-pdf", pageNo: sixFirstPage, q: item.name })}</div>
    <h2 class="detail-title">${escapeHtml(item.name)} · 原文与注解</h2>
    <p class="detail-subtitle">${escapeHtml(item.summary)}</p>
    <div class="tag-row"><span class="tag">${escapeHtml(item.name)}</span><span class="status-pill ${item.status === "reviewed" ? "status-reviewed" : "status-pending"}">${escapeHtml(item.status_label)}</span></div>
    <div class="warning-box">这是学习条目，不替代面诊、脉诊和个体化辨证。</div>
    <section class="dossier-section">
      <div class="dossier-section-number">01</div>
      <h3>原文</h3>
      <div class="dossier-quote">${original.map((row) => `<p>${escapeHtml(row)}</p>`).join("")}</div>
      <div class="source-note source-locator"><span>${escapeHtml(source)} · ${escapeHtml(item.proof_note || "")}</span>${ctxButtonHtml("滑动对照原书全文 ↗", { bookId: "ni-shanghan-pdf", pageNo: sixFirstPage, q: (original[0] || item.name || "").slice(0, 18) })}</div>
    </section>
    <section class="dossier-section">
      <div class="dossier-section-number">02</div>
      <h3>原文注解</h3>
      ${annotations.length ? `<div class="dossier-notes">${annotations.map((row) => `<article><div class="source-locator"><span>倪海厦伤寒论 · 第 ${escapeHtml(row.page)} 页</span>${ctxButtonHtml("滑动看前后文 ↗", { bookId: "ni-shanghan-pdf", pageNo: Number(row.page || sixFirstPage), q: (row.text || "").slice(0, 18) })}</div><p>${escapeHtml(row.text)}</p></article>`).join("")}</div>` : `<div class="missing-composition">原文已列；注解待补。</div>`}
    </section>
    <section class="dossier-section">
      <div class="dossier-section-number">03</div>
      <h3>理解总结</h3>
      ${understanding.length ? understanding.map((row) => `<article class="six-understanding"><h4>${escapeHtml(row.heading)}</h4><p>${escapeHtml(row.text)}</p></article>`).join("") : `<div class="missing-composition">尚待逐条整理。</div>`}
    </section>
    <section class="dossier-section">
      <div class="dossier-section-number">04</div>
      <h3>关联方剂</h3>
      ${related.length ? `<div class="herb-formulas">${related.map((id) => `<button class="herb-formula-link" data-formula-id="${encodeURIComponent(id)}">${escapeHtml(id.split(":").slice(1).join(":"))}</button>`).join("")}</div>` : `<div class="section-copy">关系待接入。</div>`}
    </section>
    <section class="dossier-section">
      <div class="dossier-section-number">05</div>
      <h3>《黄帝内经·素问》理论渊源（${item.neijing_relations?.length || 0}）</h3>
      ${renderNeijingRelations(item.neijing_relations)}
    </section>
  </div>`;
}

async function loadSixChannels() {
  const data = await request("/api/six-channels");
  state.sixItems = data.items || [];
  renderSixList();
  const dossierDeepLink = /^#\/six\/[^/]+\/dossier$/.test(location.hash);
  if (!state.selectedSix && state.sixItems.length && !dossierDeepLink) {
    const hashMatch = location.hash.match(/^#\/six\/([^/]+)/);
    const target = hashMatch ? decodeURIComponent(hashMatch[1]) : state.sixItems[0].id;
    await selectSix(target);
  }
}

async function selectSix(id) {
  const cached = state.sixItems.find((item) => item.id === id);
  state.selectedSix = cached?.neijing_relations ? cached : await request(`/api/six-channels/${encodeURIComponent(id)}`);
  state.view = "six";
  setView("six");
  location.hash = `#/six/${encodeURIComponent(id)}`;
  renderSixList();
  renderSixDetail(state.selectedSix);
}

function openSix(id) {
  setView("six");
  if (!state.sixItems.length) {
    loadSixChannels().then(() => selectSix(id)).catch(() => showNotice("六经条目读取失败"));
  } else {
    selectSix(id).catch(() => showNotice("六经条目读取失败"));
  }
}

function openSixDossier(id) {
  setView("six");
  const item = state.sixItems.find((row) => row.id === id);
  if (item?.neijing_relations) {
    state.selectedSix = item;
    location.hash = `#/six/${encodeURIComponent(id)}/dossier`;
    renderSixList();
    renderSixDossier(item);
    return;
  }
  request(`/api/six-channels/${encodeURIComponent(id)}`)
    .then((data) => {
      state.selectedSix = data;
      location.hash = `#/six/${encodeURIComponent(id)}/dossier`;
      renderSixDossier(data);
    })
    .catch(() => showNotice("六经原文读取失败"));
}

async function loadFormulas(reset = false) {
  if (reset) {
    state.formulaPage = 1;
    state.formulaItems = [];
    state.selectedFormula = null;
    $("#formula-detail").innerHTML = `<div class="empty-state"><span class="empty-mark">方</span><h2>正在读取方剂目录</h2><p>本地原文正在建立索引。</p></div>`;
  }
  const params = new URLSearchParams({
    q: state.formulaQuery,
    type: state.formulaType,
    meridian: state.formulaMeridian,
    book: state.formulaBook,
    status: state.formulaStatus,
    review: state.formulaReview,
    page: String(state.formulaPage),
    page_size: "30",
  });
  const data = await request(`/api/formulas?${params}`);
  state.formulaTotal = data.total;
  state.formulaItems.push(...data.items);
  renderFormulaList();
  const preservedHash = location.hash.startsWith("#/dossier/") || location.hash.startsWith("#/six/");
  const preserveDecoction = location.hash.includes("/decoction/");
  const preserveFormulaPage = /^#\/formulas\/[^/]+\/(source|rationale|proof)$/.test(location.hash);
  if (!state.selectedFormula && state.formulaItems.length && !preservedHash && !preserveDecoction && !preserveFormulaPage) {
    const hashMatch = location.hash.match(/^#\/formulas\/(.+)$/);
    const targetId = hashMatch ? decodeURIComponent(hashMatch[1]) : state.formulaItems[0].id;
    await selectFormula(targetId);
  }
}

async function loadHerbs(reset = false) {
  if (reset) {
    state.herbPage = 1;
    state.herbItems = [];
    state.selectedHerb = null;
  }
  const params = new URLSearchParams({
    q: state.herbQuery,
    category: state.herbCategory,
    page: String(state.herbPage),
    page_size: "30",
  });
  const data = await request(`/api/herbs?${params}`);
  state.herbTotal = data.total;
  state.herbItems.push(...data.items);
  renderHerbList();
  if (!state.selectedHerb && state.herbItems.length) {
    const hashMatch = location.hash.match(/^#\/herbs\/(.+)$/);
    const targetId = hashMatch ? decodeURIComponent(hashMatch[1]) : state.herbItems[0].id;
    await selectHerb(targetId);
  }
}

async function selectFormula(id) {
  state.selectedFormula = await request(`/api/formulas/${encodeURIComponent(id)}`);
  if (state.view !== "formulas") setView("formulas");
  location.hash = `#/formulas/${encodeURIComponent(id)}`;
  renderFormulaList();
  renderFormulaDetail(state.selectedFormula);
}

async function selectHerb(id) {
  state.selectedHerb = await request(`/api/herbs/${encodeURIComponent(id)}`);
  state.view = "herbs";
  setView("herbs");
  location.hash = `#/herbs/${encodeURIComponent(id)}`;
  renderHerbList();
  renderHerbDetail(state.selectedHerb);
}

function openHerb(id) {
  setView("herbs", true);
  if (window.bencaoUI) {
    window.bencaoUI.openEntry(id).catch(() => showNotice("该药味暂无本经条目"));
    return;
  }
  selectHerb(id).catch(() => showNotice("该药味暂无本经条目"));
}

function openFormula(id) {
  setView("formulas");
  selectFormula(id).catch(() => showNotice("该方剂暂时无法读取"));
}

async function openDossier(id) {
  state.selectedFormula = await request(`/api/formulas/${encodeURIComponent(id)}`);
  state.dossierFormula = state.selectedFormula;
  setView("formulas");
  location.hash = `#/dossier/${encodeURIComponent(id)}`;
  renderDossier(state.selectedFormula);
}

async function openDecoction(id, mode) {
  state.selectedFormula = await request(`/api/formulas/${encodeURIComponent(id)}`);
  setView("formulas");
  location.hash = `#/formulas/${encodeURIComponent(id)}/decoction/${mode}`;
  renderDecoctionPage(state.selectedFormula, mode);
}

async function openFormulaPage(id, page) {
  state.selectedFormula = await request(`/api/formulas/${encodeURIComponent(id)}`);
  setView("formulas");
  location.hash = `#/formulas/${encodeURIComponent(id)}/${page}`;
  if (page === "source") renderFormulaSourcePage(state.selectedFormula);
  if (page === "rationale") renderFormulaRationalePage(state.selectedFormula);
  if (page === "proof") renderFormulaProofPage(state.selectedFormula);
}

function closeDossier(id) {
  location.hash = `#/formulas/${encodeURIComponent(id)}`;
  renderFormulaDetail(state.selectedFormula);
}

function closeDecoction(id) {
  location.hash = `#/formulas/${encodeURIComponent(id)}`;
  renderFormulaDetail(state.selectedFormula);
}

function closeFormulaPage(id) {
  location.hash = `#/formulas/${encodeURIComponent(id)}`;
  renderFormulaDetail(state.selectedFormula);
}

function debounce(fn, wait = 180) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

document.querySelectorAll(".module-tab").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

$("#formula-query").addEventListener("input", debounce((event) => {
  state.formulaQuery = event.target.value.trim();
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
}));
$("#formula-type").addEventListener("change", (event) => {
  state.formulaType = event.target.value;
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-book").addEventListener("change", (event) => {
  state.formulaBook = event.target.value;
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-status").addEventListener("change", (event) => {
  state.formulaStatus = event.target.value;
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-review").addEventListener("change", (event) => {
  state.formulaReview = event.target.value;
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-meridian").addEventListener("change", (event) => {
  state.formulaMeridian = event.target.value;
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-clear").addEventListener("click", () => {
  state.formulaQuery = "";
  state.formulaType = "";
  state.formulaMeridian = "";
  state.formulaBook = "";
  state.formulaStatus = "";
  state.formulaReview = "";
  $("#formula-query").value = "";
  $("#formula-type").value = "";
  $("#formula-meridian").value = "";
  $("#formula-book").value = "";
  $("#formula-status").value = "";
  $("#formula-review").value = "";
  loadFormulas(true).catch(() => showNotice("方剂目录读取失败"));
});
$("#formula-more").addEventListener("click", () => {
  state.formulaPage += 1;
  loadFormulas().catch(() => showNotice("方剂目录读取失败"));
});
$("#herb-query")?.addEventListener("input", debounce((event) => {
  state.herbQuery = event.target.value.trim();
  loadHerbs(true).catch(() => showNotice("药物目录读取失败"));
}));
$("#herb-category")?.addEventListener("change", (event) => {
  state.herbCategory = event.target.value;
  loadHerbs(true).catch(() => showNotice("药物目录读取失败"));
});
$("#herb-clear")?.addEventListener("click", () => {
  state.herbQuery = "";
  state.herbCategory = "";
  if ($("#herb-query")) $("#herb-query").value = "";
  if ($("#herb-category")) $("#herb-category").value = "";
  loadHerbs(true).catch(() => showNotice("药物目录读取失败"));
});
$("#herb-more")?.addEventListener("click", () => {
  state.herbPage += 1;
  loadHerbs().catch(() => showNotice("药物目录读取失败"));
});
$("#formula-list").addEventListener("click", (event) => {
  const item = event.target.closest("[data-kind='formula']");
  if (item) selectFormula(decodeURIComponent(item.dataset.id)).catch(() => showNotice("方剂读取失败"));
});
$("#herb-list")?.addEventListener("click", (event) => {
  const item = event.target.closest("[data-kind='herb']");
  if (item) selectHerb(decodeURIComponent(item.dataset.id)).catch(() => showNotice("药物读取失败"));
});
document.addEventListener("click", (event) => {
  const switchBtn = event.target.closest("[data-switch-view]");
  if (switchBtn) {
    event.preventDefault();
    setView(switchBtn.dataset.switchView);
    return;
  }
  const njConceptJump = event.target.closest("[data-nj-jump-concept]");
  if (njConceptJump) {
    event.preventDefault();
    const tid = decodeURIComponent(njConceptJump.dataset.njJumpConcept);
    setView("neijing", true);
    window.neijingUI?.openConcept?.(tid).catch(() => showNotice("内经专题读取失败"));
    return;
  }
  const njChapterJump = event.target.closest("[data-nj-jump-chapter]");
  if (njChapterJump) {
    event.preventDefault();
    const cid = decodeURIComponent(njChapterJump.dataset.njJumpChapter);
    setView("neijing", true);
    window.neijingUI?.openChapter?.(cid).catch(() => showNotice("内经篇目读取失败"));
    return;
  }
  const herbLink = event.target.closest("[data-herb-id]");
  if (herbLink) {
    event.preventDefault();
    openHerb(decodeURIComponent(herbLink.dataset.herbId));
  }
  const formulaLink = event.target.closest("[data-formula-id]");
  if (formulaLink && !formulaLink.dataset.formulaPage) {
    event.preventDefault();
    openFormula(decodeURIComponent(formulaLink.dataset.formulaId));
  }
  const dossierButton = event.target.closest("[data-open-dossier]");
  if (dossierButton) {
    event.preventDefault();
    openDossier(decodeURIComponent(dossierButton.dataset.openDossier)).catch(() => showNotice("完整考证读取失败"));
  }
  const closeButton = event.target.closest("[data-close-dossier]");
  if (closeButton) {
    event.preventDefault();
    closeDossier(decodeURIComponent(closeButton.dataset.closeDossier));
  }
  const scrollButton = event.target.closest("[data-scroll-section]");
  if (scrollButton) {
    const section = document.getElementById(scrollButton.dataset.scrollSection);
    const panel = section?.closest(".detail-panel");
    if (section && panel) {
      const top = section.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop - 8;
      panel.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }
  }
  const sixLink = event.target.closest("[data-six-id]");
  if (sixLink) {
    event.preventDefault();
    openSix(decodeURIComponent(sixLink.dataset.sixId));
  }
  const decoctionButton = event.target.closest("[data-open-decoction]");
  if (decoctionButton) {
    event.preventDefault();
    openDecoction(decodeURIComponent(decoctionButton.dataset.openDecoction), decoctionButton.dataset.decoctionMode || "ancient").catch(() => showNotice("煎药法读取失败"));
  }
  const closeDecoctionButton = event.target.closest("[data-close-decoction]");
  if (closeDecoctionButton) {
    event.preventDefault();
    closeDecoction(decodeURIComponent(closeDecoctionButton.dataset.closeDecoction));
  }
  const formulaPageButton = event.target.closest("[data-formula-page]");
  if (formulaPageButton) {
    event.preventDefault();
    openFormulaPage(decodeURIComponent(formulaPageButton.dataset.formulaId), formulaPageButton.dataset.formulaPage).catch(() => showNotice("原文页读取失败"));
  }
  const closeFormulaPageButton = event.target.closest("[data-close-formula-page]");
  if (closeFormulaPageButton) {
    event.preventDefault();
    closeFormulaPage(decodeURIComponent(closeFormulaPageButton.dataset.closeFormulaPage));
  }
  const sixDossierButton = event.target.closest("[data-open-six-dossier]");
  if (sixDossierButton) {
    event.preventDefault();
    openSixDossier(decodeURIComponent(sixDossierButton.dataset.openSixDossier));
  }
  const closeSixDossier = event.target.closest("[data-close-six-dossier]");
  if (closeSixDossier) {
    event.preventDefault();
    openSix(decodeURIComponent(closeSixDossier.dataset.closeSixDossier));
  }
});
window.addEventListener("hashchange", () => {
  const dossierMatch = location.hash.match(/^#\/dossier\/(.+)$/);
  if (dossierMatch) {
    openDossier(decodeURIComponent(dossierMatch[1])).catch(() => {});
    return;
  }
  const sixDossierMatch = location.hash.match(/^#\/six\/([^/]+)\/dossier$/);
  if (sixDossierMatch) {
    openSixDossier(decodeURIComponent(sixDossierMatch[1]));
    return;
  }
  const sixMatch = location.hash.match(/^#\/six\/(.+)$/);
  if (sixMatch) {
    openSix(decodeURIComponent(sixMatch[1]));
    return;
  }
  const decoctionMatch = location.hash.match(/^#\/formulas\/([^/]+)\/decoction\/(ancient|modern)$/);
  if (decoctionMatch) {
    openDecoction(decodeURIComponent(decoctionMatch[1]), decoctionMatch[2]).catch(() => {});
    return;
  }
  const formulaPageMatch = location.hash.match(/^#\/formulas\/([^/]+)\/(source|rationale|proof)$/);
  if (formulaPageMatch) {
    openFormulaPage(decodeURIComponent(formulaPageMatch[1]), formulaPageMatch[2]).catch(() => {});
    return;
  }
  if (location.hash === "#/ai" || location.hash.startsWith("#/ai/")) {
    setView("ai");
    return;
  }
  if (location.hash === "#/acupuncture" || location.hash.startsWith("#/acupuncture/")) {
    setView("acupuncture");
    window.acupunctureUI?.handleHash(location.hash).catch(() => {});
    return;
  }
  if (location.hash === "#/herbs" || location.hash.startsWith("#/herbs/")) {
    setView("herbs", true);
    window.bencaoUI?.handleHash(location.hash).catch(() => {});
    return;
  }
  if (location.hash === "#/neijing" || location.hash.startsWith("#/neijing/")) {
    setView("neijing", true);
    window.neijingUI?.handleHash(location.hash).catch(() => {});
    return;
  }
  const match = location.hash.match(/^#\/(formulas|herbs)\/(.+)$/);
  if (!match) return;
  const [, kind, id] = match;
  if (kind === "formulas") openFormula(decodeURIComponent(id));
  if (kind === "herbs") openHerb(decodeURIComponent(id));
});

async function boot() {
  const hash = location.hash.match(/^#\/(ai|acupuncture|herbs|neijing|formulas|six|dossier)(?:\/|$)/);
  const isStage5Hash =
    location.hash.startsWith("#/library") || location.hash.startsWith("#/stage5");
  if (hash?.[1] === "acupuncture") setView("acupuncture", true);
  else if (hash?.[1] === "herbs") setView("herbs", true);
  else if (hash?.[1] === "neijing") setView("neijing", true);
  else if (hash?.[1] === "six") setView("six", true);
  else if (hash?.[1] === "formulas" || hash?.[1] === "dossier") setView("formulas", true);
  else if (!isStage5Hash) setView("ai", true);

  let aiBootPromise = null;
  if (!isStage5Hash && state.view === "ai") {
    aiBootPromise = Promise.resolve(window.niAI?.activate());
  }

  try {
    const overview = await request("/api/overview");
    const shanghan = overview.by_book?.["伤寒论"] || 0;
    const jinkui = overview.by_book?.["金匮要略"] || 0;
    const reviewed = overview.review_status?.reviewed || 0;
    const acup = overview.acupuncture_summary;
    const bc = overview.bencao_summary;
    const nj = overview.neijing_summary?.stats;
    const acupNote = acup ? ` · 针灸 ${acup.meridians?.approved || 0}经/${acup.acupoints?.approved || 0}穴/${acup.techniques?.approved || 0}法/${acup.conditions?.approved || 0}症` : "";
    const bcNote = bc ? ` · 本草 ${bc.edition_total || 385}味(${bc.main_classic_total || 357}正经+${bc.chapter3_supplement_count || 28}增补)/${bc.comparisons_count || 38}对照` : ` · ${overview.herbs} 味药`;
    const njNote = nj ? ` · 内经 ${nj.approved_chapters || 0}/${nj.total_chapters || 74}篇/${nj.total_concepts || 0}专题` : "";
    $("#dataset-note").textContent = `v0.1.0 构建版（持续优化中） · ${overview.formulas} 条方 · 伤寒 ${shanghan} / 金匮 ${jinkui} · 逐方校 ${reviewed}/${overview.formulas}${acupNote}${bcNote}${njNote}`;
    if (isStage5Hash) {
      await window.libraryStage5?.handleHash(location.hash);
      return;
    }

    if (aiBootPromise) {
      await aiBootPromise;
    }
    if (state.view === "acupuncture") {
      if (location.hash.startsWith("#/acupuncture/")) {
        await window.acupunctureUI?.handleHash(location.hash);
      } else {
        await window.acupunctureUI?.activate();
      }
    }
    if (state.view === "neijing") {
      if (location.hash.startsWith("#/neijing/")) {
        await window.neijingUI?.handleHash(location.hash);
      } else {
        await window.neijingUI?.activate();
      }
    }
    if (state.view === "formulas") {
      await loadFormulas(true);
    }
    const decoctionHash = location.hash.match(/^#\/formulas\/([^/]+)\/decoction\/(ancient|modern)$/);
    if (decoctionHash) await openDecoction(decodeURIComponent(decoctionHash[1]), decoctionHash[2]);
    const formulaPageHash = location.hash.match(/^#\/formulas\/([^/]+)\/(source|rationale|proof)$/);
    if (formulaPageHash) await openFormulaPage(decodeURIComponent(formulaPageHash[1]), formulaPageHash[2]);
    const dossierHash = location.hash.match(/^#\/dossier\/(.+)$/);
    if (dossierHash) await openDossier(decodeURIComponent(dossierHash[1]));
    if (hash?.[1] === "six") {
      await loadSixChannels();
      const sixDossierHash = location.hash.match(/^#\/six\/([^/]+)\/dossier$/);
      if (sixDossierHash) openSixDossier(decodeURIComponent(sixDossierHash[1]));
    }
    if (state.view === "herbs") {
      if (location.hash.startsWith("#/herbs/")) {
        await window.bencaoUI?.handleHash(location.hash);
      } else if (window.bencaoUI) {
        await window.bencaoUI.activate();
      } else {
        await loadHerbs(true);
      }
    }
  } catch (error) {
    showNotice("本地目录未启动或数据缺失");
  }
}

boot();
