/* Huangdi Neijing Stage 3 workbench: Doctrinal sub-modules, 74-chapter Suwen inventory & full-page source viewer */
(function initNeijingModule() {
  const njState = {
    booted: false,
    dim: "concepts", // "diagnose" | "concepts" | "chapters" | "pages"
    submodule: "",
    volume: "",
    query: "",
    reviewFilter: "",
    riskFilter: "",
    overview: null,
    diagnoseResult: null,
    concepts: [],
    chapters: [],
    editionInventory: null,
    pageHits: [],
    selectedKind: "", // "concept" | "chapter" | "page" | "inventory"
    selectedId: "",
    selectedPage: null,
    showPageImage: false,
  };

  const REV_LABEL = { approved: "已审定", pending: "目录锚定·待精校", needs_changes: "待修订", rejected: "已弃用" };
  const EV_LABEL = { verified: "逐字已核", anchored: "已锚定页码", unlinked: "未锚定", conflicted: "存在分歧" };
  const GEN_LABEL = { assisted: "人机协校", manual: "人工整理", auto: "自动提取" };
  const RISK_LABEL = { standard: "常规医理", high_risk: "危重/高敏边界", emergency: "急症警示" };
  const ROLE_LABEL = {
    source_quote: "讲记引《素问》原句",
    ni_teaching: "倪海厦讲授与临床阐述",
    other_annotations: "历代注家与他篇互参",
    collation_notes: "版本校勘与转录注记",
    organizer_summary: "整理归纳说明",
  };
  const REL_LABEL = {
    grounds_theory: "理论出处",
    guides_differentiation: "辨证指导",
    corresponds_to_channel: "衔接六经",
    corresponds_to_meridian: "衔接经络",
    supports_acupoint: "衔接穴位",
    relates_condition: "关联治症",
    illuminates_formula: "启迪经方",
    contextualizes_herb: "关联本草",
    paired_doctrine: "对举互参",
    contrasts_with: "辨异对照",
    relates_chapter: "关联篇目",
  };
  const MOD_BADGE = {
    neijing: "《内经》",
    acupuncture: "针灸",
    six_channels: "六经",
    formulas: "伤寒经方",
    jinkui_formulas: "金匮经方",
    herbs: "神农本草",
  };

  const qEl = (sel) => document.querySelector(sel);

  function esc(val) {
    return String(val ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function req(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`请求失败 (${res.status})`);
    return res.json();
  }

  function showNjError(err) {
    const detail = qEl("#nj-detail");
    const msg = err?.message || "黄帝内经数据读取失败";
    if (detail) {
      detail.innerHTML = `<div class="detail-inner"><div class="acup-safety-banner acup-banner-risk"><strong>加载提示</strong><p>${esc(msg)}</p></div></div>`;
    }
  }

  function statusBadges(item, includeReview = true) {
    const rev = item.review_status || "pending";
    const ev = item.evidence_status || "anchored";
    const gen = item.generation_status || "auto";
    const risk = item.risk_level || "standard";
    const revCls = rev === "approved" ? "acup-pill-approved" : "acup-pill-pending";
    const riskCls = risk === "emergency" ? "acup-pill-emergency" : (risk === "high_risk" ? "acup-pill-risk" : "acup-pill-std");
    return `<div class="acup-status-row">
      ${includeReview ? `<span class="acup-pill ${revCls}">${esc(REV_LABEL[rev] || rev)}</span>` : ""}
      <span class="acup-pill acup-pill-ev">${esc(EV_LABEL[ev] || ev)}</span>
      <span class="acup-pill acup-pill-gen">${esc(GEN_LABEL[gen] || gen)}</span>
      <span class="acup-pill ${riskCls}">${esc(RISK_LABEL[risk] || risk)}</span>
    </div>`;
  }

  function renderLayers(layers) {
    if (!layers) return "";
    const order = ["source_quote", "ni_teaching", "other_annotations", "collation_notes", "organizer_summary"];
    const blocks = order
      .filter((key) => Array.isArray(layers[key]) && layers[key].length)
      .map(
        (key) => `<div class="acup-layer-card acup-layer-${key}">
          <h4>${esc(ROLE_LABEL[key] || key)}</h4>
          <ul>${layers[key].map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
        </div>`
      )
      .join("");
    return blocks ? `<div class="acup-layers-grid">${blocks}</div>` : "";
  }

  function renderOpenQuestions(questions) {
    if (!questions || !questions.length) return "";
    return `<div class="section-block acup-open-box">
      <div class="section-title">尚待考证与进一步校补</div>
      <ul>${questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
    </div>`;
  }

  function renderSpans(spans) {
    if (!spans || !spans.length) return "";
    return `<div class="section-block">
      <div class="section-title">原书证据锚点（点击直达对应页文稿与原书影印）</div>
      <div class="acup-spans-list">${spans
        .map(
          (sp) => `<div class="acup-span-card">
            <div class="acup-span-head">
              <strong>${esc(sp.chapter_path || sp.page_id)}</strong>
              <span>${sp.source_id === "ni-neijing-vol1-pdf" ? "上册" : "下册"} · PDF p.${esc(sp.pdf_page)}${sp.printed_page ? `（印制 p.${esc(sp.printed_page)}）` : ""}</span>
              <button class="acup-span-btn" type="button" data-nj-page="${esc(sp.source_id)}:${esc(sp.pdf_page)}">打开第 ${esc(sp.pdf_page)} 页</button>
              <button class="acup-span-btn ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="${esc(sp.source_id)}" data-ctx-page="${esc(sp.pdf_page)}" data-ctx-q="${esc((sp.quote || "").slice(0, 22))}">上下文滑动对照 ↗</button>
            </div>
            <blockquote>${esc(sp.quote)}</blockquote>
          </div>`
        )
        .join("")}</div>
    </div>`;
  }

  function crossLinkHref(moduleKey, targetId) {
    const enc = encodeURIComponent(targetId);
    if (moduleKey === "acupuncture") {
      if (targetId.startsWith("meridian:")) return `#/acupuncture/meridians/${enc}`;
      if (targetId.startsWith("acupoint:")) return `#/acupuncture/points/${enc}`;
      if (targetId.startsWith("cond:")) return `#/acupuncture/conditions/${enc}`;
      if (targetId.startsWith("tech:")) return `#/acupuncture/techniques/${enc}`;
      return "#/acupuncture";
    }
    if (moduleKey === "six_channels") return `#/six/${enc}`;
    if (moduleKey === "formulas" || moduleKey === "jinkui_formulas") return `#/formulas/${enc}`;
    if (moduleKey === "herbs") return `#/herbs/${enc}`;
    return "#/neijing";
  }

  function renderClassicLinksAndRelations(classicLinks, relations) {
    const extCards = [];
    const seenExt = new Set();
    for (const lk of classicLinks || []) {
      const mod = lk.target_module;
      const tid = lk.target_id;
      if (!mod || !tid || mod === "neijing") continue;
      seenExt.add(`${mod}:${tid}`);
      extCards.push(`<a class="nj-link-card" href="${crossLinkHref(mod, tid)}">
        <div class="nj-link-head">
          <span class="acup-pill acup-pill-approved">${esc(MOD_BADGE[mod] || mod)}</span>
          <strong>${esc(lk.label || lk.peer?.canonical_name || tid)}</strong>
          <em>直达模块 ↗</em>
        </div>
        <p>${esc(lk.rationale || "")}</p>
      </a>`);
    }
    for (const r of relations || []) {
      const mod = r.peer?.module;
      const tid = r.peer?.id;
      if (!mod || !tid || mod === "neijing" || seenExt.has(`${mod}:${tid}`)) continue;
      seenExt.add(`${mod}:${tid}`);
      extCards.push(`<a class="nj-link-card" href="${crossLinkHref(mod, tid)}">
        <div class="nj-link-head">
          <span class="acup-pill acup-pill-approved">${esc(MOD_BADGE[mod] || mod)}</span>
          <strong>${esc(r.peer?.canonical_name || r.label || tid)}</strong>
          <em>直达模块 ↗</em>
        </div>
        <p>${esc(r.rationale || r.label || "")}</p>
      </a>`);
    }

    const internalRels = (relations || []).filter((r) => r.peer?.module === "neijing");
    const relCards = internalRels.map((r) => {
      const peer = r.peer || {};
      const actionAttr = peer.chapter_id
        ? `data-nj-open-chapter="${esc(peer.chapter_id)}"`
        : `data-nj-open-concept="${esc(peer.id)}"`;
      return `<button type="button" class="nj-rel-btn" ${actionAttr}>
        <div class="nj-link-head">
          <span class="acup-pill acup-pill-ev">${esc(REL_LABEL[r.relation_type] || r.relation_type)}</span>
          <strong>${esc(peer.canonical_name || r.label)}</strong>
        </div>
        <p>${esc(r.rationale || r.label || "")}</p>
      </button>`;
    });

    let html = "";
    if (extCards.length) {
      html += `<div class="section-block">
        <div class="section-title">经典关联 · 跨模块直达（针灸 · 六经 · 伤寒金匮经方 · 神农本草）</div>
        <div class="nj-link-grid">${extCards.join("")}</div>
      </div>`;
    }
    if (relCards.length) {
      html += `<div class="section-block">
        <div class="section-title">《内经》篇目与对举互参关联</div>
        <div class="nj-link-grid">${relCards.join("")}</div>
      </div>`;
    }
    return html;
  }

  function renderEditionInventoryDetail() {
    const ov = njState.overview;
    const inv = ov?.edition_inventory || {};
    const stats = ov?.stats || {};
    const detail = qEl("#nj-detail");
    if (!detail) return;
    const missing = (inv.missing_suwen_chapters || [])
      .map(
        (m) =>
          `<li><strong>《素问》第 ${esc(m.suwen_number ?? m.number)} 篇 ${esc(m.classic_title || m.standard_title)}</strong> — ${esc(m.note || m.reason)}</li>`
      )
      .join("");
    const quirks = (inv.reordered_and_artifact_notes || []).map((q) => `<li>${esc(q)}</li>`).join("");
    const submodules = (ov?.submodules || [])
      .map(
        (sm) => `<button type="button" class="acup-chip-btn" data-nj-jump-sub="${esc(sm.id)}">${esc(sm.label)}（${esc(sm.count)} 专题）</button>`
      )
      .join("");

    detail.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">第三阶段 · 《黄帝内经》全本真实版本清点与规划全览</div>
      <h2 class="detail-title">${esc(ov?.collection_title || "《黄帝内经》理论与诊法")}</h2>
      <p class="detail-subtitle">${esc(ov?.scope_note || "")}</p>

      <div class="acup-safety-banner acup-banner-info">
        <strong>诚实分母声明（严格核对本地双册 PDF）</strong>
        <p>本地馆藏仅包含 <strong>《黄帝内经·素问》</strong> DVD 视频同步整理讲记（${esc(inv.total_pdf_pages || 306)} PDF页 / 印制 ${esc(inv.total_printed_pages || 301)} 页），<strong>未收录《灵枢》</strong>。已实收 ${esc(inv.unique_suwen_numbers_included || 72)} 篇独立《素问》篇号（共 ${esc(inv.toc_chapter_entries || 74)} 条篇目、${esc(stats.total_sections || 283)} 节），其中已精校 ${esc(stats.approved_chapters || 24)} 篇基石支柱与 ${esc(stats.total_concepts || 17)} 个专题（覆盖 6 大理论与辨证子模块、${esc(stats.total_relations || 112)} 条已验证双向关联），其余 ${esc(stats.pending_chapters || 50)} 篇保持目录锚定待精校。</p>
      </div>

      <div class="section-block">
        <div class="section-title">六大理论与辨证专题入口</div>
        <div class="acup-quick-chips">${submodules}</div>
      </div>

      <div class="section-block">
        <div class="section-title">馆藏缺失的 9 篇《素问》篇号明细（不作虚构填充）</div>
        <ul class="nj-bullet-list">${missing}</ul>
      </div>

      <div class="section-block">
        <div class="section-title">编排错简与转录特征核记</div>
        <ul class="nj-bullet-list">${quirks}</ul>
      </div>
    </div>`;
  }

  function renderSubbar() {
    const subbar = qEl("#nj-subbar");
    const volWrap = qEl("#nj-volume-wrap");
    if (subbar) {
      subbar.classList.toggle("hidden", njState.dim !== "concepts" && njState.dim !== "diagnose");
    }
    if (volWrap) {
      volWrap.classList.toggle("hidden", njState.dim === "concepts" || njState.dim === "diagnose");
    }
    document.querySelectorAll("[data-nj-dim]").forEach((btn) => {
      const act = btn.dataset.njDim === njState.dim;
      btn.classList.toggle("active", act);
      btn.setAttribute("aria-selected", act ? "true" : "false");
    });
    document.querySelectorAll("[data-nj-sub]").forEach((btn) => {
      const act = btn.dataset.njSub === njState.submodule;
      btn.classList.toggle("active", act);
      btn.setAttribute("aria-selected", act ? "true" : "false");
    });
  }

  function renderDiagnoseList() {
    const listEl = qEl("#nj-list");
    const d = njState.diagnoseResult;
    qEl("#nj-list-title").textContent = "辨证论治推演";
    if (!d) {
      qEl("#nj-list-subtitle").textContent = "症状 / 病机 / 脉象推演";
      qEl("#nj-count").textContent = "—";
      listEl.innerHTML = `<div class="loading">正在加载推演引擎…</div>`;
      return;
    }
    const concepts = d.concepts || [];
    const chapters = d.chapters || [];
    const pages = d.matched_pages || [];
    qEl("#nj-list-subtitle").textContent = d.query
      ? `命中 ${d.matched_concepts_count} 专题 · ${d.matched_chapters_count} 篇目 · ${pages.length} 原页`
      : `核心专题 ${concepts.length} · 纲领篇目 ${chapters.length}`;
    qEl("#nj-count").textContent = `${concepts.length + chapters.length} 项`;

    const cGroup = concepts.length
      ? `<div class="acup-tree-group">
          <div class="acup-tree-group-head"><span>理论与辨证依据（${concepts.length}）</span></div>
          ${concepts.map((c, idx) => `<button type="button" class="entity-item" data-nj-scroll="nj-diag-concept-${idx}">
            <span class="entity-name"><strong>${esc(c.canonical_name)}</strong><em>${esc(c.submodule_label)}</em></span>
            <span class="entity-meta"><span>${(c.matched_rules || []).length} 条判据</span>${c.risk_level === "high_risk" ? `<span class="acup-pill acup-pill-risk">高敏</span>` : ""}</span>
          </button>`).join("")}
        </div>`
      : "";
    const chGroup = chapters.length
      ? `<div class="acup-tree-group">
          <div class="acup-tree-group-head"><span>《素问》原书篇目（${chapters.length}）</span></div>
          ${chapters.map((ch, idx) => `<button type="button" class="entity-item" data-nj-scroll="nj-diag-ch-${idx}">
            <span class="entity-name"><strong>${esc(ch.title)}</strong><em>${esc(ch.volume_label)}</em></span>
            <span class="entity-meta"><span>印 p.${esc(ch.printed_page_start)}–${esc(ch.printed_page_end)}</span></span>
          </button>`).join("")}
        </div>`
      : "";
    const pgGroup = pages.length
      ? `<div class="acup-tree-group">
          <div class="acup-tree-group-head"><span>原书全文命中页（${pages.length}）</span></div>
          ${pages.map((pg) => `<button type="button" class="entity-item" data-nj-page="${esc(pg.source_id)}:${esc(pg.pdf_page)}">
            <span class="entity-name"><strong>${esc(pg.volume_label)} PDF p.${esc(pg.pdf_page)}</strong><em>印 p.${esc(pg.printed_page)}</em></span>
            <span class="entity-meta"><span>${esc((pg.matched_chapters || [pg.section_headings?.[0] || "原文"]).join(" / "))}</span></span>
          </button>`).join("")}
        </div>`
      : "";

    listEl.innerHTML = cGroup + chGroup + pgGroup || `<div class="loading">未命中对应条文，请换用症状、脉象或经典关键词重试。</div>`;
  }

  function renderDiagnoseDetail() {
    const detail = qEl("#nj-detail");
    const d = njState.diagnoseResult;
    if (!d) return;
    const chips = (d.prompt_chips || [])
      .map((ex) => `<button type="button" class="acup-chip-btn" data-nj-set-q="${esc(ex)}">${esc(ex)}</button>`)
      .join("");
    const riskCls = d.has_high_risk ? "acup-banner-risk" : "acup-banner-info";
    const bannerTitle = d.has_high_risk ? "高敏与危重脉证警示" : "内经理论与临床学习边界";

    const conceptsHtml = (d.concepts || []).length
      ? `<div class="section-block">
          <div class="section-title">核心辨证纲要与法则推演（${d.concepts.length} 项）</div>
          ${d.concepts.map((c, idx) => `<article id="nj-diag-concept-${idx}" class="acup-pattern-card">
            <div class="acup-pattern-head">
              <h4><span>0${idx + 1}</span> ${esc(c.canonical_name)} <small style="font-weight:400;color:var(--muted);">· ${esc(c.submodule_label)}</small></h4>
              <button type="button" class="text-button" data-nj-open-concept="${esc(c.id)}">查看专题全文</button>
            </div>
            <div class="acup-pattern-body">
              ${c.safety_warning ? `<div class="acup-safety-banner acup-banner-risk"><p>${esc(c.safety_warning)}</p></div>` : ""}
              <p><strong>纲领摘要：</strong>${esc(c.summary)}</p>
              ${c.classic_text ? `<p><strong>《素问》引文：</strong>${esc(c.classic_text)}</p>` : ""}
              ${c.ni_interpretation ? `<p><strong>倪海厦讲解：</strong>${esc(c.ni_interpretation)}</p>` : ""}
              ${(c.matched_rules || []).length ? `<div class="nj-rule-list">${c.matched_rules.map((r) => `
                <div class="nj-rule-box">
                  <div><strong>辨证条件：</strong>${esc(r.condition)}</div>
                  <div><strong>推演结论：</strong>${esc(r.conclusion)}</div>
                  ${(r.key_signs || []).length ? `<div class="symptom-row" style="margin-top:4px;">${r.key_signs.map((s) => `<span class="symptom-chip">${esc(s)}</span>`).join("")}</div>` : ""}
                  ${r.classical_basis ? `<div style="margin-top:4px;font-size:12px;color:var(--muted);"><strong>依据：</strong>${esc(r.classical_basis)}</div>` : ""}
                </div>`).join("")}</div>` : ""}
              ${(c.resolved_chapters || []).length ? `<div class="acup-quick-chips" style="margin-top:8px;">${c.resolved_chapters.map((ch) => `<button type="button" class="acup-chip-btn" data-nj-open-chapter="${esc(ch.id)}">${esc(ch.title)}</button>`).join("")}</div>` : ""}
            </div>
          </article>`).join("")}
        </div>`
      : "";

    const modOrder = [
      ["formulas", "伤寒经方"],
      ["jinkui_formulas", "金匮经方"],
      ["herbs", "神农本草"],
      ["acupuncture", "针灸经络与取穴"],
      ["six_channels", "六经辨证"],
    ];
    const extItems = [];
    for (const [modKey, modLabel] of modOrder) {
      for (const item of d.cross_module_links?.[modKey] || []) {
        extItems.push(`<a class="nj-link-card" href="${crossLinkHref(modKey, item.id)}">
          <div class="nj-link-head">
            <span class="acup-pill acup-pill-approved">${esc(modLabel)}</span>
            <strong>${esc(item.canonical_name)}</strong>
            <em>直达模块 ↗</em>
          </div>
          <p>${esc(item.from_title ? `由「${item.from_title}」推衍：` : "")}${esc(item.rationale || item.label || "")}</p>
        </a>`);
      }
    }
    const crossHtml = extItems.length
      ? `<div class="section-block">
          <div class="section-title">跨模块联合论证（内经理论 → 经方 / 本草 / 针灸 / 六经，共 ${extItems.length} 项）</div>
          <div class="nj-link-grid">${extItems.join("")}</div>
        </div>`
      : "";

    const chaptersHtml = (d.chapters || []).length
      ? `<div class="section-block">
          <div class="section-title">《素问》原书篇目与分节原文依据（${d.chapters.length} 篇）</div>
          ${d.chapters.map((ch, idx) => `<article id="nj-diag-ch-${idx}" class="acup-pattern-card">
            <div class="acup-pattern-head">
              <h4><span>0${idx + 1}</span> ${esc(ch.title)} <small style="font-weight:400;color:var(--muted);">· ${esc(ch.volume_label)} 印 p.${esc(ch.printed_page_start)}–${esc(ch.printed_page_end)}</small></h4>
              <div class="inline-actions">
                <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(ch.source_id || "")}" data-ctx-page="${esc(ch.pdf_page_start || 0)}" data-ctx-hint="${esc(ch.volume_label || "黄帝内经")}" data-ctx-q="${esc(ch.title)}">上下文滑读 ↗</button>
                <button type="button" class="text-button" data-nj-open-chapter="${esc(ch.id)}">按篇精读全篇</button>
              </div>
            </div>
            <div class="acup-pattern-body">
              <p>${esc(ch.summary)}</p>
              ${(ch.matched_sections || []).map((s) => `<div class="nj-sec-detail">
                <div class="nj-sec-detail-head">
                  <strong>${esc(s.heading)}</strong>
                  ${s.printed_page_range ? `<span>印 p.${esc(s.printed_page_range)}</span>` : ""}
                  <button type="button" class="acup-span-btn ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(ch.source_id || "")}" data-ctx-page="${esc(s.pdf_page_start || ch.pdf_page_start || 0)}" data-ctx-hint="${esc(ch.volume_label || "黄帝内经")}" data-ctx-q="${esc((s.source_quote || s.heading || "").slice(0, 20))}">对照原文上下文 ↗</button>
                </div>
                ${s.source_quote ? `<p><strong>原文：</strong>${esc(s.source_quote)}</p>` : ""}
                ${s.ni_teaching ? `<p><strong>倪注：</strong>${esc(s.ni_teaching)}</p>` : ""}
                ${s.organizer_summary ? `<p><strong>整理：</strong>${esc(s.organizer_summary)}</p>` : ""}
              </div>`).join("")}
            </div>
          </article>`).join("")}
        </div>`
      : "";

    detail.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">黄帝内经·素问 · 症状与病机辨证论治推演</div>
      <h2 class="detail-title">${d.query ? `推演结果：${esc(d.query)}` : "《黄帝内经·素问》辨证论治推演工作台"}</h2>
      <p class="detail-subtitle">依《素问》74 篇全本已校精读与 34 题六大理论专题实时匹配，贯通经方、金匮、神农本草与针灸取穴。</p>
      <div class="acup-diag-hero">
        <div class="section-title" style="margin-bottom:6px;">常见临床证候 / 病机推演示例（点击即查，或在上方搜索框输入症状组合）</div>
        <div class="acup-quick-chips">${chips}</div>
      </div>
      <div class="acup-safety-banner ${riskCls}"><strong>${bannerTitle}</strong><p>${esc(d.safety_banner || d.historical_boundary_note)}</p></div>
      ${conceptsHtml}
      ${crossHtml}
      ${chaptersHtml}
    </div>`;
  }

  function renderConceptList() {
    const list = qEl("#nj-list");
    const items = njState.concepts || [];
    qEl("#nj-list-title").textContent = "理论与辨证专题";
    qEl("#nj-list-subtitle").textContent = "八纲辨证 · 阴阳五行 · 藏象 · 病因病机 · 诊法 · 养生";
    qEl("#nj-count").textContent = `${items.length} 条`;

    if (!items.length) {
      list.innerHTML = `<div class="loading">没有匹配的专题条目，可放宽检索条件或点击“重置”。</div>`;
      return;
    }
    list.innerHTML = items
      .map((item) => {
        const sel = njState.selectedKind === "concept" && njState.selectedId === item.id ? " selected" : "";
        return `<button type="button" class="entity-item${sel}" data-nj-open-concept="${esc(item.id)}">
          <span class="entity-name">
            <strong>${esc(item.canonical_name)}</strong>
            <em>${esc(item.submodule_label)}</em>
          </span>
          <span class="entity-meta">
            <span>${esc(item.doctrine_key)}</span>
            <span>规则 ${esc(item.rule_count)}</span>
            <span>经典关联 ${esc(item.link_count)}</span>
            ${item.risk_level !== "standard" ? `<span class="status-pill status-pending">${esc(RISK_LABEL[item.risk_level] || item.risk_level)}</span>` : ""}
          </span>
        </button>`;
      })
      .join("");
  }

  function renderChapterList() {
    const list = qEl("#nj-list");
    const items = njState.chapters || [];
    const approvedCount = items.filter((c) => c.review_status === "approved").length;
    qEl("#nj-list-title").textContent = "《素问》分卷目录";
    qEl("#nj-list-subtitle").textContent = `实收72篇/74条 · 已精校 ${approvedCount} · 未收灵枢`;
    qEl("#nj-count").textContent = `${items.length} 篇目`;

    const headerNotice = `<button type="button" class="nj-inventory-pill${njState.selectedKind === "inventory" ? " active" : ""}" data-nj-inventory="1">
      📋 查看版次清点（缺《素问》9篇 · 未收《灵枢》）
    </button>`;

    if (!items.length) {
      list.innerHTML = headerNotice + `<div class="loading">没有匹配的篇目，请调整分册或关键词。</div>`;
      return;
    }

    const cards = items
      .map((ch) => {
        const sel = njState.selectedKind === "chapter" && njState.selectedId === ch.id ? " selected" : "";
        const pillCls = ch.review_status === "approved" ? "status-reviewed" : "status-pending";
        const pillText = ch.review_status === "approved" ? "已精校" : "待精校";
        return `<button type="button" class="entity-item${sel}" data-nj-open-chapter="${esc(ch.id)}">
          <span class="entity-name">
            <strong>${esc(ch.title)}</strong>
            <em>${esc(ch.volume_label)} · 印p.${esc(ch.printed_page_start)}–${esc(ch.printed_page_end)}</em>
          </span>
          <span class="entity-meta">
            <span class="status-pill ${pillCls}">${pillText}</span>
            <span>${esc(ch.classic_standard_title)}</span>
            <span>${esc(ch.total_sections)} 节</span>
            ${ch.risk_level !== "standard" ? `<span>高敏边界</span>` : ""}
          </span>
        </button>`;
      })
      .join("");

    list.innerHTML = headerNotice + cards;
  }

  function renderPagesList() {
    const list = qEl("#nj-list");
    const hits = njState.pageHits || [];
    qEl("#nj-list-title").textContent = "原书全文页检索";
    qEl("#nj-list-subtitle").textContent = "上册 152 页 + 下册 154 页（共 306 PDF 页）";
    qEl("#nj-count").textContent = `${hits.length} 页`;

    if (!hits.length) {
      list.innerHTML = `<div class="loading">没有匹配的原书页面，可换简短关键词检索。</div>`;
      return;
    }
    list.innerHTML = hits
      .map((row) => {
        const sel = njState.selectedKind === "page" && njState.selectedId === row.page_id ? " selected" : "";
        const heading = (row.chapter_headings && row.chapter_headings[0]) || (row.section_headings && row.section_headings[0]) || row.header || "正文页面";
        return `<button type="button" class="entity-item${sel}" data-nj-page="${esc(row.source_id)}:${esc(row.pdf_page)}">
          <span class="entity-name">
            <strong>${esc(row.volume_label)} · PDF p.${esc(row.pdf_page)}${row.printed_page ? `（印p.${esc(row.printed_page)}）` : ""}</strong>
            <em>${esc(heading)}</em>
          </span>
          <span class="entity-meta">
            <span>${esc(row.snippet || "")}</span>
          </span>
        </button>`;
      })
      .join("");
  }

  function renderConceptDetail(item) {
    const detail = qEl("#nj-detail");
    const warn = item.safety_warning
      ? `<div class="acup-safety-banner acup-banner-risk"><strong>危重边界与医疗界限</strong><p>${esc(item.safety_warning)}</p></div>`
      : "";
    const boundary = item.historical_boundary_note
      ? `<div class="acup-safety-banner acup-banner-info"><strong>古典理论边界声明（非现代临床循证定论）</strong><p>${esc(item.historical_boundary_note)}</p></div>`
      : "";

    const rulesHtml = (item.differentiation_rules || [])
      .map(
        (rule, idx) => `<div class="acup-pattern-card">
          <div class="acup-pattern-head">
            <h4><span>0${idx + 1}</span>${esc(rule.condition)}</h4>
          </div>
          <div class="acup-pattern-body">
            <p><strong>表现特征：</strong>${esc(rule.manifestations)}</p>
            <p><strong>传统辨别与治法思路：</strong>${esc(rule.traditional_judgment)}</p>
            <p><strong>原书凭据：</strong>${esc(rule.classic_basis)}</p>
          </div>
        </div>`
      )
      .join("");

    const chaptersChips = (item.resolved_chapters || [])
      .map(
        (c) => `<button type="button" class="acup-chip-btn" data-nj-open-chapter="${esc(c.id)}">${esc(c.title)}（${esc(c.volume_label)} 印p.${esc(c.printed_page_start)}–${esc(c.printed_page_end)}）</button>`
      )
      .join("");

    const firstSpan = item.source_spans?.[0] || item.resolved_chapters?.[0] || {};
    const firstCtxPage = firstSpan.pdf_page || firstSpan.pdf_page_start || 0;
    const firstCtxBook = firstSpan.source_id || "";
    detail.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker detail-kicker-row">
        <span>理论专题 · ${esc(item.submodule_label)} · ${esc(item.doctrine_key)}</span>
        ${firstCtxPage || item.canonical_name ? `<button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(firstCtxBook)}" data-ctx-page="${esc(firstCtxPage)}" data-ctx-hint="黄帝内经" data-ctx-q="${esc(item.canonical_name)}">原书上下文滑读 ↗</button>` : ""}
      </div>
      <h2 class="detail-title">${esc(item.canonical_name)}</h2>
      <p class="detail-subtitle">${esc(item.summary)}</p>
      ${statusBadges(item)}
      ${warn}
      ${boundary}

      ${chaptersChips ? `<div class="section-block">
        <div class="section-title">依托《素问》讲记篇目（点击直达精读）</div>
        <div class="acup-quick-chips">${chaptersChips}</div>
      </div>` : ""}

      <div class="section-block">
        <div class="section-title">辨证原则与结构化判读规则</div>
        ${rulesHtml}
      </div>

      <div class="section-block">
        <div class="section-title">严格分层整理（经典引文 vs 倪海厦讲授 vs 版本校注）</div>
        ${renderLayers(item.content_layers)}
      </div>

      ${renderOpenQuestions(item.open_questions)}
      ${renderClassicLinksAndRelations(item.classic_links, item.relations)}
      ${renderSpans(item.source_spans)}
    </div>`;
  }

  function renderChapterDetail(ch) {
    const detail = qEl("#nj-detail");
    const pass = ch.passage || {};
    const warn = pass.safety_warning
      ? `<div class="acup-safety-banner acup-banner-risk"><strong>危重与高敏边界提示</strong><p>${esc(pass.safety_warning)}</p></div>`
      : "";
    const boundary = pass.historical_boundary_note
      ? `<div class="acup-safety-banner acup-banner-info"><strong>版本与古典理论边界说明</strong><p>${esc(pass.historical_boundary_note)}</p></div>`
      : "";

    const keyPoints = (pass.key_points || []).length
      ? `<div class="section-block">
          <div class="section-title">本篇核心纲领与要义</div>
          <ul class="nj-bullet-list">${pass.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>
        </div>`
      : "";

    const conceptChips = (ch.related_concepts || []).length
      ? `<div class="section-block">
          <div class="section-title">归属理论与辨证专题（点击互参）</div>
          <div class="acup-quick-chips">${ch.related_concepts
            .map(
              (c) => `<button type="button" class="acup-chip-btn" data-nj-open-concept="${esc(c.id)}">${esc(c.submodule_label)} · ${esc(c.canonical_name)}</button>`
            )
            .join("")}</div>
        </div>`
      : "";

    const sectionNotesHtml = (pass.section_notes || []).length
      ? `<div class="section-block">
          <div class="section-title">逐节原文、倪师讲授与整理详解（${pass.section_notes.length} 节）</div>
          <div class="nj-sec-detail-list">${pass.section_notes
            .map(
              (s) => `<article class="nj-sec-detail">
                <div class="nj-sec-detail-head">
                  <strong>${esc(s.heading)}</strong>
                  <span>${s.printed_page_range ? `印 p.${esc(s.printed_page_range)}` : ""}</span>
                  ${s.pdf_page_start ? `<button type="button" class="acup-span-btn" data-nj-page="${esc(ch.source_id)}:${esc(s.pdf_page_start)}">PDF p.${esc(s.pdf_page_start)}</button>` : ""}
                  <button type="button" class="acup-span-btn ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(ch.source_id)}" data-ctx-page="${esc(s.pdf_page_start || ch.pdf_page_start || 0)}" data-ctx-q="${esc((s.source_quote || s.heading || "").slice(0, 20))}">上下文滑动对照 ↗</button>
                </div>
                ${s.source_quote ? `<p><strong>《素问》引文：</strong>${esc(s.source_quote)}</p>` : ""}
                ${s.ni_teaching ? `<p><strong>倪海厦讲授：</strong>${esc(s.ni_teaching)}</p>` : ""}
                ${s.organizer_summary ? `<p><strong>整理摘要：</strong>${esc(s.organizer_summary)}</p>` : ""}
              </article>`
            )
            .join("")}</div>
        </div>`
      : "";

    const navBarHtml = ch.prev_chapter || ch.next_chapter
      ? `<div class="nj-prev-next-bar">
          ${ch.prev_chapter ? `<button type="button" class="acup-span-btn" data-nj-open-chapter="${esc(ch.prev_chapter.id)}">← 上一篇：${esc(ch.prev_chapter.title)}</button>` : `<span></span>`}
          ${ch.next_chapter ? `<button type="button" class="acup-span-btn" data-nj-open-chapter="${esc(ch.next_chapter.id)}">下一篇：${esc(ch.next_chapter.title)} →</button>` : `<span></span>`}
        </div>`
      : "";

    const sectionsHtml = (ch.sections || []).length
      ? `<div class="section-block">
          <div class="section-title">本篇原书子节目录（共 ${ch.sections.length} 节 · 点击查看对应页文本与影印）</div>
          <div class="nj-sections-list">${ch.sections
            .map(
              (s) => `<div class="nj-sec-row-wrap">
                <button type="button" class="nj-sec-row" data-nj-page="${esc(s.source_id)}:${esc(s.pdf_page_start)}">
                  <strong>${esc(s.title)}</strong>
                  <span>${esc(s.volume_label)} PDF p.${esc(s.pdf_page_start)}–${esc(s.pdf_page_end)}（印制 p.${esc(s.printed_page_start)}–${esc(s.printed_page_end)}）</span>
                </button>
                <button type="button" class="acup-span-btn ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(s.source_id)}" data-ctx-page="${esc(s.pdf_page_start)}" data-ctx-q="${esc(s.title)}">上下文滑读 ↗</button>
              </div>`
            )
            .join("")}</div>
        </div>`
      : "";

    const pagesHtml = (ch.pages_preview || []).length
      ? `<div class="section-block">
          <div class="section-title">原书页面实录预览（全篇 ${ch.pages_preview.length} 页 · 点击打开完整原文与高清扫描页）</div>
          <div class="acup-spans-list">${ch.pages_preview
            .map(
              (p) => `<div class="acup-span-card">
                <div class="acup-span-head">
                  <strong>${esc(p.page_id)}（PDF p.${esc(p.pdf_page)} / 印p.${esc(p.printed_page)}）</strong>
                  <div class="inline-actions">
                    <button type="button" class="acup-span-btn" data-nj-page="${esc(p.source_id)}:${esc(p.pdf_page)}">查阅全页与扫描图</button>
                    <button type="button" class="acup-span-btn ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(p.source_id)}" data-ctx-page="${esc(p.pdf_page)}" data-ctx-q="${esc((p.excerpt || ch.title || "").slice(0, 18))}">上下文连续滑读 ↗</button>
                  </div>
                </div>
                <blockquote>${esc(p.excerpt)}…</blockquote>
              </div>`
            )
            .join("")}</div>
        </div>`
      : "";

    detail.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">${esc(ch.volume_label)} · ${esc(ch.classic_standard_title)} · PDF p.${esc(ch.pdf_page_start)}–${esc(ch.pdf_page_end)}（印制 p.${esc(ch.printed_page_start)}–${esc(ch.printed_page_end)}） <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(ch.source_id)}" data-ctx-page="${esc(ch.pdf_page_start || 1)}" data-ctx-q="${esc(ch.title)}">全篇上下文滑读 ↗</button></div>
      <h2 class="detail-title">${esc(ch.title)}</h2>
      <p class="detail-subtitle">${esc(pass.summary || "")}</p>
      ${statusBadges(pass)}
      ${navBarHtml}
      ${ch.collation_note ? `<div class="acup-safety-banner acup-banner-risk"><strong>版本与题名校记</strong><p>${esc(ch.collation_note)}</p></div>` : ""}
      ${warn}
      ${boundary}
      ${conceptChips}
      ${keyPoints}
      <div class="section-block">
        <div class="section-title">严格分层整理</div>
        ${renderLayers(pass.content_layers)}
      </div>
      ${sectionNotesHtml}
      ${renderOpenQuestions(pass.open_questions)}
      ${renderClassicLinksAndRelations([], ch.relations)}
      ${sectionsHtml}
      ${renderSpans(pass.source_spans)}
      ${pagesHtml}
      ${navBarHtml}
    </div>`;
  }

  function renderSourcePageDetail(page) {
    const detail = qEl("#nj-detail");
    const src = page.source_id;
    const num = Number(page.pdf_page);
    const maxP = src === "ni-neijing-vol1-pdf" ? 152 : 154;
    const prevBtn = num > 1
      ? `<button type="button" class="acup-span-btn" data-nj-page="${esc(src)}:${num - 1}">← 上一页</button>`
      : "";
    const nextBtn = num < maxP
      ? `<button type="button" class="acup-span-btn" data-nj-page="${esc(src)}:${num + 1}">下一页 →</button>`
      : "";

    const covHtml = (page.covering_chapters || [])
      .map(
        (c) => `<button type="button" class="acup-chip-btn" data-nj-open-chapter="${esc(c.chapter_id)}">${esc(c.title)}（${esc(c.classic_standard_title)}）</button>`
      )
      .join("");

    const quotesHtml = (page.quoted_classic_fragments || []).length
      ? `<div class="section-block">
          <div class="section-title">本页提取的引号引文片段（仅供参考校对）</div>
          <div class="acup-quick-chips">${page.quoted_classic_fragments.map((q) => `<span class="tag">“${esc(q)}”</span>`).join("")}</div>
        </div>`
      : "";

    const imgSection = njState.showPageImage
      ? `<div class="acup-page-img-wrap">
          <img ${window.tcmImgAttrs ? window.tcmImgAttrs(page.image_url) : `src="${esc(page.image_url)}"`} alt="${esc(page.volume_label)} PDF 第 ${num} 页高清扫描图">
        </div>`
      : "";

    detail.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">${esc(page.volume_label)} · ${esc(page.page_id)} · ${esc(page.ocr_status || "clean_digital")}</div>
      <h2 class="detail-title">原书第 ${num} PDF 页${page.printed_page ? `（印制第 ${esc(page.printed_page)} 页）` : ""}</h2>
      <div class="acup-quick-chips" style="margin-top:8px;">
        ${prevBtn}
        ${nextBtn}
        <button type="button" class="acup-chip-btn" data-nj-toggle-img="${esc(src)}:${num}">${njState.showPageImage ? "隐藏原书扫图" : "查看原书 PDF 扫图对照"}</button>
      </div>
      ${covHtml ? `<div class="section-block"><div class="section-title">所属篇目</div><div class="acup-quick-chips">${covHtml}</div></div>` : ""}
      ${imgSection}
      ${quotesHtml}
      <div class="section-block">
        <div class="section-title">原页清洗全文（保留换行）</div>
        <pre class="acup-page-body nj-pre">${esc(page.body_text || page.raw_text || "")}</pre>
      </div>
    </div>`;
  }

  async function refreshListAndRender() {
    renderSubbar();
    const q = encodeURIComponent((njState.query || "").trim());
    const rev = encodeURIComponent(njState.reviewFilter || "");
    const risk = encodeURIComponent(njState.riskFilter || "");
    if (njState.dim === "diagnose") {
      const sub = encodeURIComponent(njState.submodule || "");
      const data = await req(`/api/neijing/diagnose?q=${q}&submodule=${sub}&risk_level=${risk}`);
      njState.diagnoseResult = data;
      renderDiagnoseList();
      renderDiagnoseDetail();
    } else if (njState.dim === "concepts") {
      const sub = encodeURIComponent(njState.submodule || "");
      const data = await req(`/api/neijing/concepts?q=${q}&submodule=${sub}&review_status=${rev}&risk_level=${risk}`);
      njState.concepts = data.items || [];
      renderConceptList();
      if (!njState.selectedKind || njState.selectedKind === "inventory") {
        if (njState.concepts.length && (njState.query || njState.submodule)) {
          await openConcept(njState.concepts[0].id, true);
        } else {
          renderEditionInventoryDetail();
        }
      }
    } else if (njState.dim === "chapters") {
      const vol = encodeURIComponent(njState.volume || "");
      const data = await req(`/api/neijing/chapters?q=${q}&volume=${vol}&review_status=${rev}&risk_level=${risk}`);
      njState.chapters = data.items || [];
      njState.editionInventory = data.edition_inventory;
      renderChapterList();
      if (njState.selectedKind === "inventory" || !njState.selectedKind) {
        renderEditionInventoryDetail();
      }
    } else {
      const vol = encodeURIComponent(njState.volume || "");
      const data = await req(`/api/neijing/pages?q=${q}&volume=${vol}&limit=80`);
      njState.pageHits = data.items || [];
      renderPagesList();
      if (njState.selectedKind !== "page") {
        if (njState.pageHits.length) {
          await openSourcePage(njState.pageHits[0].source_id, njState.pageHits[0].pdf_page, true);
        } else {
          renderEditionInventoryDetail();
        }
      }
    }
  }

  async function openConcept(conceptId, skipHash = false) {
    const item = await req(`/api/neijing/concepts/${encodeURIComponent(conceptId)}`);
    njState.dim = "concepts";
    njState.selectedKind = "concept";
    njState.selectedId = conceptId;
    renderSubbar();
    renderConceptList();
    renderConceptDetail(item);
    if (!skipHash) {
      location.hash = `#/neijing/concepts/${encodeURIComponent(conceptId)}`;
    }
  }

  async function openChapter(chapterId, skipHash = false) {
    if (!njState.chapters.length) {
      const data = await req("/api/neijing/chapters");
      njState.chapters = data.items || [];
    }
    const ch = await req(`/api/neijing/chapters/${encodeURIComponent(chapterId)}`);
    njState.dim = "chapters";
    njState.selectedKind = "chapter";
    njState.selectedId = chapterId;
    renderSubbar();
    renderChapterList();
    renderChapterDetail(ch);
    if (!skipHash) {
      location.hash = `#/neijing/chapters/${encodeURIComponent(chapterId)}`;
    }
  }

  async function openSourcePage(sourceId, pdfPage, skipHash = false) {
    const page = await req(`/api/neijing/source-pages/${encodeURIComponent(sourceId)}/${Number(pdfPage)}`);
    njState.selectedKind = "page";
    njState.selectedId = page.page_id;
    njState.selectedPage = page;
    renderSourcePageDetail(page);
    if (njState.dim === "pages") {
      renderPagesList();
    }
    if (!skipHash) {
      location.hash = `#/neijing/page/${encodeURIComponent(sourceId)}/${Number(pdfPage)}`;
    }
  }

  async function ensureLoaded() {
    if (njState.booted) return;
    bindEvents();
    njState.overview = await req("/api/neijing/overview");
    njState.booted = true;
  }

  async function activate() {
    await ensureLoaded();
    await refreshListAndRender();
  }

  async function handleHash(hashStr) {
    await ensureLoaded();
    if (!hashStr || hashStr === "#/neijing" || hashStr === "#/neijing/") {
      njState.dim = "concepts";
      njState.selectedKind = "";
      njState.selectedId = "";
      await refreshListAndRender();
      return true;
    }
    const diagMatch = hashStr.match(/^#\/neijing\/diagnose(?:\/(.*))?$/);
    if (diagMatch) {
      njState.dim = "diagnose";
      njState.query = diagMatch[1] ? decodeURIComponent(diagMatch[1]) : njState.query;
      if (qEl("#nj-query")) qEl("#nj-query").value = njState.query;
      await refreshListAndRender();
      return true;
    }
    const cMatch = hashStr.match(/^#\/neijing\/concepts\/(.+)$/);
    if (cMatch) {
      await openConcept(decodeURIComponent(cMatch[1]), true);
      return true;
    }
    const chMatch = hashStr.match(/^#\/neijing\/chapters\/(.+)$/);
    if (chMatch) {
      await openChapter(decodeURIComponent(chMatch[1]), true);
      return true;
    }
    const pgMatch = hashStr.match(/^#\/neijing\/page\/([^/]+)\/(\d+)$/);
    if (pgMatch) {
      njState.dim = "pages";
      await refreshListAndRender();
      await openSourcePage(decodeURIComponent(pgMatch[1]), Number(pgMatch[2]), true);
      return true;
    }
    return false;
  }

  function bindEvents() {
    const view = qEl("#neijing-view");
    if (!view || view.dataset.bound === "1") return;
    view.dataset.bound = "1";

    view.addEventListener("click", (event) => {
      const dimBtn = event.target.closest("[data-nj-dim]");
      if (dimBtn) {
        njState.dim = dimBtn.dataset.njDim;
        njState.selectedKind = "";
        njState.selectedId = "";
        refreshListAndRender().catch(showNjError);
        return;
      }
      const subBtn = event.target.closest("[data-nj-sub]");
      if (subBtn) {
        njState.submodule = subBtn.dataset.njSub;
        njState.selectedKind = "";
        njState.selectedId = "";
        refreshListAndRender().catch(showNjError);
        return;
      }
      const jumpSubBtn = event.target.closest("[data-nj-jump-sub]");
      if (jumpSubBtn) {
        njState.dim = "concepts";
        njState.submodule = jumpSubBtn.dataset.njJumpSub;
        njState.selectedKind = "";
        refreshListAndRender().catch(showNjError);
        return;
      }
      const invBtn = event.target.closest("[data-nj-inventory]");
      if (invBtn) {
        njState.selectedKind = "inventory";
        njState.selectedId = "";
        renderEditionInventoryDetail();
        return;
      }
      const conceptBtn = event.target.closest("[data-nj-open-concept]");
      if (conceptBtn) {
        openConcept(conceptBtn.dataset.njOpenConcept).catch(showNjError);
        return;
      }
      const chapBtn = event.target.closest("[data-nj-open-chapter]");
      if (chapBtn) {
        openChapter(chapBtn.dataset.njOpenChapter).catch(showNjError);
        return;
      }
      const setQBtn = event.target.closest("[data-nj-set-q]");
      if (setQBtn) {
        njState.dim = "diagnose";
        njState.query = setQBtn.dataset.njSetQ || "";
        njState.selectedKind = "";
        if (qEl("#nj-query")) qEl("#nj-query").value = njState.query;
        refreshListAndRender().catch(showNjError);
        return;
      }
      const scrollBtn = event.target.closest("[data-nj-scroll]");
      if (scrollBtn) {
        const target = document.getElementById(scrollBtn.dataset.njScroll);
        const panel = qEl("#nj-detail");
        if (target && panel) {
          const top = target.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop - 10;
          panel.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
        }
        return;
      }
      const imgBtn = event.target.closest("[data-nj-toggle-img]");
      if (imgBtn) {
        const [src, num] = imgBtn.dataset.njToggleImg.split(":");
        njState.showPageImage = !njState.showPageImage;
        openSourcePage(src, Number(num), true).catch(showNjError);
        return;
      }
      const pgBtn = event.target.closest("[data-nj-page]");
      if (pgBtn) {
        const [src, num] = pgBtn.dataset.njPage.split(":");
        openSourcePage(src, Number(num)).catch(showNjError);
        return;
      }
    });

    qEl("#nj-query")?.addEventListener("input", (e) => {
      njState.query = e.target.value;
      window.clearTimeout(bindEvents.timer);
      bindEvents.timer = window.setTimeout(() => {
        njState.selectedKind = "";
        refreshListAndRender().catch(showNjError);
      }, 180);
    });
    qEl("#nj-query")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        njState.selectedKind = "";
        refreshListAndRender().catch(showNjError);
      }
    });
    qEl("#nj-search-run")?.addEventListener("click", () => {
      njState.query = qEl("#nj-query")?.value || "";
      njState.selectedKind = "";
      refreshListAndRender().catch(showNjError);
    });
    qEl("#nj-volume-filter")?.addEventListener("change", (e) => {
      njState.volume = e.target.value;
      njState.selectedKind = "";
      refreshListAndRender().catch(showNjError);
    });
    qEl("#nj-review-filter")?.addEventListener("change", (e) => {
      njState.reviewFilter = e.target.value;
      njState.selectedKind = "";
      refreshListAndRender().catch(showNjError);
    });
    qEl("#nj-risk-filter")?.addEventListener("change", (e) => {
      njState.riskFilter = e.target.value;
      njState.selectedKind = "";
      refreshListAndRender().catch(showNjError);
    });
    qEl("#nj-reset")?.addEventListener("click", () => {
      njState.query = "";
      njState.submodule = "";
      njState.volume = "";
      njState.reviewFilter = "";
      njState.riskFilter = "";
      njState.selectedKind = "";
      njState.selectedId = "";
      if (qEl("#nj-query")) qEl("#nj-query").value = "";
      if (qEl("#nj-volume-filter")) qEl("#nj-volume-filter").value = "";
      if (qEl("#nj-review-filter")) qEl("#nj-review-filter").value = "";
      if (qEl("#nj-risk-filter")) qEl("#nj-risk-filter").value = "";
      refreshListAndRender().catch(showNjError);
    });
  }

  window.neijingUI = {
    activate,
    handleHash,
    openConcept,
    openChapter,
  };
})();
