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
    continuousMode: true,
    streamLoading: false,
    streamLoadingAll: false,
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
    const contCheckbox = qEl("#bc-continuous-mode");
    if (contCheckbox) contCheckbox.checked = Boolean(bcState.continuousMode);
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

  function renderHerbBookEntryHtml(entry, { diagCtx = null, isStreamItem = false } = {}) {
    const props = entry.properties || {};
    const classic = entry.classic_original || {};
    const apps = entry.applications || {};
    const ni = entry.ni_haixia_annotations || {};
    const proc = entry.processing_and_compatibility || {};
    const isCh3 = classic.in_shennong_classic === false || entry.in_shennong_classic === false || entry.kind === "ch3";
    const risk = props.risk_level || entry.risk_level || "standard";

    let safetyBanner = "";
    const toxNote =
      props.toxicity && props.toxicity !== "无毒"
        ? props.toxicity
        : risk === "emergency"
          ? "古经虽注“无毒”或未明言，实具重金属/炼变/严峻禁忌红线"
          : "虽注无毒，仍具偏性或古今品种分歧";
    if (risk === "emergency") {
      safetyBanner = `<div class="bc-banner bc-banner-emergency">
        <strong>高风险警示（${esc(toxNote)}）：</strong><span>${esc((props.risk_reasons || []).join("；") || "本书标注本品具强攻泻或峻毒偏性，仅作古典医药文献研读，须严遵先起黍粟、病去即止与正确炮制方法。")}</span>
      </div>`;
    } else if (risk === "high_risk") {
      safetyBanner = `<div class="bc-banner bc-banner-risk">
        <strong>慎用提示（${esc(toxNote)}）：</strong><span>${esc((props.risk_reasons || []).join("；") || "含小毒、妊娠禁忌或古今品种分歧，使用前须核下方《禁忌》与《基原争议》。")}</span>
      </div>`;
    }

    const diagBanner = diagCtx
      ? `<div class="bc-diag-banner">
          <div class="bc-diag-banner-head">
            <strong>本次“症状找药”命中依据</strong>
            <span>综合匹配分：${esc(diagCtx.score)}</span>
          </div>
          ${diagCtx.matched_terms?.length ? `<div class="tag-row">${diagCtx.matched_terms.map((t) => `<span class="symptom-chip">命中：${esc(t)}</span>`).join("")}</div>` : ""}
          ${diagCtx.why_recommended ? `<p><strong>选用依据：</strong>${esc(diagCtx.why_recommended)}</p>` : ""}
          ${diagCtx.when_to_use ? `<p><strong>适用指征：</strong>${esc(diagCtx.when_to_use)}</p>` : ""}
          ${diagCtx.contraindication_guard ? `<p class="bc-guard-line"><strong>避忌防线：</strong>${esc(diagCtx.contraindication_guard)}</p>` : ""}
        </div>`
      : "";

    const rows = [];
    const addRow = (label, valHtml, extraClass = "") => {
      if (!valHtml) return;
      rows.push(`<div class="bc-book-row${extraClass ? ` ${extraClass}` : ""}">
        <strong class="bc-book-label">${esc(label)}</strong>
        <div class="bc-book-val">${valHtml}</div>
      </div>`);
    };

    // 1. 本经原文 / 第三章仲景增补
    const classicParts = [];
    if (classic.text) classicParts.push(`<span>${esc(classic.text)}</span>`);
    if (classic.appended_notes?.length) {
      classicParts.push(`<div class="bc-book-subline">${classic.appended_notes.map(esc).join("<br>")}</div>`);
    }
    if (classic.edition_note) {
      classicParts.push(`<div class="bc-book-subline bc-muted-line">校勘：${esc(classic.edition_note)}</div>`);
    }
    addRow(
      isCh3 ? "【第三章仲景增补】" : "【本经原文】",
      classicParts.join("") || (isCh3 ? "" : `<span class="bc-muted-line">原文未录</span>`),
      isCh3 ? "is-ch3" : "is-classic"
    );

    // 2. 产地
    if (props.origin) {
      addRow("【产地】", esc(props.origin));
    }

    // 3. 性味 · 四气五味 · 归经
    const natureTags = [...(props.four_natures || []), ...(props.five_flavors || [])];
    const propBits = [];
    if (props.qi_wei_raw) propBits.push(esc(props.qi_wei_raw));
    if (natureTags.length) {
      const tagStr = `四气五味：${natureTags.join(" · ")}${props.toxicity && props.toxicity !== "未明言" ? `（${props.toxicity}）` : ""}`;
      if (!props.qi_wei_raw || !props.qi_wei_raw.includes(natureTags[0])) propBits.push(esc(tagStr));
    }
    if (props.meridians?.length) propBits.push(`归经：${esc(props.meridians.join("、"))}`);
    if (propBits.length) {
      addRow("【性味归经】", propBits.join("　|　"));
    }

    // 4. 主治
    if (apps.main_summary || apps.symptom_keywords?.length) {
      const kwHtml = apps.symptom_keywords?.length
        ? `<div class="bc-inline-tags">${apps.symptom_keywords
            .map((s) => `<button type="button" class="symptom-chip bc-sym-jump" data-bc-diag-chip="${esc(s)}" title="以此症状重新找药">${esc(s)}</button>`)
            .join("")}</div>`
        : "";
      addRow("【主治】", `${apps.main_summary ? `<span>${esc(apps.main_summary)}</span>` : ""}${kwHtml}`);
    }

    // 5. 历代注家（别录 / 甄权 / 大明 / 容川 / 药征 / 灵胎等，按原书顺序逐条罗列）
    for (const c of entry.historical_commentaries || []) {
      const rawTag = String(c.tag || c.scholar || "按注").trim();
      const label = rawTag.startsWith("【") ? rawTag : `【${rawTag}】`;
      if (c.text) addRow(label, esc(c.text));
    }

    // 6. 倪海厦原文按语与临证提要
    if (ni.explicit_ni_notes?.length) {
      addRow("【倪注】", ni.explicit_ni_notes.map(esc).join("\n\n"), "is-ni");
    }
    if (ni.chapter3_pithy_summary) {
      addRow("【倪氏总提要】", esc(ni.chapter3_pithy_summary), "is-ni");
    } else if (ni.chapter3_editor_intro && isCh3) {
      addRow("【第三章按语】", esc(ni.chapter3_editor_intro), "is-ni");
    }
    if (ni.unlabeled_clinical_excerpts?.length) {
      addRow("【原书按语阐述】", ni.unlabeled_clinical_excerpts.map(esc).join("\n\n"), "is-ni");
    }
    const niSynthesis = [];
    if (ni.why_it_works) niSynthesis.push(`<div><strong>为什么用：</strong>${esc(ni.why_it_works)}</div>`);
    if (ni.when_to_use) niSynthesis.push(`<div><strong>何时选用：</strong>${esc(ni.when_to_use)}</div>`);
    if (ni.clinical_experience?.length) {
      niSynthesis.push(`<div><strong>用方经验：</strong>${ni.clinical_experience.map(esc).join("；")}</div>`);
    }
    if (ni.differentiation_notes) {
      niSynthesis.push(`<div class="bc-warn-inline"><strong>辨异警戒：</strong>${esc(ni.differentiation_notes)}</div>`);
    }
    if (niSynthesis.length) {
      addRow("【倪氏临证提要】", niSynthesis.join(""), "is-ni-summary");
    }

    // 7. 用量
    if (proc.dosage) {
      addRow("【用量】", esc(proc.dosage));
    }

    // 8. 炮制及生熟差异
    if (proc.processing || proc.processing_differences) {
      const procParts = [];
      if (proc.processing) procParts.push(`<span>${esc(proc.processing)}</span>`);
      if (proc.processing_differences) {
        procParts.push(`<div class="bc-book-subline"><strong>生熟炮制之异：</strong>${esc(proc.processing_differences)}</div>`);
      }
      addRow("【炮制】", procParts.join(""));
    }

    // 9. 禁忌与七情配伍
    if (proc.contraindications || proc.seven_relations?.length) {
      const relStr = proc.seven_relations?.length
        ? `<div class="bc-inline-tags">${proc.seven_relations.map((r) => `<span class="tag">${esc(r)}</span>`).join("")}</div>`
        : "";
      addRow(
        "【禁忌与配伍】",
        `${proc.contraindications ? `<span class="bc-warn-inline">${esc(proc.contraindications)}</span>` : ""}${relStr}`,
        proc.contraindications ? "is-contra" : ""
      );
    }

    // 10. 附品 / 同条分支
    if (proc.appendices?.length) {
      addRow(
        "【同条附品】",
        proc.appendices
          .map((ap) => `<div><strong>${esc(ap.title || "附品")}：</strong>${esc(ap.text || "")}</div>`)
          .join("")
      );
    }

    // 11. 基原争议 · 待考 · 校按
    const contList = entry.identity_controversies || [];
    const openList = entry.open_questions || [];
    const orgList = entry.organizer_notes || [];
    const dualLink =
      entry.name === "白芷"
        ? entry.kind === "ch3"
          ? `<button type="button" class="text-button" data-bc-entry="${encodeURIComponent("bencao:白芷")}">对照查看《本经·中品第173条》白芷 ↗</button>`
          : `<button type="button" class="text-button" data-bc-entry="${encodeURIComponent("bencao:ch3-白芷")}">对照查看《第三章第15条》增补白芷 ↗</button>`
        : "";
    if (contList.length || openList.length || orgList.length || dualLink) {
      const contParts = [];
      if (dualLink) contParts.push(`<div>${dualLink}</div>`);
      contList.forEach((c) => {
        contParts.push(`<div><strong>${esc(c.topic)}：</strong>${esc(c.summary)}${c.policy ? `（原则：${esc(c.policy)}）` : ""}</div>`);
      });
      openList.forEach((oq) => {
        contParts.push(`<div class="bc-muted-line"><strong>尚待考证：</strong>${esc(oq)}</div>`);
      });
      if (orgList.length) {
        contParts.push(`<div class="bc-muted-line"><strong>校按：</strong>${orgList.map(esc).join("；")}</div>`);
      }
      addRow("【争议与校按】", contParts.join(""), "is-controversy");
    }

    // 12. 仲景经方反向关联（直接罗列全部入方与剂量）
    const allUsages = entry.formula_usages || [];
    if (allUsages.length) {
      const shanghanCount = allUsages.filter((u) => u.book === "伤寒论").length;
      const jinkuiCount = allUsages.filter((u) => u.book === "金匮要略").length;
      const activeBook = isStreamItem ? "" : bcState.formulaBookFilter;
      const shownUsages = activeBook ? allUsages.filter((u) => u.book === activeBook) : allUsages;
      const filterRow =
        !isStreamItem && allUsages.length > 6
          ? `<div class="bc-formula-filter-row">
              <button type="button" class="s4-chip${!activeBook ? " bc-chip-active" : ""}" data-bc-fbook="">全部 (${allUsages.length})</button>
              ${shanghanCount ? `<button type="button" class="s4-chip${activeBook === "伤寒论" ? " bc-chip-active" : ""}" data-bc-fbook="伤寒论">伤寒论 (${shanghanCount})</button>` : ""}
              ${jinkuiCount ? `<button type="button" class="s4-chip${activeBook === "金匮要略" ? " bc-chip-active" : ""}" data-bc-fbook="金匮要略">金匮要略 (${jinkuiCount})</button>` : ""}
            </div>`
          : "";
      const formulaChips = `<div class="bc-inline-formula-list">${shownUsages
        .map(
          (u) => `<button type="button" class="bc-inline-formula" data-formula-id="${encodeURIComponent(u.formula_id)}" title="${esc(u.book)}${u.mapping_note ? ` · ${u.mapping_note}` : ""}${u.controversy ? ` · ${u.controversy}` : ""}">
            <strong>${esc(u.formula_name)}</strong>
            <span>(${esc(u.ingredient_raw_name)} ${esc(u.dose || "见原方")}${u.processing ? `·${esc(u.processing)}` : ""})</span>
          </button>`
        )
        .join("")}</div>`;
      addRow(`【入经方 (${allUsages.length}方)】`, `${filterRow}${formulaChips}`);
    }

    // 13. 鉴别对照 & 黄帝内经渊源
    const compsDetailed = entry.comparisons_detailed || [];
    const njRels = entry.neijing_relations || [];
    if (compsDetailed.length || njRels.length) {
      const linkBits = [];
      for (const cmp of compsDetailed) {
        linkBits.push(
          `<button type="button" class="tag bc-peer-btn" data-bc-comp="${encodeURIComponent(cmp.id)}">鉴别：${esc(cmp.title)} ↗</button>`
        );
      }
      for (const rel of njRels) {
        const attr =
          rel.target_kind === "chapter"
            ? `data-nj-jump-chapter="${encodeURIComponent(rel.target_nav_id)}"`
            : `data-nj-jump-concept="${encodeURIComponent(rel.target_nav_id)}"`;
        linkBits.push(`<button type="button" class="tag" ${attr}>内经：${esc(rel.canonical_name)} ↗</button>`);
      }
      addRow("【鉴别与内经】", `<div class="bc-inline-tags">${linkBits.join("")}</div>`);
    }

    // 14. 原书逐页锚点与可选展开扫描图
    const uniquePages = [...new Set(entry.pdf_pages || (entry.page_start ? [entry.page_start] : []))].filter(Boolean);
    const spans = entry.source_spans || [];
    const openImagesHtml = uniquePages
      .filter((pNo) => bcState.pagePreviewOpen[pNo])
      .map(
        (pNo) => `<div class="bc-page-img-frame"><img ${window.tcmImgAttrs ? window.tcmImgAttrs(`/api/bencao/source-pages/${pNo}/image`) : `src="/api/bencao/source-pages/${pNo}/image"`} alt="《倪注神农本草经》PDF 第 ${pNo} 页" loading="lazy"></div>`
      )
      .join("");
    if (spans.length || openImagesHtml) {
      const spanSummary = spans
        .slice(0, 2)
        .map(
          (sp) =>
            `<button type="button" class="text-button" data-bc-open-page="${sp.pdf_page}">PDF P.${sp.pdf_page}${sp.printed_page ? `（书页 ${esc(sp.printed_page)}）` : ""} 逐字页 ↗</button>`
        )
        .join(" ");
      addRow("【底本溯源】", `${spanSummary}${openImagesHtml}`);
    }

    const pageImgsBtns = uniquePages
      .map(
        (pNo) =>
          `<button type="button" class="text-button" data-bc-toggle-img="${pNo}">${bcState.pagePreviewOpen[pNo] ? `收起 P.${pNo} 扫描图` : `P.${pNo} 扫描图`}</button>`
      )
      .join("");

    const modeJumpBtn = isStreamItem
      ? `<button type="button" class="text-button" data-bc-focus-single="${encodeURIComponent(entry.id)}">仅看此味</button>`
      : bcState.dim === "catalog" && bcState.continuousMode
      ? `<button type="button" class="text-button" data-bc-back-stream="${encodeURIComponent(entry.id)}">返回连续全页顺读 ↗</button>`
      : "";

    const isFocused = bcState.selectedKind === "entry" && bcState.selectedId === entry.id;
    return `<article class="bc-book-sheet${isFocused && isStreamItem ? " is-focused" : ""}" data-bc-herb-id="${esc(entry.id)}">
      <header class="bc-book-head">
        <div class="bc-book-title-wrap">
          <h3 class="bc-book-title">${esc(entry.seq_raw ? `${entry.seq_raw}、` : "")}${esc(entry.name)}</h3>
          <span class="bc-book-meta">${esc(entry.grade)}${entry.page_start ? ` · PDF P.${esc(entry.page_start)}${entry.page_end && entry.page_end !== entry.page_start ? `–${esc(entry.page_end)}` : ""}` : ""}${entry.toc_printed_page ? `（书页 ${esc(entry.toc_printed_page)}）` : ""}</span>
          ${entry.aliases?.length ? `<span class="bc-book-alias">异名：${esc(entry.aliases.join("、"))}</span>` : ""}
        </div>
        <div class="bc-book-actions">
          ${reviewBadgeHtml(entry.review_status)}
          ${risk !== "standard" ? riskBadgeHtml(risk) : ""}
          ${isCh3 ? `<span class="bc-pill bc-pill-ch3">本经未载·第三章增补</span>` : ""}
          ${entry.newly_recovered_in_stage2 && !isCh3 ? `<span class="bc-pill bc-pill-recovered">Stage 2 复原</span>` : ""}
          <button type="button" class="text-button" data-ask-ni-kind="herb" data-ask-ni-id="${encodeURIComponent(entry.id)}" data-ask-ni-name="${encodeURIComponent(entry.name)}">请倪师精讲 ↗</button>
          <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${esc(entry.page_start || 1)}" data-ctx-q="${esc(entry.name)}">原书上下文 ↗</button>
          ${pageImgsBtns}
          ${modeJumpBtn}
        </div>
      </header>
      ${safetyBanner}
      ${diagBanner}
      <div class="bc-book-body">${rows.join("")}</div>
    </article>`;
  }

  function buildStreamFooterHtml() {
    const remaining = Math.max(0, bcState.entryTotal - bcState.entries.length);
    if (!bcState.entries.length) return "";
    if (remaining <= 0) {
      return `<div class="bc-stream-footer"><span>—— 当前目录已全部连续罗列完毕（共 ${bcState.entryTotal} 味） ——</span></div>`;
    }
    return `<div class="bc-stream-footer">
      <button type="button" class="primary-btn" data-bc-stream-more="1">${bcState.streamLoading ? "正在展开后续药物..." : `继续向下展开下 ${Math.min(40, remaining)} 味（已罗列 ${bcState.entries.length} / ${bcState.entryTotal} 味）`}</button>
      <button type="button" class="dossier-button" data-bc-stream-all="1"${bcState.streamLoadingAll ? " disabled" : ""}>${bcState.streamLoadingAll ? `正在批量展开 (${bcState.entries.length}/${bcState.entryTotal})...` : `一次罗列当前全部 (${bcState.entryTotal} 味)`}</button>
    </div>`;
  }

  function renderContinuousCatalogStream() {
    const detailEl = qEl("#bc-detail");
    if (!detailEl) return;
    if (!bcState.entries.length) {
      detailEl.innerHTML = `<div class="empty-state"><span class="empty-mark">药</span><h2>未检索到符合条件的药物条目</h2><p>请调整上方筛选条件或点“重置”。</p></div>`;
      return;
    }
    const itemsHtml = bcState.entries
      .map((entry) => renderHerbBookEntryHtml(entry, { isStreamItem: true }))
      .join("");
    const expandAllHeader =
      bcState.entries.length < bcState.entryTotal
        ? `<button type="button" class="text-button" data-bc-stream-all="1"${bcState.streamLoadingAll ? " disabled" : ""}>${bcState.streamLoadingAll ? `展开中 (${bcState.entries.length}/${bcState.entryTotal})...` : `一次展开全部 ${bcState.entryTotal} 味 ↓`}</button>`
        : "";
    detailEl.innerHTML = `<div class="detail-inner bc-stream-wrap">
      <div class="bc-stream-banner">
        <span><strong>连续像书一样顺读：</strong>当前已顺排罗列 <strong>${bcState.entries.length}</strong> / ${bcState.entryTotal} 味（每味直接按原书顺序列出经文、产地、性味主治、历代注家、倪注、炮制禁忌与入方 · 点击左侧药名可速跳定位）</span>
        ${expandAllHeader}
      </div>
      <div class="bc-continuous-stream">${itemsHtml}</div>
      ${buildStreamFooterHtml()}
    </div>`;
  }

  function renderEntryDetail(entry, diagCtx = null) {
    const detailEl = qEl("#bc-detail");
    if (!detailEl || !entry) return;
    bcState.selectedEntry = entry;
    detailEl.innerHTML = `<div class="detail-inner bc-single-sheet">${renderHerbBookEntryHtml(entry, { diagCtx, isStreamItem: false })}</div>`;
    detailEl.scrollTop = 0;
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

  async function loadCatalog(reset = false, autoSelect = true, { batchSize = null } = {}) {
    if (bcState.streamLoading) return;
    bcState.streamLoading = true;
    try {
      if (reset) {
        bcState.entryPage = 1;
        bcState.entries = [];
      }
      const wantStream = Boolean(bcState.continuousMode);
      const effectiveSize = batchSize || (wantStream ? 40 : 30);
      const params = new URLSearchParams({
        q: bcState.query,
        grade: bcState.grade,
        nature: bcState.nature,
        flavor: bcState.flavor,
        risk_level: bcState.riskLevel,
        has_formulas: bcState.hasFormulas ? "true" : "false",
        recovered_only: bcState.recoveredOnly ? "true" : "false",
        page: String(bcState.entryPage),
        page_size: String(effectiveSize),
        include_detail: wantStream ? "true" : "false",
      });
      const data = await req(`/api/bencao/entries?${params}`);
      bcState.entryTotal = data.total;
      const newItems = data.items || [];
      bcState.entries.push(...newItems);
      renderCatalogList();

      if (wantStream && bcState.dim === "catalog" && autoSelect !== "list_only") {
        if (reset) {
          bcState.selectedKind = bcState.entries.length ? "entry" : "";
          bcState.selectedId = bcState.entries[0]?.id || "";
          bcState.selectedEntry = bcState.entries[0] || null;
          renderCatalogList();
          renderContinuousCatalogStream();
          const dEl = qEl("#bc-detail");
          if (dEl) dEl.scrollTop = 0;
        } else {
          const detailEl = qEl("#bc-detail");
          const streamEl = detailEl?.querySelector(".bc-continuous-stream");
          const prevScroll = detailEl ? detailEl.scrollTop : 0;
          if (streamEl && newItems.length) {
            streamEl.insertAdjacentHTML(
              "beforeend",
              newItems.map((e) => renderHerbBookEntryHtml(e, { isStreamItem: true })).join("")
            );
            const footerEl = detailEl.querySelector(".bc-stream-footer");
            if (footerEl) footerEl.outerHTML = buildStreamFooterHtml();
            const bannerCount = detailEl.querySelector(".bc-stream-banner strong:nth-of-type(2)");
            if (bannerCount) bannerCount.textContent = String(bcState.entries.length);
            if (detailEl) detailEl.scrollTop = prevScroll;
          } else {
            renderContinuousCatalogStream();
            if (detailEl) detailEl.scrollTop = prevScroll;
          }
        }
        return;
      }

      if (!autoSelect) return;
      if (bcState.entries.length && (reset || !bcState.selectedEntry) && bcState.selectedKind !== "entry") {
        await openEntry(bcState.entries[0].id, { skipHash: true });
      } else if (reset && bcState.entries.length && !bcState.entries.some((e) => e.id === bcState.selectedId)) {
        await openEntry(bcState.entries[0].id, { skipHash: true });
      }
    } finally {
      bcState.streamLoading = false;
    }
  }

  async function loadAllRemainingCatalog() {
    if (bcState.streamLoadingAll) return;
    bcState.streamLoadingAll = true;
    const footerEl = qEl("#bc-detail .bc-stream-footer");
    if (footerEl) footerEl.outerHTML = buildStreamFooterHtml();
    try {
      while (bcState.dim === "catalog" && bcState.continuousMode && bcState.entries.length < bcState.entryTotal) {
        bcState.entryPage += 1;
        await loadCatalog(false, true, { batchSize: 120 });
      }
    } finally {
      bcState.streamLoadingAll = false;
      if (bcState.dim === "catalog" && bcState.continuousMode) {
        const dEl = qEl("#bc-detail");
        const prev = dEl ? dEl.scrollTop : 0;
        renderContinuousCatalogStream();
        if (dEl) dEl.scrollTop = prev;
      }
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
            loadCatalog(true, false).then(() => openEntry(eid)).catch(showError);
            return;
          }
        }
        if (bcState.dim === "catalog" && bcState.continuousMode) {
          const sheets = Array.from(document.querySelectorAll("#bc-detail .bc-book-sheet[data-bc-herb-id]"));
          const hitEl = sheets.find((el) => el.dataset.bcHerbId === eid);
          if (hitEl) {
            bcState.selectedKind = "entry";
            bcState.selectedId = eid;
            renderCatalogList();
            sheets.forEach((el) => el.classList.toggle("is-focused", el === hitEl));
            hitEl.scrollIntoView({ behavior: "smooth", block: "start" });
            return;
          }
        }
        openEntry(eid).catch(showError);
        return;
      }

      const focusSingleBtn = event.target.closest("[data-bc-focus-single]");
      if (focusSingleBtn) {
        openEntry(decodeURIComponent(focusSingleBtn.dataset.bcFocusSingle)).catch(showError);
        return;
      }

      const backStreamBtn = event.target.closest("[data-bc-back-stream]");
      if (backStreamBtn) {
        const eid = decodeURIComponent(backStreamBtn.dataset.bcBackStream);
        bcState.continuousMode = true;
        updateToolbarVisibility();
        if (bcState.entries.some((e) => e.id === eid) && bcState.entries[0]?.classic_original) {
          renderContinuousCatalogStream();
          const sheets = Array.from(document.querySelectorAll("#bc-detail .bc-book-sheet[data-bc-herb-id]"));
          const hitEl = sheets.find((el) => el.dataset.bcHerbId === eid);
          if (hitEl) hitEl.scrollIntoView({ behavior: "smooth", block: "start" });
        } else {
          loadCatalog(true).catch(showError);
        }
        return;
      }

      if (event.target.closest("[data-bc-stream-more]")) {
        if (!bcState.streamLoading && bcState.entries.length < bcState.entryTotal) {
          bcState.entryPage += 1;
          loadCatalog(false).catch(showError);
        }
        return;
      }

      if (event.target.closest("[data-bc-stream-all]")) {
        loadAllRemainingCatalog().catch(showError);
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
        if (bcState.dim === "catalog" && bcState.continuousMode && !qEl("#bc-detail .bc-single-sheet")) {
          const detailEl = qEl("#bc-detail");
          const prevTop = detailEl ? detailEl.scrollTop : 0;
          renderContinuousCatalogStream();
          if (detailEl) detailEl.scrollTop = prevTop;
        } else if (bcState.selectedEntry) {
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

    qEl("#bc-continuous-mode")?.addEventListener("change", (ev) => {
      bcState.continuousMode = Boolean(ev.target.checked);
      if (bcState.dim === "catalog") {
        loadCatalog(true).catch(showError);
      }
    });

    qEl("#bc-detail")?.addEventListener("scroll", () => {
      const detailEl = qEl("#bc-detail");
      if (
        !detailEl ||
        bcState.dim !== "catalog" ||
        !bcState.continuousMode ||
        bcState.streamLoading ||
        bcState.streamLoadingAll ||
        bcState.entries.length >= bcState.entryTotal ||
        !detailEl.querySelector(".bc-continuous-stream")
      ) {
        return;
      }
      if (detailEl.scrollHeight - detailEl.scrollTop - detailEl.clientHeight < 360) {
        bcState.entryPage += 1;
        loadCatalog(false).catch(showError);
      }
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
