/* Stage 2 《神农本草经》 workbench:
 * - Symptom-to-herb clinical differentiation (/api/bencao/diagnose)
 * - Full 385-herb edition catalog (357 classic + 28 Ch3 Zhang Zhongjing formulas supplements)
 * - Preface & 13 general theory rules + volume-by-volume chapter browser
 * - 38 side-by-side herb differential comparisons
 * - 154-page verbatim PDF text & PNG page image溯源
 * - Bidirectional dose/processing links to 299 Shanghan/Jinkui formulas + Neijing + Acupuncture
 */
(function initBencaoModule() {
  const bcState = {
    booted: false,
    dim: "catalog", // "diagnose" | "catalog" | "theory" | "comparisons" | "pages"
    query: "",
    grade: "",
    nature: "",
    flavor: "",
    riskLevel: "",
    hasFormulas: false,
    recoveredOnly: false,
    compCategory: "",
    overview: null,
    diagnoseResult: null,
    entries: [],
    entryTotal: 0,
    entryPage: 1,
    chapters: [],
    comparisons: [],
    comparisonCategories: [],
    pageHits: [],
    selectedKind: "", // "entry" | "chapter" | "comparison" | "page"
    selectedId: "",
    selectedEntry: null,
    formulaBookFilter: "", // "" | "伤寒论" | "金匮要略"
    pagePreviewOpen: {}, // pdf_page -> boolean
  };

  const REV_LABEL = {
    approved: "精校深注",
    parsed_reviewed: "原书逐条校录",
    classic_only: "经文独存·尚待后考",
  };
  const RISK_LABEL = {
    emergency: "高危·毒剧/妊娠/重金属警戒",
    high_risk: "慎用·小毒/峻烈/基原争议",
    standard: "常规审慎",
  };

  const qEl = (sel) => document.querySelector(sel);

  function esc(val) {
    return String(val ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function req(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`请求失败 (${res.status})`);
    return res.json();
  }

  function showError(err) {
    const detail = qEl("#bc-detail");
    const msg = err?.message || "神农本草经数据读取失败";
    if (detail) {
      detail.innerHTML = `<div class="detail-inner"><div class="bc-banner bc-banner-emergency"><strong>读取提示</strong><p>${esc(msg)}</p></div></div>`;
    }
  }

  function riskBadgeHtml(risk) {
    if (risk === "emergency") {
      return `<span class="bc-pill bc-pill-emergency">高危警戒</span>`;
    }
    if (risk === "high_risk") {
      return `<span class="bc-pill bc-pill-risk">偏性/争议慎用</span>`;
    }
    return `<span class="bc-pill bc-pill-std">常规</span>`;
  }

  function reviewBadgeHtml(status) {
    if (status === "approved") {
      return `<span class="bc-pill bc-pill-approved">精校深注</span>`;
    }
    if (status === "classic_only") {
      return `<span class="bc-pill bc-pill-open">仅存经文·待考</span>`;
    }
    return `<span class="bc-pill bc-pill-reviewed">原书校录</span>`;
  }

  function updateToolbarVisibility() {
    const isCatalog = bcState.dim === "catalog";
    const isDiagnose = bcState.dim === "diagnose";
    const isTheory = bcState.dim === "theory";
    const isComp = bcState.dim === "comparisons";
    const isPages = bcState.dim === "pages";

    document.querySelectorAll("#bc-dim-switch [data-bc-dim]").forEach((btn) => {
      const active = btn.dataset.bcDim === bcState.dim;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });

    const catFilters = qEl("#bc-catalog-filters");
    const compFilterBox = qEl("#bc-comp-filter-box");
    const diagBtn = qEl("#bc-diag-btn");
    const chipStrip = qEl("#bc-prompt-chips");
    const toggleRow = qEl("#bc-toggle-row");
    const queryInput = qEl("#bc-query");

    if (catFilters) catFilters.classList.toggle("hidden", !isCatalog);
    if (toggleRow) toggleRow.classList.toggle("hidden", !isCatalog);
    if (compFilterBox) compFilterBox.classList.toggle("hidden", !isComp);
    if (diagBtn) diagBtn.classList.toggle("hidden", !(isDiagnose || isCatalog));
    if (chipStrip) chipStrip.classList.toggle("hidden", !(isDiagnose || isCatalog));

    if (queryInput) {
      if (isDiagnose) {
        queryInput.placeholder = "输入症状、证候、体质或经方症候（如：心中懊憹 失眠烦躁、四肢厥逆 里寒、便血 黑便）";
      } else if (isTheory) {
        queryInput.placeholder = "筛选本草章节、前言或药性总义 13 则（输入关键词）";
      } else if (isComp) {
        queryInput.placeholder = "搜索鉴别药对或辨异要点（如：桂枝、生附子、白术、大黄、石脂）";
      } else if (isPages) {
        queryInput.placeholder = "检索全书 154 页逐字原文（如：神农本草经、朱砂、仲景、吴普）";
      } else {
        queryInput.placeholder = "输入药名、别名、性味、症状、入方或原书关键词（共 385 味）";
      }
    }

    const titleEl = qEl("#bc-list-title");
    const subEl = qEl("#bc-list-subtitle");
    const meta = {
      diagnose: ["症状找药与辨证推演", "严格依据《本经》经文、倪海厦按语及仲景经方实证排序"],
      catalog: ["神农本草经全书目录 (385 味)", "上品 142 · 中品 112 · 下品 103 · 第三章增补经方药 28"],
      theory: ["前言 · 药性总义 · 原书八卷篇目", "含序言服药法、总义 13 则（五味阴阳升降七情九炮）及各品目次"],
      comparisons: ["本草药性鉴别对照 (38 组)", "生熟炮制之异 · 同名混名红线 · 仲景对药辨析"],
      pages: ["《倪注神农本草经》全页图鉴 (154 页)", "逐字数字化校本 + SHA-256 存证 + PDF 原页高清图预览"],
    };
    const [t, s] = meta[bcState.dim] || meta.catalog;
    if (titleEl) titleEl.textContent = t;
    if (subEl) subEl.textContent = s;

    const moreBtn = qEl("#bc-more");
    if (moreBtn && !isCatalog) {
      moreBtn.classList.add("hidden");
    }
  }

  function renderPromptChips(chips) {
    const host = qEl("#bc-prompt-chips-list");
    if (!host) return;
    host.innerHTML = (chips || [])
      .map(
        (c) =>
          `<button type="button" class="s4-chip" data-bc-prompt="${esc(c)}">${esc(c)}</button>`
      )
      .join("");
  }

  function renderHonestyBanner(ov) {
    const host = qEl("#bc-honesty-note");
    if (!host || !ov) return;
    host.innerHTML = `<strong>版本实证说明：</strong>
      <span>《神农本草经》序言沿称“365 味”以应周天之数；本电子底本实际逐条校入<strong>正经 357 味</strong>（上品 ${ov.edition_counts?.juan1_upper ?? 142} + 中品 ${ov.edition_counts?.juan2_middle ?? 112} + 下品 ${ov.edition_counts?.juan3_lower ?? 103}）+ 第三章倪海厦依《伤寒》《金匮》补录<strong>经方药 ${ov.chapter3_supplement_count ?? 28} 味</strong> = <strong>${ov.edition_total ?? 385} 味</strong>。</span>
      <span class="bc-honesty-pill">Stage 2 已补全旧版 351 味快照遗漏之 ${ov.newly_recovered_count ?? 34} 味 · 另 ${ov.classic_only_count ?? 79} 味独存经文标为“待考”不加臆解</span>`;
  }

  function renderCatalogList() {
    const listEl = qEl("#bc-list");
    const countEl = qEl("#bc-count");
    const moreBtn = qEl("#bc-more");
    if (!listEl) return;

    const selected = bcState.selectedKind === "entry" ? bcState.selectedId : "";
    listEl.innerHTML =
      bcState.entries
        .map((item) => {
          const isCh3 = item.in_shennong_classic === false;
          const isSel = selected === item.id;
          return `<button type="button" class="entity-item${isSel ? " selected" : ""}" data-bc-entry="${encodeURIComponent(item.id)}">
            <span class="entity-name">
              <strong>${esc(item.seq_raw ? `${item.seq_raw} · ` : "")}${esc(item.name)}</strong>
              <em>${esc(item.grade || (isCh3 ? "第三章增补" : "本经"))}</em>
            </span>
            <span class="entity-meta">
              ${reviewBadgeHtml(item.review_status)}
              ${item.risk_level !== "standard" ? riskBadgeHtml(item.risk_level) : ""}
              ${isCh3 ? `<span class="bc-pill bc-pill-ch3">本经未载·第三章增补</span>` : ""}
              ${item.newly_recovered_in_stage2 && !isCh3 ? `<span class="bc-pill bc-pill-recovered">Stage 2 复原</span>` : ""}
              ${item.formula_count ? `<span class="bc-pill bc-pill-formula">入 ${item.formula_count} 方</span>` : ""}
              ${item.comparison_count ? `<span>对照 ${item.comparison_count}</span>` : ""}
              <span>P.${esc(item.page_start)}</span>
            </span>
            ${item.qi_wei_raw ? `<span class="acup-entity-sub">${esc(item.qi_wei_raw)}</span>` : item.main_summary ? `<span class="acup-entity-sub">${esc(item.main_summary.slice(0, 60))}</span>` : ""}
          </button>`;
        })
        .join("") || `<div class="loading">没有符合当前筛选条件的中药条目。</div>`;

    if (countEl) countEl.textContent = `${bcState.entryTotal} 味`;
    if (moreBtn) {
      moreBtn.classList.toggle("hidden", bcState.entries.length >= bcState.entryTotal);
    }
  }

  function renderDiagnoseList(data) {
    const listEl = qEl("#bc-list");
    const countEl = qEl("#bc-count");
    if (!listEl) return;

    const items = data?.items || [];
    const alerts = (data?.safety_alerts || [])
      .map((msg) => `<div class="bc-inline-alert">${esc(msg)}</div>`)
      .join("");

    const compsHtml = (data?.related_comparisons || []).length
      ? `<div class="s4-left-mods">
          <div class="s4-mini-title">相关药性鉴别对照（${data.related_comparisons.length} 组）</div>
          ${data.related_comparisons
            .map(
              (c) => `<button type="button" class="s4-mini-mod" data-bc-comp="${encodeURIComponent(c.id)}">
                <strong>${esc(c.title)}</strong>
                <span>${esc(c.clinical_question || c.category || "")}</span>
              </button>`
            )
            .join("")}
        </div>`
      : "";

    if (!data?.query) {
      listEl.innerHTML = `<div class="loading">请在上方输入症状/证候，或直接点击常见主症提示词开始“以症求药、辨证选药”推演。</div>`;
      if (countEl) countEl.textContent = "待检索";
      return;
    }

    const cards = items
      .map((item) => {
        const isSel = bcState.selectedKind === "entry" && bcState.selectedId === item.id;
        return `<button type="button" class="entity-item${isSel ? " selected" : ""}" data-bc-diag-entry="${encodeURIComponent(item.id)}">
          <span class="entity-name">
            <strong>${esc(item.name)}</strong>
            <em>匹配度 ${esc(item.score)}</em>
          </span>
          <span class="entity-meta">
            <span class="bc-pill bc-pill-reviewed">${esc(item.grade)}</span>
            ${item.risk_level !== "standard" ? riskBadgeHtml(item.risk_level) : ""}
            ${item.formula_count ? `<span class="bc-pill bc-pill-formula">入 ${item.formula_count} 方</span>` : ""}
          </span>
          <span class="acup-entity-sub">命中词：${(item.matched_terms || []).map((t) => `【${esc(t)}】`).join(" ") || "综合药性"}</span>
          ${item.why_recommended ? `<span class="bc-diag-snippet">${esc(item.why_recommended.slice(0, 88))}${item.why_recommended.length > 88 ? "…" : ""}</span>` : ""}
        </button>`;
      })
      .join("");

    listEl.innerHTML =
      alerts +
      (cards || `<div class="loading">未检索到直接匹配的药物，请尝试缩短或更换症状关键词。</div>`) +
      compsHtml;
    if (countEl) countEl.textContent = `命中 ${data.total ?? items.length} 味`;
  }

  function renderTheoryList() {
    const listEl = qEl("#bc-list");
    const countEl = qEl("#bc-count");
    if (!listEl) return;
    const kw = (bcState.query || "").trim();
    const filtered = bcState.chapters.filter((ch) => {
      if (!kw) return true;
      return `${ch.title} ${ch.summary || ""} ${ch.grade || ""}`.includes(kw);
    });
    listEl.innerHTML =
      filtered
        .map((ch) => {
          const isSel = bcState.selectedKind === "chapter" && bcState.selectedId === ch.id;
          const pagesLabel = ch.pdf_pages?.length
            ? `P.${ch.pdf_pages[0]}–${ch.pdf_pages[ch.pdf_pages.length - 1]}`
            : "";
          return `<button type="button" class="entity-item${isSel ? " selected" : ""}" data-bc-chapter="${encodeURIComponent(ch.id)}">
            <span class="entity-name">
              <strong>${esc(ch.title)}</strong>
              <em>${esc(pagesLabel)}</em>
            </span>
            <span class="entity-meta">
              ${ch.entry_count ? `<span class="bc-pill bc-pill-approved">${ch.entry_count} 味药物</span>` : ""}
              ${ch.rules_count ? `<span class="bc-pill bc-pill-reviewed">${ch.rules_count} 则药性总义</span>` : ""}
              ${ch.grade ? `<span>${esc(ch.grade)}</span>` : ""}
            </span>
            ${ch.summary ? `<span class="acup-entity-sub">${esc(ch.summary)}</span>` : ""}
          </button>`;
        })
        .join("") || `<div class="loading">无匹配的本草卷章。</div>`;
    if (countEl) countEl.textContent = `${filtered.length} 章`;
  }

  function renderComparisonsList() {
    const listEl = qEl("#bc-list");
    const countEl = qEl("#bc-count");
    if (!listEl) return;

    listEl.innerHTML =
      bcState.comparisons
        .map((comp) => {
          const isSel = bcState.selectedKind === "comparison" && bcState.selectedId === comp.id;
          const names = (comp.herbs_meta || []).map((h) => h.short_name || h.name).join(" vs ");
          return `<button type="button" class="entity-item${isSel ? " selected" : ""}" data-bc-comp="${encodeURIComponent(comp.id)}">
            <span class="entity-name">
              <strong>${esc(comp.title)}</strong>
              <em>${esc(comp.category)}</em>
            </span>
            <span class="entity-meta">
              <span class="bc-pill bc-pill-reviewed">${esc(names || `${comp.entry_ids?.length || 0} 味对照`)}</span>
              ${comp.safety_note ? `<span class="bc-pill bc-pill-risk">含鉴别红线</span>` : ""}
            </span>
            <span class="acup-entity-sub">${esc(comp.clinical_question || "")}</span>
          </button>`;
        })
        .join("") || `<div class="loading">没有匹配的对照专题。</div>`;
    if (countEl) countEl.textContent = `${bcState.comparisons.length} 组`;
  }

  function renderPagesList() {
    const listEl = qEl("#bc-list");
    const countEl = qEl("#bc-count");
    if (!listEl) return;

    listEl.innerHTML =
      bcState.pageHits
        .map((pg) => {
          const isSel = bcState.selectedKind === "page" && String(bcState.selectedId) === String(pg.pdf_page);
          return `<button type="button" class="entity-item${isSel ? " selected" : ""}" data-bc-page="${pg.pdf_page}">
            <span class="entity-name">
              <strong>PDF 第 ${pg.pdf_page} 页${pg.printed_page ? `（书页 ${esc(pg.printed_page)}）` : ""}</strong>
              <em>${pg.is_blank ? "空白衬页" : esc(pg.page_role || "正文")}</em>
            </span>
            <span class="acup-entity-sub">${esc(pg.snippet || "（空白页）")}</span>
          </button>`;
        })
        .join("") || `<div class="loading">未检索到匹配的书页原文。</div>`;
    if (countEl) countEl.textContent = `${bcState.pageHits.length} 页`;
  }

  function renderComparisonCardHtml(comp) {
    const herbsBtns = (comp.herbs_meta || [])
      .map(
        (h) =>
          `<button type="button" class="tag bc-peer-btn" data-bc-entry="${encodeURIComponent(h.id)}">
            查看【${esc(h.name)}】详情 · ${esc(h.grade)}${h.formula_count ? ` · 入 ${h.formula_count} 方` : ""} ↗
          </button>`
      )
      .join("");
    const pointsRows = (comp.comparison_points || [])
      .map((pt) => {
        const aspect = pt.aspect || pt.dimension || pt.key || "鉴别要点";
        const entries = Object.entries(pt).filter(([k]) => !["aspect", "dimension", "key"].includes(k));
        return `<tr>
          <th>${esc(aspect)}</th>
          <td>${entries
            .map(([k, v]) => `<div class="bc-point-row"><strong>${esc(k)}：</strong><span>${esc(v)}</span></div>`)
            .join("")}</td>
        </tr>`;
      })
      .join("");

    return `<div class="bc-comp-card">
      <div class="bc-comp-head">
        <div>
          <span class="bc-pill bc-pill-reviewed">${esc(comp.category || "本草对照")}</span>
          <h4>${esc(comp.title)}</h4>
        </div>
      </div>
      ${comp.clinical_question ? `<p class="bc-comp-q"><strong>临证鉴别关键：</strong>${esc(comp.clinical_question)}</p>` : ""}
      ${herbsBtns ? `<div class="tag-row">${herbsBtns}</div>` : ""}
      ${pointsRows ? `<table class="bc-comp-table"><tbody>${pointsRows}</tbody></table>` : ""}
      ${comp.ni_clinical_key ? `<div class="review-note"><strong>【倪氏临证抉择要点】</strong>${esc(comp.ni_clinical_key)}</div>` : ""}
      ${comp.safety_note ? `<div class="warning-box"><strong>【高危与红线警示】</strong>${esc(comp.safety_note)}</div>` : ""}
      ${comp.source_ref ? `<div class="source-locator">出处锚点：${esc(comp.source_ref)} <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${esc(comp.source_page || 0)}" data-ctx-q="${esc((comp.herbs || [comp.title || ""])[0])}">滑动对照原书上下文 ↗</button></div>` : ""}
    </div>`;
  }

  function renderEntryDetail(entry, diagCtx = null) {
    const detailEl = qEl("#bc-detail");
    if (!detailEl || !entry) return;
    bcState.selectedEntry = entry;

    const props = entry.properties || {};
    const classic = entry.classic_original || {};
    const apps = entry.applications || {};
    const ni = entry.ni_haixia_annotations || {};
    const proc = entry.processing_and_compatibility || {};
    const isCh3 = classic.in_shennong_classic === false || entry.kind === "ch3";
    const risk = props.risk_level || "standard";

    let safetyBanner = "";
    const toxNote =
      props.toxicity && props.toxicity !== "无毒"
        ? props.toxicity
        : risk === "emergency"
          ? "古经虽注“无毒”或未明言，实具重金属/炼变/严峻禁忌红线"
          : "虽注无毒，仍具偏性或古今品种分歧";
    if (risk === "emergency") {
      safetyBanner = `<div class="bc-banner bc-banner-emergency">
        <strong>高风险 · 毒剧 / 峻攻 / 妊娠 / 重金属警示（${esc(toxNote)}）</strong>
        <p>${esc((props.risk_reasons || []).join("；") || "本书标注本品具强攻泻或峻毒偏性，仅作古典医药文献研读，须严遵先起黍粟、病去即止与正确炮制方法，绝不可未经专业辨证擅自单服。")}</p>
      </div>`;
    } else if (risk === "high_risk") {
      safetyBanner = `<div class="bc-banner bc-banner-risk">
        <strong>临床偏性与古今名实慎用提示（${esc(toxNote)}）</strong>
        <p>${esc((props.risk_reasons || []).join("；") || "含小毒、妊娠禁忌或古今品种分歧，使用前须核下方《禁忌》与《基原争议》。")}</p>
      </div>`;
    }

    const diagBanner = diagCtx
      ? `<div class="bc-diag-banner">
          <div class="bc-diag-banner-head">
            <strong>本次“症状找药”推演命中依据</strong>
            <span>综合匹配分：${esc(diagCtx.score)}</span>
          </div>
          ${diagCtx.matched_terms?.length ? `<div class="tag-row">${diagCtx.matched_terms.map((t) => `<span class="symptom-chip">命中：${esc(t)}</span>`).join("")}</div>` : ""}
          ${diagCtx.why_recommended ? `<p><strong>选用依据：</strong>${esc(diagCtx.why_recommended)}</p>` : ""}
          ${diagCtx.when_to_use ? `<p><strong>适用指征：</strong>${esc(diagCtx.when_to_use)}</p>` : ""}
          ${diagCtx.contraindication_guard ? `<p class="bc-guard-line"><strong>避忌防线：</strong>${esc(diagCtx.contraindication_guard)}</p>` : ""}
        </div>`
      : "";

    // Layer 1: Classic Original
    const classicHtml = isCh3
      ? `<div class="bc-ch3-notice">
          <strong>【本经未载 · 第三章仲景经方增补条目】</strong>
          <p>${esc(classic.text)}</p>
          ${classic.edition_note ? `<small>${esc(classic.edition_note)}</small>` : ""}
        </div>`
      : `<div class="dossier-quote source-quote">${esc(classic.text || "原文未录")}</div>
        ${classic.appended_notes?.length ? `<div class="review-note">${classic.appended_notes.map(esc).join("<br>")}</div>` : ""}
        ${classic.edition_note ? `<div class="source-note">校勘说明：${esc(classic.edition_note)}</div>` : ""}`;

    // Layer 2: Properties
    const natureTags = [...(props.four_natures || []), ...(props.five_flavors || [])];
    const propGridHtml = `<div class="bc-prop-grid">
      <div class="bc-prop-card"><span>气味毒性原文</span><strong>${esc(props.qi_wei_raw || "见《本经》经文")}</strong></div>
      <div class="bc-prop-card"><span>四气 · 五味</span><strong>${natureTags.length ? esc(natureTags.join(" · ")) : "见经文"}${props.toxicity && props.toxicity !== "未明言" ? `（${esc(props.toxicity)}）` : ""}</strong></div>
      <div class="bc-prop-card"><span>归经线索</span><strong>${(props.meridians || []).length ? esc(props.meridians.join("、")) : "原文未单独标归经"}</strong></div>
      <div class="bc-prop-card"><span>产地生境</span><strong>${esc(props.origin || "《本经》/《别录》未单列")}</strong></div>
    </div>
    ${apps.main_summary ? `<div class="bc-subblock"><h5>【主治纲领】</h5><p class="section-copy">${esc(apps.main_summary)}</p></div>` : ""}
    ${apps.symptom_keywords?.length ? `<div class="tag-row bc-sym-tags">${apps.symptom_keywords.map((s) => `<button type="button" class="symptom-chip bc-sym-jump" data-bc-diag-chip="${esc(s)}" title="以此症状重新找药">${esc(s)}</button>`).join("")}</div>` : ""}`;

    // Layer 3: Ni Haixia Annotations
    const niBlocks = [];
    if (ni.why_it_works) niBlocks.push(`<div class="bc-ni-box"><h5>为什么用 · 药理与气味象义</h5><p>${esc(ni.why_it_works)}</p></div>`);
    if (ni.when_to_use) niBlocks.push(`<div class="bc-ni-box"><h5>何时选用 · 临床抓手</h5><p>${esc(ni.when_to_use)}</p></div>`);
    if (ni.differentiation_notes) niBlocks.push(`<div class="bc-ni-box bc-ni-warn"><h5>临证辨异与误用警戒</h5><p>${esc(ni.differentiation_notes)}</p></div>`);
    if (ni.clinical_experience?.length) {
      niBlocks.push(`<div class="bc-ni-box"><h5>临床用方经验</h5><ul>${ni.clinical_experience.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`);
    }
    if (ni.explicit_ni_notes?.length) {
      niBlocks.push(`<div class="bc-ni-box bc-ni-verbatim"><h5>原书【倪注】按语全文</h5>${ni.explicit_ni_notes.map((n) => `<blockquote class="dossier-quote">${esc(n)}</blockquote>`).join("")}</div>`);
    }
    if (ni.chapter3_pithy_summary) {
      niBlocks.push(`<div class="bc-ni-box bc-ni-verbatim"><h5>第三章倪氏总提要</h5><p>${esc(ni.chapter3_pithy_summary)}</p></div>`);
    } else if (ni.chapter3_editor_intro && isCh3) {
      niBlocks.push(`<div class="bc-ni-box"><h5>第三章按语说明</h5><p>${esc(ni.chapter3_editor_intro)}</p></div>`);
    }
    if (ni.unlabeled_clinical_excerpts?.length) {
      niBlocks.push(`<div class="bc-ni-box"><h5>讲记口述阐述节录</h5>${ni.unlabeled_clinical_excerpts.map((u) => `<p>${esc(u)}</p>`).join("")}</div>`);
    }
    const niHtml = niBlocks.length
      ? niBlocks.join("")
      : `<div class="missing-composition">原书此条仅录经文（及旧注片断），未附【倪注】口述按语；系统严守存真规范，不代为增补。</div>`;

    // Layer 4: Processing & Compatibility
    const procDiffText = proc.processing_differences || "";
    const procHtml = `<div class="bc-proc-grid">
      <div><h5>【原书用量】</h5><p>${esc(proc.dosage || "原文未单列【用量】")}</p></div>
      <div><h5>【炮制方法】</h5><p>${esc(proc.processing || "原文未单列【炮制】")}</p></div>
      ${procDiffText ? `<div class="bc-proc-full"><h5>【生熟炮制关键差异】</h5><p>${esc(procDiffText)}</p></div>` : ""}
      ${proc.seven_relations?.length ? `<div class="bc-proc-full"><h5>【七情配伍：畏恶反杀使忌】</h5><div class="tag-row">${proc.seven_relations.map((r) => `<span class="tag">${esc(r)}</span>`).join("")}</div></div>` : ""}
      ${proc.contraindications ? `<div class="bc-proc-full bc-contra-box"><h5>【禁忌与慎用】</h5><p>${esc(proc.contraindications)}</p></div>` : ""}
      ${proc.appendices?.length ? `<div class="bc-proc-full"><h5>【同条附品 / 炮制品分支】</h5>${proc.appendices.map((ap) => `<div class="bc-sub-appendix"><strong>${esc(ap.title || "附品")}：</strong><span>${esc(ap.text || "")}</span></div>`).join("")}</div>` : ""}
    </div>`;

    // Layer 5: Historical Commentaries
    const commList = entry.historical_commentaries || [];
    const commHtml = commList.length
      ? `<div class="bc-comm-list">${commList
          .map(
            (c) => `<article class="bc-comm-card">
              <div class="bc-comm-head"><strong>${esc(c.tag || c.scholar)}</strong><span>${esc(c.scholar || "")}</span></div>
              <p>${esc(c.text)}</p>
            </article>`
          )
          .join("")}</div>`
      : `<div class="section-copy">本条原书未单列别录、甄权、容川、灵胎等后世注家分段。</div>`;

    // Layer 6: Controversies & Open Questions & Organizer Notes
    const contList = entry.identity_controversies || [];
    const openList = entry.open_questions || [];
    const orgList = entry.organizer_notes || [];
    const dualLink =
      entry.name === "白芷"
        ? entry.kind === "ch3"
          ? `<button type="button" class="text-button" data-bc-entry="${encodeURIComponent("bencao:白芷")}">对照查看《本经·中品第173条》白芷 ↗</button>`
          : `<button type="button" class="text-button" data-bc-entry="${encodeURIComponent("bencao:ch3-白芷")}">对照查看《第三章第15条》增补白芷 ↗</button>`
        : "";
    const controversyHtml =
      contList.length || openList.length || orgList.length || dualLink
        ? `${dualLink ? `<div class="tag-row">${dualLink}</div>` : ""}
           ${contList
             .map(
               (c) => `<div class="bc-controversy-box">
                 <strong>【基原 / 别名 / 用药争议（绝不强并）】${esc(c.topic)}</strong>
                 <p>${esc(c.summary)}</p>
                 ${c.policy ? `<small>处理原则：${esc(c.policy)}</small>` : ""}
               </div>`
             )
             .join("")}
           ${openList
             .map(
               (oq) => `<div class="bc-open-q-box">
                 <strong>【尚待考证 · 保留原貌不推演】</strong>
                 <p>${esc(oq)}</p>
               </div>`
             )
             .join("")}
           ${orgList.length ? `<div class="review-note"><strong>【整理者校按】</strong>${orgList.map(esc).join("；")}</div>` : ""}`
        : `<div class="section-copy">本条基原清楚，暂无古今同名争议或待考悬案。</div>`;

    // Layer 7: Comparisons
    const compsDetailed = entry.comparisons_detailed || [];
    const compHtml = compsDetailed.length
      ? compsDetailed.map(renderComparisonCardHtml).join("")
      : `<div class="section-copy">本品暂无单独成组的鉴别对照表；可切换至顶部“本草鉴别对照 (38)”查阅全部鉴别专题。</div>`;

    // Layer 8: Formula Usages (Bidirectional Links with Exact Dose & Processing!)
    const allUsages = entry.formula_usages || [];
    const shanghanCount = allUsages.filter((u) => u.book === "伤寒论").length;
    const jinkuiCount = allUsages.filter((u) => u.book === "金匮要略").length;
    const activeBook = bcState.formulaBookFilter;
    const shownUsages = activeBook ? allUsages.filter((u) => u.book === activeBook) : allUsages;
    const formulaHtml = allUsages.length
      ? `${allUsages.length > 6 ? `<div class="bc-formula-filter-row">
            <button type="button" class="s4-chip${!activeBook ? " bc-chip-active" : ""}" data-bc-fbook="">全部 (${allUsages.length})</button>
            ${shanghanCount ? `<button type="button" class="s4-chip${activeBook === "伤寒论" ? " bc-chip-active" : ""}" data-bc-fbook="伤寒论">伤寒论 (${shanghanCount})</button>` : ""}
            ${jinkuiCount ? `<button type="button" class="s4-chip${activeBook === "金匮要略" ? " bc-chip-active" : ""}" data-bc-fbook="金匮要略">金匮要略 (${jinkuiCount})</button>` : ""}
          </div>` : ""}
          <div class="bc-formula-grid">${shownUsages
            .map(
              (u) => `<button type="button" class="bc-formula-card" data-formula-id="${encodeURIComponent(u.formula_id)}">
                <div class="bc-formula-head">
                  <strong>${esc(u.formula_name)}</strong>
                  <span>${esc(u.book)}${u.six_meridian ? ` · ${esc(u.six_meridian)}` : u.chapter ? ` · ${esc(u.chapter)}` : ""} ↗</span>
                </div>
                <div class="bc-formula-dose">
                  <span>原方用名：<strong>${esc(u.ingredient_raw_name)}</strong></span>
                  <span>剂量：<strong>${esc(u.dose || "见原方")}</strong></span>
                  ${u.processing ? `<span>炮制/制法：<strong>${esc(u.processing)}</strong></span>` : ""}
                </div>
                ${u.mapping_note ? `<div class="bc-formula-note">别名对照：${esc(u.mapping_note)}</div>` : ""}
                ${u.controversy ? `<div class="bc-formula-warn">争议提示：${esc(u.controversy)}</div>` : ""}
              </button>`
            )
            .join("")}</div>`
      : `<div class="section-copy">《伤寒论》《金匮要略》现行 299 首经方正方中未直接检出以此药为固定主药的条文。</div>`;

    // Layer 9: Neijing & Acupuncture Cross-Links
    const njRels = entry.neijing_relations || [];
    const njHtml = njRels.length
      ? `<div class="nj-link-grid">${njRels
          .map((rel) => {
            const attr =
              rel.target_kind === "chapter"
                ? `data-nj-jump-chapter="${encodeURIComponent(rel.target_nav_id)}"`
                : `data-nj-jump-concept="${encodeURIComponent(rel.target_nav_id)}"`;
            return `<button type="button" class="nj-rel-btn" ${attr}>
              <div class="nj-link-head">
                <strong>${esc(rel.canonical_name)}</strong>
                <em>${esc(rel.submodule_label || rel.chapter_title || "内经")} · ↗</em>
              </div>
              <p>${esc(rel.rationale || rel.label || "查看《黄帝内经·素问》原文与倪注")}</p>
            </button>`;
          })
          .join("")}</div>`
      : `<div class="section-copy">暂无直接锚定的《黄帝内经》专题链接；可结合下方五味五色阴阳升降总义理解其气味机理。</div>`;

    // Layer 10: Source spans + PNG Page Viewer
    const spans = entry.source_spans || [];
    const uniquePages = [...new Set(entry.pdf_pages || [entry.page_start])];
    const spansHtml = `<div class="bc-source-list">
      ${spans
        .map(
          (sp) => `<div class="source-box">
            <div class="source-locator">
              <span>底本溯源：倪注《神农本草经》 · PDF 第 ${sp.pdf_page} 页${sp.printed_page ? `（书页 ${esc(sp.printed_page)}）` : ""} · SHA256:${esc((sp.text_sha256 || "").slice(0, 12))}</span>
              <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${sp.pdf_page}" data-ctx-q="${esc((sp.quote || entry.name).slice(0, 20))}">上下文滑动对照（消除跨页截断）↗</button>
            </div>
            <p>逐字锚定引文：“${esc(sp.quote)}”</p>
          </div>`
        )
        .join("")}
      <div class="bc-page-preview-bar">
        ${uniquePages
          .map((pNo) => {
            const open = Boolean(bcState.pagePreviewOpen[pNo]);
            return `<div class="bc-page-toggle-wrap">
              <button type="button" class="text-button" data-bc-toggle-img="${pNo}">${open ? `收起 PDF 第 ${pNo} 页原页图` : `展开查看 PDF 第 ${pNo} 页原书扫描图`}</button>
              <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${pNo}" data-ctx-q="${esc(entry.name)}">上下文连续滑读（PDF p.${pNo} 起）↗</button>
              <button type="button" class="text-button" data-bc-open-page="${pNo}">转至原页逐字校对视图 ↗</button>
              ${open ? `<div class="bc-page-img-frame"><img ${window.tcmImgAttrs ? window.tcmImgAttrs(`/api/bencao/source-pages/${pNo}/image`) : `src="/api/bencao/source-pages/${pNo}/image"`} alt="《倪注神农本草经》PDF 第 ${pNo} 页" loading="lazy"></div>` : ""}
            </div>`;
          })
          .join("")}
      </div>
    </div>`;

    detailEl.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">倪海厦注《神农本草经》 · ${esc(entry.grade)} · 第 ${esc(entry.seq_raw)} 条 · PDF P.${esc(entry.page_start)}${entry.page_end && entry.page_end !== entry.page_start ? `–${esc(entry.page_end)}` : ""}${entry.toc_printed_page ? `（书页 ${esc(entry.toc_printed_page)}）` : ""} <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${esc(entry.page_start || 1)}" data-ctx-q="${esc(entry.name)}">滑动对照本经上下页 ↗</button></div>
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">${esc(entry.name)}</h2>
          <p class="detail-subtitle">${entry.aliases?.length ? `原书异名 / 别称：${esc(entry.aliases.join(" · "))}` : isCh3 ? "第三章张仲景经方实用增补药味" : "《神农本草经》正经药味"}</p>
        </div>
        <div class="tag-row">
          ${reviewBadgeHtml(entry.review_status)}
          ${riskBadgeHtml(risk)}
          ${isCh3 ? `<span class="bc-pill bc-pill-ch3">本经未载·第三章增补</span>` : ""}
          ${entry.newly_recovered_in_stage2 && !isCh3 ? `<span class="bc-pill bc-pill-recovered">Stage 2 遗漏复原</span>` : ""}
        </div>
      </div>

      ${safetyBanner}
      ${diagBanner}

      <div class="section-nav-pills">
        <button type="button" data-scroll-section="bc-sec-classic">① 本经原文</button>
        <button type="button" data-scroll-section="bc-sec-props">② 性味归经</button>
        <button type="button" data-scroll-section="bc-sec-ni">③ 倪注临证</button>
        <button type="button" data-scroll-section="bc-sec-proc">④ 炮制禁忌</button>
        <button type="button" data-scroll-section="bc-sec-comm">⑤ 历代注家 (${commList.length})</button>
        <button type="button" data-scroll-section="bc-sec-cont">⑥ 争议待考</button>
        <button type="button" data-scroll-section="bc-sec-comp">⑦ 鉴别对照 (${compsDetailed.length})</button>
        <button type="button" data-scroll-section="bc-sec-formula">⑧ 经方关联 (${allUsages.length})</button>
        <button type="button" data-scroll-section="bc-sec-neijing">⑨ 内经渊源</button>
        <button type="button" data-scroll-section="bc-sec-source">⑩ 原页图鉴</button>
      </div>

      <section id="bc-sec-classic" class="section-block">
        <div class="section-title">1.《神农本草经》原文与版本位次（严格区分正经与增补）</div>
        ${classicHtml}
      </section>

      <section id="bc-sec-props" class="section-block">
        <div class="section-title">2. 药物性味 · 四气五味 · 归经 · 主治纲领</div>
        ${propGridHtml}
      </section>

      <section id="bc-sec-ni" class="section-block">
        <div class="section-title">3. 倪海厦注解与临床使用法度</div>
        ${niHtml}
      </section>

      <section id="bc-sec-proc" class="section-block">
        <div class="section-title">4. 炮制 · 生熟异同 · 七情配伍 · 禁忌边界</div>
        ${procHtml}
      </section>

      <section id="bc-sec-comm" class="section-block">
        <div class="section-title">5. 历代注家分段（《别录》/ 甄权 / 大明 / 唐容川 / 徐灵胎 / 《药征》等）</div>
        ${commHtml}
      </section>

      <section id="bc-sec-cont" class="section-block">
        <div class="section-title">6. 古今基原争议（绝不强并） · 尚待考证 · 校按</div>
        ${controversyHtml}
      </section>

      <section id="bc-sec-comp" class="section-block">
        <div class="section-title">7. 相似药与生熟炮制鉴别对照</div>
        ${compHtml}
      </section>

      <section id="bc-sec-formula" class="section-block">
        <div class="section-title">8. 《伤寒论》《金匮要略》经方反向关联（含剂量与炮制 · 共 ${allUsages.length} 方次）</div>
        ${formulaHtml}
      </section>

      <section id="bc-sec-neijing" class="section-block">
        <div class="section-title">9. 《黄帝内经》理论渊源（${njRels.length}）</div>
        ${njHtml}
      </section>

      <section id="bc-sec-source" class="section-block">
        <div class="section-title">10. 逐页数字化文本溯源与原书 PDF 图像</div>
        ${spansHtml}
      </section>
    </div>`;
  }

  function renderChapterDetail(ch) {
    const detailEl = qEl("#bc-detail");
    if (!detailEl || !ch) return;

    const rulesHtml = ch.rules?.length
      ? `<div class="section-block">
          <div class="section-title">药性总义专题（共 ${ch.rules.length} 则 · 点击可看具体原页）</div>
          <div class="bc-rules-list">${ch.rules
            .map(
              (r) => `<article class="bc-rule-card">
                <div class="bc-rule-head">
                  <strong>${esc(r.title)}</strong>
                  <span class="bc-pill bc-pill-reviewed">${esc(r.category || "总义")}</span>
                </div>
                ${r.summary ? `<p><strong>要义归纳：</strong>${esc(r.summary)}</p>` : ""}
                ${r.quote ? `<blockquote class="dossier-quote">${esc(r.quote)}</blockquote>` : ""}
                ${r.clinical_impact ? `<div class="review-note"><strong>临床指导意义：</strong>${esc(r.clinical_impact)}</div>` : ""}
              </article>`
            )
            .join("")}</div>
        </div>`
      : "";

    const entriesHtml = ch.entries?.length
      ? `<div class="section-block">
          <div class="section-title">本卷所收全部药物目次（共 ${ch.entries.length} 味 · 点击直达详档）</div>
          <div class="bc-chapter-herb-grid">${ch.entries
            .map(
              (e) => `<button type="button" class="bc-chapter-herb-btn" data-bc-entry="${encodeURIComponent(e.id)}">
                <strong>${esc(e.seq_raw ? `${e.seq_raw}. ` : "")}${esc(e.name)}</strong>
                <span>P.${e.page_start}${e.formula_count ? ` · ${e.formula_count}方` : ""}${e.risk_level === "emergency" ? " · 毒/危" : ""}</span>
              </button>`
            )
            .join("")}</div>
        </div>`
      : "";

    const fullTextHtml = ch.full_text || ch.excerpt
      ? `<div class="section-block">
          <div class="section-title">原书章节全文逐字实录</div>
          <pre class="bc-verbatim-pre">${esc(ch.full_text || ch.excerpt)}</pre>
        </div>`
      : "";

    const pageJumpBtns = (ch.pdf_pages || [])
      .slice(0, 12)
      .map((p) => `<button type="button" class="text-button" data-bc-open-page="${p}">PDF P.${p}</button>`)
      .join("");

    detailEl.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">原书章节 · 第 ${esc(ch.order)} 部分</div>
      <h2 class="detail-title">${esc(ch.title)}</h2>
      <p class="detail-subtitle">${esc(ch.summary || "")}</p>
      <div class="tag-row">
        ${ch.grade ? `<span class="tag">${esc(ch.grade)}</span>` : ""}
        ${ch.pdf_pages?.length ? `<span class="tag">PDF P.${ch.pdf_pages[0]}–${ch.pdf_pages[ch.pdf_pages.length - 1]}</span>` : ""}
        ${ch.rules?.length ? `<span class="tag">${ch.rules.length} 则药性总义</span>` : ""}
        ${ch.entries?.length ? `<span class="tag">${ch.entries.length} 味药物</span>` : ""}
      </div>
      ${pageJumpBtns ? `<div class="section-block"><div class="section-title">调看该章原页图像</div><div class="tag-row">${pageJumpBtns}</div></div>` : ""}
      ${rulesHtml}
      ${entriesHtml}
      ${fullTextHtml}
    </div>`;
  }

  function renderComparisonDetail(comp) {
    const detailEl = qEl("#bc-detail");
    if (!detailEl || !comp) return;
    detailEl.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">本草鉴别对照 · ${esc(comp.category)}</div>
      <h2 class="detail-title">${esc(comp.title)}</h2>
      ${renderComparisonCardHtml(comp)}
    </div>`;
  }

  function renderPageDetail(pageObj) {
    const detailEl = qEl("#bc-detail");
    if (!detailEl || !pageObj) return;
    const linked = pageObj.linked_herbs || [];
    detailEl.innerHTML = `<div class="detail-inner">
      <div class="detail-kicker">原书 PDF 全页逐字溯源 · 第 ${pageObj.pdf_page} 页${pageObj.printed_page ? `（书内印刷页 ${esc(pageObj.printed_page)}）` : ""}</div>
      <div class="dossier-title-row">
        <div>
          <h2 class="detail-title">《倪注神农本草经》第 ${pageObj.pdf_page} 页</h2>
          <p class="detail-subtitle">页型：${esc(pageObj.page_role || "正文")} · SHA-256：${esc(pageObj.text_sha256 || "")}</p>
        </div>
        <div class="tag-row">
          ${pageObj.pdf_page > 1 ? `<button type="button" class="quiet-button" data-bc-open-page="${pageObj.pdf_page - 1}">← 上一页</button>` : ""}
          ${pageObj.pdf_page < 154 ? `<button type="button" class="quiet-button" data-bc-open-page="${pageObj.pdf_page + 1}">下一页 →</button>` : ""}
        </div>
      </div>

      ${linked.length ? `<div class="section-block">
        <div class="section-title">本页锚定药物条目（${linked.length} 味 · 点击直达）</div>
        <div class="tag-row">${linked.map((h) => `<button type="button" class="tag" data-bc-entry="${encodeURIComponent(h.id)}">${esc(h.seq_raw ? `${h.seq_raw}. ` : "")}${esc(h.name)} (${esc(h.grade)}) ↗</button>`).join("")}</div>
      </div>` : ""}

      <div class="section-block">
        <div class="section-title">原书扫描图像实况</div>
        <div class="bc-page-img-frame"><img ${window.tcmImgAttrs ? window.tcmImgAttrs(pageObj.image_url) : `src="${esc(pageObj.image_url)}"`} alt="第 ${pageObj.pdf_page} 页扫描图"></div>
      </div>

      <div class="section-block">
        <div class="section-title">PDF 文字层逐字提取原文</div>
        <pre class="bc-verbatim-pre">${esc(pageObj.text || "（本页为空白衬页，无正文文本）")}</pre>
      </div>
    </div>`;
  }

  async function loadCatalog(reset = false, autoSelect = true) {
    if (reset) {
      bcState.entryPage = 1;
      bcState.entries = [];
    }
    const params = new URLSearchParams({
      q: bcState.query,
      grade: bcState.grade,
      nature: bcState.nature,
      flavor: bcState.flavor,
      risk_level: bcState.riskLevel,
      has_formulas: bcState.hasFormulas ? "true" : "false",
      recovered_only: bcState.recoveredOnly ? "true" : "false",
      page: String(bcState.entryPage),
      page_size: "30",
    });
    const data = await req(`/api/bencao/entries?${params}`);
    bcState.entryTotal = data.total;
    bcState.entries.push(...(data.items || []));
    renderCatalogList();
    if (!autoSelect) return;
    if (bcState.entries.length && (reset || !bcState.selectedEntry) && bcState.selectedKind !== "entry") {
      await openEntry(bcState.entries[0].id, { skipHash: true });
    } else if (reset && bcState.entries.length && !bcState.entries.some((e) => e.id === bcState.selectedId)) {
      await openEntry(bcState.entries[0].id, { skipHash: true });
    }
  }

  async function runDiagnose(qText, { updateHash = false } = {}) {
    const q = (qText ?? bcState.query ?? "").trim();
    bcState.dim = "diagnose";
    bcState.query = q;
    const inp = qEl("#bc-query");
    if (inp) inp.value = q;
    updateToolbarVisibility();

    if (!q) {
      bcState.diagnoseResult = null;
      renderDiagnoseList(null);
      return;
    }
    const params = new URLSearchParams({
      q,
      grade: bcState.grade,
      risk_level: bcState.riskLevel,
    });
    const data = await req(`/api/bencao/diagnose?${params}`);
    bcState.diagnoseResult = data;
    renderDiagnoseList(data);
    if (data.items?.length) {
      await openEntry(data.items[0].id, { diagCtx: data.items[0], skipHash: !updateHash });
    }
  }

  async function loadChapters() {
    if (!bcState.chapters.length) {
      const data = await req("/api/bencao/chapters");
      bcState.chapters = data.items || [];
    }
    renderTheoryList();
    if (bcState.chapters.length && bcState.selectedKind !== "chapter") {
      await openChapter("ch1-preface");
    }
  }

  async function loadComparisons() {
    const params = new URLSearchParams({
      q: bcState.query,
      category: bcState.compCategory,
    });
    const data = await req(`/api/bencao/comparisons?${params}`);
    bcState.comparisons = data.items || [];
    bcState.comparisonCategories = data.categories || [];
    const catSelect = qEl("#bc-comp-category");
    if (catSelect && catSelect.options.length <= 1 && bcState.comparisonCategories.length) {
      catSelect.innerHTML =
        `<option value="">全部鉴别组 (38)</option>` +
        bcState.comparisonCategories
          .map((c) => `<option value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`)
          .join("");
      catSelect.value = bcState.compCategory;
    }
    renderComparisonsList();
    if (bcState.comparisons.length && (bcState.selectedKind !== "comparison" || !bcState.comparisons.some((c) => c.id === bcState.selectedId))) {
      await openComparison(bcState.comparisons[0].id, { skipHash: true });
    }
  }

  async function loadPages() {
    const params = new URLSearchParams({
      q: bcState.query,
      limit: "154",
    });
    const data = await req(`/api/bencao/pages?${params}`);
    bcState.pageHits = data.items || [];
    renderPagesList();
    if (bcState.pageHits.length && (bcState.selectedKind !== "page" || !bcState.pageHits.some((p) => String(p.pdf_page) === String(bcState.selectedId)))) {
      await openPage(bcState.pageHits[0].pdf_page);
    }
  }

  async function openEntry(entryId, { diagCtx = null, skipHash = false } = {}) {
    let targetId = entryId;
    const entry = await req(`/api/bencao/entries/${encodeURIComponent(targetId)}`);
    bcState.selectedKind = "entry";
    bcState.selectedId = entry.id;
    bcState.formulaBookFilter = "";
    if (!skipHash) {
      location.hash = `#/herbs/${encodeURIComponent(entry.id)}`;
    }
    if (bcState.dim === "catalog") {
      renderCatalogList();
    } else if (bcState.dim === "diagnose") {
      renderDiagnoseList(bcState.diagnoseResult);
    }
    renderEntryDetail(entry, diagCtx);
  }

  async function openChapter(chapterId) {
    const ch = await req(`/api/bencao/chapters/${encodeURIComponent(chapterId)}`);
    bcState.dim = "theory";
    bcState.selectedKind = "chapter";
    bcState.selectedId = ch.id;
    updateToolbarVisibility();
    renderTheoryList();
    renderChapterDetail(ch);
  }

  async function openComparison(compId, { skipHash = false } = {}) {
    const comp = await req(`/api/bencao/comparisons/${encodeURIComponent(compId)}`);
    bcState.dim = "comparisons";
    bcState.selectedKind = "comparison";
    bcState.selectedId = comp.id;
    updateToolbarVisibility();
    if (!bcState.comparisons.length) {
      const all = await req("/api/bencao/comparisons");
      bcState.comparisons = all.items || [];
    }
    renderComparisonsList();
    renderComparisonDetail(comp);
    if (!skipHash) {
      location.hash = `#/herbs/compare/${encodeURIComponent(comp.id)}`;
    }
  }

  async function openPage(pdfPage) {
    const pNo = Number(pdfPage);
    if (!pNo) return;
    bcState.dim = "pages";
    bcState.selectedKind = "page";
    bcState.selectedId = String(pNo);
    updateToolbarVisibility();
    if (!bcState.pageHits.length) {
      const data = await req("/api/bencao/pages?limit=154");
      bcState.pageHits = data.items || [];
    }
    const pageObj = await req(`/api/bencao/source-pages/${pNo}`);
    renderPagesList();
    renderPageDetail(pageObj);
  }

  async function switchDim(newDim) {
    const prevDim = bcState.dim;
    bcState.dim = newDim;
    bcState.selectedKind = "";
    bcState.selectedId = "";
    if (prevDim !== newDim && (newDim === "theory" || newDim === "comparisons" || newDim === "pages")) {
      bcState.query = "";
      if (qEl("#bc-query")) qEl("#bc-query").value = "";
    }
    updateToolbarVisibility();
    if (newDim === "catalog") {
      await loadCatalog(true);
    } else if (newDim === "diagnose") {
      if (bcState.query) {
        await runDiagnose(bcState.query);
      } else {
        const defaultChip = bcState.overview?.prompt_chips?.[0] || "心中懊憹 失眠烦躁";
        await runDiagnose(defaultChip);
      }
    } else if (newDim === "theory") {
      await loadChapters();
    } else if (newDim === "comparisons") {
      await loadComparisons();
    } else if (newDim === "pages") {
      await loadPages();
    }
  }

  async function ensureOverview() {
    if (!bcState.overview) {
      bcState.overview = await req("/api/bencao/overview");
      renderHonestyBanner(bcState.overview);
      renderPromptChips(bcState.overview.prompt_chips || []);
    }
  }

  function wireEvents() {
    const view = qEl("#herbs-view");
    if (!view || view.dataset.bcWired === "1") return;
    view.dataset.bcWired = "1";

    view.addEventListener("click", (event) => {
      const dimBtn = event.target.closest("[data-bc-dim]");
      if (dimBtn) {
        switchDim(dimBtn.dataset.bcDim).catch(showError);
        return;
      }

      const promptBtn = event.target.closest("[data-bc-prompt]");
      if (promptBtn) {
        runDiagnose(promptBtn.dataset.bcPrompt).catch(showError);
        return;
      }

      const symJumpBtn = event.target.closest("[data-bc-diag-chip]");
      if (symJumpBtn) {
        runDiagnose(symJumpBtn.dataset.bcDiagChip).catch(showError);
        return;
      }

      const entryBtn = event.target.closest("[data-bc-entry]");
      if (entryBtn) {
        const eid = decodeURIComponent(entryBtn.dataset.bcEntry);
        if (bcState.dim !== "catalog" && bcState.dim !== "diagnose") {
          bcState.dim = "catalog";
          updateToolbarVisibility();
          if (!bcState.entries.length) {
            loadCatalog(true).then(() => openEntry(eid)).catch(showError);
            return;
          }
        }
        openEntry(eid).catch(showError);
        return;
      }

      const diagEntryBtn = event.target.closest("[data-bc-diag-entry]");
      if (diagEntryBtn) {
        const eid = decodeURIComponent(diagEntryBtn.dataset.bcDiagEntry);
        const hit = (bcState.diagnoseResult?.items || []).find((x) => x.id === eid) || null;
        openEntry(eid, { diagCtx: hit }).catch(showError);
        return;
      }

      const chapBtn = event.target.closest("[data-bc-chapter]");
      if (chapBtn) {
        openChapter(decodeURIComponent(chapBtn.dataset.bcChapter)).catch(showError);
        return;
      }

      const compBtn = event.target.closest("[data-bc-comp]");
      if (compBtn) {
        openComparison(decodeURIComponent(compBtn.dataset.bcComp)).catch(showError);
        return;
      }

      const pageBtn = event.target.closest("[data-bc-page]");
      if (pageBtn) {
        openPage(Number(pageBtn.dataset.bcPage)).catch(showError);
        return;
      }

      const openPageBtn = event.target.closest("[data-bc-open-page]");
      if (openPageBtn) {
        openPage(Number(openPageBtn.dataset.bcOpenPage)).catch(showError);
        return;
      }

      const toggleImgBtn = event.target.closest("[data-bc-toggle-img]");
      if (toggleImgBtn) {
        const pNo = Number(toggleImgBtn.dataset.bcToggleImg);
        bcState.pagePreviewOpen[pNo] = !bcState.pagePreviewOpen[pNo];
        if (bcState.selectedEntry) {
          renderEntryDetail(bcState.selectedEntry);
        }
        return;
      }

      const fbookBtn = event.target.closest("[data-bc-fbook]");
      if (fbookBtn) {
        bcState.formulaBookFilter = fbookBtn.dataset.bcFbook || "";
        if (bcState.selectedEntry) {
          renderEntryDetail(bcState.selectedEntry);
        }
        return;
      }
    });

    let debounceTimer = null;
    const onQueryChange = () => {
      bcState.query = (qEl("#bc-query")?.value || "").trim();
      if (bcState.dim === "catalog") loadCatalog(true).catch(showError);
      else if (bcState.dim === "diagnose") runDiagnose(bcState.query).catch(showError);
      else if (bcState.dim === "theory") renderTheoryList();
      else if (bcState.dim === "comparisons") loadComparisons().catch(showError);
      else if (bcState.dim === "pages") loadPages().catch(showError);
    };

    qEl("#bc-query")?.addEventListener("input", () => {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(onQueryChange, 180);
    });
    qEl("#bc-query")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        bcState.query = (ev.target.value || "").trim();
        if (bcState.dim === "diagnose" || bcState.dim === "catalog") {
          runDiagnose(bcState.query).catch(showError);
        } else {
          onQueryChange();
        }
      }
    });

    qEl("#bc-diag-btn")?.addEventListener("click", () => {
      const val = (qEl("#bc-query")?.value || "").trim();
      runDiagnose(val || "恶寒无汗 喘咳表实").catch(showError);
    });

    const reloadCatalogOnFilter = () => {
      bcState.grade = qEl("#bc-grade")?.value || "";
      bcState.nature = qEl("#bc-nature")?.value || "";
      bcState.flavor = qEl("#bc-flavor")?.value || "";
      bcState.riskLevel = qEl("#bc-risk")?.value || "";
      bcState.hasFormulas = Boolean(qEl("#bc-only-formulas")?.checked);
      bcState.recoveredOnly = Boolean(qEl("#bc-only-recovered")?.checked);
      if (bcState.dim === "diagnose") {
        runDiagnose(bcState.query).catch(showError);
      } else {
        loadCatalog(true).catch(showError);
      }
    };

    ["#bc-grade", "#bc-nature", "#bc-flavor", "#bc-risk", "#bc-only-formulas", "#bc-only-recovered"].forEach((sel) => {
      qEl(sel)?.addEventListener("change", reloadCatalogOnFilter);
    });

    qEl("#bc-comp-category")?.addEventListener("change", (ev) => {
      bcState.compCategory = ev.target.value || "";
      loadComparisons().catch(showError);
    });

    qEl("#bc-clear")?.addEventListener("click", () => {
      bcState.query = "";
      bcState.grade = "";
      bcState.nature = "";
      bcState.flavor = "";
      bcState.riskLevel = "";
      bcState.hasFormulas = false;
      bcState.recoveredOnly = false;
      bcState.compCategory = "";
      if (qEl("#bc-query")) qEl("#bc-query").value = "";
      if (qEl("#bc-grade")) qEl("#bc-grade").value = "";
      if (qEl("#bc-nature")) qEl("#bc-nature").value = "";
      if (qEl("#bc-flavor")) qEl("#bc-flavor").value = "";
      if (qEl("#bc-risk")) qEl("#bc-risk").value = "";
      if (qEl("#bc-only-formulas")) qEl("#bc-only-formulas").checked = false;
      if (qEl("#bc-only-recovered")) qEl("#bc-only-recovered").checked = false;
      if (qEl("#bc-comp-category")) qEl("#bc-comp-category").value = "";
      onQueryChange();
    });

    qEl("#bc-more")?.addEventListener("click", () => {
      bcState.entryPage += 1;
      loadCatalog(false).catch(showError);
    });
  }

  window.bencaoUI = {
    async activate() {
      wireEvents();
      await ensureOverview();
      updateToolbarVisibility();
      if (!bcState.booted) {
        bcState.booted = true;
        await loadCatalog(true);
      }
    },

    async openEntry(herbIdOrName) {
      wireEvents();
      await ensureOverview();
      bcState.dim = "catalog";
      updateToolbarVisibility();
      if (!bcState.booted) {
        bcState.booted = true;
        await loadCatalog(true, false);
      }
      await openEntry(herbIdOrName, { skipHash: false });
    },

    async handleHash(hash) {
      wireEvents();
      await ensureOverview();
      const cmpMatch = hash.match(/^#\/herbs\/compare\/(.+)$/);
      if (cmpMatch) {
        bcState.booted = true;
        await openComparison(decodeURIComponent(cmpMatch[1]), { skipHash: true });
        return;
      }
      const entryMatch = hash.match(/^#\/herbs\/(.+)$/);
      if (entryMatch) {
        bcState.dim = "catalog";
        updateToolbarVisibility();
        if (!bcState.booted) {
          bcState.booted = true;
          await loadCatalog(true, false);
        }
        await openEntry(decodeURIComponent(entryMatch[1]), { skipHash: true });
        return;
      }
      await this.activate();
    },
  };
})();
