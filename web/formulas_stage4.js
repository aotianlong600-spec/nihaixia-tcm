/* Stage 4 workbench: Formula clinical diagnosis, 6-channel / 20-chapter Jinkui browsing,
 * 108 modification rules, 42 cross-book variants, and 27 acupuncture-formula links.
 */
(function initFormulasStage4() {
  const s4 = {
    booted: false,
    mode: "diagnose", // "diagnose" | "catalog" | "jinkui" | "rules"
    rulesSub: "modifications", // "modifications" | "variants" | "acupuncture"
    diagQuery: "",
    diagResult: null,
    selectedFormulaId: "",
    chapters: null,
    activeChapterId: "",
    activeChapterDetail: null,
    modsData: null,
    variantsData: null,
    acupLinksData: null,
    rulesSearch: "",
    variantsDiffOnly: false,
    lastBannerHtml: "",
  };

  const q = (sel) => document.querySelector(sel);
  const esc = (val) =>
    String(val ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  async function apiJson(url) {
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} loading ${url}`);
    }
    return res.json();
  }

  function showNotice(msg) {
    const notice = q("#notice");
    if (!notice) return;
    notice.textContent = msg;
    notice.classList.remove("hidden");
    window.clearTimeout(showNotice.timer);
    showNotice.timer = window.setTimeout(() => notice.classList.add("hidden"), 3200);
  }

  function setDynamicBanner(html) {
    const panel = q("#s4-dynamic-panel");
    if (!panel) return;
    s4.lastBannerHtml = html || "";
    if (!html) {
      panel.innerHTML = "";
      panel.classList.add("hidden");
    } else {
      panel.innerHTML = html;
      panel.classList.remove("hidden");
    }
  }

  function updateToolbarAndColumns() {
    const isCatalog = s4.mode === "catalog";
    const isDiagnose = s4.mode === "diagnose";
    const formulasToolbar = q("#formulas-view > .toolbar");
    const diagBar = q("#formulas-view .s4-diagnose-bar");
    const quickChips = q("#s4-quick-chips");
    const leftHost = q("#s4-left-host");
    const catalogList = q("#formula-list");
    const catalogMore = q("#formula-more");
    const titleEl = q("#formula-list-title");
    const subEl = q("#s4-list-subtitle");

    if (formulasToolbar) formulasToolbar.classList.toggle("hidden", !isCatalog);
    if (diagBar) diagBar.classList.toggle("hidden", isCatalog);
    if (quickChips) quickChips.classList.toggle("hidden", !isDiagnose);
    if (leftHost) leftHost.classList.toggle("hidden", isCatalog);
    if (catalogList) catalogList.classList.toggle("hidden", !isCatalog);
    if (catalogMore && !isCatalog) catalogMore.classList.add("hidden");

    document.querySelectorAll("#s4-mode-strip [data-s4-mode]").forEach((btn) => {
      const active = btn.dataset.s4Mode === s4.mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });

    const TITLES = {
      diagnose: ["症状辨证推演", "输入症状或点击常见主症 · 区分寒热表里虚实"],
      catalog: ["全部经方目录", "《伤寒论》113 方 · 《金匮要略》186 方 · 同名独立保留"],
      jinkui: ["《金匮要略》二十篇", "按原书二十篇脉证、治法与方剂逐篇研读"],
      rules: ["加减规则与同名对照", "108 条经方加减化裁 · 42 组跨书对照 · 27 条针药联系"],
    };
    const [t, s] = TITLES[s4.mode] || TITLES.diagnose;
    if (titleEl) titleEl.textContent = t;
    if (subEl) subEl.textContent = s;

    if (isCatalog || s4.mode === "jinkui" || s4.mode === "rules") {
      if (isCatalog || !s4.diagResult) setDynamicBanner("");
    }
  }

  async function openFormulaDetailById(formulaId) {
    if (!formulaId) return;
    s4.selectedFormulaId = formulaId;
    try {
      const item = await apiJson(`/api/formulas/${encodeURIComponent(formulaId)}`);
      if (typeof window.__tcmRenderFormulaDetail === "function") {
        window.__tcmRenderFormulaDetail(item);
      } else {
        const detail = q("#formula-detail");
        if (detail) {
          detail.innerHTML = `<div class="detail-inner"><h2>${esc(item.name)}</h2><p>${esc(item.indication || "")}</p></div>`;
        }
      }
      // Highlight active card in #s4-left-host if present
      document.querySelectorAll("#s4-left-host [data-s4-open-formula]").forEach((el) => {
        el.classList.toggle("selected", decodeURIComponent(el.dataset.s4OpenFormula || "") === formulaId);
      });
      const panel = q("#formula-detail");
      if (panel && typeof panel.scrollTo === "function") {
        panel.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (err) {
      showNotice(`加载方剂失败：${err.message}`);
    }
  }

  function renderDiagnoseBanner(data) {
    if (!data) {
      setDynamicBanner("");
      return;
    }
    const alerts = (data.safety_alerts || [])
      .map((a) => {
        const msg = typeof a === "string" ? a : a.message || a.note || "";
        const isEmergency = typeof a === "string" ? msg.includes("急诊") || msg.includes("危急") : a.level === "emergency";
        return `<div class="s4-alert-pill ${isEmergency ? "is-emergency" : "is-warn"}"><strong>临床边界警示：</strong>${esc(msg)}</div>`;
      })
      .join("");
    const guides = (data.differentiation_guides || [])
      .map((g) => {
        const branches = (g.branches || [])
          .map(
            (b) =>
              `<button type="button" class="s4-branch-btn" data-s4-q="${esc(b.chip || b.formula || "")}">
                <div class="s4-branch-head"><strong>${esc(b.formula || "")}</strong><span>${esc(b.label || "")}</span></div>
                ${b.note ? `<small>${esc(b.note)}</small>` : ""}
              </button>`
          )
          .join("");
        return `<div class="s4-guide-card"><strong>${esc(g.title || "辨证鉴别要点")}</strong><div class="s4-branch-list">${branches}</div></div>`;
      })
      .join("");
    const facets = (data.follow_up_facets || [])
      .map((f) => {
        const token = typeof f === "string" ? f : f.chip || f.query || f.label || "";
        const label = typeof f === "string" ? f : f.label || f.term || token;
        return `<button type="button" class="s4-facet-btn" data-s4-append-q="${esc(token)}">+ ${esc(label)}</button>`;
      })
      .join("");
    const sixChips = (data.matched_six_channels || [])
      .slice(0, 4)
      .map((sc) => `<button type="button" class="s4-xref-chip" data-switch-view="six" data-s4-jump-six="${encodeURIComponent(sc.id)}">六经 · ${esc(sc.name)} (${sc.score || 0}) ↗</button>`)
      .join("");
    const jkChips = (data.matched_jinkui_chapters || [])
      .slice(0, 4)
      .map((ch) => `<button type="button" class="s4-xref-chip" data-s4-jinkui-chapter="${encodeURIComponent(ch.id)}">金匮 · ${esc(ch.name || ch.title || "")} ↗</button>`)
      .join("");

    if (!alerts && !guides && !facets && !sixChips && !jkChips) {
      setDynamicBanner("");
      return;
    }

    setDynamicBanner(`<div class="s4-banner-inner">
      ${alerts ? `<div class="s4-alerts-row">${alerts}</div>` : ""}
      ${guides ? `<div class="s4-guides-grid">${guides}</div>` : ""}
      ${facets ? `<div class="s4-facets-row"><span class="s4-chips-label">辨证追问：</span>${facets}</div>` : ""}
      ${sixChips || jkChips ? `<div class="s4-xref-row">${sixChips}${jkChips}</div>` : ""}
    </div>`);
  }

  function renderDiagnoseLeftList(data) {
    const host = q("#s4-left-host");
    if (!host) return;
    if (!data || !(data.query || "").trim()) {
      host.innerHTML = `<div class="s4-welcome-card">
        <h3>经方辨证论治工作台</h3>
        <p>覆盖《伤寒论》113 方（6 经）与《金匮要略》186 方（20 篇），支持古今同义症候识别及 <strong>无汗/有汗、渴/不渴、先便后血/先血后便</strong> 等极性鉴别。</p>
        <div class="s4-welcome-stats">
          <span>299 首全部精校</span>
          <span>108 条结构化加减</span>
          <span>42 组跨书同名对照</span>
          <span>27 条针灸联动</span>
        </div>
        <div class="s4-welcome-hint">请在上方输入症状（支持空格分隔多症）或直接点击「辨证示例」标签开始推演。</div>
      </div>`;
      return;
    }

    const formulas = data.matched_formulas || [];
    const mods = data.matched_modifications || [];
    const cards = formulas.length
      ? formulas
          .map((item, idx) => {
            const selected = item.id === s4.selectedFormulaId ? " selected" : "";
            const tokens = (item.matched_tokens || [])
              .slice(0, 5)
              .map((t) => `<span class="s4-hit-tag">${esc(t)}</span>`)
              .join("");
            const modCount = Array.isArray(item.modifications)
              ? item.modifications.length
              : (item.modifications?.as_base?.length || 0) + (item.modifications?.as_target?.length || 0);
            const acupCount = item.acupuncture_relations?.length || 0;
            return `<button type="button" class="entity-item s4-diag-card${selected}" data-s4-open-formula="${encodeURIComponent(item.id)}">
              <span class="entity-name">
                <strong>#${idx + 1} ${esc(item.name)}</strong>
                <em>${esc(item.book)} · 分数 ${esc(item.score)}</em>
              </span>
              ${tokens ? `<span class="s4-hit-row">${tokens}</span>` : ""}
              ${item.why ? `<span class="s4-why-line">${esc(item.why)}</span>` : ""}
              ${item.composition_preview ? `<span class="s4-comp-preview"><strong>药物剂量：</strong>${esc(item.composition_preview)}</span>` : ""}
              ${item.decoction_preview ? `<span class="s4-dec-preview"><strong>熬煮法：</strong>${esc(item.decoction_preview)}</span>` : ""}
              <span class="entity-meta">
                ${item.section ? `<span>${esc(item.section)}</span>` : ""}
                ${modCount ? `<span>加减 ${modCount} 条</span>` : ""}
                ${item.cross_book_variant ? `<span>跨书同名对照</span>` : ""}
                ${acupCount ? `<span>穴位关联 ${acupCount}</span>` : ""}
                ${item.toxic_herbs?.length ? `<span class="s4-tox-badge">含毒药：${esc(item.toxic_herbs.join("、"))}</span>` : ""}
              </span>
            </button>`;
          })
          .join("")
      : `<div class="s4-welcome-card"><p>未找到直接匹配的方剂，请尝试精简关键词或使用传统条文表述（如：恶寒、无汗、心下痞、往来寒热）。</p></div>`;

    const modsHtml = mods.length
      ? `<div class="s4-left-mods">
          <div class="s4-mini-title">相关加减变化法则（${mods.length}）</div>
          ${mods
            .slice(0, 6)
            .map(
              (m) => `<button type="button" class="s4-mini-mod" data-s4-open-formula="${encodeURIComponent(m.target_formula_id || m.base_formula_id || "")}">
                <strong>${esc(m.base_formula_name)} → ${esc(m.target_formula_name)}</strong>
                <span>条件：${esc(m.condition || "")} · 变化：${esc(m.changes?.summary || "")}</span>
              </button>`
            )
            .join("")}
        </div>`
      : "";

    host.innerHTML = `<div class="s4-result-meta">命中 ${data.total_matched ?? formulas.length} 首候选方（检索词：${esc((data.tokens || []).join(" + "))}）</div>${cards}${modsHtml}`;
  }

  async function runDiagnose(rawQuery, autoOpenTop = true) {
    s4.mode = "diagnose";
    s4.diagQuery = String(rawQuery ?? "").trim();
    const input = q("#s4-diag-input");
    if (input && input.value !== s4.diagQuery) input.value = s4.diagQuery;
    updateToolbarAndColumns();

    if (!s4.diagQuery) {
      s4.diagResult = null;
      setDynamicBanner("");
      renderDiagnoseLeftList(null);
      return;
    }

    try {
      const data = await apiJson(`/api/formulas/diagnose?q=${encodeURIComponent(s4.diagQuery)}`);
      s4.diagResult = data;
      renderDiagnoseBanner(data);
      const topId = data.matched_formulas?.[0]?.id || "";
      if (autoOpenTop && topId) {
        s4.selectedFormulaId = topId;
        renderDiagnoseLeftList(data);
        await openFormulaDetailById(topId);
      } else {
        renderDiagnoseLeftList(data);
      }
    } catch (err) {
      showNotice(`辨证推演失败：${err.message}`);
    }
  }

  async function loadAndRenderJinkui(chapterIdToOpen = "") {
    s4.mode = "jinkui";
    updateToolbarAndColumns();
    setDynamicBanner("");
    const host = q("#s4-left-host");
    if (!host) return;
    if (!s4.chapters) {
      host.innerHTML = `<div class="s4-welcome-card">正在加载《金匮要略》二十篇...</div>`;
      const res = await apiJson("/api/jinkui-chapters");
      s4.chapters = res.items || [];
    }
    const targetId = chapterIdToOpen || s4.activeChapterId || s4.chapters[0]?.id || "";
    s4.activeChapterId = targetId;

    host.innerHTML = s4.chapters
      .map(
        (ch) => `<button type="button" class="entity-item${ch.id === s4.activeChapterId ? " selected" : ""}" data-s4-select-chapter="${encodeURIComponent(ch.id)}">
          <span class="entity-name">
            <strong>${esc(ch.name || ch.title || ch.id)}</strong>
            <em>第 ${esc(ch.order || "")} 篇 · ${ch.formula_count || 0} 方</em>
          </span>
          <span class="entity-meta">
            <span class="status-pill status-reviewed">已逐方校</span>
            <span>${esc(ch.disease_category || (ch.summary || "").slice(0, 26))}</span>
          </span>
        </button>`
      )
      .join("");

    if (targetId) {
      await openJinkuiChapterDetail(targetId);
    }
  }

  async function openJinkuiChapterDetail(chapterId) {
    s4.activeChapterId = chapterId;
    document.querySelectorAll("#s4-left-host [data-s4-select-chapter]").forEach((el) => {
      el.classList.toggle("selected", decodeURIComponent(el.dataset.s4SelectChapter || "") === chapterId);
    });
    const detailPanel = q("#formula-detail");
    if (!detailPanel) return;
    try {
      const ch = await apiJson(`/api/jinkui-chapters/${encodeURIComponent(chapterId)}`);
      s4.activeChapterDetail = ch;
      const pulses = (ch.pulse_and_syndrome || []).map((p) => `<li>${esc(p)}</li>`).join("");
      const principles = (ch.treatment_principles || []).map((p) => `<li>${esc(p)}</li>`).join("");
      const formulasHtml = (ch.formulas || [])
        .map(
          (f) => `<button type="button" class="s4-chapter-formula-btn" data-s4-open-formula="${encodeURIComponent(f.id)}">
            <div class="nj-link-head">
              <strong>${esc(f.name)}</strong>
              <em>${esc(f.review_status === "reviewed" ? "已逐方校" : "原文索引")} · 查看组成与熬煮法 ↗</em>
            </div>
            <p>${esc(f.indication || "")}</p>
          </button>`
        )
        .join("");
      const variantsHtml = (ch.cross_book_variants || [])
        .map((v) => {
          const same = Boolean(v.same_composition_and_dose);
          return `<div class="s4-mod-card">
            <div class="s4-mod-head"><strong>${esc(v.normalized_name || v.formula_name || "")}</strong><span class="status-pill ${same ? "status-reviewed" : "status-variant"}">${same ? "两书一致" : "细节有异"}</span></div>
            <div class="s4-mod-rationale">${esc(v.summary || "")}</div>
          </div>`;
        })
        .join("");
      const modsHtml = (ch.modifications || [])
        .map(
          (m) => `<div class="s4-mod-card">
            <div class="s4-mod-head">
              <strong>${esc(m.base_formula_name)} → ${esc(m.target_formula_name)}</strong>
              <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-hint="金匮要略" data-ctx-q="${esc(m.target_formula_name || m.base_formula_name)}">查原书上下文 ↗</button>
            </div>
            <div class="s4-mod-diff">条件：${esc(m.condition || "")} · 变化：${esc(m.changes?.summary || "")}</div>
            ${m.rationale ? `<div class="s4-mod-rationale">${esc(m.rationale)}</div>` : ""}
          </div>`
        )
        .join("");
      const acupHtml = (ch.acupuncture_relations || []).length
        ? `<div class="section-block"><div class="section-title">本篇针灸与诊法联系（${ch.acupuncture_relations.length}）</div><div class="nj-link-grid">${ch.acupuncture_relations
            .map(
              (rel) => `<button type="button" class="nj-rel-btn" data-s4-acup-seg="points" data-s4-acup-id="${encodeURIComponent(rel.target_id)}">
                <div class="nj-link-head"><strong>${esc(rel.target_name || rel.target_id)}</strong><em>${esc(rel.relation_kind || "针药关联")} ↗</em></div>
                <p>${esc(rel.quote || rel.note || "")}</p>
              </button>`
            )
            .join("")}</div></div>`
        : "";

      detailPanel.innerHTML = `<div class="detail-inner">
        <div class="detail-kicker">《金匮要略》第 ${esc(ch.order || "")} 篇 · ${esc(ch.disease_category || "原书篇目")} · 全篇 ${ch.formula_count || 0} 方</div>
        <h2 class="detail-title">${esc(ch.name || ch.title || ch.id)}</h2>
        <p class="detail-subtitle">${esc(ch.summary || "")}</p>
        ${pulses ? `<div class="section-block"><div class="section-title">原书病证分类与脉证提纲</div><ul class="s4-bullet-list">${pulses}</ul></div>` : ""}
        ${principles ? `<div class="section-block"><div class="section-title">原书治法原则</div><ul class="s4-bullet-list">${principles}</ul></div>` : ""}
        <div class="section-block">
          <div class="section-title">本篇所载经方（${(ch.formulas || []).length} 首）</div>
          <div class="nj-link-grid">${formulasHtml || `<div class="section-copy">本篇未单独列方，重在脉证总论。</div>`}</div>
        </div>
        ${modsHtml ? `<div class="section-block"><div class="section-title">本篇加减变化（${ch.modifications.length}）</div><div class="s4-mod-list">${modsHtml}</div></div>` : ""}
        ${variantsHtml ? `<div class="section-block"><div class="section-title">涉及《伤寒↔金匮》同名方（${ch.cross_book_variants.length}）</div><div class="s4-mod-list">${variantsHtml}</div></div>` : ""}
        ${acupHtml}
      </div>`;
      if (typeof detailPanel.scrollTo === "function") {
        detailPanel.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (err) {
      showNotice(`加载《金匮》篇目失败：${err.message}`);
    }
  }

  async function loadAndRenderRules() {
    s4.mode = "rules";
    updateToolbarAndColumns();
    setDynamicBanner("");
    const host = q("#s4-left-host");
    if (!host) return;

    const search = (s4.rulesSearch || "").trim();
    const headerBar = `<div class="s4-rules-controls">
      <div class="s4-sub-pills">
        <button type="button" class="s4-sub-pill${s4.rulesSub === "modifications" ? " active" : ""}" data-s4-rules-sub="modifications">加减规则 (108)</button>
        <button type="button" class="s4-sub-pill${s4.rulesSub === "variants" ? " active" : ""}" data-s4-rules-sub="variants">跨书同名对照 (42)</button>
        <button type="button" class="s4-sub-pill${s4.rulesSub === "acupuncture" ? " active" : ""}" data-s4-rules-sub="acupuncture">书内针药关联 (27)</button>
      </div>
      <div class="s4-rules-filter-row">
        <input id="s4-rules-search" type="search" value="${esc(search)}" placeholder="筛选方名、加减条件、差异药味或穴位..." />
        ${
          s4.rulesSub === "variants"
            ? `<label class="s4-check-label"><input type="checkbox" id="s4-diff-only" ${s4.variantsDiffOnly ? "checked" : ""} /> 仅看有差异 (${s4.variantsData?.diff_count ?? 27} 组)</label>`
            : ""
        }
      </div>
    </div>`;

    if (s4.rulesSub === "modifications") {
      if (!s4.modsData) {
        const res = await apiJson("/api/formula-modifications");
        s4.modsData = res.items || [];
      }
      const items = s4.modsData.filter((row) => {
        if (!search) return true;
        const text = `${row.base_formula_name} ${row.target_formula_name} ${row.condition} ${row.changes?.summary || ""} ${row.rationale || ""}`.toLowerCase();
        return text.includes(search.toLowerCase());
      });
      const listHtml = items
        .map(
          (row) => `<div class="s4-rule-item">
            <div class="s4-mod-head">
              <strong>${esc(row.base_formula_name)} → ${esc(row.target_formula_name)}</strong>
              <span class="s4-hit-tag">${esc(row.book || "经方")}</span>
            </div>
            <div class="s4-mod-diff"><strong>条文前提：</strong>${esc(row.condition || "")}</div>
            <div class="s4-mod-diff"><strong>加减变化：</strong>${esc(row.changes?.summary || "")}</div>
            ${row.rationale ? `<div class="s4-mod-rationale"><strong>原书/倪注理由：</strong>${esc(row.rationale)}</div>` : ""}
            <div class="s4-rule-actions">
              ${row.base_formula_id ? `<button type="button" class="text-button" data-s4-open-formula="${encodeURIComponent(row.base_formula_id)}">看原方：${esc(row.base_formula_name)}</button>` : ""}
              ${row.target_formula_id ? `<button type="button" class="text-button" data-s4-open-formula="${encodeURIComponent(row.target_formula_id)}">看变化方：${esc(row.target_formula_name)}</button>` : ""}
            </div>
          </div>`
        )
        .join("");
      host.innerHTML = `${headerBar}<div class="s4-result-meta">共 ${items.length} 条规则</div>${listHtml || `<div class="s4-welcome-card">无匹配加减规则</div>`}`;
    } else if (s4.rulesSub === "variants") {
      if (!s4.variantsData) {
        s4.variantsData = await apiJson("/api/formula-variants");
      }
      const items = (s4.variantsData.items || []).filter((v) => {
        if (s4.variantsDiffOnly && v.same_composition_and_dose) return false;
        if (!search) return true;
        return `${v.normalized_name || ""} ${v.summary || ""}`.toLowerCase().includes(search.toLowerCase());
      });
      const listHtml = items
        .map((v) => {
          const same = Boolean(v.same_composition_and_dose);
          return `<div class="s4-rule-item">
            <div class="s4-mod-head">
              <strong>${esc(v.normalized_name || "")}</strong>
              <span class="status-pill ${same ? "status-reviewed" : "status-variant"}">${same ? "两书基本一致" : "存在差异"}</span>
            </div>
            <div class="s4-mod-rationale">${esc(v.summary || "")}</div>
            <div class="s4-rule-actions">
              <button type="button" class="text-button" data-s4-open-formula="${encodeURIComponent(v.shanghan_id)}">查《伤寒论》版 ↗</button>
              <button type="button" class="text-button" data-s4-open-formula="${encodeURIComponent(v.jinkui_id)}">查《金匮》版 ↗</button>
            </div>
          </div>`;
        })
        .join("");
      host.innerHTML = `${headerBar}<div class="s4-result-meta">共 ${items.length} 组同名对照（两书一致 ${s4.variantsData.exact_same_count ?? 15} · 有异 ${s4.variantsData.diff_count ?? 27}）</div>${listHtml}`;
    } else {
      if (!s4.acupLinksData) {
        const res = await apiJson("/api/formula-acupuncture-links");
        s4.acupLinksData = res.items || [];
      }
      const KIND_SEG = { acupoint: "points", meridian: "meridians", condition: "conditions", technique: "techniques" };
      const items = s4.acupLinksData.filter((rel) => {
        if (!search) return true;
        return `${rel.formula_name || ""} ${rel.target_name || ""} ${rel.quote || ""} ${rel.note || ""}`.toLowerCase().includes(search.toLowerCase());
      });
      const listHtml = items
        .map((rel) => {
          const seg = KIND_SEG[rel.target_kind] || "points";
          const fname = rel.formula_name || (rel.formula_id ? rel.formula_id.split(":").slice(1).join(":") : "") || rel.chapter_id || "";
          return `<div class="s4-rule-item">
            <div class="s4-mod-head">
              <strong>${esc(fname)} ↔ ${esc(rel.target_name || rel.target_id)}</strong>
              <span class="s4-hit-tag">${esc(rel.relation_kind || "针药联系")}</span>
            </div>
            ${rel.quote ? `<div class="s4-mod-diff">${esc(rel.quote)}</div>` : ""}
            ${rel.note ? `<div class="s4-mod-rationale">${esc(rel.note)}</div>` : ""}
            <div class="s4-rule-actions">
              ${rel.formula_id ? `<button type="button" class="text-button" data-s4-open-formula="${encodeURIComponent(rel.formula_id)}">打开经方 ↗</button>` : ""}
              ${rel.chapter_id && !rel.formula_id ? `<button type="button" class="text-button" data-s4-jinkui-chapter="${encodeURIComponent(rel.chapter_id)}">打开金匮篇目 ↗</button>` : ""}
              <button type="button" class="text-button" data-s4-acup-seg="${esc(seg)}" data-s4-acup-id="${encodeURIComponent(rel.target_id)}">赴针灸：${esc(rel.target_name || rel.target_id)} ↗</button>
              <button type="button" class="text-button ctx-ref-btn" data-ctx-loc="1" data-ctx-hint="针灸" data-ctx-q="${esc((rel.quote || rel.target_name || fname).slice(0, 20))}">查原书上下文 ↗</button>
            </div>
          </div>`;
        })
        .join("");
      host.innerHTML = `${headerBar}<div class="s4-result-meta">共 ${items.length} 条原书针灸关联</div>${listHtml}`;
    }
  }

  function switchMode(mode) {
    s4.mode = mode;
    updateToolbarAndColumns();
    if (mode === "diagnose") {
      if (s4.diagResult) {
        renderDiagnoseBanner(s4.diagResult);
        renderDiagnoseLeftList(s4.diagResult);
      } else {
        renderDiagnoseLeftList(null);
      }
    } else if (mode === "jinkui") {
      loadAndRenderJinkui(s4.activeChapterId).catch((e) => showNotice(e.message));
    } else if (mode === "rules") {
      loadAndRenderRules().catch((e) => showNotice(e.message));
    }
  }

  function jumpToAcupuncture(seg, targetId) {
    const hash = `#/acupuncture/${seg}/${encodeURIComponent(targetId)}`;
    window.location.hash = hash;
    const acupTab =
      document.querySelector('[data-view-tab="acupuncture"], [data-view="acupuncture"], [data-tab="acupuncture"]') ||
      Array.from(document.querySelectorAll("header button, nav button")).find((b) => b.textContent.trim().includes("针灸"));
    if (acupTab) acupTab.click();
    if (window.acupunctureUI?.handleHash) {
      window.acupunctureUI.handleHash(hash).catch((err) => showNotice(err.message));
    }
  }

  async function enrichSixChannelDetail(channelId) {
    const sixDetail = q("#six-detail");
    if (!sixDetail || !channelId || sixDetail.querySelector(".s4-six-extra")) return;
    try {
      const ch = await apiJson(`/api/six-channels/${encodeURIComponent(channelId)}`);
      const inner = sixDetail.querySelector(".detail-inner");
      if (!inner || inner.querySelector(".s4-six-extra")) return;

      const bridgeHtml = (ch.bridge_formulas_detail || [])
        .map(
          (f) => `<button type="button" class="nj-rel-btn" data-formula-id="${encodeURIComponent(f.id)}">
            <div class="nj-link-head"><strong>${esc(f.name)}</strong><em>${esc(f.book || "衔接方")} ↗</em></div>
            <p>${esc(f.indication || "")}</p>
          </button>`
        )
        .join("");

      const modsHtml = (ch.modifications || [])
        .slice(0, 12)
        .map(
          (m) => `<div class="s4-mod-card">
            <div class="s4-mod-head"><strong>${esc(m.base_formula_name)} → ${esc(m.target_formula_name)}</strong></div>
            <div class="s4-mod-diff">条件：${esc(m.condition || "")} · 变化：${esc(m.changes?.summary || "")}</div>
          </div>`
        )
        .join("");

      const acupHtml = (ch.acupuncture_relations || [])
        .map(
          (rel) => `<button type="button" class="nj-rel-btn" data-s4-acup-seg="points" data-s4-acup-id="${encodeURIComponent(rel.target_id)}">
            <div class="nj-link-head"><strong>${esc(rel.target_name || rel.target_id)}</strong><em>${esc(rel.relation_kind || "针药联用")} ↗</em></div>
            <p>${esc(rel.quote || rel.note || "")}</p>
          </button>`
        )
        .join("");

      const extraWrap = document.createElement("div");
      extraWrap.className = "s4-six-extra";
      extraWrap.innerHTML = `
        ${bridgeHtml ? `<div class="section-block"><div class="section-title">本经跨入《金匮》与他经桥梁方（${ch.bridge_formulas_detail.length}）</div><div class="nj-link-grid">${bridgeHtml}</div></div>` : ""}
        ${modsHtml ? `<div class="section-block"><div class="section-title">本经典型加减变方链（前 ${Math.min(12, ch.modifications.length)} / 共 ${ch.modifications.length} 条）</div><div class="s4-mod-list">${modsHtml}</div></div>` : ""}
        ${acupHtml ? `<div class="section-block"><div class="section-title">本经针灸取穴与刺灸警示（${ch.acupuncture_relations.length}）</div><div class="nj-link-grid">${acupHtml}</div></div>` : ""}
      `;
      inner.appendChild(extraWrap);
    } catch {
      // keep base six-channel detail intact silently
    }
  }

  function bindStage4Events() {
    if (s4.booted) return;
    s4.booted = true;

    document.addEventListener("click", (e) => {
      const modeBtn = e.target.closest("[data-s4-mode]");
      if (modeBtn) {
        switchMode(modeBtn.dataset.s4Mode);
        return;
      }

      const jumpSixBtn = e.target.closest("[data-s4-jump-six]");
      if (jumpSixBtn) {
        const scId = jumpSixBtn.dataset.s4JumpSix || "";
        window.setTimeout(() => {
          const targetRow = q(`#six-list [data-six-id="${CSS.escape(scId)}"]`) || q(`#six-list [data-six-id="${scId}"]`);
          if (targetRow) targetRow.click();
        }, 80);
        return;
      }

      const jumpModeBtn = e.target.closest("[data-s4-jump-mode]");
      if (jumpModeBtn) {
        const m = jumpModeBtn.dataset.s4JumpMode;
        window.setTimeout(() => switchMode(m), 0);
        return;
      }

      const chipBtn = e.target.closest("[data-s4-q]");
      if (chipBtn) {
        runDiagnose(chipBtn.dataset.s4Q, true);
        return;
      }

      const appendBtn = e.target.closest("[data-s4-append-q]");
      if (appendBtn) {
        const token = appendBtn.dataset.s4AppendQ || "";
        const cur = (q("#s4-diag-input")?.value || s4.diagQuery || "").trim();
        const tokens = cur ? cur.split(/\s+/) : [];
        if (token && !tokens.includes(token)) {
          tokens.push(token);
        }
        runDiagnose(tokens.join(" "), true);
        return;
      }

      if (e.target.closest("#s4-diag-btn")) {
        runDiagnose(q("#s4-diag-input")?.value || "", true);
        return;
      }

      const openFormulaBtn = e.target.closest("[data-s4-open-formula]");
      if (openFormulaBtn) {
        const fid = decodeURIComponent(openFormulaBtn.dataset.s4OpenFormula || "");
        openFormulaDetailById(fid);
        return;
      }

      const chapterCard = e.target.closest("[data-s4-select-chapter]");
      if (chapterCard) {
        const cid = decodeURIComponent(chapterCard.dataset.s4SelectChapter || "");
        openJinkuiChapterDetail(cid);
        return;
      }

      const openJkBtn = e.target.closest("[data-s4-jinkui-chapter]");
      if (openJkBtn) {
        const cid = decodeURIComponent(openJkBtn.dataset.s4JinkuiChapter || "");
        loadAndRenderJinkui(cid);
        return;
      }

      const subBtn = e.target.closest("[data-s4-rules-sub]");
      if (subBtn) {
        s4.rulesSub = subBtn.dataset.s4RulesSub;
        loadAndRenderRules().catch((err) => showNotice(err.message));
        return;
      }

      const acupBtn = e.target.closest("[data-s4-acup-id]");
      if (acupBtn) {
        const seg = acupBtn.dataset.s4AcupSeg || "points";
        const aid = decodeURIComponent(acupBtn.dataset.s4AcupId || "");
        jumpToAcupuncture(seg, aid);
        return;
      }

      const sixBtn = e.target.closest("#six-list [data-six-id]");
      if (sixBtn) {
        const scId = decodeURIComponent(sixBtn.dataset.sixId || "");
        window.setTimeout(() => enrichSixChannelDetail(scId), 260);
      }

      // Whenever a hash/link opens a formula from another tab into #formula-detail while in catalog-hidden toolbar, keep detail visible cleanly
      const extFormulaBtn = e.target.closest("#herb-detail [data-formula-id], #nj-detail [data-formula-id], #six-detail [data-formula-id]");
      if (extFormulaBtn) {
        const fid = decodeURIComponent(extFormulaBtn.dataset.formulaId || "");
        window.setTimeout(() => openFormulaDetailById(fid), 80);
      }
    });

    q("#s4-diag-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runDiagnose(e.target.value, true);
      }
    });

    document.addEventListener("input", (e) => {
      if (e.target && e.target.id === "s4-rules-search") {
        s4.rulesSearch = e.target.value;
        loadAndRenderRules().catch((err) => showNotice(err.message));
      }
    });

    document.addEventListener("change", (e) => {
      if (e.target && e.target.id === "s4-diff-only") {
        s4.variantsDiffOnly = Boolean(e.target.checked);
        loadAndRenderRules().catch((err) => showNotice(err.message));
      }
    });

    // Observe #six-detail to append Stage 4 bridge formulas, mods & acupuncture links
    const sixDetailEl = q("#six-detail");
    if (sixDetailEl && typeof MutationObserver !== "undefined") {
      const obs = new MutationObserver(() => {
        const dossierBtn = sixDetailEl.querySelector("[data-open-six-dossier]");
        const selectedSixBtn = q("#six-list .entity-item.selected[data-six-id]");
        const sid =
          (dossierBtn && decodeURIComponent(dossierBtn.dataset.openSixDossier || "")) ||
          (selectedSixBtn && decodeURIComponent(selectedSixBtn.dataset.sixId || ""));
        if (sid && !sixDetailEl.querySelector(".s4-six-extra")) {
          enrichSixChannelDetail(sid);
        }
      });
      obs.observe(sixDetailEl, { childList: true });
    }

    // Boot default diagnose screen
    updateToolbarAndColumns();
    renderDiagnoseLeftList(null);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindStage4Events);
  } else {
    bindStage4Events();
  }

  window.Stage4Formulas = {
    switchMode,
    runDiagnose,
    openFormulaDetailById,
    openJinkuiChapterDetail,
  };
})();
