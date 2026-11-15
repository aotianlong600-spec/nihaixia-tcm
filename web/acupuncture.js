/* Acupuncture triple-mode workspace: Bianzheng consultation, textbook reading & knowledge graph */
(function initAcupunctureModule() {
  const acupState = {
    booted: false,
    dim: "diagnose", // "diagnose" | "book" | "knowledge"
    sub: "meridians", // "meridians" | "points" | "techniques" | "conditions" | "indexes"
    query: "",
    reviewFilter: "",
    riskFilter: "",
    meridianFilter: "",
    expandedChapter: "ch4",
    chaptersData: null,
    overview: null,
    diagnoseData: null,
    bookPageHits: [],
    meridians: [],
    points: [],
    techniques: [],
    conditions: [],
    indexes: { acupoint_terms: [], condition_terms: [] },
    selectedKind: "",
    selectedId: "",
    selectedPage: null,
    showPageImage: false,
  };

  const GEN_LABEL = { auto: "自动提取", assisted: "人机协校", manual: "人工录入" };
  const EV_LABEL = { unlinked: "未锚定", anchored: "已锚定原文", verified: "逐字已核", conflicted: "存在分歧" };
  const REV_LABEL = { pending: "待审校", needs_changes: "待修改", approved: "已审定", rejected: "已弃用" };
  const RISK_LABEL = { standard: "常规教学", high_risk: "高风险教学", emergency: "急症/肿瘤警示" };
  const ROLE_LABEL = {
    source_quote: "经典引文",
    ni_teaching: "倪海厦讲授",
    other_annotations: "他家/脚注",
    collation_notes: "校勘与版本",
    organizer_summary: "整理摘要",
  };
  const REL_LABEL = {
    meridian_to_acupoint: "本经穴位",
    acupoint_to_condition: "所治病症",
    condition_to_meridian: "涉及经络",
    acupoint_to_technique: "对应法则",
    acupoint_to_combination: "配穴组合",
    meridian_to_channel_pair: "表里经脉",
    technique_to_condition: "法则适用",
  };
  const CAT_LABEL = {
    needle_timing: "时机与禁忌",
    emergency_care: "急救与晕针",
    measurement_and_depth: "寸度与深浅",
    five_shu_and_mother_child: "五俞与子母",
    tonification_sedation: "补泻手法",
    needling_pattern: "刺法与定穴",
    formulaic_point_selection: "取穴法则",
    bloodletting_and_plum_blossom: "放血与梅花针",
    moxibustion: "艾灸与灸禁",
    cupping_and_instruments: "火罐与九针",
    meridian_clock_and_five_elements: "干支流注与五行",
    eight_extra_vessels: "奇经八脉与十五络",
    complex_needling_methods: "复式飞经补泻法",
    diagnostic_methods: "望诊压痛与脉诊",
    acupoint_formulas: "经外成方配穴组",
  };

  const qEl = (sel) => document.querySelector(sel);

  function esc(value) {
    return String(value ?? "")
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

  function showAcupError(err) {
    const detail = qEl("#acup-detail");
    const msg = err?.message || "请求失败";
    if (detail) {
      detail.innerHTML = `<div class="acup-safety-banner acup-banner-risk"><strong>数据加载提示</strong><p>${esc(msg)}</p></div>`;
    }
  }

  function statusPills(item) {
    const gen = item.generation_status || "auto";
    const ev = item.evidence_status || "unlinked";
    const rev = item.review_status || "pending";
    const risk = item.risk_level || "standard";
    const riskCls = risk === "emergency" ? "acup-pill-emergency" : risk === "high_risk" ? "acup-pill-risk" : "acup-pill-std";
    const revCls = rev === "approved" ? "acup-pill-approved" : "acup-pill-pending";
    return `<div class="acup-status-row">
      <span class="acup-pill ${revCls}">${esc(REV_LABEL[rev] || rev)}</span>
      <span class="acup-pill acup-pill-ev">${esc(EV_LABEL[ev] || ev)}</span>
      <span class="acup-pill acup-pill-gen">${esc(GEN_LABEL[gen] || gen)}</span>
      <span class="acup-pill ${riskCls}">${esc(RISK_LABEL[risk] || risk)}</span>
    </div>`;
  }

  function riskBanner(item) {
    const risk = item.risk_level || "standard";
    const warn = item.safety_warning || "";
    if (!warn && risk === "standard") return "";
    const cls = risk === "emergency" ? "acup-banner-emergency" : risk === "high_risk" ? "acup-banner-risk" : "acup-banner-info";
    return `<div class="acup-safety-banner ${cls}">
      <strong>${esc(RISK_LABEL[risk] || "教学边界提示")}</strong>
      <p>${esc(warn || "教学资料仅供研究学习，不作为个人自疗或非专业操作指南。")}</p>
    </div>`;
  }

  function renderSpans(spans) {
    if (!spans?.length) return `<p class="muted-line">暂无原文页码锚点。</p>`;
    return `<div class="acup-spans-list">${spans.map((sp) => `
      <article class="acup-span-card">
        <div class="acup-span-head">
          <button class="text-button" type="button" data-acup-page="${sp.pdf_page}">
            查看第 ${esc(sp.printed_page || sp.pdf_page)} 页原文
          </button>
          <button class="text-button ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="ni-acupuncture-v2-20100703" data-ctx-page="${sp.pdf_page}" data-ctx-q="${esc((sp.quote || "").slice(0, 22))}">
            上下文滑动对照 ↗
          </button>
          <span>${esc(sp.chapter_path || sp.page_id)}</span>
          <code>${esc((sp.quote_sha256 || "").slice(0, 10))}</code>
        </div>
        <blockquote>${esc(sp.quote)}</blockquote>
      </article>`).join("")}</div>`;
  }

  function renderContentLayers(layers) {
    if (!layers) return "";
    const order = ["source_quote", "ni_teaching", "other_annotations", "collation_notes", "organizer_summary"];
    const blocks = order
      .filter((key) => Array.isArray(layers[key]) && layers[key].length)
      .map((key) => `
        <article class="acup-layer-card acup-layer-${key}">
          <h4>${esc(ROLE_LABEL[key])}</h4>
          <ul>${layers[key].map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
        </article>`);
    if (!blocks.length) return `<p class="muted-line">本条目分层注释尚待补充。</p>`;
    return `<div class="acup-layers-grid">${blocks.join("")}</div>`;
  }

  function renderOpenQuestions(questions) {
    if (!questions?.length) return "";
    return `<section class="detail-section acup-open-box">
      <h3>尚待考证（按教材如实留白）</h3>
      <ul>${questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
    </section>`;
  }

  function peerActionAttr(peer) {
    if (!peer || !peer.id) return "";
    if (peer.record_type === "meridian") return `data-acup-open="meridian" data-acup-id="${encodeURIComponent(peer.id)}"`;
    if (peer.record_type === "acupoint") return `data-acup-open="point" data-acup-id="${encodeURIComponent(peer.id)}"`;
    if (peer.record_type === "technique") return `data-acup-open="technique" data-acup-id="${encodeURIComponent(peer.id)}"`;
    if (peer.record_type === "condition_teaching") return `data-acup-open="condition" data-acup-id="${encodeURIComponent(peer.id)}"`;
    return "";
  }

  function renderRelations(relations) {
    if (!relations?.length) return `<p class="muted-line">暂无跨条目双向关联。</p>`;
    return `<div class="acup-rel-grid">${relations.map((rel) => {
      const p = rel.peer || {};
      const attr = peerActionAttr(p);
      return `<div class="acup-rel-card">
        <div class="acup-rel-top">
          <span class="acup-rel-type">${esc(REL_LABEL[rel.relation_type] || rel.relation_type)}</span>
          <button class="herb-formula-link" type="button" ${attr}>
            ${esc(p.canonical_name || p.id)}
            <small>${esc(REV_LABEL[p.review_status] || p.review_status || "")}</small>
          </button>
        </div>
        <p>${esc(rel.note || rel.label)}</p>
      </div>`;
    }).join("")}</div>`;
  }

  async function ensureLoaded() {
    if (acupState.booted) return;
    const [overview, chaptersData, meridiansRes, conditionsRes] = await Promise.all([
      req("/api/acupuncture/overview"),
      req("/api/acupuncture/chapters"),
      req("/api/acupuncture/meridians"),
      req("/api/acupuncture/conditions"),
    ]);
    acupState.overview = overview;
    acupState.chaptersData = chaptersData;
    acupState.meridians = meridiansRes.items || [];
    acupState.conditions = conditionsRes.items || [];
    const sel = qEl("#acup-meridian-filter");
    if (sel) {
      sel.innerHTML = `<option value="">全部经络</option>` +
        acupState.meridians.map((m) => `<option value="${esc(m.id)}">${esc(m.canonical_name)}</option>`).join("");
    }
    acupState.booted = true;
  }

  async function refreshData() {
    const q = encodeURIComponent(acupState.query || "");
    const rev = encodeURIComponent(acupState.reviewFilter || "");
    const risk = encodeURIComponent(acupState.riskFilter || "");
    const mid = encodeURIComponent(acupState.meridianFilter || "");

    if (acupState.dim === "diagnose") {
      acupState.diagnoseData = await req(
        `/api/acupuncture/diagnose?q=${q}&risk_level=${risk}&meridian_id=${mid}`
      );
      return;
    }

    if (acupState.dim === "book") {
      if ((acupState.query || "").trim()) {
        const d = await req(`/api/acupuncture/diagnose?q=${q}`);
        acupState.bookPageHits = d.matched_pages || [];
      } else {
        acupState.bookPageHits = [];
      }
      return;
    }

    if (acupState.sub === "meridians") {
      const data = await req(`/api/acupuncture/meridians?q=${q}&review_status=${rev}&risk_level=${risk}`);
      acupState.meridians = data.items || [];
    } else if (acupState.sub === "points") {
      const data = await req(`/api/acupuncture/points?q=${q}&meridian_id=${mid}&review_status=${rev}&risk_level=${risk}`);
      acupState.points = data.items || [];
    } else if (acupState.sub === "techniques") {
      const data = await req(`/api/acupuncture/techniques?q=${q}&review_status=${rev}&risk_level=${risk}`);
      acupState.techniques = data.items || [];
    } else if (acupState.sub === "conditions") {
      const data = await req(`/api/acupuncture/conditions?q=${q}&review_status=${rev}&risk_level=${risk}`);
      acupState.conditions = data.items || [];
    } else if (acupState.sub === "indexes") {
      acupState.indexes = await req(`/api/acupuncture/indexes?q=${q}`);
    }
  }

  function renderDiagnoseList() {
    const listEl = qEl("#acup-list");
    const d = acupState.diagnoseData;
    const ov = acupState.overview || {};
    qEl("#acup-list-title").textContent = "症状辨证推演";

    if (!d || !d.query) {
      const conds = acupState.conditions || [];
      qEl("#acup-list-subtitle").textContent = `已核 ${ov.meridians?.approved || 0} 经 · ${ov.acupoints?.approved || 0} 穴 · ${ov.conditions?.approved || 0} 治症专题`;
      qEl("#acup-count").textContent = `${conds.length} 专题`;
      const condHtml = `<div class="acup-tree-group">
        <div class="acup-tree-group-head"><span>第六章全书治症专题直达（点击审阅或输入症状推演）</span></div>
        ${conds.map((c) => `
          <button class="entity-item${acupState.selectedKind === "condition" && acupState.selectedId === c.id ? " selected" : ""}" data-acup-open="condition" data-acup-id="${encodeURIComponent(c.id)}">
            <span class="entity-name"><strong>${esc(c.canonical_name)}</strong><em>p.${c.page_range?.[0] || "?"}–${c.page_range?.[1] || "?"} · ${c.sub_pattern_count || 0} 分型</em></span>
            <span class="entity-meta">
              <span class="status-pill ${c.review_status === "approved" ? "status-reviewed" : "status-pending"}">${c.review_status === "approved" ? "已审定" : "待审"}</span>
              ${c.risk_level !== "standard" ? `<span class="status-pill ${c.risk_level === "emergency" ? "acup-pill-emergency" : "acup-pill-risk"}">${c.risk_level === "emergency" ? "急症" : "高风险"}</span>` : ""}
            </span>
          </button>`).join("")}
      </div>`;
      listEl.innerHTML = condHtml;
      return;
    }

    const pats = d.matched_patterns || [];
    const pts = d.matched_points || [];
    const pgs = d.matched_pages || [];
    qEl("#acup-list-subtitle").textContent = `命中 ${pats.length} 辨证分型 · ${pts.length} 相关穴位 · ${pgs.length} 原书页`;
    qEl("#acup-count").textContent = `${pats.length + pts.length} 条`;

    const patList = pats.length ? `<div class="acup-tree-group">
      <div class="acup-tree-group-head"><span>辨证分型候选（${pats.length}）</span></div>
      ${pats.map((p, idx) => `
        <button class="entity-item" data-acup-scroll="acup-diag-pat-${idx}">
          <span class="entity-name"><strong>${esc(p.pattern_name)}</strong><em>${esc(p.condition_name)} · p.${p.condition_page_range?.[0] || "?"}</em></span>
          <span class="entity-meta"><span class="status-pill status-reviewed">分型 ${idx + 1}</span></span>
        </button>`).join("")}
    </div>` : "";

    const ptList = pts.length ? `<div class="acup-tree-group">
      <div class="acup-tree-group-head"><span>主治命中穴位（${pts.length}）</span></div>
      ${pts.map((pt) => `
        <button class="entity-item" data-acup-open="point" data-acup-id="${encodeURIComponent(pt.id)}">
          <span class="entity-name"><strong>${esc(pt.canonical_name)}</strong><em>${esc(pt.meridian_name)} · ${(pt.special_categories || [])[0] || "临床常用"}</em></span>
          <span class="entity-meta"><span class="status-pill ${pt.review_status === "approved" ? "status-reviewed" : "status-pending"}">${pt.review_status === "approved" ? "已核" : "待核"}</span></span>
        </button>`).join("")}
    </div>` : "";

    const pgList = pgs.length ? `<div class="acup-tree-group">
      <div class="acup-tree-group-head"><span>原书全文命中页（${pgs.length}）</span></div>
      ${pgs.map((pg) => `
        <button class="entity-item" data-acup-page="${pg.pdf_page}">
          <span class="entity-name"><strong>第 ${pg.printed_page || pg.pdf_page} 页</strong><em>${esc(pg.snippet)}</em></span>
        </button>`).join("")}
    </div>` : "";

    listEl.innerHTML = patList + ptList + pgList || `<div class="loading">未找到匹配条目，请尝试更常见的中医或俗称症状关键词。</div>`;
  }

  function renderDiagnoseDetail() {
    const detail = qEl("#acup-detail");
    const d = acupState.diagnoseData;
    const ov = acupState.overview || {};
    if (!detail || !d) return;

    if (!d.query) {
      const examples = d.quick_examples || [];
      const qualifiers = d.qualifier_chips || [];
      detail.innerHTML = `<article class="detail-article">
        <div class="acup-diag-hero">
          <h3>《倪海厦人纪针灸》症状辨证取穴工作台</h3>
          <p>输入一个或多个症状（用空格隔开，如 <code>偏头痛 恶寒</code>、<code>鼻塞 流清涕</code>、<code>凌晨两点醒 胁痛</code>），系统会依全书 <strong>六章原文、十五经络与奇穴、五输子母/俞募/原络/八脉法则及第六章 34 治症</strong> 推演可能证型、所需鉴别条件、推荐穴位、定位操作及禁忌边界。</p>
          <div>
            <strong style="font-size:12px;color:#275337;">点击常见主症试测辨证：</strong>
            <div class="acup-quick-chips">${examples.map((ex) => `<button class="acup-chip-btn" type="button" data-acup-set-q="${esc(ex)}">${esc(ex)}</button>`).join("")}</div>
          </div>
          <div style="margin-top:12px;">
            <strong style="font-size:12px;color:#6e5520;">追加八纲/部位/人群修饰（可组合点击）：</strong>
            <div class="acup-quick-chips">${qualifiers.map(([lbl, chip]) => `<button class="acup-chip-btn is-qualifier" type="button" data-acup-add-q="${esc(chip)}">+ ${esc(lbl)}</button>`).join("")}</div>
          </div>
        </div>

        <section class="detail-section">
          <h3>当前本地针灸知识库覆盖概况</h3>
          <div class="acup-kv-grid">
            <div><span>全书原典页数</span><p>${ov.total_pages || 216} 页 · ${ov.chapters?.total_chapters || 6} 章 ${ov.chapters?.total_sections || 297} 节（已审定 ${ov.chapters?.approved_sections || 0} 节）</p></div>
            <div><span>经络与奇穴</span><p>${ov.meridians?.approved || 0} / ${ov.meridians?.total || 15} 经组已核 · 穴位 ${ov.acupoints?.approved || 0} 核 / ${ov.acupoints?.total || 0} 档</p></div>
            <div><span>针灸法则与治症</span><p>${ov.techniques?.approved || 0} 项法则技法 · 第六章 ${ov.conditions?.approved || 0} / ${ov.conditions?.total || 34} 专题（共 ${d.stats?.total_patterns || 0} 辨证分型）</p></div>
            <div><span>书后附表索引</span><p>穴位拼音索引 ${ov.acupoints?.indexed_terms || 378} 词 · 治症索引 ${ov.conditions?.indexed_terms || 274} 词</p></div>
          </div>
        </section>

        <section class="detail-section">
          <h3>使用与安全原则（不可逾越的边界）</h3>
          <ul class="dossier-steps">
            <li>同一症状先按<strong>虚实、寒热、表里、经络循行、发病时辰</strong>区分，再按子母补泻、俞募、原络、对侧缪刺或奇穴法则取穴。</li>
            <li>严格分离<strong>经典引文 / 倪海厦口授 / 脚注他解 / 尚待考证</strong>，原书未言明处如实标注，不由模型臆测补全。</li>
            <li>涉及针刺深浅、放血、火针烧针、肿瘤积水、出血昏迷、孕妇与儿童内容，仅作专业文献教学展示，不构成自疗操作指令。</li>
          </ul>
        </section>
      </article>`;
      return;
    }

    const alertsHtml = (d.safety_alerts || []).map((msg) => `
      <div class="acup-safety-banner acup-banner-emergency">
        <strong>临床与教学风险前置警示</strong>
        <p>${esc(msg)}</p>
      </div>`).join("");

    const guidesHtml = (d.channel_guides || []).map((g) => `
      <div class="acup-guide-box">
        <h4>${esc(g.title)}（点击具体分经/分型进一步收敛）</h4>
        <div class="acup-guide-grid">
          ${g.branches.map((br) => `
            <button type="button" class="acup-guide-branch" data-acup-add-q="${esc(br.query_chip)}">
              <strong>${esc(br.label)}</strong>
              <span>归经：${esc(br.meridian)}</span>
              <p>${esc(br.note)}</p>
            </button>`).join("")}
        </div>
      </div>`).join("");

    const clocksHtml = (d.matched_meridian_clocks || []).map((ck) => `
      <div class="acup-clock-card">
        <strong>子午流注时辰提示 · ${esc(ck.window)} → ${esc(ck.meridian_name)}：</strong>${esc(ck.rule)}
        <button type="button" class="text-button" data-acup-open="meridian" data-acup-id="${encodeURIComponent(ck.meridian_id)}">查看${esc(ck.meridian_name)}五俞</button>
      </div>`).join("");

    const followUpsHtml = (d.follow_up_facets || []).length ? `
      <div style="margin-top:12px;">
        <strong style="font-size:12px;color:#6e5520;">补充辨证条件（点击追加到当前症状查询，进一步筛选证型）：</strong>
        <div class="acup-quick-chips">
          ${d.follow_up_facets.map((f) => `<button type="button" class="acup-chip-btn is-qualifier" data-acup-add-q="${esc(f.chip)}">+ ${esc(f.label)}</button>`).join("")}
        </div>
      </div>` : "";

    const patternsHtml = (d.matched_patterns || []).map((pat, idx) => `
      <article id="acup-diag-pat-${idx}" class="acup-pattern-card">
        <div class="acup-pattern-head">
          <h4><span>${String(idx + 1).padStart(2, "0")}</span> ${esc(pat.pattern_name)} <small style="font-size:12px;color:#5a655c;">（${esc(pat.condition_name)}）</small></h4>
          <div class="inline-actions">
            ${pat.risk_level !== "standard" ? `<span class="acup-pill ${pat.risk_level === "emergency" ? "acup-pill-emergency" : "acup-pill-risk"}">${esc(RISK_LABEL[pat.risk_level] || pat.risk_level)}</span>` : ""}
            <button type="button" class="text-button" data-acup-open="condition" data-acup-id="${encodeURIComponent(pat.condition_id)}">完整专题</button>
            ${pat.source_spans?.[0] ? `<button type="button" class="text-button" data-acup-page="${pat.source_spans[0].pdf_page}">第 ${pat.source_spans[0].pdf_page} 页原文</button>` : ""}
          </div>
        </div>
        <div class="acup-pattern-body">
          ${pat.safety_warning ? `<div class="acup-safety-banner ${pat.risk_level === "emergency" ? "acup-banner-emergency" : "acup-banner-risk"}"><p>${esc(pat.safety_warning)}</p></div>` : ""}
          <div>
            <strong>匹配症状与证候表现：</strong>
            <div class="symptom-row">${(pat.symptoms || []).map((s) => `<span class="symptom-chip">${esc(s)}</span>`).join("")}</div>
          </div>
          <p><strong>传统辨证与判别条件：</strong>${esc(pat.syndrome_differentiation)}</p>
          <div>
            <strong>涉及经络与核心选穴处方（点击穴位看定位与刺灸法）：</strong>
            <div class="acup-point-chips" style="margin-bottom:6px;">
              ${(pat.resolved_meridians || []).map((m) => `<button type="button" class="text-button" data-acup-open="meridian" data-acup-id="${encodeURIComponent(m.id)}">归经：${esc(m.canonical_name)}</button>`).join("")}
              ${(pat.related_techniques || []).map((t) => `<button type="button" class="text-button" data-acup-open="technique" data-acup-id="${encodeURIComponent(t.id)}">法则：${esc(t.canonical_name)}</button>`).join("")}
            </div>
            <div class="acup-rx-grid">
              ${(pat.resolved_points || []).map((pt) => `
                <div class="acup-rx-card">
                  <div class="acup-rx-head">
                    <button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(pt.id)}">${esc(pt.canonical_name)}<small>${esc(pt.meridian_name || "")}</small></button>
                    <span class="acup-pill ${pt.review_status === "approved" ? "acup-pill-approved" : "acup-pill-pending"}">${esc(REV_LABEL[pt.review_status] || pt.review_status)}</span>
                  </div>
                  ${(pt.special_categories || []).length ? `<div class="acup-rx-meta">${esc(pt.special_categories.slice(0, 3).join(" · "))}</div>` : ""}
                  <p class="acup-rx-loc"><strong>定位：</strong>${esc(pt.location_simplified || pt.location_source || "点击查看详情")}</p>
                  ${pt.technique_notes ? `<p class="acup-rx-note"><strong>刺灸：</strong>${esc(pt.technique_notes.slice(0, 120))}${pt.technique_notes.length > 120 ? "…" : ""}</p>` : ""}
                  ${pt.cautions ? `<p class="acup-rx-note" style="color:#8c3c1f;"><strong>注意：</strong>${esc(pt.cautions.slice(0, 90))}${pt.cautions.length > 90 ? "…" : ""}</p>` : ""}
                </div>`).join("")}
            </div>
          </div>
          <p><strong>为什么选这些穴（原书道理）：</strong>${esc(pat.why_selected)}</p>
          ${pat.differentiation_notes ? `<p><strong>不同情况区分与操作法则：</strong>${esc(pat.differentiation_notes)}</p>` : ""}
          ${(pat.open_questions || []).length ? `<div class="acup-sub-open"><strong>本分型尚待考证：</strong><ul>${pat.open_questions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
          ${renderSpans(pat.source_spans)}
        </div>
      </article>`).join("");

    const pointsHtml = (d.matched_points || []).length ? `
      <section class="detail-section">
        <h3>按穴位主治直接命中参考（共 ${d.matched_points.length} 穴）</h3>
        <div class="acup-rx-grid">
          ${d.matched_points.map((pt) => `
            <div class="acup-rx-card">
              <div class="acup-rx-head">
                <button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(pt.id)}">${esc(pt.canonical_name)}<small>${esc(pt.meridian_name || "")}</small></button>
                ${pt.source_spans?.[0] ? `<button type="button" class="text-button" data-acup-page="${pt.source_spans[0].pdf_page}">p.${pt.source_spans[0].pdf_page}</button>` : ""}
              </div>
              ${(pt.special_categories || []).length ? `<div class="acup-rx-meta">${esc(pt.special_categories.slice(0, 3).join(" · "))}</div>` : ""}
              <p class="acup-rx-loc"><strong>主治：</strong>${esc((pt.indications || []).slice(0, 6).join("、"))}</p>
              <p class="acup-rx-loc" style="margin-top:4px;"><strong>定位：</strong>${esc(pt.location_simplified || pt.location_source || "点击查看")}</p>
            </div>`).join("")}
        </div>
      </section>` : "";

    const techsHtml = (d.matched_techniques || []).length ? `
      <section class="detail-section">
        <h3>相关针灸法则与补泻纲领（${d.matched_techniques.length}）</h3>
        <div class="acup-rel-grid">
          ${d.matched_techniques.map((t) => `
            <div class="acup-rel-card">
              <div class="acup-rel-top">
                <span class="acup-rel-type">${esc(CAT_LABEL[t.category] || t.category)}</span>
                <button type="button" class="herb-formula-link" data-acup-open="technique" data-acup-id="${encodeURIComponent(t.id)}">${esc(t.canonical_name)}</button>
              </div>
              <p>${esc(t.summary)}</p>
            </div>`).join("")}
        </div>
      </section>` : "";

    const idxPagesHtml = (d.matched_indexes?.length || d.matched_pages?.length) ? `
      <section class="detail-section">
        <h3>原书治症索引与全文页码佐证</h3>
        ${(d.matched_indexes || []).length ? `<div class="acup-point-chips" style="margin-bottom:10px;">${d.matched_indexes.map((it) => `
          <span class="symptom-chip"><strong>${esc(it.name)}</strong>：${(it.pages || []).map((pg) => `<button type="button" class="text-button" data-acup-page="${pg}">p.${pg}</button>`).join(" ")}</span>`).join("")}</div>` : ""}
        <div class="acup-spans-list">
          ${(d.matched_pages || []).map((pg) => `
            <article class="acup-span-card">
              <div class="acup-span-head">
                <button type="button" class="text-button" data-acup-page="${pg.pdf_page}">阅读第 ${pg.printed_page || pg.pdf_page} 页原文</button>
                <span>命中：${esc((pg.matched_tokens || []).join("、"))}</span>
              </div>
              <blockquote>${esc(pg.snippet)}</blockquote>
            </article>`).join("")}
        </div>
      </section>` : "";

    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">辨证取穴推演：「${esc(d.query)}」</h2>
          <p class="detail-sub">命中 ${d.matched_patterns?.length || 0} 条辨证分型 · ${d.matched_points?.length || 0} 条对症穴位 · ${d.matched_pages?.length || 0} 页原书线索</p>
        </div>
        <button type="button" class="quiet-button" id="acup-clear-diag">清空条件</button>
      </div>
      ${alertsHtml}
      ${clocksHtml}
      ${guidesHtml}
      ${followUpsHtml}
      <section class="detail-section">
        <h3>第六章治症分型与选穴推导（按匹配度排序）</h3>
        ${patternsHtml || `<p class="muted-line">第六章分型中暂无直接匹配，已自动展开下方单穴主治与全书 216 页原文页码线索供对照查核。</p>`}
      </section>
      ${pointsHtml}
      ${techsHtml}
      ${idxPagesHtml}
    </article>`;
  }

  function renderBookList() {
    const listEl = qEl("#acup-list");
    const data = acupState.chaptersData;
    if (!data) {
      listEl.innerHTML = `<div class="loading">正在读取针灸目录...</div>`;
      return;
    }
    const q = (acupState.query || "").trim().toLowerCase();
    const rev = acupState.reviewFilter;
    qEl("#acup-list-title").textContent = "原书六章目录";
    qEl("#acup-list-subtitle").textContent = `全书 ${data.total_pages} 页 · ${data.stats.total_chapters} 章 ${data.stats.total_sections} 节（已审定 ${data.stats.approved_sections} 节）`;
    qEl("#acup-count").textContent = `${data.stats.total_chapters} 章 / ${data.stats.total_sections} 节`;

    const frontHtml = `<div class="acup-tree-group">
      <div class="acup-tree-group-head"><span>前置内容与附录索引</span></div>
      ${(data.frontmatter || []).concat(data.appendices || []).map((f) => `
        <button class="entity-item${acupState.selectedKind === "page" && acupState.selectedPage === f.page_start ? " selected" : ""}" data-acup-page="${f.page_start}">
          <span class="entity-name"><strong>${esc(f.title)}</strong><em>p.${f.page_start}–${f.page_end}</em></span>
        </button>`).join("")}
    </div>`;

    const chaptersHtml = (data.chapters || []).map((ch) => {
      const secs = (ch.sections || []).filter((s) => {
        if (rev === "approved" && s.pilot_status !== "approved") return false;
        if (rev === "pending" && s.pilot_status === "approved") return false;
        if (q) {
          const hit = `${ch.title} ${s.title} ${s.page_start}`.toLowerCase().includes(q);
          if (!hit) return false;
        }
        return true;
      });
      const isExpanded = q || rev === "approved" || acupState.expandedChapter === ch.id;
      const badge = ch.approved_sections > 0 ? `已核 ${ch.approved_sections}/${ch.total_sections}` : `待校 0/${ch.total_sections}`;
      return `<div class="acup-chapter-block">
        <button class="acup-chapter-toggle${isExpanded ? " expanded" : ""}" type="button" data-acup-toggle-ch="${esc(ch.id)}">
          <div>
            <strong>${esc(ch.title)}</strong>
            <small>p.${ch.page_start}–${ch.page_end} · ${esc(badge)}</small>
          </div>
          <span>${isExpanded ? "▾" : "▸"}</span>
        </button>
        ${isExpanded ? `<div class="acup-section-items">
          <button class="entity-item acup-sec-page-btn" data-acup-page="${ch.page_start}">
            <span class="entity-name"><strong>阅读本章首页原文</strong><em>p.${ch.page_start}</em></span>
          </button>
          ${secs.map((sec) => {
            let openKind = "";
            let openId = "";
            if (sec.condition_id) {
              openKind = "condition";
              openId = sec.condition_id;
            } else if (sec.meridian_id === "meridian:ren_du_intro") {
              openKind = "technique";
              openId = "tech:ren_du_diagnostic_and_tonification";
            } else if (sec.meridian_id && sec.level === "meridian") {
              openKind = "meridian";
              openId = sec.meridian_id;
            }
            const pill = sec.pilot_status === "approved" ? `<span class="status-pill status-reviewed">已核</span>` : `<span class="status-pill status-pending">第${sec.page_start}页</span>`;
            const primaryAttr = openKind ? `data-acup-open="${openKind}" data-acup-id="${encodeURIComponent(openId)}"` : `data-acup-page="${sec.page_start}"`;
            return `<div class="acup-sec-row${sec.level === "subsection" ? " is-sub" : ""}">
              <button class="entity-item${acupState.selectedId === openId && openId ? " selected" : ""}" ${primaryAttr}>
                <span class="entity-name"><strong>${esc(sec.title)}</strong><em>p.${sec.page_start}${sec.page_end > sec.page_start ? `–${sec.page_end}` : ""}</em></span>
                <span class="entity-meta">${pill}${sec.timestamp ? `<span>${esc(sec.timestamp)}</span>` : ""}</span>
              </button>
              <button class="acup-mini-page" type="button" title="直达原书第${sec.page_start}页" data-acup-page="${sec.page_start}">页码</button>
            </div>`;
          }).join("")}
        </div>` : ""}
      </div>`;
    }).join("");

    const pageHitsHtml = (acupState.bookPageHits || []).length ? `<div class="acup-tree-group">
      <div class="acup-tree-group-head"><span>全书正文关键词直达页（${acupState.bookPageHits.length}）</span></div>
      ${acupState.bookPageHits.map((pg) => `
        <button class="entity-item" data-acup-page="${pg.pdf_page}">
          <span class="entity-name"><strong>第 ${pg.printed_page || pg.pdf_page} 页</strong><em>${esc(pg.snippet)}</em></span>
        </button>`).join("")}
    </div>` : "";

    listEl.innerHTML = chaptersHtml + pageHitsHtml + frontHtml;
  }

  function renderKnowledgeList() {
    const listEl = qEl("#acup-list");
    const sub = acupState.sub;
    const ov = acupState.overview || {};
    const items = sub === "meridians"
      ? acupState.meridians
      : sub === "points"
        ? acupState.points
        : sub === "techniques"
          ? acupState.techniques
          : sub === "conditions"
            ? acupState.conditions
            : [];

    const titles = {
      meridians: ["经络归属", `十二正经、任督及经外奇穴（已核 ${ov.meridians?.approved || 0}/${ov.meridians?.total || 15}）`],
      points: ["穴位列表", `全书穴位主治、定位与配穴（已核 ${ov.acupoints?.approved || 0}/${ov.acupoints?.total || 0}）`],
      techniques: ["针灸法则与用法", `时机禁忌、九针、五俞补泻、奇经八脉与复杂针法（${ov.techniques?.approved || 0} 项）`],
      conditions: ["第六章治症专题", `全书34个治症专题（已核 ${ov.conditions?.approved || 0}/${ov.conditions?.total || 34}）`],
      indexes: ["原书后附索引", `第201–216页 穴位拼音索引（${ov.acupoints?.indexed_terms || 378}）与治症索引（${ov.conditions?.indexed_terms || 274}）`],
    };
    const [t, st] = titles[sub];
    qEl("#acup-list-title").textContent = t;
    qEl("#acup-list-subtitle").textContent = st;

    if (sub === "indexes") {
      const acup = acupState.indexes.acupoint_terms || [];
      const cond = acupState.indexes.condition_terms || [];
      qEl("#acup-count").textContent = `${acup.length + cond.length} 词`;
      const mkIdx = (label, arr, isCond) => `<div class="acup-tree-group">
        <div class="acup-tree-group-head"><span>${esc(label)}（${arr.length}）</span></div>
        ${arr.slice(0, 180).map((it) => `
          <div class="acup-idx-item">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
              <strong>${esc(it.name)}</strong>
              ${isCond ? `<button type="button" class="text-button" data-acup-set-q="${esc(it.name)}">辨证推演</button>` : `<button type="button" class="text-button" data-acup-find-point="${esc(it.name)}">查本穴</button>`}
            </div>
            <div class="acup-idx-pages">${(it.pages || []).map((pg) => `<button type="button" class="text-button" data-acup-page="${pg}">p.${pg}</button>`).join("")}</div>
          </div>`).join("")}
        ${arr.length > 180 ? `<p class="muted-line" style="padding:8px 12px;">已显示前 180 条，请输入关键词缩小筛选。</p>` : ""}
      </div>`;
      listEl.innerHTML = mkIdx("穴位拼音索引", acup, false) + mkIdx("治症索引", cond, true);
      return;
    }

    qEl("#acup-count").textContent = `${items.length} 条`;
    const kindMap = { meridians: "meridian", points: "point", techniques: "technique", conditions: "condition" };
    const openKind = kindMap[sub];

    listEl.innerHTML = items.map((item) => {
      const selected = acupState.selectedKind === openKind && acupState.selectedId === item.id;
      const revPill = item.review_status === "approved"
        ? `<span class="status-pill status-reviewed">已审定</span>`
        : `<span class="status-pill status-pending">待审</span>`;
      const riskPill = item.risk_level === "emergency"
        ? `<span class="status-pill acup-pill-emergency">急症/肿瘤</span>`
        : item.risk_level === "high_risk"
          ? `<span class="status-pill acup-pill-risk">高风险</span>`
          : "";
      const extra = sub === "meridians"
        ? `p.${(item.page_range || [])[0] || "?"}–${(item.page_range || [])[1] || "?"} · 穴位 ${item.acupoint_count || 0}`
        : sub === "points"
          ? `${item.meridian_name || item.meridian_id}${item.sequence ? ` · 第${item.sequence}穴` : ""}`
          : sub === "techniques"
            ? (CAT_LABEL[item.category] || item.category)
            : `p.${(item.page_range || [])[0] || "?"} · 子分型 ${item.sub_pattern_count || 0}`;
      return `<button class="entity-item${selected ? " selected" : ""}" data-acup-open="${openKind}" data-acup-id="${encodeURIComponent(item.id)}">
        <span class="entity-name"><strong>${esc(item.canonical_name)}</strong><em>${esc(extra)}</em></span>
        <span class="entity-meta">${revPill}${riskPill}</span>
      </button>`;
    }).join("") || `<div class="loading">没有匹配的针灸条目。</div>`;
  }

  function renderCurrentList() {
    document.querySelectorAll(".acup-dim-tab").forEach((b) => {
      const active = b.dataset.acupDim === acupState.dim;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    qEl("#acup-subbar")?.classList.toggle("hidden", acupState.dim !== "knowledge");
    qEl("#acup-meridian-wrap")?.classList.toggle("hidden", !(acupState.dim === "knowledge" && acupState.sub === "points"));
    document.querySelectorAll(".acup-subtab").forEach((b) => {
      const active = b.dataset.acupSub === acupState.sub;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (acupState.dim === "diagnose") {
      renderDiagnoseList();
      if (!acupState.selectedKind) renderDiagnoseDetail();
    } else if (acupState.dim === "book") {
      renderBookList();
    } else {
      renderKnowledgeList();
    }
  }

  async function openMeridian(id, skipHash) {
    const detail = qEl("#acup-detail");
    detail.innerHTML = `<div class="loading">正在读取经络考证卡...</div>`;
    const m = await req(`/api/acupuncture/meridians/${encodeURIComponent(id)}`);
    acupState.selectedKind = "meridian";
    acupState.selectedId = id;
    if (!skipHash) history.replaceState(null, "", `#/acupuncture/meridians/${encodeURIComponent(id)}`);
    renderCurrentList();

    const fs = m.five_shu_table || {};
    const fsEntries = [
      ["井穴", fs.well_wood || fs.well_metal || fs.well],
      ["荣穴", fs.ying_fire || fs.ying_water || fs.ying],
      ["俞/原穴", fs.shu_earth_yuan || fs.shu_wood || fs.shu],
      ["原穴", fs.yuan],
      ["经穴", fs.jing_metal_ben || fs.jing_fire || fs.jing],
      ["合穴", fs.he_water_child || fs.he_earth || fs.he],
      ["络穴", fs.luo],
      ["郄穴", fs.xi],
    ].filter(([, pid]) => pid);

    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">${esc(m.canonical_name)}</h2>
          <p class="detail-sub">${esc((m.aliases || []).join(" · "))} · 原书第 ${(m.page_range || [])[0] || "?"}–${(m.page_range || [])[1] || "?"} 页</p>
        </div>
        <div class="inline-actions">
          ${m.page_range?.[0] ? `<button class="dossier-button" type="button" data-acup-page="${m.page_range[0]}">阅读原书第 ${m.page_range[0]} 页</button>` : ""}
          ${m.page_range?.[0] ? `<button class="dossier-button ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="ni-acupuncture-v2-20100703" data-ctx-page="${m.page_range[0]}" data-ctx-q="${esc(m.canonical_name)}">上下文滑读 ↗</button>` : ""}
        </div>
      </div>
      ${statusPills(m)}
      ${riskBanner(m)}
      <p class="lead">${esc(m.summary)}</p>

      <section class="detail-section">
        <h3>经络核心属性</h3>
        <div class="acup-kv-grid">
          <div><span>脏腑表里</span><p>${esc(m.zang_fu)}</p>${m.paired_meridian ? `<button class="text-button" type="button" data-acup-open="meridian" data-acup-id="${encodeURIComponent(m.paired_meridian.id)}">查看表里经：${esc(m.paired_meridian.canonical_name)}</button>` : ""}</div>
          <div><span>阴阳五行</span><p>${esc(m.yin_yang_five_element)}</p></div>
          <div><span>气血流注</span><p>${esc(m.flow_hour)}</p></div>
        </div>
        <p style="margin-top:10px;font-size:13px;color:#475148;">${esc(m.pathway_source)}</p>
        ${fsEntries.length ? `<div class="acup-fiveshu-row">${fsEntries.map(([lbl, pid]) => {
          const pt = (m.resolved_acupoints || []).find((x) => x.id === pid);
          return `<button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(pid)}">${esc(lbl)}：${esc(pt?.canonical_name || pid.split(":").pop())}</button>`;
        }).join("")}</div>` : ""}
      </section>

      <section class="detail-section">
        <h3>所属穴位与关联点（${(m.resolved_acupoints || []).length}）</h3>
        <div class="acup-point-chips">${(m.resolved_acupoints || []).map((pt) => `
          <button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(pt.id)}">
            ${pt.sequence ? `${pt.sequence}. ` : ""}${esc(pt.canonical_name)}
            <small>${esc((pt.special_categories || [])[0] || REV_LABEL[pt.review_status] || "")}</small>
          </button>`).join("") || `<p class="muted-line">该经络穴位尚待逐章审校录入。</p>`}
        </div>
      </section>

      <section class="detail-section">
        <h3>五层内容严格区分</h3>
        ${renderContentLayers(m.content_layers)}
      </section>

      ${renderOpenQuestions(m.open_questions)}

      <section class="detail-section">
        <h3>原文依据锚点（点击看整页扫描与脚注）</h3>
        ${renderSpans(m.source_spans)}
      </section>

      <section class="detail-section">
        <h3>双向关联网络（${(m.relations || []).length}）</h3>
        ${renderRelations(m.relations)}
      </section>

      ${renderNeijingLinks(m.neijing_relations)}
    </article>`;
  }

  function renderNeijingLinks(items) {
    if (!items || !items.length) return "";
    return `<section class="detail-section">
      <h3>《黄帝内经·素问》理论渊源（${items.length}）</h3>
      <div class="nj-link-grid">${items.map((rel) => {
        const attr = rel.target_kind === "chapter"
          ? `data-nj-jump-chapter="${encodeURIComponent(rel.target_nav_id)}"`
          : `data-nj-jump-concept="${encodeURIComponent(rel.target_nav_id)}"`;
        return `<button type="button" class="nj-rel-btn" ${attr}>
          <div class="nj-link-head">
            <strong>${esc(rel.canonical_name)}</strong>
            <em>${esc(rel.submodule_label || rel.chapter_title || "内经")} · ↗</em>
          </div>
          <p>${esc(rel.rationale || rel.label || "查看《黄帝内经·素问》原文与倪注")}</p>
        </button>`;
      }).join("")}</div>
    </section>`;
  }

  async function openPoint(id, skipHash) {
    const detail = qEl("#acup-detail");
    detail.innerHTML = `<div class="loading">正在读取穴位条目...</div>`;
    const pt = await req(`/api/acupuncture/points/${encodeURIComponent(id)}`);
    acupState.selectedKind = "point";
    acupState.selectedId = id;
    if (!skipHash) history.replaceState(null, "", `#/acupuncture/points/${encodeURIComponent(id)}`);
    renderCurrentList();

    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">${esc(pt.canonical_name)}</h2>
          <p class="detail-sub">${pt.meridian ? `<button class="text-button" type="button" data-acup-open="meridian" data-acup-id="${encodeURIComponent(pt.meridian.id)}">${esc(pt.meridian.canonical_name)}</button>` : ""}${pt.sequence ? ` · 第 ${pt.sequence} 穴` : ""}${pt.pinyin ? ` · ${esc(pt.pinyin)}` : ""}${(pt.aliases || []).length ? ` · 别名：${esc(pt.aliases.join("、"))}` : ""}</p>
        </div>
        <div class="inline-actions">
          ${pt.source_spans?.[0] ? `<button class="dossier-button" type="button" data-acup-page="${pt.source_spans[0].pdf_page}">原书第 ${pt.source_spans[0].pdf_page} 页</button>` : ""}
          ${pt.source_spans?.[0] ? `<button class="dossier-button ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="ni-acupuncture-v2-20100703" data-ctx-page="${pt.source_spans[0].pdf_page}" data-ctx-q="${esc(pt.canonical_name)}">上下文滑读 ↗</button>` : ""}
        </div>
      </div>
      ${statusPills(pt)}
      ${riskBanner(pt)}
      <p class="lead">${esc(pt.summary)}</p>

      ${(pt.special_categories || []).length ? `<div class="symptom-row">${pt.special_categories.map((c) => `<span class="symptom-chip">${esc(c)}</span>`).join("")}</div>` : ""}

      <section class="detail-section">
        <h3>穴位定位、主治与刺灸细节</h3>
        <div class="acup-kv-grid">
          <div><span>原书取穴定位</span><p>${esc(pt.location_source || "尚待第四章本经精读补全")}</p></div>
          <div><span>整理简明定位</span><p>${esc(pt.location_simplified || "尚待第四章本经精读补全")}</p></div>
        </div>
        ${(pt.indications || []).length ? `<h4 class="acup-subhead">原文主治与临床归类</h4><div class="symptom-row">${pt.indications.map((i) => `<span class="symptom-chip">${esc(i)}</span>`).join("")}</div>` : ""}
        ${pt.technique_notes ? `<h4 class="acup-subhead">针刺/灸法操作与补泻注意</h4><p class="acup-para">${esc(pt.technique_notes)}</p>` : ""}
        ${pt.cautions ? `<h4 class="acup-subhead">禁忌与安全注意</h4><p class="acup-para">${esc(pt.cautions)}</p>` : ""}
        ${(pt.resolved_combinations || []).length ? `<h4 class="acup-subhead">原书配穴组合</h4><div class="acup-rel-grid">${pt.resolved_combinations.map((cb) => `
          <div class="acup-rel-card">
            <button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(cb.point?.id || cb.point_id)}">${esc(cb.point?.canonical_name || cb.point_id)}<small>${esc(REV_LABEL[cb.point?.review_status] || "")}</small></button>
            <p>${esc(cb.purpose)}</p>
          </div>`).join("")}</div>` : ""}
      </section>

      <section class="detail-section">
        <h3>五层内容严格区分</h3>
        ${renderContentLayers(pt.content_layers)}
      </section>

      ${renderOpenQuestions(pt.open_questions)}

      <section class="detail-section">
        <h3>原文依据锚点</h3>
        ${renderSpans(pt.source_spans)}
      </section>

      <section class="detail-section">
        <h3>双向关联网络（${(pt.relations || []).length}）</h3>
        ${renderRelations(pt.relations)}
      </section>

      ${renderNeijingLinks(pt.neijing_relations)}
    </article>`;
  }

  async function openTechnique(id, skipHash) {
    const detail = qEl("#acup-detail");
    detail.innerHTML = `<div class="loading">正在读取针灸法则条目...</div>`;
    const tech = await req(`/api/acupuncture/techniques/${encodeURIComponent(id)}`);
    acupState.selectedKind = "technique";
    acupState.selectedId = id;
    if (!skipHash) history.replaceState(null, "", `#/acupuncture/techniques/${encodeURIComponent(id)}`);
    renderCurrentList();

    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">${esc(tech.canonical_name)}</h2>
          <p class="detail-sub">${esc(CAT_LABEL[tech.category] || tech.category)}${(tech.aliases || []).length ? ` · ${esc(tech.aliases.join("、"))}` : ""}</p>
        </div>
        ${tech.source_spans?.[0] ? `<button class="dossier-button" type="button" data-acup-page="${tech.source_spans[0].pdf_page}">原书第 ${tech.source_spans[0].pdf_page} 页</button>` : ""}
      </div>
      ${statusPills(tech)}
      ${riskBanner(tech)}
      <p class="lead">${esc(tech.summary)}</p>

      <section class="detail-section">
        <h3>法则核心与分步要点</h3>
        <p class="acup-para"><strong>核心用途：</strong>${esc(tech.clinical_purpose)}</p>
        <ol class="dossier-steps">${(tech.steps_or_rules || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        ${tech.cautions ? `<p class="acup-para" style="margin-top:10px;color:#7a3e28;"><strong>风险边界：</strong>${esc(tech.cautions)}</p>` : ""}
      </section>

      <section class="detail-section">
        <h3>五层内容严格区分</h3>
        ${renderContentLayers(tech.content_layers)}
      </section>

      ${renderOpenQuestions(tech.open_questions)}

      <section class="detail-section">
        <h3>原文依据锚点</h3>
        ${renderSpans(tech.source_spans)}
      </section>

      <section class="detail-section">
        <h3>双向关联网络（${(tech.relations || []).length}）</h3>
        ${renderRelations(tech.relations)}
      </section>

      ${renderNeijingLinks(tech.neijing_relations)}
    </article>`;
  }

  async function openCondition(id, skipHash) {
    const detail = qEl("#acup-detail");
    detail.innerHTML = `<div class="loading">正在读取治症专题...</div>`;
    const cond = await req(`/api/acupuncture/conditions/${encodeURIComponent(id)}`);
    acupState.selectedKind = "condition";
    acupState.selectedId = id;
    if (!skipHash) history.replaceState(null, "", `#/acupuncture/conditions/${encodeURIComponent(id)}`);
    renderCurrentList();

    const patternsHtml = (cond.sub_patterns || []).map((pat, i) => `
      <article class="acup-pattern-card">
        <div class="acup-pattern-head">
          <h4><span>0${i + 1}</span> ${esc(pat.pattern_name)}</h4>
          ${pat.source_spans?.[0] ? `<button class="text-button" type="button" data-acup-page="${pat.source_spans[0].pdf_page}">第 ${pat.source_spans[0].pdf_page} 页原文</button>` : ""}
        </div>
        <div class="acup-pattern-body">
          <div>
            <strong>症状表现：</strong>
            <div class="symptom-row">${(pat.symptoms || []).map((s) => `<span class="symptom-chip">${esc(s)}</span>`).join("")}</div>
          </div>
          <p><strong>传统辨证与依据：</strong>${esc(pat.syndrome_differentiation)}</p>
          <div>
            <strong>涉及经络与原文取穴：</strong>
            <div class="acup-point-chips">
              ${(pat.resolved_meridians || []).map((m) => `<button type="button" class="text-button" data-acup-open="meridian" data-acup-id="${encodeURIComponent(m.id)}">经：${esc(m.canonical_name)}</button>`).join("")}
              ${(pat.resolved_points || []).map((pt) => `<button type="button" class="herb-formula-link" data-acup-open="point" data-acup-id="${encodeURIComponent(pt.id)}">穴：${esc(pt.canonical_name)}<small>${esc(REV_LABEL[pt.review_status] || "")}</small></button>`).join("")}
            </div>
          </div>
          <p><strong>为什么选用这些穴（推理链）：</strong>${esc(pat.why_selected)}</p>
          ${pat.differentiation_notes ? `<p><strong>不同情况区分与边界：</strong>${esc(pat.differentiation_notes)}</p>` : ""}
          ${(pat.open_questions || []).length ? `<div class="acup-sub-open"><strong>本分型尚待考证：</strong><ul>${pat.open_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></div>` : ""}
          ${renderSpans(pat.source_spans)}
        </div>
      </article>`).join("");

    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">${esc(cond.canonical_name)}</h2>
          <p class="detail-sub">第六章 针灸治症系列 · 原书第 ${(cond.page_range || [])[0] || "?"}–${(cond.page_range || [])[1] || "?"} 页${(cond.aliases || []).length ? ` · 含：${esc(cond.aliases.slice(0, 5).join("、"))}` : ""}</p>
        </div>
        <div class="inline-actions">
          ${cond.page_range?.[0] ? `<button class="dossier-button" type="button" data-acup-page="${cond.page_range[0]}">阅读原书第 ${cond.page_range[0]} 页</button>` : ""}
          ${cond.page_range?.[0] ? `<button class="dossier-button ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="ni-acupuncture-v2-20100703" data-ctx-page="${cond.page_range[0]}" data-ctx-q="${esc(cond.canonical_name)}">上下文滑读 ↗</button>` : ""}
        </div>
      </div>
      ${statusPills(cond)}
      ${riskBanner(cond)}
      <p class="lead">${esc(cond.summary)}</p>

      <section class="detail-section">
        <h3>分型辨证、取穴理由与适用边界（${(cond.sub_patterns || []).length} 项）</h3>
        ${patternsHtml || `<p class="muted-line">本治症条目当前仅作全书第六章目录锚定，证候分型与证据链尚待逐章精读拆条；可点击右上角“阅读原书”直接查看扫描原页文字。</p>`}
      </section>

      <section class="detail-section">
        <h3>五层内容严格区分</h3>
        ${renderContentLayers(cond.content_layers)}
      </section>

      ${renderOpenQuestions(cond.open_questions)}

      <section class="detail-section">
        <h3>双向关联网络（${(cond.relations || []).length}）</h3>
        ${renderRelations(cond.relations)}
      </section>

      ${renderNeijingLinks(cond.neijing_relations)}
    </article>`;
  }

  async function openSourcePage(pdfPage, skipHash) {
    const p = Number(pdfPage);
    if (!p || p < 1 || p > 216) return;
    const detail = qEl("#acup-detail");
    detail.innerHTML = `<div class="loading">正在读取原书第 ${p} 页...</div>`;
    const row = await req(`/api/acupuncture/source-pages/${p}`);
    acupState.selectedKind = "page";
    acupState.selectedId = String(p);
    acupState.selectedPage = p;
    if (!skipHash) history.replaceState(null, "", `#/acupuncture/page/${p}`);
    renderCurrentList();

    const footnotes = row.footnotes || [];
    const secs = row.covering_sections || [];
    detail.innerHTML = `<article class="detail-article">
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">原书第 ${esc(row.printed_page || row.pdf_page)} 页</h2>
          <p class="detail-sub">《倪海厦人纪系列之针灸教程》· V2-20100703 · PDF 第 ${row.pdf_page} / 216 页</p>
        </div>
        <div class="inline-actions">
          <button class="text-button" type="button" ${p <= 1 ? "disabled" : ""} data-acup-page="${p - 1}">← 上一页</button>
          <button class="text-button" type="button" ${p >= 216 ? "disabled" : ""} data-acup-page="${p + 1}">下一页 →</button>
          <button class="dossier-button" type="button" data-acup-toggle-img="${p}">${acupState.showPageImage ? "收起原页图像" : "对照原页图像"}</button>
        </div>
      </div>

      ${secs.length ? `<div class="proof-row">${secs.map((s) => `<span class="proof-chip">${esc(s.chapter_title)} · ${esc(s.section_title)}</span>`).join("")}</div>` : ""}

      ${acupState.showPageImage ? `<div class="acup-page-img-wrap">
        <img ${window.tcmImgAttrs ? window.tcmImgAttrs(row.image_url) : `src="${esc(row.image_url)}"`} alt="针灸教程第 ${p} 页原页扫描图" loading="lazy">
      </div>` : ""}

      <section class="detail-section">
        <h3>正文内容（已几何去页眉页脚与脚注线）</h3>
        <div class="curated-quote acup-page-body">${esc(row.body_text)}</div>
      </section>

      ${footnotes.length ? `<section class="detail-section">
        <h3>本页原书脚注与字词音释</h3>
        <div class="acup-footnotes">${footnotes.map((fn) => `<p>${esc(fn)}</p>`).join("")}</div>
      </section>` : ""}

      <section class="detail-section">
        <h3>溯源检验信息</h3>
        <p class="source-note">页码锚点：${esc(row.page_id)} · 行数：${esc(row.line_count)} · SHA-256：<code>${esc((row.text_sha256 || "").slice(0, 16))}...</code></p>
      </section>
    </article>`;
  }

  async function runDiagnoseQuery(newQ, skipHash) {
    acupState.dim = "diagnose";
    acupState.selectedKind = "";
    acupState.selectedId = "";
    acupState.query = newQ;
    if (qEl("#acup-query")) qEl("#acup-query").value = newQ;
    if (!skipHash) {
      const targetHash = newQ ? `#/acupuncture/diagnose/${encodeURIComponent(newQ)}` : "#/acupuncture/";
      history.replaceState(null, "", targetHash);
    }
    await onActivate();
  }

  async function onActivate() {
    await ensureLoaded();
    await refreshData();
    renderCurrentList();
  }

  function bindEvents() {
    document.addEventListener("click", (event) => {
      const dimBtn = event.target.closest("[data-acup-dim]");
      if (dimBtn) {
        acupState.dim = dimBtn.dataset.acupDim;
        acupState.selectedKind = "";
        acupState.selectedId = "";
        onActivate().catch(showAcupError);
        return;
      }
      const subBtn = event.target.closest("[data-acup-sub]");
      if (subBtn) {
        acupState.sub = subBtn.dataset.acupSub;
        onActivate().catch(showAcupError);
        return;
      }
      const chBtn = event.target.closest("[data-acup-toggle-ch]");
      if (chBtn) {
        const cid = chBtn.dataset.acupToggleCh;
        acupState.expandedChapter = acupState.expandedChapter === cid ? "" : cid;
        renderBookList();
        return;
      }
      const setQ = event.target.closest("[data-acup-set-q]");
      if (setQ) {
        runDiagnoseQuery(setQ.dataset.acupSetQ).catch(showAcupError);
        return;
      }
      const addQ = event.target.closest("[data-acup-add-q]");
      if (addQ) {
        const chip = addQ.dataset.acupAddQ;
        const cur = (acupState.query || "").trim();
        const nextQ = cur.includes(chip) ? cur : (cur ? `${cur} ${chip}` : chip);
        runDiagnoseQuery(nextQ).catch(showAcupError);
        return;
      }
      const findPt = event.target.closest("[data-acup-find-point]");
      if (findPt) {
        const kw = findPt.dataset.acupFindPoint || "";
        acupState.dim = "knowledge";
        acupState.sub = "points";
        acupState.query = kw;
        if (qEl("#acup-query")) qEl("#acup-query").value = kw;
        onActivate().then(async () => {
          if (acupState.points.length === 1) {
            await openPoint(acupState.points[0].id);
            return;
          }
          if (acupState.points.length === 0 && kw) {
            acupState.sub = "techniques";
            await onActivate();
            if (acupState.techniques.length === 1) {
              await openTechnique(acupState.techniques[0].id);
            }
          }
        }).catch(showAcupError);
        return;
      }
      const scrollBtn = event.target.closest("[data-acup-scroll]");
      if (scrollBtn) {
        const sec = document.getElementById(scrollBtn.dataset.acupScroll);
        const panel = sec?.closest(".detail-panel");
        if (sec && panel) {
          const top = sec.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop - 8;
          panel.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
        }
        return;
      }
      const openBtn = event.target.closest("[data-acup-open]");
      if (openBtn) {
        event.preventDefault();
        const kind = openBtn.dataset.acupOpen;
        const id = decodeURIComponent(openBtn.dataset.acupId);
        if (kind === "meridian") openMeridian(id).catch(showAcupError);
        else if (kind === "point") openPoint(id).catch(showAcupError);
        else if (kind === "technique") openTechnique(id).catch(showAcupError);
        else if (kind === "condition") openCondition(id).catch(showAcupError);
        return;
      }
      const pgBtn = event.target.closest("[data-acup-page]");
      if (pgBtn) {
        event.preventDefault();
        openSourcePage(pgBtn.dataset.acupPage).catch(showAcupError);
        return;
      }
      const imgBtn = event.target.closest("[data-acup-toggle-img]");
      if (imgBtn) {
        acupState.showPageImage = !acupState.showPageImage;
        openSourcePage(imgBtn.dataset.acupToggleImg, true).catch(showAcupError);
        return;
      }
      if (event.target.closest("#acup-clear-diag") || event.target.closest("#acup-reset")) {
        acupState.reviewFilter = "";
        acupState.riskFilter = "";
        acupState.meridianFilter = "";
        if (qEl("#acup-review-filter")) qEl("#acup-review-filter").value = "";
        if (qEl("#acup-risk-filter")) qEl("#acup-risk-filter").value = "";
        if (qEl("#acup-meridian-filter")) qEl("#acup-meridian-filter").value = "";
        runDiagnoseQuery("").catch(showAcupError);
      }
    });

    qEl("#acup-query")?.addEventListener("input", (e) => {
      acupState.query = e.target.value;
      window.clearTimeout(bindEvents.timer);
      bindEvents.timer = window.setTimeout(() => {
        if (acupState.dim === "diagnose") {
          acupState.selectedKind = "";
          acupState.selectedId = "";
        }
        onActivate().catch(showAcupError);
      }, 180);
    });
    qEl("#acup-query")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runDiagnoseQuery(e.target.value).catch(showAcupError);
      }
    });
    qEl("#acup-diagnose-run")?.addEventListener("click", () => {
      runDiagnoseQuery(qEl("#acup-query")?.value || "").catch(showAcupError);
    });
    qEl("#acup-review-filter")?.addEventListener("change", (e) => {
      acupState.reviewFilter = e.target.value;
      onActivate().catch(showAcupError);
    });
    qEl("#acup-risk-filter")?.addEventListener("change", (e) => {
      acupState.riskFilter = e.target.value;
      onActivate().catch(showAcupError);
    });
    qEl("#acup-meridian-filter")?.addEventListener("change", (e) => {
      acupState.meridianFilter = e.target.value;
      onActivate().catch(showAcupError);
    });
  }

  async function handleHash(hashStr) {
    await ensureLoaded();
    if (!hashStr || hashStr === "#/acupuncture" || hashStr === "#/acupuncture/") {
      acupState.dim = "diagnose";
      acupState.selectedKind = "";
      acupState.selectedId = "";
      await onActivate();
      return true;
    }
    const diagMatch = hashStr.match(/^#\/acupuncture\/diagnose\/(.*)$/);
    if (diagMatch) {
      await runDiagnoseQuery(decodeURIComponent(diagMatch[1]), true);
      return true;
    }
    const m = hashStr.match(/^#\/acupuncture\/(meridians|points|techniques|conditions|page)\/(.+)$/);
    if (!m) return false;
    const [, kind, rawTarget] = m;
    const target = decodeURIComponent(rawTarget);
    if (kind === "page") {
      acupState.dim = "book";
      renderCurrentList();
      await openSourcePage(target, true);
    } else if (kind === "meridians") {
      acupState.dim = "knowledge";
      acupState.sub = "meridians";
      await refreshData();
      await openMeridian(target, true);
    } else if (kind === "points") {
      acupState.dim = "knowledge";
      acupState.sub = "points";
      await refreshData();
      await openPoint(target, true);
    } else if (kind === "techniques") {
      acupState.dim = "knowledge";
      acupState.sub = "techniques";
      await refreshData();
      await openTechnique(target, true);
    } else if (kind === "conditions") {
      acupState.dim = "knowledge";
      acupState.sub = "conditions";
      await refreshData();
      await openCondition(target, true);
    }
    return true;
  }

  bindEvents();
  window.acupunctureUI = {
    activate: onActivate,
    handleHash,
  };
})();
