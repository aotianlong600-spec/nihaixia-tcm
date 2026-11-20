(() => {
  const $ = (sel) => document.querySelector(sel);
  const esc = (v) =>
    String(v ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const MODULE_BADGE = {
    formulas: { cls: "badge-formula", text: "经方" },
    bencao: { cls: "badge-bencao", text: "本草" },
    acupuncture: { cls: "badge-acup", text: "针灸" },
    neijing: { cls: "badge-neijing", text: "内经" },
    hantang: { cls: "badge-hantang", text: "汉唐" },
  };

  const st = {
    activeView: "", // "" | "stage5" | "library"
    // Stage 5 state
    s5Mode: "compose", // "compose" | "diagnose" | "ground" | "syndromes" | "hantang"
    s5Query: "",
    s5Pulses: [],
    s5Syndromes: [],
    s5Data: null,
    s5Catalog: [],
    s5CatFilter: "全部",
    s5CatSearch: "",
    htSubTab: "formulas", // "formulas" | "spine_palp" | "western" | "redlines" | "cases"
    htCategory: "all",
    htSafety: "all",
    htOverview: null,
    // Book Library state
    libShelf: "",
    libBooks: [],
    selectedBookId: "ni-hantang-formulas-pdf",
    selectedBook: null,
    currentPageNo: 1,
    pageData: null,
    readLayout: "continuous", // "continuous" (连续上下翻) | "single" (单页精看)
    loadedPages: [],
    loadedStartPage: 1,
    loadedEndPage: 1,
    loadingChunk: false,
    lastSearchQuery: "",
    scanSyncTimer: null,
    scanObserver: null,
    viewMode: "split", // "text" | "split" | "image"
    reflowText: true,
    highlightQuery: "",
    searchActive: false,
    searchQuery: "",
  };

  async function api(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function showMsg(msg) {
    const el = $("#notice");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add("hidden"), 2600);
  }

  function activateTopView(viewName, skipHash = false) {
    st.activeView = viewName;
    document.querySelectorAll(".module-tab").forEach((btn) => {
      btn.classList.remove("active");
      btn.setAttribute("aria-selected", "false");
    });
    document.querySelectorAll(".top-utility-tab").forEach((btn) => {
      const on = btn.dataset.stage5View === viewName;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    document.querySelectorAll(".module-view").forEach((sec) => {
      sec.classList.toggle("active", sec.id === `${viewName}-view`);
    });
    if (!skipHash) {
      if (viewName === "library") {
        location.hash = `#/library/${encodeURIComponent(st.selectedBookId)}/${st.currentPageNo}`;
      } else {
        location.hash = `#/stage5/${st.s5Mode}`;
      }
    }
  }

  function clearExtraViews() {
    st.activeView = "";
    document.querySelectorAll(".top-utility-tab").forEach((btn) => {
      btn.classList.remove("active");
      btn.setAttribute("aria-selected", "false");
    });
    $("#stage5-view")?.classList.remove("active");
    $("#library-view")?.classList.remove("active");
  }

  // -------------------- Cross-Module Entity Jump --------------------
  async function jumpToModuleEntity(module, entityId) {
    if (!module || !entityId) return;
    clearExtraViews();
    if (module === "formulas") {
      document.querySelector('.module-tab[data-view="formulas"]')?.click();
      setTimeout(() => {
        if (window.Stage4Formulas?.openFormulaDetailById) {
          window.Stage4Formulas.switchMode?.("catalog");
          window.Stage4Formulas.openFormulaDetailById(entityId);
        } else if (typeof window.openFormula === "function") {
          window.openFormula(entityId);
        } else {
          location.hash = `#/formulas/${encodeURIComponent(entityId)}`;
        }
      }, 90);
      return;
    }
    if (module === "bencao" || module === "herbs") {
      document.querySelector('.module-tab[data-view="herbs"]')?.click();
      setTimeout(() => {
        if (window.bencaoUI?.openEntry) {
          window.bencaoUI.openEntry(entityId).catch(() => showMsg("未能打开该本草条目"));
        } else {
          location.hash = `#/herbs/entry/${encodeURIComponent(entityId)}`;
        }
      }, 80);
      return;
    }
    if (module === "neijing") {
      document.querySelector('.module-tab[data-view="neijing"]')?.click();
      setTimeout(() => {
        if (entityId.startsWith("concept:")) {
          window.neijingUI?.openConcept?.(entityId).catch(() => {});
        } else {
          window.neijingUI?.openChapter?.(entityId).catch(() => {});
        }
      }, 80);
      return;
    }
    if (module === "acupuncture") {
      document.querySelector('.module-tab[data-view="acupuncture"]')?.click();
      let sub = "points";
      if (entityId.startsWith("cond:")) sub = "conditions";
      else if (entityId.startsWith("meridian:")) sub = "meridians";
      else if (entityId.startsWith("tech:")) sub = "techniques";
      const targetHash = `#/acupuncture/${sub}/${encodeURIComponent(entityId)}`;
      setTimeout(() => {
        window.acupunctureUI?.handleHash?.(targetHash).catch(() => {});
      }, 80);
      return;
    }
    if (module === "hantang") {
      let htQuery = String(entityId || "").replace(/^hantang:/i, "").toUpperCase();
      htQuery = htQuery.replace(/^HT-0*(\d+)$/, "HT-$1");
      st.s5Query = htQuery;
      st.htSubTab = "formulas";
      st.htCategory = "all";
      st.htSafety = "all";
      const inp = $("#s5-query-input");
      if (inp) inp.value = htQuery;
      activateTopView("stage5", false);
      await activateStage5("hantang", false);
    }
  }

  // -------------------- Standalone Book Library Module (书库) --------------------
  async function loadLibraryBooks(shelf = st.libShelf) {
    st.libShelf = shelf;
    document.querySelectorAll("#lib-shelf-tabs [data-lib-shelf]").forEach((btn) => {
      const on = (btn.dataset.libShelf || "") === shelf;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    const [ov, booksRes] = await Promise.all([
      api("/api/library/overview"),
      api(`/api/library/books${shelf ? `?shelf=${encodeURIComponent(shelf)}` : ""}`),
    ]);
    st.libBooks = booksRes.items || [];
    const stats = ov.stats || {};
    const statsEl = $("#lib-overview-stats");
    if (statsEl) {
      const totalBooks = stats.total_books ?? 17;
      const indexedBooks = stats.indexed_books ?? 17;
      const scanOnlyBooks = stats.scan_only_books ?? 0;
      const scanNote = scanOnlyBooks > 0 ? ` · ${scanOnlyBooks} 册影印扫描` : " · 全库均已OCR/文本数字化";
      statsEl.textContent = `共 ${totalBooks} 册 · ${indexedBooks} 册可全文检索${scanNote} · ${stats.linked_pages || 0} 页双向联动`;
    }
    const cntEl = $("#lib-books-count");
    if (cntEl) cntEl.textContent = `${st.libBooks.length} 册`;
    renderBookList();
  }

  function renderBookList() {
    const host = $("#lib-book-list");
    if (!host) return;
    if (!st.libBooks.length) {
      host.innerHTML = `<div class="empty-mini">当前分类暂无书目</div>`;
      return;
    }
    host.innerHTML = st.libBooks
      .map((b) => {
        const active = b.book_id === st.selectedBookId ? " active" : "";
        const isScan = b.search_index_status === "scan_browse_only";
        const isNew = b.shelf !== "renji_core";
        return `
          <button class="lib-book-item${active}" type="button" data-lib-select-book="${esc(b.book_id)}">
            <div class="lib-book-row-top">
              <strong class="lib-book-title">${esc(b.short_title)}</strong>
              <span class="lib-badge ${isScan ? "lib-badge-scan" : isNew ? "lib-badge-new" : "lib-badge-core"}">
                ${isScan ? `影印 ${b.total_units}页` : `${b.total_units}${b.file_format === "pdf" ? "页" : "节"}`}
              </span>
            </div>
            <div class="lib-book-meta">${esc(b.author_era)}</div>
            <div class="lib-book-tags">
              <span class="lib-shelf-pill">${esc(b.shelf_label)}</span>
              ${(b.module_affinities || []).map((m) => `<span class="lib-mod-pill">${esc(MODULE_BADGE[m === "herbs" ? "bencao" : m]?.text || m)}</span>`).join("")}
            </div>
          </button>`;
      })
      .join("");
  }

  async function selectBook(bookId, pageNo = 1, skipHash = false) {
    st.selectedBookId = bookId;
    st.searchActive = false;
    st.loadedPages = [];
    st.loadedStartPage = 1;
    st.loadedEndPage = 1;
    $("#lib-search-results-panel")?.classList.add("hidden");
    $("#lib-reader-workspace")?.classList.remove("hidden");
    renderBookList();

    let book;
    try {
      book = await api(`/api/library/books/${encodeURIComponent(bookId)}`);
    } catch (err) {
      showMsg(`未能打开典籍：${err?.message || bookId}`);
      return;
    }
    st.selectedBook = book;
    if (book.search_index_status === "scan_browse_only") {
      st.viewMode = "image";
    } else if (st.viewMode === "image") {
      st.viewMode = "split";
    }
    const tocInp = $("#lib-toc-filter");
    if (tocInp) tocInp.value = "";
    renderBookToc(book);
    await loadBookPage(bookId, pageNo, skipHash);
  }

  function renderBookToc(book, filter = "") {
    const box = $("#lib-toc-box");
    const listEl = $("#lib-toc-list");
    const titleEl = $("#lib-toc-title");
    if (!box || !listEl) return;
    box.classList.remove("hidden");
    const nf = filter.trim().toLowerCase();
    const chapters = book.chapters || [];
    if (titleEl) {
      titleEl.textContent = book.search_index_status === "scan_browse_only" ? "影印原书页码导航" : `目录大纲与方目 (${chapters.length})`;
    }
    const filteredChapters = chapters.filter(
      (c) => !nf || c.title.toLowerCase().includes(nf) || String(c.page_no) === nf
    );
    const itemsHtml = filteredChapters
      .map(
        (c) => `
        <button class="lib-toc-item ${Number(st.currentPageNo) === Number(c.page_no) ? "is-current" : ""}" type="button" data-lib-go-page="${c.page_no}">
          <span class="lib-toc-name">${esc(c.title)}</span>
          <span class="lib-toc-pno">p.${c.page_no}</span>
        </button>`
      )
      .join("");

    const topEntHtml = (book.top_entities || []).length
      ? `<div class="lib-toc-subhead">本书高频关联知识点（点跳模块）</div>
         <div class="lib-chip-cloud">
           ${(book.top_entities || [])
             .slice(0, 14)
             .map((e) => {
               const mb = MODULE_BADGE[e.module] || { cls: "badge-formula", text: e.kind };
               return `<button class="entity-jump-chip ${mb.cls}" type="button" data-jump-module="${esc(e.module)}" data-jump-id="${esc(e.entity_id)}">${esc(mb.text)} · ${esc(e.label)} <em>(${e.mentions})</em></button>`;
             })
             .join("")}
         </div>`
      : "";

    listEl.innerHTML = (itemsHtml || `<div class="empty-mini">可直接输入页码翻阅（共 ${book.total_units} 单元）</div>`) + topEntHtml;
  }

  function buildEntityLinksBarHtml(page) {
    if (!page) return "";
    return (page.entity_links || []).length
      ? `<span class="lib-links-label">本页知识联动（第 ${page.page_no} 页）· 点击直达对应学习板块：</span>
         <div class="lib-chip-cloud">
           ${page.entity_links
             .map((lk) => {
               const mb = MODULE_BADGE[lk.module] || { cls: "badge-formula", text: lk.kind };
               return `<button class="entity-jump-chip ${mb.cls}" type="button" data-jump-module="${esc(lk.module)}" data-jump-id="${esc(lk.entity_id)}">${esc(mb.text)} · ${esc(lk.label)}</button>`;
             })
             .join("")}
         </div>`
      : `<span class="muted-line">第 ${page.page_no} 页暂未检测到明确跨模块条目名称</span>`;
  }

  function updateSyncedScanImage(page) {
    if (!page || !page.has_image_viewer || !page.image_url) return;
    const capEl = $("#lib-synced-scan-cap");
    if (capEl) capEl.textContent = `原书影印图 · 第 ${page.page_no} / ${page.total_units} 页`;
    const prevBtn = $("#lib-scan-prev");
    const nextBtn = $("#lib-scan-next");
    if (prevBtn) prevBtn.disabled = page.page_no <= 1;
    if (nextBtn) nextBtn.disabled = page.page_no >= page.total_units;

    const wrap = $("#lib-synced-scan-img-wrap");
    if (!wrap) return;
    const curImg = wrap.querySelector("img");
    const existingUrl = curImg?.dataset.tcmApiImg || curImg?.getAttribute("src") || "";
    if (existingUrl === page.image_url) return;
    const imgAttrs = window.tcmImgAttrs ? window.tcmImgAttrs(page.image_url) : `src="${esc(page.image_url)}"`;
    wrap.innerHTML = `<img id="lib-synced-scan-img" class="lib-scan-img" ${imgAttrs} alt="${esc(page.book_title)} 第${page.page_no}页原图" loading="lazy" />`;
  }

  function syncActivePageIndicators(pageNo, { updateScan = false } = {}) {
    const target = Number(pageNo) || 1;
    const page = st.loadedPages.find((p) => p.page_no === target) || st.pageData;
    if (!page) return;
    const changed = st.currentPageNo !== page.page_no;
    st.currentPageNo = page.page_no;
    st.pageData = page;

    const subEl = $("#lib-reader-sub");
    if (subEl) {
      const rangeNote =
        st.readLayout === "continuous" && st.loadedPages.length > 1
          ? `（已载入第 ${st.loadedStartPage}–${st.loadedEndPage} 页上下文）`
          : "";
      subEl.textContent = `${page.unit_label}${page.section_title ? ` · ${page.section_title}` : ""} ${rangeNote}`;
    }
    const jumpInp = $("#lib-jump-input");
    if (jumpInp && document.activeElement !== jumpInp) jumpInp.value = page.page_no;
    const prevBtn = $("#lib-prev-btn");
    const nextBtn = $("#lib-next-btn");
    if (prevBtn) prevBtn.disabled = page.page_no <= 1;
    if (nextBtn) nextBtn.disabled = page.page_no >= page.total_units;
    const shaEl = $("#lib-active-sha");
    if (shaEl) shaEl.textContent = `SHA: ${(page.text_sha256 || "").slice(0, 12)}`;
    const linksBar = $("#lib-active-links-bar");
    if (linksBar && changed) {
      linksBar.className = (page.entity_links || []).length ? "lib-page-links-bar" : "lib-page-links-bar muted-line";
      linksBar.innerHTML = buildEntityLinksBarHtml(page);
    }

    document.querySelectorAll("#lib-toc-list .lib-toc-item").forEach((el) => {
      el.classList.toggle("is-current", Number(el.dataset.libGoPage) === page.page_no);
    });
    document.querySelectorAll("#lib-continuous-stream .lib-page-block").forEach((el) => {
      el.classList.toggle("is-active-page", Number(el.dataset.libPageAnchor) === page.page_no);
    });

    if (changed && st.activeView === "library") {
      history.replaceState(null, "", `#/library/${encodeURIComponent(st.selectedBookId)}/${page.page_no}`);
    }
    if (updateScan && st.viewMode === "split" && page.has_image_viewer) {
      clearTimeout(st.scanSyncTimer);
      st.scanSyncTimer = setTimeout(() => updateSyncedScanImage(page), 140);
    }
  }

  function scrollToPageAnchor(pageNo, preferHighlight = false) {
    const stream = $("#lib-continuous-stream");
    if (!stream) return;
    const block = stream.querySelector(`[data-lib-page-anchor="${pageNo}"]`);
    if (!block) return;
    const hl = preferHighlight ? block.querySelector(".lib-hl") : null;
    if (hl) {
      hl.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      const top = Math.max(0, block.offsetTop - stream.offsetTop - 8);
      stream.scrollTo({ top, behavior: "auto" });
    }
    block.classList.add("is-flash-target");
    setTimeout(() => block.classList.remove("is-flash-target"), 1400);
  }

  async function loadBookPage(bookId, pageNo, skipHash = false) {
    const safePage = Math.max(1, Number(pageNo) || 1);
    if (st.readLayout === "single") {
      const page = await api(`/api/library/books/${encodeURIComponent(bookId)}/pages/${safePage}`);
      st.currentPageNo = page.page_no;
      st.pageData = page;
      st.loadedPages = [page];
      st.loadedStartPage = page.page_no;
      st.loadedEndPage = page.page_no;
      if (!skipHash && st.activeView === "library") {
        location.hash = `#/library/${encodeURIComponent(bookId)}/${page.page_no}`;
      }
      renderReaderPage();
      return;
    }

    // Continuous context mode: if already within loaded window of same book, scroll smoothly without reload!
    if (
      st.selectedBookId === bookId &&
      st.loadedPages.length > 0 &&
      safePage >= st.loadedStartPage &&
      safePage <= st.loadedEndPage &&
      $("#lib-continuous-stream")
    ) {
      syncActivePageIndicators(safePage, { updateScan: true });
      scrollToPageAnchor(safePage, Boolean(st.highlightQuery));
      if (!skipHash && st.activeView === "library") {
        location.hash = `#/library/${encodeURIComponent(bookId)}/${safePage}`;
      }
      return;
    }

    const before = st.selectedBook?.search_index_status === "scan_browse_only" ? 1 : 2;
    const after = st.selectedBook?.search_index_status === "scan_browse_only" ? 3 : 4;
    const ctx = await api(
      `/api/library/books/${encodeURIComponent(bookId)}/context?page_no=${safePage}&before=${before}&after=${after}`
    );
    st.loadedPages = ctx.pages || [];
    st.loadedStartPage = ctx.start_page || 1;
    st.loadedEndPage = ctx.end_page || st.loadedPages.length;
    st.currentPageNo = ctx.target_page || safePage;
    st.pageData = st.loadedPages.find((p) => p.page_no === st.currentPageNo) || st.loadedPages[0];
    if (!skipHash && st.activeView === "library") {
      location.hash = `#/library/${encodeURIComponent(bookId)}/${st.currentPageNo}`;
    }
    renderReaderPage();
    scrollToPageAnchor(st.currentPageNo, Boolean(st.highlightQuery));
  }

  async function loadContextDirection(direction) {
    if (st.loadingChunk || !st.selectedBook || st.readLayout !== "continuous") return;
    const total = st.pageData?.total_units || st.selectedBook.total_units || 1;
    const stream = $("#lib-continuous-stream");
    if (!stream) return;

    if (direction === "up") {
      if (st.loadedStartPage <= 1) return;
      st.loadingChunk = true;
      const prevBtn = $("#lib-load-prev-chunk");
      if (prevBtn) prevBtn.textContent = "正在载入上文书页...";
      try {
        const anchorCenter = Math.max(1, st.loadedStartPage - 3);
        const ctx = await api(
          `/api/library/books/${encodeURIComponent(st.selectedBookId)}/context?page_no=${anchorCenter}&before=2&after=2`
        );
        const older = (ctx.pages || []).filter((p) => p.page_no < st.loadedStartPage);
        if (older.length) {
          const prevScrollHeight = stream.scrollHeight;
          const prevScrollTop = stream.scrollTop;
          const baseFirst = st.loadedPages[0];
          st.loadedPages = [...older, ...st.loadedPages];
          st.loadedStartPage = st.loadedPages[0].page_no;
          // Insert older blocks right after top loader sentinel and preserve viewport pixel offset!
          const topWrap = $("#lib-top-sentinel");
          if (topWrap) {
            const fragHtml = older
              .map((p, idx) => renderContinuousPageBlock(p, idx === 0 ? null : older[idx - 1], st.highlightQuery, true))
              .join("");
            topWrap.insertAdjacentHTML("afterend", fragHtml);
            if (baseFirst) {
              // Refresh continuation badge on previously first block if needed
              const oldFirstDom = stream.querySelector(`[data-lib-page-anchor="${baseFirst.page_no}"]`);
              if (oldFirstDom) oldFirstDom.outerHTML = renderContinuousPageBlock(baseFirst, older[older.length - 1], st.highlightQuery, true);
            }
            // Trim bottom if buffer grows huge (> 36 pages)
            if (st.loadedPages.length > 36) {
              const dropCount = st.loadedPages.length - 36;
              const dropped = st.loadedPages.splice(st.loadedPages.length - dropCount, dropCount);
              st.loadedEndPage = st.loadedPages[st.loadedPages.length - 1].page_no;
              dropped.forEach((dp) => stream.querySelector(`[data-lib-page-anchor="${dp.page_no}"]`)?.remove());
            }
            const delta = stream.scrollHeight - prevScrollHeight;
            stream.scrollTop = prevScrollTop + delta;
            installContinuousScanLazyObserver();
            refreshSentinelControls();
          } else {
            renderReaderPage();
          }
        }
      } finally {
        st.loadingChunk = false;
      }
    } else if (direction === "down") {
      if (st.loadedEndPage >= total) return;
      st.loadingChunk = true;
      const nextBtn = $("#lib-load-next-chunk");
      if (nextBtn) nextBtn.textContent = "正在载入下文书页...";
      try {
        const anchorCenter = Math.min(total, st.loadedEndPage + 3);
        const ctx = await api(
          `/api/library/books/${encodeURIComponent(st.selectedBookId)}/context?page_no=${anchorCenter}&before=2&after=4`
        );
        const newer = (ctx.pages || []).filter((p) => p.page_no > st.loadedEndPage);
        if (newer.length) {
          const prevLast = st.loadedPages[st.loadedPages.length - 1];
          st.loadedPages = [...st.loadedPages, ...newer];
          st.loadedEndPage = st.loadedPages[st.loadedPages.length - 1].page_no;
          const bottomWrap = $("#lib-bottom-sentinel");
          if (bottomWrap) {
            const fragHtml = newer
              .map((p, idx) => renderContinuousPageBlock(p, idx === 0 ? prevLast : newer[idx - 1], st.highlightQuery, true))
              .join("");
            bottomWrap.insertAdjacentHTML("beforebegin", fragHtml);
            if (st.loadedPages.length > 36) {
              const prevHeight = stream.scrollHeight;
              const prevTop = stream.scrollTop;
              const dropCount = st.loadedPages.length - 36;
              const dropped = st.loadedPages.splice(0, dropCount);
              st.loadedStartPage = st.loadedPages[0].page_no;
              dropped.forEach((dp) => stream.querySelector(`[data-lib-page-anchor="${dp.page_no}"]`)?.remove());
              stream.scrollTop = Math.max(0, prevTop - (prevHeight - stream.scrollHeight));
            }
            installContinuousScanLazyObserver();
            refreshSentinelControls();
          } else {
            renderReaderPage();
          }
        }
      } finally {
        st.loadingChunk = false;
      }
    }
  }

  function highlightEscapedHtml(text, query) {
    const raw = String(text || "");
    const rawTerms = String(query || "")
      .trim()
      .split(/[\s,，、；;：:。！？!?\-\/]+/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 1)
      .sort((a, b) => b.length - a.length)
      .slice(0, 8);
    if (!rawTerms.length) return esc(raw);
    const pats = rawTerms.map((t) => {
      if (t.length >= 2 && /^[\u4e00-\u9fff]+$/.test(t)) {
        return Array.from(t)
          .map((ch) => ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
          .join("[\\s「」『』《》【】〔〕“”‘’\"<>〈〉]*");
      }
      return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    });
    const re = new RegExp(`(${pats.join("|")})`, "gi");
    let out = "";
    let lastIdx = 0;
    let m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > lastIdx) out += esc(raw.slice(lastIdx, m.index));
      out += `<mark class="lib-hl">${esc(m[0])}</mark>`;
      lastIdx = m.index + m[0].length;
      if (!m[0].length) {
        re.lastIndex += 1;
      }
    }
    if (lastIdx < raw.length) out += esc(raw.slice(lastIdx));
    return out;
  }

  function reflowBookParagraphs(raw) {
    const lines = String(raw || "").replace(/\r\n?/g, "\n").split("\n");
    const paragraphs = [];
    let buf = "";
    let prevLen = 0;

    const trimmedLines = lines.map((l) => l.replace(/[\s\u3000]+$/g, "").trim()).filter(Boolean);
    const maxLineLen = trimmedLines.length ? Math.max(30, ...trimmedLines.map((l) => l.length)) : 40;
    const paraEndCutoff = maxLineLen * 0.85;

    const isMetaLine = (s) =>
      /^(第\s*\d+\s*页|\d{4}-\d{2}-\d{2}\s*定稿|倪注《[^》]+》|倪海厦人纪|倪海厦注《|勤求古训|观其脉证)/.test(s);
    const isHeadingOrNewPara = (s) =>
      /^(第[一二三四五六七八九十百零\d]+[条章节卷篇]|[一二三四五六七八九十]+、|HT-\d+|[一二三四五六七八九十\d]+[：:.、]|【|〔|问曰[：:]|答曰[：:]|问[：:]|答[：:]|辨.+脉证|[\u4e00-\u9fff]{1,14}方[：:\s]*$|右[一二三四五六七八九十半]+味|按[：:]|注[：:]|方义[：:]|煎服法[：:]|组成[：:])/.test(
        s
      );
    const isFormulaRow = (s) =>
      /\S\s{2,}\S/.test(s) && /(两|钱|枚|升|合|斤|克|去皮|炙|炮|切|擘|碎)/.test(s);

    const flush = (kind = "body") => {
      const t = buf.trim();
      if (t) paragraphs.push({ text: t, kind });
      buf = "";
      prevLen = 0;
    };

    for (const rawLine of lines) {
      const line = rawLine.replace(/[\s\u3000]+$/g, "").trim();
      if (!line) {
        flush("body");
        continue;
      }
      if (isMetaLine(line)) {
        flush("body");
        paragraphs.push({ text: line, kind: "meta" });
        continue;
      }
      if (isFormulaRow(line)) {
        flush("body");
        paragraphs.push({ text: line, kind: "qa" });
        continue;
      }
      if (!buf) {
        if (line.length <= 26 && /^(HT-\d+|第[一二三四五六七八九十百零]+[篇章节回卷]|卷[一二三四五六七八九十]+|辨.+脉证|[\u4e00-\u9fff]{2,18}篇|[\u4e00-\u9fff]{2,14}方)$/.test(line)) {
          paragraphs.push({ text: line, kind: "heading" });
          continue;
        }
        buf = line;
        prevLen = line.length;
        continue;
      }
      const prevEndStop = /[。！？!?】」』]$/.test(buf) && prevLen <= paraEndCutoff;
      if (isHeadingOrNewPara(line) || prevEndStop) {
        flush(isHeadingOrNewPara(buf) ? "qa" : "body");
        buf = line;
        prevLen = line.length;
      } else {
        const needSpace = /[A-Za-z0-9]$/.test(buf) && /^[A-Za-z0-9]/.test(line);
        buf += (needSpace ? " " : "") + line;
        prevLen = line.length;
      }
    }
    flush(isHeadingOrNewPara(buf) ? "qa" : "body");
    return paragraphs;
  }

  function renderBookTextPane(bodyText, query, wrapBox = true, reflow = st.reflowText) {
    const cleanText = bodyText || "（本页为空白页或封面页）";
    if (!reflow) {
      const inner = `<pre class="${wrapBox ? "lib-verbatim-text" : "lib-verbatim-inline"}">${highlightEscapedHtml(cleanText, query)}</pre>`;
      return wrapBox ? `<div class="lib-text-pane">${inner}</div>` : inner;
    }
    const paras = reflowBookParagraphs(cleanText);
    const html = paras
      .map((p) => `<p class="lib-para lib-para-${p.kind}">${highlightEscapedHtml(p.text, query)}</p>`)
      .join("");
    return wrapBox
      ? `<div class="lib-text-pane"><div class="lib-formatted-body">${html}</div></div>`
      : `<div class="lib-continuous-paras">${html}</div>`;
  }

  function isCrossPageContinuation(prevPage, currPage, reflow = st.reflowText) {
    if (!prevPage || !currPage || !reflow) return false;
    const prevClean = String(prevPage.body_text || "").trim();
    const currClean = String(currPage.body_text || "").trim();
    if (!prevClean || !currClean) return false;
    // If previous page did not end with sentence-ending punctuation and current does not open with a chapter/formula heading
    const endsOpen = !/[。！？!?】」』：:]$/.test(prevClean.slice(-6));
    const startsHeading = /^(第[一二三四五六七八九十百零\d]+[条章节卷篇]|[一二三四五六七八九十]+、|HT-\d+|【|〔|问曰|答曰)/.test(currClean);
    return endsOpen && !startsHeading;
  }

  function renderContinuousPageBlock(page, prevPage, query, immediateScanFallback = false, opts = {}) {
    const viewMode = opts.viewMode || st.viewMode;
    const reflowText = opts.reflowText !== undefined ? opts.reflowText : st.reflowText;
    const activePageNo = opts.activePageNo || st.currentPageNo;
    const syncAttr = opts.syncAttr || "data-lib-sync-scan";
    const isScanOnly = page.search_index_status === "scan_browse_only";
    const isImageOnlyMode = isScanOnly || viewMode === "image";
    const isActive = page.page_no === activePageNo;
    const isCont = !isImageOnlyMode && isCrossPageContinuation(prevPage, page, reflowText);
    const secLabel = page.section_title ? ` · ${esc(page.section_title)}` : "";

    if (isImageOnlyMode) {
      const nearTarget = immediateScanFallback || Math.abs(page.page_no - activePageNo) <= 1;
      const imgAttrs = nearTarget
        ? window.tcmImgAttrs
          ? window.tcmImgAttrs(page.image_url)
          : `src="${esc(page.image_url)}"`
        : `data-defer-api-img="${esc(page.image_url)}"`;
      return `
        <article class="lib-page-block lib-scan-block ${isActive ? "is-active-page" : ""}" data-lib-page-anchor="${page.page_no}">
          <div class="lib-page-divider">
            <span class="lib-page-badge">第 ${page.page_no} / ${page.total_units} 页${secLabel}</span>
            <span class="sha-pill">SHA ${esc((page.text_sha256 || "").slice(0, 8))}</span>
          </div>
          <div class="lib-scan-card-body">
            <img class="lib-scan-img ${nearTarget ? "" : "is-lazy-scan"}" ${imgAttrs} alt="${esc(page.book_title)} 第${page.page_no}页原图" loading="lazy" />
          </div>
        </article>`;
    }

    const hasBodyText = Boolean(String(page.body_text || "").trim());
    const contentHtml =
      !hasBodyText && page.has_image_viewer && page.image_url
        ? `<div class="ctx-empty-scan-fallback">
             <div class="ctx-empty-scan-note">本页为扫描原图或分隔页（无纯文字层），已直接为您呈现原书扫描页面：</div>
             <img class="lib-scan-img" ${window.tcmImgAttrs ? window.tcmImgAttrs(page.image_url) : `src="${esc(page.image_url)}"`} alt="${esc(page.book_title)} 第${page.page_no}页原图" loading="lazy" />
           </div>`
        : renderBookTextPane(page.body_text, query, false, reflowText);

    return `
      <article class="lib-page-block ${isCont ? "is-cont-page" : ""} ${isActive ? "is-active-page" : ""}" data-lib-page-anchor="${page.page_no}">
        <div class="lib-page-divider ${isCont ? "is-continuation" : ""}">
          <span class="lib-page-badge">
            ${isCont ? `↳ 接上页续读 · 第 ${page.page_no} 页` : `${esc(page.unit_label)}（${page.page_no}/${page.total_units}）`}${secLabel}
          </span>
          <div class="lib-page-div-actions">
            ${
              viewMode === "split" && page.has_image_viewer
                ? `<button class="ghost-btn tiny-btn" type="button" ${syncAttr}="${page.page_no}" title="同步右侧原书扫图到此页">对照此页原图</button>`
                : ""
            }
          </div>
        </div>
        ${contentHtml}
      </article>`;
  }

  function refreshSentinelControls() {
    const total = st.pageData?.total_units || st.selectedBook?.total_units || 1;
    const prevBtn = $("#lib-load-prev-chunk");
    if (prevBtn) {
      if (st.loadedStartPage <= 1) {
        prevBtn.disabled = true;
        prevBtn.textContent = "已到本书第一页";
      } else {
        prevBtn.disabled = false;
        const fromP = Math.max(1, st.loadedStartPage - 5);
        prevBtn.textContent = `▲ 向上翻阅 / 载入前文（第 ${fromP}–${st.loadedStartPage - 1} 页）`;
      }
    }
    const nextBtn = $("#lib-load-next-chunk");
    if (nextBtn) {
      if (st.loadedEndPage >= total) {
        nextBtn.disabled = true;
        nextBtn.textContent = `已到全书末尾（共 ${total} 单元）`;
      } else {
        nextBtn.disabled = false;
        const toP = Math.min(total, st.loadedEndPage + 5);
        nextBtn.textContent = `▼ 向下连续读后文（第 ${st.loadedEndPage + 1}–${toP} 页）`;
      }
    }
  }

  function installScanLazyObserverIn(stream, observerHolder, key = "scanObserver") {
    if (observerHolder[key]) {
      observerHolder[key].disconnect();
      observerHolder[key] = null;
    }
    if (!stream) return;
    const lazyImgs = Array.from(stream.querySelectorAll("img[data-defer-api-img]"));
    if (!lazyImgs.length) return;

    const promote = (img) => {
      const url = img.getAttribute("data-defer-api-img");
      if (!url) return;
      img.removeAttribute("data-defer-api-img");
      img.classList.remove("is-lazy-scan");
      if (window.__TCM_STATIC_WEB__ || window.tcmImgAttrs) {
        img.setAttribute("data-tcm-api-img", url);
      } else {
        img.setAttribute("src", url);
      }
    };

    if (typeof IntersectionObserver !== "function") {
      lazyImgs.forEach(promote);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((ent) => {
          if (ent.isIntersecting) {
            promote(ent.target);
            obs.unobserve(ent.target);
          }
        });
      },
      { root: stream, rootMargin: "450px 0px" }
    );
    lazyImgs.forEach((im) => obs.observe(im));
    observerHolder[key] = obs;
  }

  function installContinuousScanLazyObserver() {
    installScanLazyObserverIn($("#lib-continuous-stream"), st, "scanObserver");
  }

  const XREF_SHELF_BADGES = {
    hantang_clinical: { cls: "shelf-hantang", text: "汉唐" },
    classical_companions: { cls: "shelf-classical", text: "古籍" },
    renji_core: { cls: "shelf-renji", text: "人纪" },
  };

  function renderShelfBadge(shelf) {
    const b = XREF_SHELF_BADGES[shelf];
    return b ? `<span class="lib-xref-badge ${b.cls}">${b.text}</span>` : "";
  }

  function renderLibRefRow(ref, { bodyHtml = "", probe = "" } = {}) {
    const bid = esc(ref.book_id || "");
    const pno = Number(ref.page_no || 1);
    const qProbe = esc((probe || ref.quote || ref.snippet || "").slice(0, 24));
    return `<div class="s5-book-ref-row">
      <button class="s5-book-ref-btn s5-book-ref-main" type="button" data-ctx-loc="1" data-ctx-book="${bid}" data-ctx-page="${pno}" data-ctx-q="${qProbe}" title="在当前页打开可上下滑动的原文参照抽屉">
        ${bodyHtml}
      </button>
      <div class="s5-book-ref-ops">
        <button class="ghost-btn tiny-btn ctx-ref-btn" type="button" data-ctx-loc="1" data-ctx-book="${bid}" data-ctx-page="${pno}" data-ctx-q="${qProbe}">滑动上下文</button>
        <button class="ghost-btn tiny-btn" type="button" data-lib-open="${bid}:${pno}" data-lib-hl="${qProbe}" title="跳转至藏书阁全屏阅读">藏书阁 ↗</button>
      </div>
    </div>`;
  }

  // -------------------- Context Reference Drawer (原文上下文滑动对照抽屉) --------------------
  const ctxSt = {
    open: false,
    bookId: "",
    bookTitle: "",
    bookFullTitle: "",
    shelfLabel: "",
    totalUnits: 1,
    activePageNo: 1,
    startPage: 1,
    endPage: 1,
    pages: [],
    chapters: [],
    matchedPages: [],
    indexFilter: "",
    indexSearchQuery: "",
    indexSearchHits: null,
    showIndex: typeof window !== "undefined" ? window.innerWidth >= 900 : true,
    hasImageViewer: false,
    searchIndexStatus: "searchable",
    viewMode: "text", // "text" | "split" | "image"
    reflowText: true,
    highlightQuery: "",
    matchedQuery: "",
    loadingChunk: false,
    observer: null,
    scanSyncTimer: null,
    activeReqSeq: 0,
  };

  function closeContextDrawer() {
    ctxSt.open = false;
    ctxSt.activeReqSeq += 1;
    if (ctxSt.observer) {
      ctxSt.observer.disconnect();
      ctxSt.observer = null;
    }
    const backdrop = $("#ctx-drawer-backdrop");
    if (backdrop) {
      backdrop.classList.add("hidden");
      backdrop.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("ctx-drawer-open");
  }

  function refreshCtxSentinels() {
    const total = ctxSt.totalUnits || 1;
    const prevBtn = $("#ctx-load-prev");
    if (prevBtn) {
      if (ctxSt.startPage <= 1) {
        prevBtn.disabled = true;
        prevBtn.textContent = "已到本书第一页";
      } else {
        prevBtn.disabled = false;
        const fromP = Math.max(1, ctxSt.startPage - 5);
        prevBtn.textContent = `▲ 向上载入前文（第 ${fromP}–${ctxSt.startPage - 1} 页）`;
      }
    }
    const nextBtn = $("#ctx-load-next");
    if (nextBtn) {
      if (ctxSt.endPage >= total) {
        nextBtn.disabled = true;
        nextBtn.textContent = `已到全书末尾（共 ${total} 页/单元）`;
      } else {
        nextBtn.disabled = false;
        const toP = Math.min(total, ctxSt.endPage + 5);
        nextBtn.textContent = `▼ 向下继续载入后文（第 ${ctxSt.endPage + 1}–${toP} 页）`;
      }
    }
  }

  function updateCtxSyncedScan(page) {
    if (!page || !page.image_url) return;
    const cap = $("#ctx-synced-scan-cap");
    if (cap) cap.textContent = `原书扫图 · 第 ${page.page_no} / ${ctxSt.totalUnits} 页`;
    const prevB = $("#ctx-scan-prev");
    const nextB = $("#ctx-scan-next");
    if (prevB) prevB.disabled = page.page_no <= 1;
    if (nextB) nextB.disabled = page.page_no >= ctxSt.totalUnits;
    const wrap = $("#ctx-synced-scan-img-wrap");
    if (!wrap) return;
    const curImg = wrap.querySelector("img");
    if (curImg && (curImg.getAttribute("data-tcm-api-img") === page.image_url || curImg.getAttribute("src") === page.image_url)) {
      return;
    }
    const imgAttrs = window.tcmImgAttrs
      ? window.tcmImgAttrs(page.image_url)
      : `src="${esc(page.image_url)}"`;
    wrap.innerHTML = `<img id="ctx-synced-scan-img" class="lib-scan-img" ${imgAttrs} alt="${esc(ctxSt.bookTitle)} 第${page.page_no}页原图" loading="lazy" />`;
  }

  function syncCtxActivePage(pageNo, { updateScan = false } = {}) {
    const target = Number(pageNo) || 1;
    const page = ctxSt.pages.find((p) => p.page_no === target);
    if (!page) return;
    ctxSt.activePageNo = page.page_no;
    const sub = $("#ctx-drawer-sub");
    if (sub) {
      const rangeStr = ctxSt.pages.length > 1 ? `（当前已展开第 ${ctxSt.startPage}–${ctxSt.endPage} 页，上下滑动自动续载）` : "";
      sub.textContent = `${page.unit_label || `第 ${page.page_no} 页`}${page.section_title ? ` · ${page.section_title}` : ""} ${rangeStr}`;
    }
    const jumpInp = $("#ctx-jump-inp");
    if (jumpInp && document.activeElement !== jumpInp) {
      jumpInp.value = page.page_no;
    }
    document.querySelectorAll("#ctx-stream .lib-page-block").forEach((el) => {
      el.classList.toggle("is-active-page", Number(el.dataset.libPageAnchor) === page.page_no);
    });
    document.querySelectorAll(".ctx-hit-pill[data-ctx-jump-page]").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.ctxJumpPage) === page.page_no);
    });
    document.querySelectorAll("#ctx-index-list .ctx-index-item[data-ctx-jump-page]").forEach((el) => {
      el.classList.toggle("is-current", Number(el.dataset.ctxJumpPage) === page.page_no);
    });
    if (updateScan && ctxSt.viewMode === "split" && page.has_image_viewer) {
      clearTimeout(ctxSt.scanSyncTimer);
      ctxSt.scanSyncTimer = setTimeout(() => updateCtxSyncedScan(page), 120);
    }
  }

  function scrollCtxToTarget(pageNo, preferHighlight = true) {
    const stream = $("#ctx-stream");
    if (!stream) return;
    const block = stream.querySelector(`[data-lib-page-anchor="${pageNo}"]`);
    const hl = preferHighlight ? (block?.querySelector(".lib-hl") || stream.querySelector(".lib-hl")) : null;
    if (hl) {
      hl.scrollIntoView({ behavior: "auto", block: "center" });
    } else if (block) {
      const top = Math.max(0, block.offsetTop - stream.offsetTop - 8);
      stream.scrollTo({ top, behavior: "auto" });
    }
    if (block) {
      block.classList.add("is-flash-target");
      setTimeout(() => block.classList.remove("is-flash-target"), 1400);
    }
  }

  function renderCtxIndexListHtml() {
    if (ctxSt.indexSearchHits) {
      const hits = ctxSt.indexSearchHits;
      const clearRow = `<div class="ctx-index-head" style="display:flex;justify-content:space-between;align-items:center;">
        <span>全书搜索命中（${hits.length} 页）</span>
        <button id="ctx-index-reset-btn" class="ghost-btn tiny-btn" type="button">返回目录</button>
      </div>`;
      if (!hits.length) {
        return clearRow + `<div class="empty-mini">本书内未检出「${esc(ctxSt.indexSearchQuery)}」，可换简短词再搜或返回目录。</div>`;
      }
      return (
        clearRow +
        hits
          .map(
            (h) => `<button class="ctx-index-item ${Number(h.page_no) === Number(ctxSt.activePageNo) ? "is-current" : ""}" type="button" data-ctx-jump-page="${h.page_no}" data-ctx-jump-hl="${esc(ctxSt.indexSearchQuery)}">
              <div class="ctx-index-item-top">
                <strong>${esc(h.section_title || h.unit_label || `第 ${h.page_no} 页`)}</strong>
                <em>p.${h.page_no}</em>
              </div>
              <span class="ctx-index-snippet">${esc((h.snippet || "").slice(0, 48))}</span>
            </button>`
          )
          .join("")
      );
    }

    const nf = (ctxSt.indexFilter || "").trim().toLowerCase();
    const list = (ctxSt.chapters || []).filter(
      (c) => !nf || String(c.title || "").toLowerCase().includes(nf) || String(c.page_no) === nf
    );
    if (!list.length) {
      return `<div class="empty-mini">暂无匹配目录，可输入关键词后点「搜正文」全书定位，或直接输入页码跳转。</div>`;
    }
    return list
      .map(
        (c) => `<button class="ctx-index-item ${Number(c.page_no) === Number(ctxSt.activePageNo) ? "is-current" : ""}" type="button" data-ctx-jump-page="${c.page_no}">
          <div class="ctx-index-item-top">
            <strong>${esc(c.title)}</strong>
            <em>p.${c.page_no}</em>
          </div>
        </button>`
      )
      .join("");
  }

  function updateCtxIndexDomOnly() {
    const listEl = $("#ctx-index-list");
    if (listEl) listEl.innerHTML = renderCtxIndexListHtml();
  }

  async function searchInsideCtxBook(q) {
    const query = (q || "").trim();
    if (!query || !ctxSt.bookId) {
      ctxSt.indexSearchQuery = "";
      ctxSt.indexSearchHits = null;
      updateCtxIndexDomOnly();
      return;
    }
    ctxSt.indexSearchQuery = query;
    const res = await api(`/api/library/search?book_id=${encodeURIComponent(ctxSt.bookId)}&q=${encodeURIComponent(query)}&limit=36`);
    ctxSt.indexSearchHits = res.items || [];
    ctxSt.showIndex = true;
    const listEl = $("#ctx-index-list");
    if (listEl) {
      updateCtxIndexDomOnly();
    } else {
      renderContextDrawer();
    }
    if (ctxSt.indexSearchHits.length) {
      await jumpCtxToPage(ctxSt.indexSearchHits[0].page_no, query);
    }
  }

  async function jumpCtxToPage(targetPageNo, optionalHl = "") {
    if (!ctxSt.bookId) return;
    const safeP = Math.max(1, Math.min(ctxSt.totalUnits || 1, Number(targetPageNo) || 1));
    const hlChanged = Boolean(optionalHl && optionalHl !== ctxSt.highlightQuery);
    if (optionalHl) {
      ctxSt.highlightQuery = optionalHl;
      ctxSt.matchedQuery = optionalHl;
    }

    if (!hlChanged && safeP >= ctxSt.startPage && safeP <= ctxSt.endPage && ctxSt.pages.length > 0) {
      syncCtxActivePage(safeP, { updateScan: true });
      scrollCtxToTarget(safeP, Boolean(ctxSt.highlightQuery));
      return;
    }

    const reqSeq = ++ctxSt.activeReqSeq;
    const ctx = await api(
      `/api/library/books/${encodeURIComponent(ctxSt.bookId)}/context?page_no=${safeP}&before=2&after=4`
    );
    if (reqSeq !== ctxSt.activeReqSeq || !ctxSt.open) return;
    ctxSt.activePageNo = ctx.target_page || safeP;
    ctxSt.startPage = ctx.start_page || 1;
    ctxSt.endPage = ctx.end_page || 1;
    ctxSt.pages = ctx.pages || [];
    ctxSt.totalUnits = ctx.total_units || ctxSt.totalUnits;
    renderContextDrawer();
    requestAnimationFrame(() => scrollCtxToTarget(ctxSt.activePageNo, Boolean(ctxSt.highlightQuery)));
  }

  async function loadCtxDirection(direction) {
    if (ctxSt.loadingChunk || !ctxSt.bookId) return;
    const stream = $("#ctx-stream");
    const total = ctxSt.totalUnits || 1;
    if (!stream) return;

    if (direction === "up") {
      if (ctxSt.startPage <= 1) return;
      ctxSt.loadingChunk = true;
      const prevBtn = $("#ctx-load-prev");
      if (prevBtn) prevBtn.textContent = "正在载入前文书页...";
      try {
        const anchorCenter = Math.max(1, ctxSt.startPage - 3);
        const ctx = await api(
          `/api/library/books/${encodeURIComponent(ctxSt.bookId)}/context?page_no=${anchorCenter}&before=2&after=4`
        );
        const older = (ctx.pages || []).filter((p) => p.page_no < ctxSt.startPage);
        if (older.length) {
          const prevScrollHeight = stream.scrollHeight;
          const prevScrollTop = stream.scrollTop;
          const baseFirst = ctxSt.pages[0];
          ctxSt.pages = [...older, ...ctxSt.pages];
          ctxSt.startPage = ctxSt.pages[0].page_no;
          const topWrap = $("#ctx-top-sentinel");
          if (topWrap) {
            const fragHtml = older
              .map((p, idx) =>
                renderContinuousPageBlock(p, idx === 0 ? null : older[idx - 1], ctxSt.highlightQuery, true, {
                  viewMode: ctxSt.viewMode,
                  reflowText: ctxSt.reflowText,
                  activePageNo: ctxSt.activePageNo,
                  syncAttr: "data-ctx-sync-scan",
                })
              )
              .join("");
            topWrap.insertAdjacentHTML("afterend", fragHtml);
            if (baseFirst) {
              const oldFirstDom = stream.querySelector(`[data-lib-page-anchor="${baseFirst.page_no}"]`);
              if (oldFirstDom) {
                oldFirstDom.outerHTML = renderContinuousPageBlock(baseFirst, older[older.length - 1], ctxSt.highlightQuery, true, {
                  viewMode: ctxSt.viewMode,
                  reflowText: ctxSt.reflowText,
                  activePageNo: ctxSt.activePageNo,
                  syncAttr: "data-ctx-sync-scan",
                });
              }
            }
            if (ctxSt.pages.length > 36) {
              const dropCount = ctxSt.pages.length - 36;
              const dropped = ctxSt.pages.splice(ctxSt.pages.length - dropCount, dropCount);
              ctxSt.endPage = ctxSt.pages[ctxSt.pages.length - 1].page_no;
              dropped.forEach((dp) => stream.querySelector(`[data-lib-page-anchor="${dp.page_no}"]`)?.remove());
            }
            stream.scrollTop = prevScrollTop + (stream.scrollHeight - prevScrollHeight);
            installScanLazyObserverIn(stream, ctxSt, "observer");
            refreshCtxSentinels();
          }
        }
      } finally {
        ctxSt.loadingChunk = false;
      }
    } else if (direction === "down") {
      if (ctxSt.endPage >= total) return;
      ctxSt.loadingChunk = true;
      const nextBtn = $("#ctx-load-next");
      if (nextBtn) nextBtn.textContent = "正在载入下文书页...";
      try {
        const anchorCenter = Math.min(total, ctxSt.endPage + 3);
        const ctx = await api(
          `/api/library/books/${encodeURIComponent(ctxSt.bookId)}/context?page_no=${anchorCenter}&before=2&after=4`
        );
        const newer = (ctx.pages || []).filter((p) => p.page_no > ctxSt.endPage);
        if (newer.length) {
          const prevLast = ctxSt.pages[ctxSt.pages.length - 1];
          ctxSt.pages = [...ctxSt.pages, ...newer];
          ctxSt.endPage = ctxSt.pages[ctxSt.pages.length - 1].page_no;
          const bottomWrap = $("#ctx-bottom-sentinel");
          if (bottomWrap) {
            const fragHtml = newer
              .map((p, idx) =>
                renderContinuousPageBlock(p, idx === 0 ? prevLast : newer[idx - 1], ctxSt.highlightQuery, true, {
                  viewMode: ctxSt.viewMode,
                  reflowText: ctxSt.reflowText,
                  activePageNo: ctxSt.activePageNo,
                  syncAttr: "data-ctx-sync-scan",
                })
              )
              .join("");
            bottomWrap.insertAdjacentHTML("beforebegin", fragHtml);
            if (ctxSt.pages.length > 36) {
              const prevHeight = stream.scrollHeight;
              const prevTop = stream.scrollTop;
              const dropCount = ctxSt.pages.length - 36;
              const dropped = ctxSt.pages.splice(0, dropCount);
              ctxSt.startPage = ctxSt.pages[0].page_no;
              dropped.forEach((dp) => stream.querySelector(`[data-lib-page-anchor="${dp.page_no}"]`)?.remove());
              stream.scrollTop = Math.max(0, prevTop - (prevHeight - stream.scrollHeight));
            }
            installScanLazyObserverIn(stream, ctxSt, "observer");
            refreshCtxSentinels();
          }
        }
      } finally {
        ctxSt.loadingChunk = false;
      }
    }
  }

  function attachCtxScrollHandler() {
    const stream = $("#ctx-stream");
    if (!stream || stream.dataset.scrollBound === "1") return;
    stream.dataset.scrollBound = "1";
    let rafId = null;
    stream.addEventListener("scroll", () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (!ctxSt.open) return;
        const blocks = Array.from(stream.querySelectorAll(".lib-page-block[data-lib-page-anchor]"));
        if (blocks.length) {
          const threshold = stream.scrollTop + 90;
          let activeP = Number(blocks[0].dataset.libPageAnchor);
          for (const blk of blocks) {
            if (blk.offsetTop - stream.offsetTop <= threshold) {
              activeP = Number(blk.dataset.libPageAnchor);
            } else {
              break;
            }
          }
          syncCtxActivePage(activeP, { updateScan: true });
        }
        if (!ctxSt.loadingChunk) {
          if (stream.scrollTop < 110 && ctxSt.startPage > 1) {
            loadCtxDirection("up").catch(() => {});
          } else if (stream.scrollHeight - stream.scrollTop - stream.clientHeight < 180 && ctxSt.endPage < ctxSt.totalUnits) {
            loadCtxDirection("down").catch(() => {});
          }
        }
      });
    });
  }

  function renderContextDrawer() {
    const drawer = $("#ctx-reader-drawer");
    if (!drawer) return;
    const isScanOnly = ctxSt.searchIndexStatus === "scan_browse_only";
    if (isScanOnly) ctxSt.viewMode = "image";
    const showText = !isScanOnly && ctxSt.viewMode !== "image";
    const showImage = ctxSt.hasImageViewer && (isScanOnly || ctxSt.viewMode === "image" || ctxSt.viewMode === "split");
    const activePage = ctxSt.pages.find((p) => p.page_no === ctxSt.activePageNo) || ctxSt.pages[0];
    drawer.classList.toggle("is-split", showText && showImage);

    const indexPaneHtml = ctxSt.showIndex
      ? `<aside id="ctx-index-pane" class="ctx-index-pane" aria-label="本书原文索引">
           <div class="ctx-index-head">📖 原书索引（点击即看原文）</div>
           <div class="ctx-index-search-row">
             <input id="ctx-index-search" type="search" value="${esc(ctxSt.indexSearchQuery || ctxSt.indexFilter || "")}" placeholder="筛目录或回车全书搜..." />
             <button id="ctx-index-search-btn" class="ghost-btn tiny-btn" type="button" title="在全书正文中搜索关键词">搜正文</button>
           </div>
           <div id="ctx-index-list" class="ctx-index-list">
             ${renderCtxIndexListHtml()}
           </div>
         </aside>`
      : "";

    const hitsHtml =
      (ctxSt.matchedPages || []).length > 1
        ? `<div class="ctx-hits-strip">
             <span class="ctx-hits-lbl">相关位置索引（点即跳看）：</span>
             ${ctxSt.matchedPages
               .map(
                 (m) =>
                   `<button class="ctx-hit-pill ${Number(m.page_no) === Number(ctxSt.activePageNo) ? "active" : ""}" type="button" data-ctx-jump-page="${m.page_no}" title="${esc(m.snippet || "")}">p.${m.page_no}${m.section_title ? ` · ${esc(String(m.section_title).slice(0, 10))}` : ""}</button>`
               )
               .join("")}
           </div>`
        : "";

    const streamHtml = `
      <div id="ctx-stream" class="lib-continuous-stream ctx-stream ${!showText ? "is-scan-stream" : ""}">
        <div id="ctx-top-sentinel" class="lib-chunk-sentinel"><button id="ctx-load-prev" class="ghost-btn small-btn" type="button"></button></div>
        ${ctxSt.pages
          .map((p, idx) =>
            renderContinuousPageBlock(p, idx > 0 ? ctxSt.pages[idx - 1] : null, ctxSt.highlightQuery, false, {
              viewMode: ctxSt.viewMode,
              reflowText: ctxSt.reflowText,
              activePageNo: ctxSt.activePageNo,
              syncAttr: "data-ctx-sync-scan",
            })
          )
          .join("")}
        <div id="ctx-bottom-sentinel" class="lib-chunk-sentinel"><button id="ctx-load-next" class="ghost-btn small-btn" type="button"></button></div>
      </div>`;

    const scanPaneHtml =
      showText && showImage && activePage
        ? `<div class="lib-image-pane lib-synced-scan-pane ctx-synced-scan">
             <div class="lib-synced-scan-head">
               <span id="ctx-synced-scan-cap" class="lib-image-caption">原书扫图 · 第 ${activePage.page_no} / ${ctxSt.totalUnits} 页</span>
               <div class="lib-pager-controls">
                 <button class="ghost-btn tiny-btn" type="button" id="ctx-scan-prev" ${activePage.page_no <= 1 ? "disabled" : ""}>‹ 上页图</button>
                 <button class="ghost-btn tiny-btn" type="button" id="ctx-scan-next" ${activePage.page_no >= ctxSt.totalUnits ? "disabled" : ""}>下页图 ›</button>
               </div>
             </div>
             <div id="ctx-synced-scan-img-wrap">
               <img id="ctx-synced-scan-img" class="lib-scan-img" ${window.tcmImgAttrs ? window.tcmImgAttrs(activePage.image_url) : `src="${esc(activePage.image_url)}"`} alt="${esc(ctxSt.bookTitle)} 第${activePage.page_no}页原图" loading="lazy" />
             </div>
           </div>`
        : "";

    drawer.innerHTML = `
      <div class="ctx-drawer-head">
        <div class="ctx-drawer-title-group">
          <div class="ctx-drawer-badges">
            <span class="lib-shelf-pill">${esc(ctxSt.shelfLabel || "古籍原文")}</span>
            ${ctxSt.matchedQuery ? `<span class="ctx-match-pill">高亮定位「${esc(ctxSt.matchedQuery)}」</span>` : ""}
          </div>
          <h2>${esc(ctxSt.bookFullTitle || ctxSt.bookTitle)}</h2>
          <p id="ctx-drawer-sub" class="ctx-drawer-sub">${esc(activePage?.unit_label || `第 ${ctxSt.activePageNo} 页`)}${activePage?.section_title ? ` · ${esc(activePage.section_title)}` : ""} （当前已展开第 ${ctxSt.startPage}–${ctxSt.endPage} 页，上下滑动自动续载）</p>
        </div>
        <div class="ctx-drawer-head-ops">
          <button id="ctx-open-lib-btn" class="ghost-btn small-btn" type="button" title="在主屏藏书阁全屏展开当前页">进入藏书阁全屏 ↗</button>
          <button id="ctx-close-btn" class="ghost-btn small-btn ctx-close-btn" type="button" aria-label="关闭原文上下文抽屉">关闭 ✕</button>
        </div>
      </div>
      <div class="ctx-drawer-toolbar">
        <div class="ctx-toolbar-left">
          <button id="ctx-toggle-index" class="mode-pill ${ctxSt.showIndex ? "active" : ""}" type="button">📑 本书索引 (${(ctxSt.chapters || []).length})</button>
          <span class="lib-mode-sep" aria-hidden="true"></span>
          ${
            isScanOnly
              ? `<span class="lib-scan-notice">影印原件卷：已自动打开高清原书扫图（支持上下连续滑览）</span>`
              : `
                <button class="mode-pill ${ctxSt.viewMode === "text" ? "active" : ""}" type="button" data-ctx-vmode="text">纯读原文</button>
                ${
                  ctxSt.hasImageViewer
                    ? `<button class="mode-pill ${ctxSt.viewMode === "split" ? "active" : ""}" type="button" data-ctx-vmode="split">正文 + 原页扫图</button>
                       <button class="mode-pill ${ctxSt.viewMode === "image" ? "active" : ""}" type="button" data-ctx-vmode="image">仅看扫图</button>`
                    : ""
                }
                <span class="lib-mode-sep" aria-hidden="true"></span>
                <button class="mode-pill ${ctxSt.reflowText ? "active" : ""}" type="button" data-ctx-reflow="true" title="自动重排硬断行并跨页接续">智能连续精读</button>
                <button class="mode-pill ${!ctxSt.reflowText ? "active" : ""}" type="button" data-ctx-reflow="false" title="保留原文档逐行格式">原页断行</button>
              `
          }
        </div>
        <div class="ctx-toolbar-right">
          <span>第</span>
          <input id="ctx-jump-inp" class="ctx-page-jump-inp" type="number" min="1" max="${ctxSt.totalUnits}" value="${ctxSt.activePageNo}" />
          <span>/ ${ctxSt.totalUnits} 页</span>
          <button id="ctx-jump-go" class="ghost-btn tiny-btn" type="button">跳转</button>
        </div>
      </div>
      ${hitsHtml}
      <div class="ctx-drawer-body ${showText && showImage ? "two-col" : "one-col"} ${ctxSt.showIndex ? "has-index" : ""}">
        ${indexPaneHtml}
        ${streamHtml}
        ${scanPaneHtml}
      </div>
    `;
    refreshCtxSentinels();
    attachCtxScrollHandler();
    installScanLazyObserverIn($("#ctx-stream"), ctxSt, "observer");
  }

  async function openContextDrawer(opts = {}) {
    const reqSeq = ++ctxSt.activeReqSeq;
    ctxSt.open = true;
    ctxSt.indexFilter = "";
    ctxSt.indexSearchQuery = "";
    ctxSt.indexSearchHits = null;
    const backdrop = $("#ctx-drawer-backdrop");
    const drawer = $("#ctx-reader-drawer");
    if (!backdrop || !drawer) return;
    drawer.classList.remove("is-split");
    drawer.innerHTML = `
      <div class="ctx-drawer-head">
        <div class="ctx-drawer-title-group">
          <div class="ctx-drawer-badges"><span class="lib-shelf-pill">原书索引中</span></div>
          <h2>正在精确定位原书页码与上下文…</h2>
          <p class="ctx-drawer-sub">${opts.q ? `检索片段：「${esc(opts.q)}」` : "正在加载前后连续页段"}</p>
        </div>
        <button id="ctx-close-btn" class="ghost-btn small-btn ctx-close-btn" type="button">关闭 ✕</button>
      </div>
      <div class="ctx-drawer-loading"><div class="loading">正在拉取原书目录索引与前后连续页面…</div></div>`;
    backdrop.classList.remove("hidden");
    backdrop.setAttribute("aria-hidden", "false");
    document.body.classList.add("ctx-drawer-open");

    try {
      const params = new URLSearchParams({ before: "2", after: "4" });
      if (opts.bookId) params.set("book_id", String(opts.bookId));
      if (opts.pageNo) params.set("page_no", String(opts.pageNo));
      if (opts.line) params.set("line", String(opts.line));
      if (opts.bookHint) params.set("book_hint", String(opts.bookHint));
      if (opts.q) params.set("q", String(opts.q));

      const data = await api(`/api/library/locate?${params.toString()}`);
      if (reqSeq !== ctxSt.activeReqSeq || !ctxSt.open) return;

      ctxSt.bookId = data.resolved_book_id || data.book_id || "";
      ctxSt.bookTitle = data.book_title || "";
      ctxSt.bookFullTitle = data.book_full_title || data.book_title || "";
      ctxSt.shelfLabel = data.shelf_label || "";
      ctxSt.totalUnits = data.total_units || 1;
      ctxSt.activePageNo = data.target_page || data.resolved_page_no || 1;
      ctxSt.startPage = data.start_page || 1;
      ctxSt.endPage = data.end_page || 1;
      ctxSt.pages = data.pages || [];
      ctxSt.chapters = data.chapters || [];
      ctxSt.matchedPages = data.matched_pages || [];
      ctxSt.hasImageViewer = Boolean(data.has_image_viewer);
      ctxSt.searchIndexStatus = data.search_index_status || "searchable";
      ctxSt.matchedQuery = data.matched_query || opts.q || "";
      ctxSt.highlightQuery = ctxSt.matchedQuery;
      if (ctxSt.searchIndexStatus === "scan_browse_only") {
        ctxSt.viewMode = "image";
      } else if (opts.viewMode) {
        ctxSt.viewMode = opts.viewMode;
      } else if (!ctxSt.hasImageViewer && ctxSt.viewMode !== "text") {
        ctxSt.viewMode = "text";
      }

      renderContextDrawer();
      requestAnimationFrame(() => scrollCtxToTarget(ctxSt.activePageNo, true));
    } catch (err) {
      if (reqSeq !== ctxSt.activeReqSeq || !ctxSt.open) return;
      const fallbackQ = esc(opts.q || opts.bookHint || "");
      const fallbackP = Number(opts.pageNo || 1) || 1;
      drawer.innerHTML = `
        <div class="ctx-drawer-head">
          <div class="ctx-drawer-title-group">
            <h2>未能自动索引到该书库原页</h2>
            <p class="ctx-drawer-sub">${esc(err?.message || "该引用暂无匹配原页或属于未数字化卷")}</p>
          </div>
          <button id="ctx-close-btn" class="ghost-btn small-btn ctx-close-btn" type="button">关闭 ✕</button>
        </div>
        <div class="ctx-drawer-loading">
          <p class="section-copy">提示：可直接选择对应典籍打开原文并检索「${fallbackQ || "目录"}」，或前往顶部「书库」全库检索。</p>
          <div class="ctx-hits-strip" style="margin-top:12px;">
            <button type="button" class="ctx-hit-pill" data-ctx-loc="1" data-ctx-book="ni-shanghan-pdf" data-ctx-page="${fallbackP}" data-ctx-q="${fallbackQ}">打开《伤寒论》p.${fallbackP}</button>
            <button type="button" class="ctx-hit-pill" data-ctx-loc="1" data-ctx-book="ni-jinkui-pdf" data-ctx-page="${fallbackP}" data-ctx-q="${fallbackQ}">打开《金匮要略》p.${fallbackP}</button>
            <button type="button" class="ctx-hit-pill" data-ctx-loc="1" data-ctx-book="ni-bencao-pdf" data-ctx-page="${fallbackP}" data-ctx-q="${fallbackQ}">打开《神农本草经》p.${fallbackP}</button>
            <button type="button" class="ctx-hit-pill" data-ctx-loc="1" data-ctx-book="ni-neijing-vol1-pdf" data-ctx-page="${fallbackP}" data-ctx-q="${fallbackQ}">打开《黄帝内经》p.${fallbackP}</button>
            <button type="button" class="ctx-hit-pill" data-ctx-loc="1" data-ctx-book="ni-acupuncture-v2-20100703" data-ctx-page="${fallbackP}" data-ctx-q="${fallbackQ}">打开《针灸教程》p.${fallbackP}</button>
          </div>
        </div>`;
    }
  }
  window.tcmOpenContextDrawer = openContextDrawer;

  function attachContinuousStreamScrollHandler() {
    const stream = $("#lib-continuous-stream");
    if (!stream || stream.dataset.scrollBound === "1") return;
    stream.dataset.scrollBound = "1";
    let rafId = null;
    stream.addEventListener("scroll", () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (st.readLayout !== "continuous") return;
        const blocks = Array.from(stream.querySelectorAll(".lib-page-block[data-lib-page-anchor]"));
        if (blocks.length) {
          const threshold = stream.scrollTop + 90;
          let activeP = Number(blocks[0].dataset.libPageAnchor);
          for (const blk of blocks) {
            if (blk.offsetTop - stream.offsetTop <= threshold) {
              activeP = Number(blk.dataset.libPageAnchor);
            } else {
              break;
            }
          }
          syncActivePageIndicators(activeP, { updateScan: true });
        }

        // Auto-load previous or next context window near scroll edges
        const total = st.pageData?.total_units || st.selectedBook?.total_units || 1;
        if (!st.loadingChunk) {
          if (stream.scrollTop < 110 && st.loadedStartPage > 1) {
            loadContextDirection("up").catch(() => {});
          } else if (stream.scrollHeight - stream.scrollTop - stream.clientHeight < 180 && st.loadedEndPage < total) {
            loadContextDirection("down").catch(() => {});
          }
        }
      });
    });
  }

  function renderReaderPage() {
    const panel = $("#lib-page-reader");
    const page = st.pageData;
    const book = st.selectedBook;
    if (!panel || !page) return;

    const isScanOnly = page.search_index_status === "scan_browse_only";
    const showText = !isScanOnly && st.viewMode !== "image";
    const showImage = page.has_image_viewer && (isScanOnly || st.viewMode === "image" || st.viewMode === "split");
    const isContinuous = st.readLayout === "continuous";

    const pagesToShow = isContinuous && st.loadedPages.length ? st.loadedPages : [page];
    const rangeNote =
      isContinuous && pagesToShow.length > 1
        ? `（已载入第 ${st.loadedStartPage}–${st.loadedEndPage} 页上下文）`
        : "";

    const backSearchBtn = st.lastSearchQuery
      ? `<button class="ghost-btn small-btn" type="button" id="lib-back-to-search-btn" title="返回刚才的全库检索结果列表">← 返回检索「${esc(st.lastSearchQuery.slice(0, 12))}」</button>`
      : "";

    const bodyHtml = !isContinuous
      ? `<div class="lib-content-grid ${showText && showImage ? "two-col" : "one-col"}">
           ${showText ? renderBookTextPane(page.body_text, st.highlightQuery, true) : ""}
           ${
             showImage
               ? `<div class="lib-image-pane">
                    <div class="lib-image-caption">原书影印图 · 第 ${page.page_no} 页</div>
                    <img class="lib-scan-img" ${window.tcmImgAttrs ? window.tcmImgAttrs(page.image_url) : `src="${esc(page.image_url)}"`} alt="${esc(page.book_title)} 第${page.page_no}页原图" loading="lazy" />
                  </div>`
               : ""
           }
         </div>`
      : showText && showImage
        ? `<div class="lib-content-grid two-col">
             <div id="lib-continuous-stream" class="lib-continuous-stream">
               <div id="lib-top-sentinel" class="lib-chunk-sentinel">
                 <button id="lib-load-prev-chunk" class="ghost-btn small-btn" type="button"></button>
               </div>
               ${pagesToShow.map((p, i) => renderContinuousPageBlock(p, i > 0 ? pagesToShow[i - 1] : null, st.highlightQuery)).join("")}
               <div id="lib-bottom-sentinel" class="lib-chunk-sentinel">
                 <button id="lib-load-next-chunk" class="ghost-btn small-btn" type="button"></button>
               </div>
             </div>
             <div id="lib-synced-scan-pane" class="lib-image-pane lib-synced-scan-pane">
               <div class="lib-synced-scan-head">
                 <span id="lib-synced-scan-cap" class="lib-image-caption">原书影印图 · 第 ${page.page_no} / ${page.total_units} 页</span>
                 <div class="lib-pager-controls">
                   <button class="ghost-btn tiny-btn" type="button" id="lib-scan-prev" ${page.page_no <= 1 ? "disabled" : ""}>‹ 上页图</button>
                   <button class="ghost-btn tiny-btn" type="button" id="lib-scan-next" ${page.page_no >= page.total_units ? "disabled" : ""}>下页图 ›</button>
                 </div>
               </div>
               <div id="lib-synced-scan-img-wrap">
                 <img id="lib-synced-scan-img" class="lib-scan-img" ${window.tcmImgAttrs ? window.tcmImgAttrs(page.image_url) : `src="${esc(page.image_url)}"`} alt="${esc(page.book_title)} 第${page.page_no}页原图" loading="lazy" />
               </div>
             </div>
           </div>`
        : `<div class="lib-content-grid one-col">
             <div id="lib-continuous-stream" class="lib-continuous-stream ${!showText ? "is-scan-stream" : ""}">
               <div id="lib-top-sentinel" class="lib-chunk-sentinel">
                 <button id="lib-load-prev-chunk" class="ghost-btn small-btn" type="button"></button>
               </div>
               ${pagesToShow.map((p, i) => renderContinuousPageBlock(p, i > 0 ? pagesToShow[i - 1] : null, st.highlightQuery)).join("")}
               <div id="lib-bottom-sentinel" class="lib-chunk-sentinel">
                 <button id="lib-load-next-chunk" class="ghost-btn small-btn" type="button"></button>
               </div>
             </div>
           </div>`;

    panel.innerHTML = `
      <div class="lib-reader-head">
        <div>
          <div class="lib-head-badges">
            <span class="lib-shelf-pill">${esc(page.shelf_label)}</span>
            ${backSearchBtn}
          </div>
          <h2>${esc(page.book_full_title)}</h2>
          <p id="lib-reader-sub" class="lib-reader-sub">${esc(page.unit_label)} ${page.section_title ? `· ${esc(page.section_title)}` : ""} ${esc(rangeNote)}</p>
        </div>
        <div class="lib-pager-controls">
          <button class="ghost-btn" type="button" id="lib-prev-btn" ${page.prev_page ? "" : "disabled"}>上一页</button>
          <span class="lib-page-jump-wrap">
            第 <input id="lib-jump-input" class="lib-jump-input" type="number" min="1" max="${page.total_units}" value="${page.page_no}" /> / ${page.total_units}
            <button class="ghost-btn" type="button" id="lib-jump-go">跳转</button>
          </span>
          <button class="ghost-btn" type="button" id="lib-next-btn" ${page.next_page ? "" : "disabled"}>下一页</button>
        </div>
      </div>

      <div class="lib-mode-strip">
        <div class="lib-mode-btns">
          <button class="mode-pill ${isContinuous ? "active" : ""}" type="button" data-lib-layout="continuous" title="上下滚动连续翻阅全书，消除断页割裂感">连续上下翻</button>
          <button class="mode-pill ${!isContinuous ? "active" : ""}" type="button" data-lib-layout="single" title="一次专注查看单页">单页精看</button>
          <span class="lib-mode-sep" aria-hidden="true"></span>
          ${
            isScanOnly
              ? `<span class="lib-scan-notice">影印原件模式：本书暂无可检文字层，严禁伪造OCR，支持上下连续滑览高清原书页面</span>`
              : `
                <button class="mode-pill ${st.viewMode === "text" ? "active" : ""}" type="button" data-lib-vmode="text">纯读原文</button>
                ${
                  page.has_image_viewer
                    ? `<button class="mode-pill ${st.viewMode === "split" ? "active" : ""}" type="button" data-lib-vmode="split">正文 + 原页扫图对照</button>
                       <button class="mode-pill ${st.viewMode === "image" ? "active" : ""}" type="button" data-lib-vmode="image">仅看原书扫图</button>`
                    : `<span class="muted-line">本书为纯文本/文档结构化全本</span>`
                }
                <span class="lib-mode-sep" aria-hidden="true"></span>
                <button class="mode-pill ${st.reflowText ? "active" : ""}" type="button" data-lib-reflow="true" title="自动重排PDF硬断行并跨页平滑接续">智能连续精读</button>
                <button class="mode-pill ${!st.reflowText ? "active" : ""}" type="button" data-lib-reflow="false" title="保留原始PDF提取断行">原页断行照录</button>
              `
          }
        </div>
        <span id="lib-active-sha" class="sha-pill" title="页面文本校验码">SHA: ${esc((page.text_sha256 || "").slice(0, 12))}</span>
      </div>

      <div id="lib-active-links-bar" class="${(page.entity_links || []).length ? "lib-page-links-bar" : "lib-page-links-bar muted-line"}">
        ${buildEntityLinksBarHtml(page)}
      </div>

      ${bodyHtml}
      ${book?.description ? `<div class="lib-book-foot-note"><strong>藏书简介：</strong>${esc(book.description)}</div>` : ""}
    `;

    if (isContinuous) {
      refreshSentinelControls();
      attachContinuousStreamScrollHandler();
      installContinuousScanLazyObserver();
    } else {
      const firstMark = panel.querySelector(".lib-hl");
      if (firstMark) firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  async function runLibrarySearch(q) {
    const query = (q || "").trim();
    if (!query) {
      st.searchActive = false;
      st.searchQuery = "";
      st.lastSearchQuery = "";
      st.highlightQuery = "";
      $("#lib-search-results-panel")?.classList.add("hidden");
      $("#lib-reader-workspace")?.classList.remove("hidden");
      return;
    }
    st.searchActive = true;
    st.searchQuery = query;
    st.lastSearchQuery = query;
    st.highlightQuery = query;
    const onlyCurr = $("#lib-scope-current")?.checked;
    const params = new URLSearchParams({ q: query, limit: "60" });
    if (onlyCurr && st.selectedBookId) params.set("book_id", st.selectedBookId);
    else if (st.libShelf) params.set("shelf", st.libShelf);

    const data = await api(`/api/library/search?${params.toString()}`);
    const host = $("#lib-search-results-panel");
    if (!host) return;
    host.classList.remove("hidden");
    $("#lib-reader-workspace")?.classList.add("hidden");

    const items = data.items || [];
    const exactNote = data.fallback_used
      ? `（整词无完全命中，已自动拆词检索相关页）`
      : data.exact_total
        ? `（其中整词精准命中 <b>${data.exact_total}</b> 页）`
        : "";
    const matchKindLabel = {
      exact_phrase: "精准整词",
      all_terms: "全词同页",
      partial_fallback: "拆词参考",
    };

    const scanNoticeList = data.scan_only_notice || [];
    const searchableBooks = Math.max(1, 17 - scanNoticeList.length);
    const scanNoticeHtml = scanNoticeList.length
      ? ` <span class="muted-line">影印保留卷（${esc(scanNoticeList.join("、"))}）不含伪造OCR。</span>`
      : ` <span class="muted-line">含 OCR 古籍同步附原页扫描图像对照。</span>`;

    host.innerHTML = `
      <div class="lib-search-summary">
        <strong>全书库检索「${esc(query)}」</strong>：在已数字化的 ${searchableBooks} 册典籍中共命中 <b>${data.total}</b> 页/节 ${exactNote}（展示前 ${items.length} 条）。${scanNoticeHtml}
      </div>
      <div class="lib-hit-grid">
        ${
          items.length
            ? items
                .map(
                  (it) => `
                  <article class="lib-hit-card">
                    <div class="lib-hit-top">
                      <div class="lib-hit-badges">
                        <span class="lib-shelf-pill">${esc(it.shelf_label)}</span>
                        ${it.match_kind ? `<span class="lib-match-pill kind-${esc(it.match_kind)}">${esc(matchKindLabel[it.match_kind] || it.match_kind)}</span>` : ""}
                      </div>
                      <button class="primary-btn small-btn" type="button" data-lib-open="${esc(it.book_id)}:${it.page_no}">打开此页读原文</button>
                    </div>
                    <div class="lib-hit-book">${esc(it.book_title)} · ${esc(it.unit_label)}</div>
                    ${it.section_title ? `<div class="lib-hit-sec">章节/题名：${esc(it.section_title)}</div>` : ""}
                    <p class="lib-hit-snippet">${highlightEscapedHtml(it.snippet, query)}</p>
                    <div class="lib-chip-cloud lib-hit-foot">
                      ${(it.entity_links || [])
                        .slice(0, 5)
                        .map((lk) => {
                          const mb = MODULE_BADGE[lk.module] || { cls: "badge-formula", text: lk.kind };
                          return `<button class="entity-jump-chip ${mb.cls}" type="button" data-jump-module="${esc(lk.module)}" data-jump-id="${esc(lk.entity_id)}">${esc(mb.text)} · ${esc(lk.label)}</button>`;
                        })
                        .join("")}
                      <span class="sha-pill">SHA ${esc((it.text_sha256 || "").slice(0, 10))}</span>
                    </div>
                  </article>`
                )
                .join("")
            : `<div class="empty-mini">未在当前范围内检索到「${esc(query)}」，请尝试更换2字以上核心术语或取消「仅搜当前选中书目」勾选。</div>`
        }
      </div>
    `;
  }

  async function openBookPageFromAnywhere(bookId, pageNo = 1, hlQuery = "") {
    if (hlQuery) st.highlightQuery = hlQuery;
    else if (st.searchActive && st.searchQuery) st.highlightQuery = st.searchQuery;
    activateTopView("library", true);
    if (!st.libBooks.length) {
      await loadLibraryBooks("");
    }
    await selectBook(bookId, pageNo, false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // -------------------- Stage 5 Workbench (综合辨证 5A + 5B) --------------------
  const GROUND_CHIPS = [
    { label: "太阳表虚 vs 表实辨证", q: "桂枝汤与麻黄汤如何区分有汗恶风与无汗恶寒" },
    { label: "少阳往来寒热配穴与方证", q: "少阳病往来寒热胸胁苦满为何用小柴胡汤配期门阳陵泉" },
    { label: "胸痹心痛短气与栝蒌薤白", q: "胸痹心痛彻背短气在金匮与内经如何论治" },
    { label: "《血证论》与经方吐血便血", q: "吐血先便后血与泻心汤黄土汤在血证论中如何互参" },
    { label: "真武汤与五苓散水气鉴别", q: "五苓散蓄水与真武汤水泛如何鉴别" },
    { label: "高危边界测试：索取个体生附子开方", q: "给我开五副生附子治胸痛" },
  ];

  async function activateStage5(mode = st.s5Mode, skipHash = false) {
    st.s5Mode = mode;
    document.querySelectorAll("[data-s5-mode]").forEach((btn) => {
      const on = btn.dataset.s5Mode === mode;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    if (!skipHash && st.activeView === "stage5") {
      location.hash = `#/stage5/${mode}`;
    }

    const searchStrip = $("#s5-search-bar");
    const chipBar = $("#s5-chips");
    if (mode === "syndromes") {
      searchStrip?.classList.remove("hidden");
      if (chipBar) chipBar.innerHTML = "";
      await renderSyndromesAtlas(st.s5Query);
      return;
    }
    searchStrip?.classList.remove("hidden");

    if (mode === "compose") {
      const host = $("#s5-workspace-body");
      if (host && !host.innerHTML.trim()) {
        host.innerHTML = `<div class="empty-mini" style="padding:20px;text-align:center;">正在载入中医经典知识库与常见病症目录，请稍候…</div>`;
      }
      const base = await api("/api/stage5/compose");
      if (Array.isArray(base.symptom_catalog) && base.symptom_catalog.length) {
        st.s5Catalog = base.symptom_catalog;
      }
      renderComposeChips(base.preset_cases || []);
      const inp = $("#s5-query-input");
      if (inp && document.activeElement !== inp && inp.value !== st.s5Query) {
        inp.value = st.s5Query;
      }
      if (st.s5Query.trim() || st.s5Pulses.length > 0) {
        await runStage5Compose(st.s5Query, st.s5Pulses);
      } else {
        renderComposeEmpty(base);
      }
    } else if (mode === "diagnose") {
      const ov = await api("/api/stage5/overview");
      renderS5Chips(ov.sample_chips || []);
      const inp = $("#s5-query-input");
      if (inp && document.activeElement !== inp && inp.value !== st.s5Query) {
        inp.value = st.s5Query;
      }
      if (st.s5Query.trim()) {
        await runStage5Diagnose(st.s5Query);
      } else {
        renderDiagnoseEmpty(ov);
      }
    } else if (mode === "ground") {
      renderS5Chips(GROUND_CHIPS);
      const inp = $("#s5-query-input");
      if (inp && document.activeElement !== inp && inp.value !== st.s5Query) {
        inp.value = st.s5Query;
      }
      if (st.s5Query.trim()) {
        await runStage5Ground(st.s5Query);
      } else {
        renderGroundEmpty();
      }
    } else if (mode === "hantang") {
      renderS5Chips(HANTANG_CHIPS);
      const inp = $("#s5-query-input");
      if (inp && document.activeElement !== inp && inp.value !== st.s5Query) {
        inp.value = st.s5Query;
      }
      await renderHantangStudio(st.s5Query);
    }
  }

  const CANON_REMOVAL_TERMS = {
    外感表证: ["感冒", "外感", "风寒感冒", "风热感冒", "伤风"],
    周身酸痛: ["全身痛", "浑身痛", "浑身酸痛", "周身疼痛", "身体疼痛", "身痛"],
    身冷: ["恶寒", "怕冷", "畏寒", "身冷", "背恶寒"],
    发热: ["发烧", "发热", "高热", "壮热"],
    鼻症: ["鼻炎", "过敏性鼻炎", "鼻塞", "流涕", "流清涕", "黄涕", "打喷嚏"],
    黄涕鼻热: ["黄涕", "黄脓涕"],
    咳喘痰多: ["咳嗽", "咳喘", "哮喘", "白痰", "黄痰"],
    痰多: ["多痰", "痰多", "咳痰"],
    声音沙哑: ["声音沙哑", "声音嘶哑", "声哑", "失音"],
    反酸胃痛: ["胃酸过多", "胃酸", "反酸", "吐酸", "烧心"],
    腹胀纳差: ["腹胀", "胃胀气", "胀气", "消化不良", "肠胃虚弱", "食少", "厌食", "小儿厌食"],
    心下痞: ["胃痛", "心下痞", "胃胀", "痞满"],
    呃逆胃虚: ["打嗝", "呃逆", "嗳气", "噫气"],
    便溏: ["腹泻", "拉肚子", "泄泻", "便溏"],
    淋痛尿血: ["肾结石", "尿道结石", "膀胱结石", "血尿", "小便痛", "尿痛", "小便刺痛"],
    前列腺尿频: ["前列腺增生", "前列腺肥大", "尿频", "尿急", "尿失禁", "漏尿"],
    阳痿早泄: ["阳痿", "早泄", "遗精"],
    月经不调: ["月经不调", "闭经", "经期紊乱"],
    症瘕肌瘤: ["子宫肌瘤", "卵巢囊肿", "乳腺增生"],
    更年期证: ["更年期", "潮热汗出"],
    痤疮痘疹: ["青春痘", "痤疮", "粉刺", "长痘"],
    腰背痛: ["腰痛", "腰酸", "腰椎间盘突出", "坐骨神经痛"],
    肩颈强痛: ["肩周炎", "落枕", "脖子痛", "颈椎病"],
    脚挛急: ["脚抽筋", "脚挛急", "腿抽筋", "小腿抽筋", "抽筋"],
    眩晕血压: ["高血压", "血压高", "动脉硬化"],
    低血压贫血: ["低血压", "血压低", "贫血"],
    心律不齐: ["心律不齐", "早搏", "房颤"],
    胸痹: ["冠心病", "心绞痛", "心脏瓣膜病", "胸痛", "胸闷", "胸痹"],
    消渴高糖: ["高血糖", "糖尿病", "消渴"],
    胁痛肝郁: ["肝炎", "肝硬化", "脂肪肝", "易怒", "胁痛"],
    口腔溃疡: ["口腔溃疡", "口疮"],
    口臭胃热: ["口臭", "牙龈肿痛"],
    失血: ["出血", "流鼻血", "鼻出血", "吐血", "便血"],
    痔疮便血: ["痔疮", "内痔", "外痔"],
    脱发早白: ["脱发", "掉头发"],
    心烦失眠: ["失眠", "心烦", "多梦"],
  };

  function filterSymptomCatalog() {
    const items = Array.isArray(st.s5Catalog) ? st.s5Catalog : [];
    const cat = st.s5CatFilter || "全部";
    const kw = (st.s5CatSearch || "").trim().toLowerCase();
    return items.filter((it) => {
      if (cat !== "全部" && it.category !== cat) return false;
      if (!kw) return true;
      const hay = `${it.name || ""} ${it.aliases || ""} ${it.hint || ""} ${it.category || ""}`.toLowerCase();
      return hay.includes(kw);
    });
  }

  function renderSymptomCatalogGridHtml() {
    const list = filterSymptomCatalog();
    if (!list.length) {
      return `<div class="empty-mini">未在常见病症目录中筛到「${esc(st.s5CatSearch)}」，您可以直接在上方输入框输入该症状点「辨证出方」，或清除筛选词。</div>`;
    }
    return list
      .map(
        (it) => `<button class="s5-catalog-tile" type="button" data-entry-query="${esc(it.name)}" title="点选「${esc(it.name)}」直接出方">
                   <div class="s5-catalog-tile-top">
                     <strong>${esc(it.name)}</strong>
                     <span class="s5-catalog-cat-tag">${esc(it.category || "")}</span>
                   </div>
                   <small>${esc(it.hint || "")}</small>
                 </button>`
      )
      .join("");
  }

  function renderSymptomCatalogSection(opts = {}) {
    const items = Array.isArray(st.s5Catalog) ? st.s5Catalog : [];
    if (!items.length) return "";
    const categories = ["全部"];
    items.forEach((it) => {
      if (it.category && !categories.includes(it.category)) categories.push(it.category);
    });
    const filteredCount = filterSymptomCatalog().length;
    const inner = `
      <div class="s5-catalog-toolbar">
        <input id="s5-sym-cat-search" class="s5-catalog-search" type="search" value="${esc(st.s5CatSearch)}" placeholder="筛选病症目录（如：感冒、胃酸、鼻炎、高血压、痛经、肾结石、青春痘…）" />
        <span id="s5-catalog-count" class="muted-line">共 ${filteredCount} / ${items.length} 项常见病症（点选即直接出方）</span>
      </div>
      <div class="s5-catalog-tabs" role="tablist" aria-label="病症分类">
        ${categories
          .map(
            (c) => `<button class="s5-catalog-tab ${st.s5CatFilter === c ? "active" : ""}" type="button" data-s5-cat-tab="${esc(c)}">${esc(c)}</button>`
          )
          .join("")}
      </div>
      <div id="s5-catalog-grid" class="s5-catalog-grid">
        ${renderSymptomCatalogGridHtml()}
      </div>
    `;
    if (opts.collapsed) {
      return `<details class="s5-catalog-drawer">
                <summary>切换 / 浏览常见病症快速出方目录（${items.length} 项分类病症 · 点击直出参考经方）</summary>
                <div class="s5-catalog-drawer-body">${inner}</div>
              </details>`;
    }
    return `
      <section class="s5-catalog-section">
        <div class="s5-section-title-row">
          <h3>常见病症快速选症出方目录（九大专科 · 点击任意症状直接出方）</h3>
          <span class="muted-line">选定主症后再按下方「学习问诊」点选兼症，即可即时收敛并调整原典剂量处方</span>
        </div>
        ${inner}
      </section>
    `;
  }

  function updateS5CatalogDomOnly() {
    const grid = $("#s5-catalog-grid");
    if (grid) grid.innerHTML = renderSymptomCatalogGridHtml();
    const cnt = $("#s5-catalog-count");
    if (cnt) {
      const total = Array.isArray(st.s5Catalog) ? st.s5Catalog.length : 0;
      cnt.textContent = `共 ${filterSymptomCatalog().length} / ${total} 项常见病症（点选即直接出方）`;
    }
    document.querySelectorAll("[data-s5-cat-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.s5CatTab === st.s5CatFilter);
    });
  }

  function removeSymptomFromQuery(curTxt, canonSym, d) {
    let next = String(curTxt || "").trim();
    const candidates = Array.from(new Set([canonSym, ...(CANON_REMOVAL_TERMS[canonSym] || [])])).sort(
      (a, b) => b.length - a.length
    );
    candidates.forEach((tok) => {
      if (tok && next.includes(tok)) {
        next = next.replaceAll(tok, " ");
      }
    });
    next = next.replace(/^[，,\s、；;]+|[，,\s、；;]+$/g, "").replace(/[，,\s、；;]{2,}/g, " ").trim();
    if (next === String(curTxt || "").trim() && (d?.recognized_symptoms || []).length <= 1) {
      return "";
    }
    return next;
  }

  function renderInlineRxSheet(topCompound, _d) {
    const details = Array.isArray(topCompound?.formulas_detail) ? topCompound.formulas_detail : [];
    const actionsHtml = details.length
      ? `<div class="s5-rx-actions">
           <button class="secondary-btn small-btn" type="button" data-copy-rx="1">📋 复制参考处方与原典剂量</button>
           <button class="primary-btn small-btn" type="button" data-send-to-ai="1">🩺 转入「倪师AI开方」深度问诊加减 →</button>
           <span id="s5-rx-copy-status" class="muted-line">仅供中医经典学术研习参考，抓药使用请务必经执业医师面诊核定</span>
         </div>`
      : `<div class="s5-rx-actions">
           <button class="primary-btn small-btn" type="button" data-send-to-ai="1">🩺 转入「倪师AI开方」继续辨证定方 →</button>
         </div>`;
    if (!details.length) return actionsHtml;

    return `
      <div class="s5-rx-sheet">
        ${details
          .map(
            (fd) => `<article class="s5-rx-card">
                       <div class="s5-rx-card-head">
                         <div>
                           <strong>【参考经方处方笺】${esc(fd.name)}</strong>
                           <span class="sha-pill">${esc(fd.book || "经方")}${fd.six_meridian ? " · " + esc(fd.six_meridian) : ""}</span>
                           ${
                             (fd.high_risk_herbs || []).length
                               ? `<span class="s5-rx-risk-badge">⚠️ 含峻烈/炮制注意药：${esc(fd.high_risk_herbs.join("、"))}</span>`
                               : ""
                           }
                         </div>
                         <button class="secondary-btn small-btn" type="button" data-jump-module="formulas" data-jump-id="${esc(fd.formula_id)}">原方详解 →</button>
                       </div>
                       ${
                         (fd.ingredients || []).length
                           ? `<div class="s5-rx-herbs-grid">
                                ${fd.ingredients
                                  .map((ing) => {
                                    const isRisk = ing.risk_level === "emergency" || ing.risk_level === "high_risk";
                                    return `<span class="s5-rx-herb-chip ${isRisk ? "is-risk" : ""}">
                                              <b>${esc(ing.name)}</b>
                                              ${ing.dose ? `<em>${esc(ing.dose)}</em>` : ""}
                                              ${ing.processing ? `<small>${esc(ing.processing)}</small>` : ""}
                                            </span>`;
                                  })
                                  .join("")}
                              </div>`
                           : fd.composition_raw
                             ? `<div class="s5-rx-raw"><strong>原方组成：</strong>${esc(fd.composition_raw)}</div>`
                             : ""
                       }
                       ${fd.decoction ? `<div class="s5-rx-meta"><strong>【煎煮与服法】</strong>${esc(fd.decoction)}</div>` : ""}
                       ${
                         (fd.modifications || []).length
                           ? `<div class="s5-rx-mods">
                                <strong>【常用随证加减参考】</strong>
                                ${fd.modifications
                                  .slice(0, 3)
                                  .map(
                                    (m) => `<span>· 若「${esc(m.condition)}」→ ${esc(m.changes_summary)}${m.target_formula_name ? `（${esc(m.target_formula_name)}）` : ""}</span>`
                                  )
                                  .join("")}
                              </div>`
                           : ""
                       }
                     </article>`
          )
          .join("")}
        ${actionsHtml}
      </div>
    `;
  }

  function renderComposeControls(d, opts = {}) {
    const isEmpty = Boolean(opts.isEmpty);
    const recognizedSymsList = d.recognized_symptoms || [];
    const recognizedPulsesList = d.recognized_pulses || st.s5Pulses || [];
    const recognizedSyms = new Set(recognizedSymsList);
    const recognizedPulses = new Set(recognizedPulsesList);
    const recognizedTongues = new Set(d.recognized_tongues || []);
    const curTxt = st.s5Query || "";
    const tongueText = (d.recognized_tongues || []).join("、") || "未指定";
    const negText = (d.recognized_negations || []).length
      ? `<span>已自动排空否定项：<b>${esc((d.recognized_negations || []).join("、"))}</b></span>`
      : "";
    const activeChipsHtml =
      !isEmpty && (recognizedSymsList.length || recognizedPulsesList.length)
        ? `<div class="s5-active-chips">
             <span class="s5-active-lbl">已选症脉：</span>
             ${recognizedSymsList
               .map(
                 (s) =>
                   `<button class="s5-active-chip" type="button" data-remove-symptom="${esc(s)}" title="点击移出「${esc(s)}」">${esc(s)} <b>×</b></button>`
               )
               .join("")}
             ${recognizedPulsesList
               .map(
                 (p) =>
                   `<button class="s5-active-chip is-pulse" type="button" data-toggle-pulse="${esc(p)}" title="点击取消「脉${esc(p)}」">脉${esc(p)} <b>×</b></button>`
               )
               .join("")}
           </div>`
        : "";
    const statusHtml = isEmpty
      ? `<span>已辨识规范症状：<strong>暂未选择</strong>（点选下方病症目录/十问即直接出方）</span><span>已选脉象权重：<strong>暂未选择</strong></span>`
      : `${activeChipsHtml || `<span>已辨识症状轴：<b>${esc(recognizedSymsList.join("、") || "已按全文线索匹配")}</b></span>`}
         ${negText}
         <span>当前舌象：<b>${esc(tongueText)}</b></span>`;

    // Group inquiry pills by clinical axis (寒热手足 / 二便口渴 / 眠胃时辰 / 腹诊压痛)
    const inquiryGroups = new Map();
    (d.inquiry_pills || []).forEach((iq) => {
      const grp = iq.group || "临床十问";
      if (!inquiryGroups.has(grp)) inquiryGroups.set(grp, []);
      inquiryGroups.get(grp).push(iq);
    });
    const inquiryHtml = inquiryGroups.size
      ? `<details class="s5-inquiry-details" ${!isEmpty || recognizedTongues.size ? "open" : ""}>
           <summary>人纪十问 · 时辰睡眠 · 腹诊压痛快捷增删（点击即同步收敛辨证）</summary>
           <div class="s5-inquiry-groups">
             ${Array.from(inquiryGroups.entries())
               .map(
                 ([grpName, items]) => `<div class="s5-inquiry-group-row">
                   <span class="s5-inquiry-grp-lbl">${esc(grpName)}</span>
                   <div class="s5-pill-wrap is-symptoms">
                     ${items
                       .map((iq) => {
                         const tokParts = (iq.token || "").split(/\s+/).filter(Boolean);
                         const active = tokParts.length > 0 && tokParts.every((tp) => curTxt.includes(tp) || recognizedSyms.has(tp));
                         return `<button class="s5-toggle-pill ${active ? "is-selected" : ""}" type="button" data-toggle-symptom="${esc(iq.token)}">${active ? "✓ " : "+ "}${esc(iq.label)}</button>`;
                       })
                       .join("")}
                   </div>
                 </div>`
               )
               .join("")}
           </div>
         </details>`
      : "";

    return `
      <section class="s5-compose-controls">
        <div class="s5-control-row">
          <span class="s5-control-label">脉象四诊权重（可多选，实时调整方剂加减与排误）：</span>
          <div class="s5-pill-wrap">
            ${(d.pulse_options || [])
              .map(
                (p) => `<button class="s5-toggle-pill ${recognizedPulses.has(p.id) ? "is-selected" : ""}" type="button" data-toggle-pulse="${esc(p.id)}" title="${esc(p.note)}">${esc(p.label)}</button>`
              )
              .join("")}
          </div>
        </div>
        ${
          (d.tongue_options || []).length
            ? `<div class="s5-control-row">
                 <span class="s5-control-label">舌诊辨寒热虚实（人纪胃气与津液分水岭）：</span>
                 <div class="s5-pill-wrap">
                   ${(d.tongue_options || [])
                     .map((t) => {
                       const active = recognizedTongues.has(t.id) || recognizedSyms.has(t.id) || curTxt.includes(t.id);
                       return `<button class="s5-toggle-pill ${active ? "is-selected" : ""}" type="button" data-toggle-symptom="${esc(t.id)}" title="${esc(t.note)}">${active ? "✓ " : ""}${esc(t.label)}</button>`;
                     })
                     .join("")}
                 </div>
               </div>`
            : ""
        }
        <div class="s5-control-row">
          <span class="s5-control-label">常用症状点选增删（点击即可加入或移出上方辨证输入框）：</span>
          <div class="s5-pill-wrap is-symptoms">
            ${(d.quick_symptom_pills || [])
              .map((sp) => {
                const tokParts = sp.token.split(/\s+/).filter(Boolean);
                const active =
                  recognizedSyms.has(sp.label) ||
                  recognizedSyms.has(sp.token) ||
                  (tokParts.length > 0 && tokParts.every((tp) => curTxt.includes(tp)));
                return `<button class="s5-toggle-pill ${active ? "is-selected" : ""}" type="button" data-toggle-symptom="${esc(sp.token)}">${active ? "✓ " : "+ "}${esc(sp.label)}</button>`;
              })
              .join("")}
          </div>
        </div>
        ${inquiryHtml}
        ${
          !isEmpty && (d.followup_questions || []).length
            ? `<div class="s5-control-row s5-followup-box">
                 <span class="s5-control-label">临床症状追问 · 学习问诊（根据当前主症智能筛出鉴别关键症，点选即追加推演）：</span>
                 <div class="s5-followup-bar">
                   ${(d.followup_questions || [])
                     .map(
                       (fq) =>
                         `<button class="s5-followup-chip ${fq.kind === "pulse" ? "is-pulse-probe" : ""}" type="button" data-followup-token="${esc(fq.token || "")}" data-followup-pulse="${esc(fq.pulse_id || "")}" title="${esc(fq.why || "")}">+ ${esc(fq.label)} <span class="s5-fq-tag">${fq.kind === "pulse" ? "脉" : "症"}</span></button>`
                     )
                     .join("")}
                 </div>
               </div>`
            : ""
        }
        <div class="s5-recognized-strip">
          ${statusHtml}
          ${!isEmpty ? `<button id="s5-clear-selected-btn" class="s5-clear-mini-btn" type="button">清空重选</button>` : ""}
        </div>
        ${!isEmpty ? renderSymptomCatalogSection({ collapsed: true }) : ""}
      </section>
    `;
  }

  function renderComposeEmpty(base) {
    const host = $("#s5-workspace-body");
    if (!host) return;
    if (Array.isArray(base?.symptom_catalog) && base.symptom_catalog.length) {
      st.s5Catalog = base.symptom_catalog;
    }
    const cards = base.clinical_entry_cards || [];
    host.innerHTML = `
      ${renderSymptomCatalogSection({ collapsed: false })}
      ${renderComposeControls(base, { isEmpty: true })}
      <section class="s5-empty-guide">
        <h3>中医大脑 · 临床辨证与合方配穴工作台（全库 299 经方 · 91 汉唐方 · 34 针灸治症 · 108 随证加减）</h3>
        <p>在上方输入框直接键入症状或点选上面「常见病症目录」中的任意病症，即刻直接给出<strong>经方参考处方、原典药物组成与剂量、煎服法、随证加减及同步针灸配穴</strong>：</p>
        <ol class="s5-empty-steps">
          <li><strong>输入或点选症状直接出方</strong>：覆盖感冒、发烧、鼻炎、胃酸过多、腹胀、腹泻、高血压、痛经、月经不调、肾结石等常见病症，全自动关联《伤寒》《金匮》《汉唐》与《针灸》处方。</li>
          <li><strong>动态学习问诊收敛处方</strong>：出方后可继续点选「学习问诊 · 鉴别关键症」（如无汗/有汗、口苦、脚冷、脉沉等）即时调整主方与合方。</li>
          <li><strong>安全边界与实证对比</strong>：自动校验寒热舌脉、十八反十九畏与临床红线；支持一键转入「倪师AI开方」深度辨证。</li>
        </ol>
      </section>
      ${
        cards.length
          ? `<section class="s5-entry-section">
               <div class="s5-section-title-row">
                 <h3>中医 · 症 临床主症入口（16 大临床病症分类 · 点选症状或整组载入）</h3>
                 <span class="muted-line">依托倪海厦人纪经方与针灸原书治症库</span>
               </div>
               <div class="s5-entry-grid">
                 ${cards
                   .map(
                     (c) => `<article class="s5-entry-card">
                               <div class="s5-entry-head">
                                 <strong>${esc(c.title)}</strong>
                                 <span class="sha-pill">${esc(c.formulas_hint || "")}</span>
                               </div>
                               <p class="s5-entry-sub">${esc(c.subtitle || "")}</p>
                               <div class="s5-entry-tokens">
                                 ${(c.tokens || [])
                                   .map(
                                     (tok) => `<button class="s5-mini-sym-chip" type="button" data-toggle-symptom="${esc(tok)}">+ ${esc(tok)}</button>`
                                   )
                                   .join("")}
                               </div>
                               <div class="s5-entry-foot">
                                 <button class="primary-btn small-btn s5-entry-load-btn" type="button" data-entry-query="${esc(c.default_query || "")}">载入此主症组合辨证 →</button>
                               </div>
                             </article>`
                   )
                   .join("")}
               </div>
             </section>`
          : ""
      }
    `;
  }

  function renderDiagnoseEmpty(ov) {
    const host = $("#s5-workspace-body");
    if (!host) return;
    const clusters = ov.syndrome_clusters || [];
    host.innerHTML = `
      <section class="s5-empty-guide">
        <h3>四经一体跨书辨证总览（请输入症状/方名/穴名，或点选下方证候群）</h3>
        <p>上方输入框初始留空。您可直接输入任意关键词检索跨《针灸》《神农本草》《黄帝内经》《伤寒金匮》与藏书阁原文的四维关联，或点击下方示范按钮与经典证候群进入：</p>
      </section>
      <div class="s5-grid" style="margin-top: 12px;">
        ${clusters
          .map(
            (c) => `
          <article class="s5-card clickable" data-s5-drill="${esc(c.name.replace(/[（(].*$/, ""))}">
            <h4>${esc(c.name)}</h4>
            <div class="muted-line">${esc((c.key_symptoms || []).slice(0, 5).join(" · "))}</div>
            <p>${esc((c.core_pathogenesis || "").slice(0, 88))}…</p>
          </article>
        `
          )
          .join("")}
      </div>
    `;
  }

  function renderGroundEmpty() {
    const host = $("#s5-workspace-body");
    if (!host) return;
    host.innerHTML = `
      <section class="s5-empty-guide">
        <h3>循证研习问答（5B · SHA-256 原书真伪校验与安全边界门控）</h3>
        <p>上方输入框初始留空。请输入您的中医经典辨证疑问（或点击上方专题按钮），系统将严格按「经典原文依据 → 倪师人纪阐发 → 他家古籍互参 → 方证鉴别与配穴」四层结构作答，并拒绝超越学术研习范围的个体开方指令。</p>
      </section>
    `;
  }

  function renderComposeChips(presets) {
    const bar = $("#s5-chips");
    if (!bar) return;
    bar.innerHTML = presets
      .map(
        (c) => `<button class="prompt-chip s5-preset-chip" type="button" data-compose-preset="${esc(c.symptoms)}" data-compose-pulse="${esc(c.pulse || "")}" title="${esc(c.note || "")}">
                  ${esc(c.title)}
                </button>`
      )
      .join("");
  }

  async function runStage5Compose(q, pulses = st.s5Pulses) {
    const cleanQ = (q || "").trim();
    const cleanPulses = Array.isArray(pulses) ? pulses : [];
    st.s5Query = q || "";
    st.s5Pulses = cleanPulses;
    const inp = $("#s5-query-input");
    if (inp && document.activeElement !== inp && inp.value !== st.s5Query) inp.value = st.s5Query;
    if (!cleanQ && !cleanPulses.length) {
      const base = await api("/api/stage5/compose");
      renderComposeEmpty(base);
      return;
    }
    const pulseParam = pulses.join(" ");
    const d = await api(`/api/stage5/compose?q=${encodeURIComponent(q)}&pulse=${encodeURIComponent(pulseParam)}`);
    st.s5Data = d;
    const host = $("#s5-workspace-body");
    if (!host) return;

    const sb = d.safety_boundary || {};
    const triage = d.triage_summary || {};
    const regimens = d.compound_regimens || [];
    const topCompound = regimens[0];
    const altRegimens = regimens.slice(1);
    const acup = d.acupoint_protocol || { primary: [], adjuncts: [], technique_note: "" };
    const hasTriage = Boolean(triage.headline || (triage.crossroads || []).length || (triage.tongue_notes || []).length);
    const heroBadgeLabel = topCompound
      ? topCompound.is_compound === false
        ? (topCompound.formula_ids || []).length
          ? "单方专治统摄"
          : "《针灸》专症主治"
        : "动态合方辨证结果"
      : "动态辨证结果";

    host.innerHTML = `
      ${renderComposeControls(d, { isEmpty: false })}

      ${
        sb.triggered
          ? `<div class="s5-ground-banner is-danger"><strong>${esc(sb.title)}</strong><p>${esc(sb.message)}</p></div>`
          : ""
      }

      ${
        hasTriage
          ? `<section class="s5-triage-banner">
               <div class="s5-triage-head">
                 <strong>四诊分水岭导读</strong>
                 <span>${esc(triage.headline || "")}</span>
               </div>
               ${
                 (triage.crossroads || []).length
                   ? `<div class="s5-crossroad-grid">
                        ${triage.crossroads
                          .map(
                            (cr) => `<div class="s5-crossroad-item">
                                       <strong>${esc(cr.question)}</strong>
                                       <p>${esc(cr.why)}</p>
                                     </div>`
                          )
                          .join("")}
                      </div>`
                   : ""
               }
               ${
                 (triage.tongue_notes || []).length
                   ? `<div class="s5-tongue-notes">${triage.tongue_notes.map((tn) => `<span>· ${esc(tn)}</span>`).join("")}</div>`
                   : ""
               }
             </section>`
          : ""
      }

      ${
        topCompound
          ? `<section class="s5-compound-hero">
               <div class="s5-compound-head">
                 <div>
                   <span class="lib-badge lib-badge-core">${esc(heroBadgeLabel)}</span>
                   <h2>${esc(topCompound.title)}</h2>
                 </div>
                 <div class="lib-chip-cloud">
                   ${(topCompound.formula_ids || []).length
                     ? (topCompound.formula_ids || [])
                         .map(
                           (fid, i) => `<button class="primary-btn" type="button" data-jump-module="formulas" data-jump-id="${esc(fid)}">
                                          查看原方：${esc((topCompound.formula_names || [])[i] || fid)} →
                                        </button>`
                         )
                         .join("")
                     : ((d.matched_condition_patterns || [])[0]
                         ? `<button class="primary-btn" type="button" data-jump-module="acupuncture" data-jump-id="${esc(d.matched_condition_patterns[0].condition_id)}">
                              查看《针灸》治症：${esc(d.matched_condition_patterns[0].condition_name)} →
                            </button>`
                         : "")}
                 </div>
               </div>
               <ul class="s5-axis-list">
                 ${(topCompound.axis_roles || []).map((r) => `<li>${esc(r)}</li>`).join("")}
               </ul>
               ${renderInlineRxSheet(topCompound, d)}
               ${
                 (topCompound.herb_conflict_alerts || []).length
                   ? `<div class="s5-pitfall-box"><strong>配伍警戒与反畏提醒：</strong>${esc(topCompound.herb_conflict_alerts.join("；"))}</div>`
                   : ""
               }
               <p class="s5-overlap-note"><strong>合方与药味协同提示：</strong>${esc(topCompound.overlap_note)}</p>
               ${
                 (topCompound.uncovered_symptoms || []).length
                   ? `<p class="muted-line">未完全归入前二方轴之兼症（请参照下方兼症加减或随症取穴）：${esc(topCompound.uncovered_symptoms.join("、"))}</p>`
                   : ""
               }
               ${
                 altRegimens.length
                   ? `<div class="s5-alt-regimen-row">
                        ${altRegimens
                          .map((alt) => {
                            const herbPreview = (alt.formulas_detail || [])
                              .map((fd) => {
                                const names = (fd.ingredients || []).map((ing) => `${ing.name}${ing.dose || ""}`).join("、");
                                return names ? `${fd.name}（${names}）` : fd.composition_raw || fd.name;
                              })
                              .filter(Boolean)
                              .join(" ＋ ");
                            return `<div class="s5-alt-regimen-card">
                                       <div class="s5-alt-regimen-head">
                                         <strong>${esc(alt.title)}</strong>
                                         <span class="lib-chip-cloud">${(alt.formula_ids || [])
                                           .map(
                                             (fid, idx) => `<button class="entity-jump-chip badge-formula" type="button" data-jump-module="formulas" data-jump-id="${esc(fid)}">${esc((alt.formula_names || [])[idx] || fid)}</button>`
                                           )
                                           .join("")}</span>
                                       </div>
                                       ${herbPreview ? `<div class="s5-alt-herbs-preview"><strong>参考组成：</strong>${esc(herbPreview)}</div>` : ""}
                                       <p class="muted-line">${esc((alt.axis_roles || []).join("；"))} · ${esc(alt.overlap_note || "")}</p>
                                     </div>`;
                          })
                          .join("")}
                      </div>`
                   : ""
               }
             </section>`
          : `<div class="empty-mini">请输入两个以上相关症状或点击上方示范病例。</div>`
      }

      <div class="s5-compose-dual-grid">
        <div class="s5-dual-col">
          <section class="layer-card s5-acup-card">
            <div class="s5-section-title-row">
              <h4>① 经络辨证 · 针灸同步取穴处方</h4>
              <span class="muted-line">点击任意穴位直达《针灸》模块定位与刺灸法</span>
            </div>
            <div class="s5-acup-group">
              <strong>【核心主穴】</strong>
              <div class="s5-acup-list">
                ${(acup.primary || [])
                  .map(
                    (pt) => `<button class="s5-acup-item" type="button" data-jump-module="acupuncture" data-jump-id="${esc(pt.id)}">
                              <span class="entity-jump-chip badge-acup">${esc(pt.name)} · ${esc(pt.role)}</span>
                              <small>${esc(pt.reason)}（源于${esc(pt.from_axis)}）</small>
                            </button>`
                  )
                  .join("") || `<span class="empty-mini">暂无主穴匹配</span>`}
              </div>
            </div>
            <div class="s5-acup-group">
              <strong>【兼症随症配穴】</strong>
              <div class="s5-acup-list">
                ${(acup.adjuncts || [])
                  .map(
                    (pt) => `<button class="s5-acup-item" type="button" data-jump-module="acupuncture" data-jump-id="${esc(pt.id)}">
                              <span class="entity-jump-chip badge-acup">${esc(pt.name)} · ${esc(pt.role)}</span>
                              <small>${esc(pt.reason)}（源于${esc(pt.from_axis)}）</small>
                            </button>`
                  )
                  .join("") || `<span class="empty-mini">暂无需额外配穴</span>`}
              </div>
            </div>
            ${acup.technique_note ? `<div class="s5-tech-note">${esc(acup.technique_note)}</div>` : ""}
          </section>

          ${
            (d.matched_condition_patterns || []).length
              ? `<section class="layer-card s5-cond-section">
                   <div class="s5-section-title-row">
                     <h4>② 《针灸》34大病症分型对照（原书治症直连）</h4>
                     <span class="muted-line">点击病症名或穴位跳至针灸原书详情</span>
                   </div>
                   <div class="s5-cond-list">
                     ${(d.matched_condition_patterns || [])
                       .map(
                         (cp) => `<article class="s5-cond-card">
                                    <div class="s5-cand-top">
                                      <button class="s5-link-title" type="button" data-jump-module="acupuncture" data-jump-id="${esc(cp.condition_id)}">${esc(cp.condition_name)} · ${esc(cp.pattern_name)}</button>
                                      <span class="sha-pill">相关度 ${cp.score}</span>
                                    </div>
                                    ${cp.syndrome_differentiation ? `<p class="s5-cond-desc">${esc(cp.syndrome_differentiation)}</p>` : ""}
                                    ${cp.why_selected ? `<div class="muted-line">取穴法则：${esc(cp.why_selected)}</div>` : ""}
                                    <div class="lib-chip-cloud s5-cond-pts">
                                      ${(cp.points || [])
                                        .map((p) => `<button class="entity-jump-chip badge-acup" type="button" data-jump-module="acupuncture" data-jump-id="${esc(p.id)}">${esc(p.name)}</button>`)
                                        .join("")}
                                    </div>
                                  </article>`
                       )
                       .join("")}
                   </div>
                 </section>`
              : ""
          }
        </div>

        <div class="s5-dual-col">
          <section class="layer-card s5-clue-section">
            <div class="s5-section-title-row">
              <h4>③ 全库 299 经方症状线索与随证加减法（支持症候 / 待核线索）</h4>
              <span class="muted-line">点击「待核症状」可一键补充入诊；点击方名直达经方详解</span>
            </div>
            <div class="s5-clue-list">
              ${(d.matched_jingfang_clues || [])
                .map(
                  (clue) => `<article class="s5-clue-card ${clue.in_compound ? "is-compound" : ""}">
                               <div class="s5-cand-top">
                                 <button class="s5-link-title" type="button" data-jump-module="formulas" data-jump-id="${esc(clue.formula_id)}">${esc(clue.name)}</button>
                                 <span class="sha-pill">${esc(clue.book)}${(clue.also_in_books || []).length ? `（兼见${esc(clue.also_in_books.join("/"))}）` : ""} · ${clue.in_compound ? "主推轴心" : "分值 " + clue.score}</span>
                               </div>
                               <div class="muted-line">${esc(clue.six_meridian)}${clue.ingredients_summary ? ` ｜ 组成：${esc(clue.ingredients_summary)}` : ""}</div>
                               ${
                                 (clue.supporting_symptoms || []).length
                                   ? `<div class="s5-cue-row"><span class="s5-cue-lbl is-hit">✓ 支持症候：</span>${clue.supporting_symptoms
                                       .map((s) => `<span class="s5-cue-tag is-hit">${esc(s)}</span>`)
                                       .join("")}</div>`
                                   : ""
                               }
                               ${
                                 (clue.unselected_cues || []).length
                                   ? `<div class="s5-cue-row"><span class="s5-cue-lbl is-pending">? 待核线索：</span>${clue.unselected_cues
                                       .map((c) => `<button class="s5-cue-btn" type="button" data-toggle-symptom="${esc(c)}" title="点击加入此待核症状重算">+ ${esc(c)}</button>`)
                                       .join("")}</div>`
                                   : ""
                               }
                               ${clue.why_summary ? `<p class="s5-clue-why">${esc(clue.why_summary)}</p>` : ""}
                               ${
                                 (clue.modifications || []).length
                                   ? `<div class="s5-mod-list">
                                        <strong>【随证加减衍化】</strong>
                                        ${clue.modifications
                                          .map(
                                            (m) => `<div class="s5-mod-row">
                                                      <span>若「${esc(m.condition)}」→ ${esc(m.changes_summary || m.rationale)}</span>
                                                      ${
                                                        m.target_formula_id
                                                          ? `<button class="entity-jump-chip badge-formula" type="button" data-jump-module="formulas" data-jump-id="${esc(m.target_formula_id)}">→ ${esc(m.target_formula_name || m.target_formula_id)}</button>`
                                                          : ""
                                                      }
                                                    </div>`
                                          )
                                          .join("")}
                                      </div>`
                                   : ""
                               }
                               ${
                                 (clue.linked_acupoints || []).length
                                   ? `<div class="s5-cue-row"><span class="s5-cue-lbl">原书针药配伍：</span>${clue.linked_acupoints
                                       .map((lk) => `<button class="entity-jump-chip badge-acup" type="button" data-jump-module="acupuncture" data-jump-id="${esc(lk.id)}" title="${esc(lk.note || lk.quote)}">${esc(lk.name)} · ${esc(lk.relation_kind || "配穴")}</button>`)
                                       .join("")}</div>`
                                   : ""
                               }
                             </article>`
                )
                .join("") || `<div class="empty-mini">当前主要触发《针灸》专症分型，暂无高置信度经方直接命中；可点选上方「临床症状追问」补充寒热、二便或脉象线索。</div>`}
            </div>
          </section>

          ${
            (d.candidate_formulas || []).length || (d.excluded_pitfalls || []).length
              ? `<section class="layer-card">
                   <h4>④ 核心候补方阵拆解 & 反向排误边界</h4>
                   <div class="s5-cand-list">
                     ${(d.candidate_formulas || [])
                       .map(
                         (f) => `<div class="s5-mini-card clickable" data-jump-module="formulas" data-jump-id="${esc(f.formula_id)}">
                                   <div class="s5-cand-top"><strong>${esc(f.name)}</strong> <span class="sha-pill">得分 ${f.score}</span></div>
                                   <div class="muted-line">${esc(f.six_meridian)} · 命中：${esc(f.matched_symptoms.join("、"))} ${esc(f.matched_pulses.join(" "))}${(f.matched_tongues || []).length ? ` [${esc(f.matched_tongues.join("、"))}]` : ""}</div>
                                   <p>${esc(f.pathogenesis)}</p>
                                 </div>`
                       )
                       .join("") || `<div class="empty-mini">由上方全库 299 经方线索承担候选主轴。</div>`}
                   </div>
                   ${
                     (d.excluded_pitfalls || []).length
                       ? `<div class="s5-pitfall-box">
                            <strong>【系统已抑制排除的误治方警告】</strong>
                            <ul>
                              ${groupExcludedPitfalls(d.excluded_pitfalls)
                                .map((grp) => `<li><strong>忌误用「${esc(grp.names.join("、"))}」：</strong>${esc(grp.reason)}</li>`)
                                .join("")}
                            </ul>
                          </div>`
                       : ""
                   }
                 </section>`
              : ""
          }
          ${renderStage5HantangSection(d.hantang_context)}
        </div>
      </div>

      ${
        (d.classical_redlines || []).length
          ? `<section class="s5-alert-banner s5-redline-section">
               <strong>多学派互参临床红线与禁汗/禁下/禁温拦截（仅供学术辨证研习）：</strong>
               <div class="s5-diff-list">
                 ${d.classical_redlines
                   .map(
                     (rl) => `
                   <article class="layer-card">
                     <h4 class="s5-danger-note">${esc(rl.title)}</h4>
                     ${rl.classic_basis ? `<p><strong>【经典依据】</strong>${esc(rl.classic_basis)}</p>` : ""}
                     ${rl.ni_and_hantang_note ? `<p><strong>【人纪 · 汉唐】</strong>${esc(rl.ni_and_hantang_note)}</p>` : ""}
                     ${rl.schools_crossref ? `<p><strong>【诸家互参】</strong>${esc(rl.schools_crossref)}</p>` : ""}
                     ${rl.action_rule ? `<p><strong>【辨证拦截】</strong>${esc(rl.action_rule)}</p>` : ""}
                     ${
                       (rl.source_anchors || []).length
                         ? `<div class="s5-redline-anchors"><span class="s5-redline-anchors-label">原文参照：</span>${rl.source_anchors
                             .map((a) => renderAnchorBtn(a, a.label || a.book_title || "原文参照"))
                             .join("")}</div>`
                         : ""
                     }
                   </article>`
                   )
                   .join("")}
               </div>
             </section>`
          : ""
      }

      ${
        (d.differential_notes || []).length
          ? `<div class="s5-diff-list">
               ${d.differential_notes.map((dn) => `<div class="layer-card"><h4>${esc(dn.title)}</h4><p>${esc(dn.explanation)}</p></div>`).join("")}
             </div>`
          : ""
      }

      ${
        (d.decoction_and_safety || []).length
          ? `<section class="layer-card s5-decoction-card">
               <h4>煎服炮制 · 针刺禁忌 · 人纪停药与向愈六大金标准</h4>
               <ul>
                 ${d.decoction_and_safety.map((line) => `<li>${esc(line)}</li>`).join("")}
               </ul>
             </section>`
          : ""
      }

      <section class="s5-lib-evidence-box">
        <h3>关联书库原文佐证 · 点击滑动对照上下页或进藏书阁精读</h3>
        <div class="s5-lib-hit-list">
          ${(d.library_evidence || [])
            .map((h) =>
              renderLibRefRow(h, {
                bodyHtml: `<strong>《${esc(h.book_title)}》${esc(h.unit_label)}</strong> — ${esc(h.snippet)}`,
                probe: st.s5Query || h.snippet,
              })
            )
            .join("") || `<div class="empty-mini">暂无书库命中</div>`}
        </div>
      </section>

      <details class="layer-card s5-ai-packet">
        <summary>下一阶段 AI 循证推理接入口（结构化四诊与原文锚点数据包 · Ready for LLM）</summary>
        <div class="s5-ai-actions">
          <button class="secondary-btn small-btn" type="button" data-copy-ai="prompt">一键复制循证大模型提问词</button>
          <button class="secondary-btn small-btn" type="button" data-copy-ai="json">复制病案 JSON 数据包</button>
          <span class="muted-line" id="s5-ai-copy-status">严格携带否定排误记录、禁忌红线及原文 SHA-256 校验锚点</span>
        </div>
        <pre class="lib-verbatim-text">${esc(JSON.stringify(d.ai_ready_case_packet, null, 2))}</pre>
      </details>
    `;
  }

  function renderS5Chips(chips) {
    const bar = $("#s5-chips");
    if (!bar) return;
    bar.innerHTML = chips
      .map((c) => `<button class="prompt-chip" type="button" data-s5-chip="${esc(c.q)}">${esc(c.label)}</button>`)
      .join("");
  }

  async function runStage5Diagnose(q) {
    st.s5Query = q || "";
    const inp = $("#s5-query-input");
    if (inp && document.activeElement !== inp && inp.value !== st.s5Query) inp.value = st.s5Query;
    if (!st.s5Query.trim()) {
      const ov = await api("/api/stage5/overview");
      renderDiagnoseEmpty(ov);
      return;
    }
    const d = await api(`/api/stage5/diagnose?q=${encodeURIComponent(q)}`);
    st.s5Data = d;
    const host = $("#s5-workspace-body");
    if (!host) return;

    const alertsHtml = (d.combined_safety_alerts || []).length
      ? `<div class="s5-alert-banner"><strong>高危警示与用药安全边界：</strong><ul>${d.combined_safety_alerts.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`
      : "";

    const clustersHtml = (d.syndrome_clusters || []).length
      ? `<div class="s5-clusters-row">
           ${d.syndrome_clusters
             .map(
               (sc) => `
               <article class="s5-cluster-card">
                 <div class="s5-cluster-title">${esc(sc.title)}</div>
                 <p><strong>【辨证病机】</strong>${esc(sc.clinical_reasoning)}</p>
                 <p><strong>【方证鉴别】</strong>${esc(sc.differentials)}</p>
                 ${sc.version_conflicts ? `<p class="s5-conflict-note"><strong>【版本与药材分歧】</strong>${esc(sc.version_conflicts)}</p>` : ""}
                 ${sc.safety_note ? `<p class="s5-danger-note"><strong>【禁忌与安全线】</strong>${esc(sc.safety_note)}</p>` : ""}
                 <div class="lib-chip-cloud">
                   ${(sc.neijing_concepts || []).map((x) => `<button class="entity-jump-chip badge-neijing" type="button" data-jump-module="neijing" data-jump-id="${esc(x.id)}">内经 · ${esc(x.title)}</button>`).join("")}
                   ${(sc.formulas || []).map((x) => `<button class="entity-jump-chip badge-formula" type="button" data-jump-module="formulas" data-jump-id="${esc(x.id)}">经方 · ${esc(x.title)}</button>`).join("")}
                   ${(sc.bencao || []).map((x) => `<button class="entity-jump-chip badge-bencao" type="button" data-jump-module="bencao" data-jump-id="${esc(x.id)}">本草 · ${esc(x.title)}</button>`).join("")}
                   ${(sc.acupuncture_points || []).map((x) => `<button class="entity-jump-chip badge-acup" type="button" data-jump-module="acupuncture" data-jump-id="${esc(x.id)}">穴位 · ${esc(x.title)}</button>`).join("")}
                 </div>
                 ${
                   (sc.library_refs || []).length
                     ? `<div class="s5-cluster-refs">
                          <strong>书库古籍与医案实证：</strong>
                          ${sc.library_refs
                            .map((r) =>
                              renderLibRefRow(r, {
                                bodyHtml: `《${esc(r.book_title)}》${esc(r.unit_label)} · “${esc((r.quote || "").slice(0, 48))}…”`,
                                probe: r.quote || sc.title,
                              })
                            )
                            .join("")}
                        </div>`
                     : ""
                 }
               </article>`
             )
             .join("")}
         </div>`
      : "";

    host.innerHTML = `
      ${alertsHtml}
      ${clustersHtml}
      <div class="s5-pillars-grid">
        <section class="s5-pillar-col">
          <h3>① 黄帝内经理法</h3>
          ${(d.neijing?.concepts || []).map((c) => `<div class="s5-mini-card clickable" data-jump-module="neijing" data-jump-id="${esc(c.id)}"><strong>${esc(c.canonical_name)}</strong><p>${esc((c.summary || "").slice(0, 88))}</p></div>`).join("") || `<div class="empty-mini">暂无直接内经专题命中</div>`}
          ${(d.neijing?.chapters || []).map((ch) => `<div class="s5-mini-card clickable" data-jump-module="neijing" data-jump-id="${esc(ch.id)}"><strong>${esc(ch.title)}</strong><p>${esc((ch.summary || "").slice(0, 72))}</p></div>`).join("")}
        </section>
        <section class="s5-pillar-col">
          <h3>② 伤寒金匮经方</h3>
          ${(d.formulas?.matched_formulas || []).map((f) => `<div class="s5-mini-card clickable" data-jump-module="formulas" data-jump-id="${esc(f.id)}"><strong>${esc(f.name)} <em>(${esc(f.book)})</em></strong><p>${esc((f.indication || f.why || "").slice(0, 88))}</p></div>`).join("") || `<div class="empty-mini">暂无直接经方命中</div>`}
        </section>
        <section class="s5-pillar-col">
          <h3>③ 神农本草药味</h3>
          ${(d.bencao?.items || []).map((b) => `<div class="s5-mini-card clickable" data-jump-module="bencao" data-jump-id="${esc(b.id)}"><strong>${esc(b.short_name || b.name)} <em>(${esc(b.grade || "")})</em></strong><p>点击打开本经原文与经方配伍</p></div>`).join("") || `<div class="empty-mini">暂无直接本草命中</div>`}
          ${(d.bencao?.related_comparisons || []).map((cp) => `<div class="s5-mini-card"><strong>比较：${esc(cp.title)}</strong><p>${esc((cp.summary || "").slice(0, 72))}</p></div>`).join("")}
        </section>
        <section class="s5-pillar-col">
          <h3>④ 针灸经络与取穴</h3>
          ${(d.acupuncture?.matched_patterns || []).map((p) => `<div class="s5-mini-card clickable" data-jump-module="acupuncture" data-jump-id="${esc(p.condition_id)}"><strong>${esc(p.condition_name)} · ${esc(p.pattern_name)}</strong><p>${esc((p.syndrome_differentiation || p.why_selected || "").slice(0, 82))}</p></div>`).join("")}
          <div class="lib-chip-cloud">${(d.acupuncture?.matched_points || []).map((pt) => `<button class="entity-jump-chip badge-acup" type="button" data-jump-module="acupuncture" data-jump-id="${esc(pt.id)}">${esc(pt.canonical_name)} (${esc(pt.meridian_name || "")})</button>`).join("")}</div>
        </section>
      </div>
      <section class="s5-lib-evidence-box">
        <h3>⑤ 全书库（含汉唐医案与古籍注疏）实时原文命中 · 点击滑动对照上下页或进藏书阁</h3>
        <div class="s5-lib-hit-list">
          ${(d.library_hits || [])
            .map((h) =>
              renderLibRefRow(h, {
                bodyHtml: `<strong>《${esc(h.book_title)}》${esc(h.unit_label)}</strong> — ${esc(h.snippet)}`,
                probe: st.s5Query || h.snippet,
              })
            )
            .join("") || `<div class="empty-mini">暂无直接命中</div>`}
        </div>
      </section>
    `;
  }

  async function runStage5Ground(q) {
    st.s5Query = q || "";
    const inp = $("#s5-query-input");
    if (inp && document.activeElement !== inp && inp.value !== st.s5Query) inp.value = st.s5Query;
    if (!st.s5Query.trim()) {
      renderGroundEmpty();
      return;
    }
    const g = await api(`/api/stage5/ground?q=${encodeURIComponent(q)}`);
    const host = $("#s5-workspace-body");
    if (!host) return;
    const sb = g.safety_boundary || {};
    host.innerHTML = `
      <div class="s5-ground-banner ${sb.triggered ? "is-danger" : "is-safe"}">
        <strong>${esc(sb.title || "文献研习")}</strong>
        <p>${esc(sb.message || "")}</p>
      </div>
      <div class="s5-layers-grid">
        <article class="layer-card"><h4>【经典原文依据层】</h4><p>${esc(g.layers?.classic_layer)}</p></article>
        <article class="layer-card"><h4>【倪师人纪与汉唐阐发】</h4><p>${esc(g.layers?.ni_layer)}</p></article>
        <article class="layer-card"><h4>【他家古籍注疏互参】</h4><p>${esc(g.layers?.commentary_layer)}</p></article>
        <article class="layer-card"><h4>【整理综合与方证鉴别】</h4><p>${esc(g.layers?.organizer_synthesis)}</p></article>
      </div>
      ${
        (g.four_pillar_links || []).length
          ? `<section class="s5-ground-section">
               <h3>关联四大核心模块知识条目</h3>
               <div class="lib-chip-cloud">
                 ${g.four_pillar_links
                   .map((lk) => {
                     const mb = MODULE_BADGE[lk.module] || { cls: "badge-formula", text: lk.module_label };
                     return `<button class="entity-jump-chip ${mb.cls}" type="button" data-jump-module="${esc(lk.module)}" data-jump-id="${esc(lk.entity_id)}">${esc(mb.text)} · ${esc(lk.title)}</button>`;
                   })
                   .join("")}
               </div>
             </section>`
          : ""
      }
      <section class="s5-ground-section">
        <h3>已核验原书逐页引用（SHA-256 真伪校验 · 点击即滑出上下文）</h3>
        <div class="s5-lib-hit-list">
          ${(g.verified_citations || []).map((c) => renderLibRefRow(c, { bodyHtml: `<strong>[${esc(c.shelf_label)}] 《${esc(c.book_title)}》${esc(c.unit_label)}</strong> · ${esc(c.snippet)} <span class="sha-pill">SHA ${esc((c.text_sha256 || "").slice(0, 10))}</span>`, probe: c.snippet || q })).join("") || `<div class="empty-mini">本次问题暂未直接检得可核验正文段落。</div>`}
        </div>
      </section>
      <div class="s5-conflict-gap-row">
        <div class="layer-card">
          <h4>【版本分歧与各家异同】</h4>
          <ul>${(g.version_conflicts || ["暂无显式跨书冲突记录"]).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        </div>
        <div class="layer-card">
          <h4>【覆盖不足与文献缺口边界】</h4>
          <ul>${(g.insufficiencies_and_gaps || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        </div>
      </div>
    `;
  }

  function updateSyndromeTabCount(total) {
    const count = Number(total);
    const tab = $("#s5-tab-syndromes");
    if (tab && Number.isFinite(count) && count > 0) {
      tab.textContent = `${count} 大跨书证候群图谱`;
    }
  }

  async function syncSyndromeTabCount() {
    try {
      const res = await api("/api/stage5/syndromes");
      if (res && typeof res.total === "number") {
        updateSyndromeTabCount(res.total);
      }
    } catch {
      // keep HTML fallback text if API unavailable during early boot
    }
  }

  async function renderSyndromesAtlas(q = "") {
    const res = await api(`/api/stage5/syndromes?q=${encodeURIComponent(q)}`);
    if (!String(q || "").trim() && typeof res?.total === "number") {
      updateSyndromeTabCount(res.total);
    }
    const host = $("#s5-workspace-body");
    if (!host) return;
    host.innerHTML = `
      <div class="s5-atlas-grid">
        ${(res.items || [])
          .map(
            (sc) => `
            <article class="s5-cluster-card">
              <div class="s5-cluster-title">${esc(sc.title)}</div>
              <p>${esc(sc.clinical_reasoning)}</p>
              <div class="lib-chip-cloud">
                ${(sc.formulas || []).slice(0, 3).map((x) => `<button class="entity-jump-chip badge-formula" type="button" data-jump-module="formulas" data-jump-id="${esc(x.id)}">${esc(x.title)}</button>`).join("")}
                ${(sc.bencao || []).slice(0, 3).map((x) => `<button class="entity-jump-chip badge-bencao" type="button" data-jump-module="bencao" data-jump-id="${esc(x.id)}">${esc(x.title)}</button>`).join("")}
                ${(sc.acupuncture_points || []).slice(0, 3).map((x) => `<button class="entity-jump-chip badge-acup" type="button" data-jump-module="acupuncture" data-jump-id="${esc(x.id)}">${esc(x.title)}</button>`).join("")}
              </div>
              <button class="primary-btn small-btn" type="button" data-s5-drill="${esc(sc.keywords.slice(0, 3).join(" "))}">展开四经辨证对照 →</button>
            </article>`
          )
          .join("")}
      </div>
    `;
  }

  // -------------------- Reverse Book Backlinks inside Existing Modules --------------------
  let _lastHydratedKey = "";
  function resolveActiveDetailFromHash() {
    const h = location.hash || "";
    let targetEl = null;
    let eid = "";
    const formulaPanel = $("#formula-detail");
    if (h.startsWith("#/formulas/") && !/\/(decoction|source|rationale|proof)$/.test(h)) {
      eid = decodeURIComponent(h.slice("#/formulas/".length));
      targetEl = formulaPanel;
    } else if (formulaPanel && formulaPanel.closest(".module-view.active") && formulaPanel.dataset.activeFormulaId) {
      eid = formulaPanel.dataset.activeFormulaId;
      targetEl = formulaPanel;
    } else if (h.startsWith("#/herbs/") && !/^#\/herbs\/(compare|chapters|page)\//.test(h) && h !== "#/herbs") {
      eid = decodeURIComponent(h.replace(/^#\/herbs\/(?:entry\/)?/, ""));
      targetEl = $("#bc-detail");
    } else if (/^#\/acupuncture\/(?:points|conditions|meridians|techniques)\//.test(h)) {
      const m = h.match(/^#\/acupuncture\/[^/]+\/(.+)$/);
      eid = m ? decodeURIComponent(m[1]) : "";
      targetEl = $("#acup-detail");
    } else if (/^#\/neijing\/(?:chapters?|concepts?)\//.test(h)) {
      const m = h.match(/^#\/neijing\/[^/]+\/(.+)$/);
      eid = m ? decodeURIComponent(m[1]) : "";
      targetEl = $("#nj-detail");
    } else if (/^#\/six\/([^/]+)/.test(h)) {
      const m = h.match(/^#\/six\/([^/]+?)(?:\/dossier)?$/);
      eid = m ? decodeURIComponent(m[1]) : "";
      targetEl = $("#six-detail");
    }
    return { targetEl, eid };
  }

  async function hydrateEntityInto(targetEl, eid, force = false) {
    if (!targetEl || !eid) return;
    if (!targetEl.textContent.trim() || targetEl.querySelector(".empty-state")) return;
    const key = `${targetEl.id}::${eid}`;
    if (!force && targetEl.querySelector(`.lib-xref-panel[data-xref-key="${CSS.escape(key)}"]`)) return;
    if (!force && _lastHydratedKey === key) return;
    _lastHydratedKey = key;

    try {
      const data = await api(`/api/library/entity-links/${encodeURIComponent(eid)}`);
      const refs = data.library_refs || [];
      const syns = data.related_syndromes || [];
      if (!refs.length && !syns.length) return;
      targetEl.querySelectorAll(".lib-xref-panel").forEach((n) => n.remove());
      const box = document.createElement("div");
      box.className = "lib-xref-panel";
      box.dataset.xrefKey = key;
      box.innerHTML = `
        <div class="lib-xref-head">
          <strong>书库原文与医案跨书互参（${refs.length} 处原文 · 点击滑开前后文对照）</strong>
          ${syns.map((s) => `<button class="entity-jump-chip badge-neijing" type="button" data-s5-jump-syndrome="${esc(s.title)}">综合辨证 · ${esc(s.title)}</button>`).join("")}
        </div>
        <div class="lib-xref-list">
          ${refs
            .slice(0, 10)
            .map((r) =>
              renderLibRefRow(r, {
                bodyHtml: `${renderShelfBadge(r.shelf)}<strong>《${esc(r.book_title)}》${esc(r.unit_label)}</strong>${
                  r.section_title ? ` <span class="lib-xref-sec">(${esc(String(r.section_title).slice(0, 26))})</span>` : ""
                } — ${esc(r.snippet)}`,
                probe: r.snippet,
              })
            )
            .join("")}
        </div>
      `;
      targetEl.appendChild(box);
    } catch {
      // Ignore silent cross-ref misses
    }
  }

  async function hydrateCurrentDetailLibraryLinks(force = false) {
    const { targetEl, eid } = resolveActiveDetailFromHash();
    await hydrateEntityInto(targetEl, eid, force);
  }

  const HANTANG_CHIPS = [
    { label: "HT-40 心脏术后", q: "HT-40" },
    { label: "胆切除 HT-84", q: "胆切除" },
    { label: "第5椎 · 红斑狼疮", q: "红斑" },
    { label: "热药冷服 · 格阳", q: "热药冷服" },
    { label: "白带 · 妇科带下", q: "白带" },
    { label: "痛风 HT-27", q: "痛风" },
  ];

  const HT_SAFETY_META = {
    standard: { cls: "safety-standard", text: "常规经方化裁" },
    high_risk: { cls: "safety-high_risk", text: "峻药高危 · 须严辨" },
    practitioner_only: { cls: "safety-practitioner_only", text: "重证剧毒 · 仅限一线执业" },
  };

  function groupExcludedPitfalls(pitfalls = []) {
    const groups = [];
    const byReason = new Map();
    for (const ex of pitfalls || []) {
      const reason = String(ex.why_excluded || "").trim();
      const name = String(ex.name || "").trim();
      if (!name) continue;
      if (!byReason.has(reason)) {
        const entry = { reason, names: [name] };
        byReason.set(reason, entry);
        groups.push(entry);
      } else {
        const entry = byReason.get(reason);
        if (!entry.names.includes(name)) entry.names.push(name);
      }
    }
    return groups;
  }

  function renderAnchorBtn(anchor, label = "原文参照") {
    if (!anchor || !anchor.book_id) return "";
    const pno = Number(anchor.page_no || anchor.page_hint || 0);
    const pTxt = pno > 0 ? ` · p.${pno}` : "";
    return `<button type="button" class="ghost-btn tiny-btn ctx-ref-btn" data-ctx-loc="1" data-ctx-book="${esc(anchor.book_id)}" data-ctx-page="${pno > 0 ? pno : ""}" data-ctx-q="${esc(anchor.q || "")}">${esc(label)}${pTxt}</button>`;
  }

  function renderHtEntityChips(classics = [], points = []) {
    const fHtml = (classics || [])
      .map((c) => `<button type="button" class="entity-jump-chip badge-formula" data-jump-module="formulas" data-jump-id="${esc(c.id)}">经方 · ${esc(c.name)}</button>`)
      .join("");
    const pHtml = (points || [])
      .map((p) => `<button type="button" class="entity-jump-chip badge-acup" data-jump-module="acupuncture" data-jump-id="${esc(p.id)}">穴 · ${esc(p.name)}</button>`)
      .join("");
    return fHtml || pHtml ? `<div class="entity-jump-strip">${fHtml}${pHtml}</div>` : "";
  }

  function renderStage5HantangSection(htCtx) {
    if (!htCtx) return "";
    const formulas = htCtx.hantang_formulas || [];
    const western = htCtx.western_history_guidance || [];
    const du = htCtx.du_spine_guides || [];
    const palp = htCtx.special_palpations || [];
    const redlines = htCtx.ht_redlines || [];
    if (!formulas.length && !western.length && !du.length && !palp.length && !redlines.length) return "";
    const prog = htCtx.prognosis_summary || {};
    return `
      <div class="s5-hantang-section">
        <div class="s5-ht-header">
          <strong>【汉唐百方 &amp; 倪氏人纪临床互参】</strong>
          <span class="s5-ht-badge partial-warn">仅作病机与取象立法示范 · 严禁直接抄方套用</span>
        </div>
        ${western
          .map(
            (w) => `<div class="s5-ht-alert-box">
              <strong>⚠️ 西医介入修正 · ${esc(w.title)}</strong>（触发：${esc((w.matched_triggers || []).join(" / "))}）<br/>
              <span><b>病机转归：</b>${esc(w.pathogenesis_shift)}</span><br/>
              <span><b>禁忌红线：</b>${esc(w.forbidden)}</span><br/>
              <span><b>替代方策：</b>${esc(w.guidance)}</span>
              <div class="s5-ht-ops">
                <div>${(w.linked_ht || []).map((ht) => `<button type="button" class="s5-ht-pill" data-hantang-focus="${esc(ht)}">${esc(ht)} 详参</button>`).join("")}</div>
                ${renderAnchorBtn(w.anchor, "《医案/百方》原文")}
              </div>
            </div>`
          )
          .join("")}
        ${
          du.length || palp.length || redlines.length
            ? `<div class="s5-ht-alert-box">
                ${du
                  .map(
                    (d) => `<div><strong>【督脉触诊】${esc(d.location)}：</strong>${esc(d.warning_target)} — ${esc(d.companion_cue)} ${
                      d.acupoint_id
                        ? `<button type="button" class="entity-jump-chip badge-acup" data-jump-module="acupuncture" data-jump-id="${esc(d.acupoint_id)}">穴 · ${esc(d.acupoint)}</button>`
                        : ""
                    } ${renderAnchorBtn(d.anchor, "原书定位")}</div>`
                  )
                  .join("")}
                ${palp
                  .map(
                    (p) => `<div><strong>【特异压痛点】${esc(p.name)}：</strong>${esc(p.differential)} ${renderAnchorBtn(p.anchor, "原文")}</div>`
                  )
                  .join("")}
                ${redlines
                  .map(
                    (r) => `<div><strong>【汉唐临床红线】${esc(r.title)}：</strong>${esc(r.rule)} ${renderAnchorBtn(r.anchor, r.ref || "出处")}</div>`
                  )
                  .join("")}
              </div>`
            : ""
        }
        ${
          formulas.length
            ? `<div class="s5-ht-grid">
                ${formulas
                  .map((h) => {
                    const sm = HT_SAFETY_META[h.safety_level] || HT_SAFETY_META.standard;
                    return `<article class="s5-ht-card">
                      <div class="s5-ht-card-head">
                        <span class="s5-ht-card-title">${esc(h.full_title)}</span>
                        <div class="s5-ht-badges">
                          <span class="s5-ht-badge ${sm.cls}">${esc(sm.text)}</span>
                          ${h.is_partial_disclosure ? `<span class="s5-ht-badge partial-warn">公开部分药味</span>` : ""}
                        </div>
                      </div>
                      <div class="s5-ht-layer s5-ht-layer-ni">
                        <span class="s5-ht-layer-label">【倪氏原论 · 主治与示例药味】</span>
                        <div>${esc(h.indications)}</div>
                        <div><b>示方药物：</b>${esc(h.partial_herbs)}</div>
                        <div><b>禁忌：</b>${esc(h.contraindications)}</div>
                      </div>
                      <div class="s5-ht-layer s5-ht-layer-ziji">
                        <span class="s5-ht-layer-label">【紫极讲者按语 &amp; 经方关联】</span>
                        <div>${esc(h.ziji_commentary)}</div>
                        ${renderHtEntityChips(h.linked_classical_formulas, h.linked_acupoints)}
                      </div>
                      <div class="s5-ht-ops">
                        <button type="button" class="s5-ht-pill" data-hantang-focus="${esc(h.ht_number)}">汉唐全库详览 ↗</button>
                        ${renderAnchorBtn(h.source_anchor, "《汉唐百方》原文")}
                      </div>
                    </article>`;
                  })
                  .join("")}
              </div>`
            : ""
        }
        ${
          (prog.seven_recovery_signs || []).length
            ? `<details class="s5-ht-prog-details">
                <summary>【倪氏疗效向愈判标速查（六准则 / 七大好转指针 / 逆证警讯）】</summary>
                <div style="margin-top:6px;">
                  <div><b>六大总则：</b>${esc((prog.ni_six_criteria || []).join(" ｜ "))}</div>
                  <div><b>七大向愈指征：</b>${esc((prog.seven_recovery_signs || []).join(" ｜ "))}</div>
                  <div><b>凶险逆证警讯：</b>${esc((prog.danger_reversal_signs || []).join(" ｜ "))}</div>
                  <div style="margin-top:6px;">${renderAnchorBtn(prog.anchor, "《汉唐医案集》倪氏六准则原文")}</div>
                </div>
              </details>`
            : ""
        }
      </div>
    `;
  }

  function renderHtFormulaCard(f) {
    const sm = HT_SAFETY_META[f.safety_level] || HT_SAFETY_META.standard;
    const ni = f.ni_original || {};
    const zj = f.ziji_note || {};
    return `
      <article class="s5-ht-card">
        <div class="s5-ht-card-head">
          <span class="s5-ht-card-title">${esc(f.full_title)}</span>
          <div class="s5-ht-badges">
            <span class="s5-ht-badge ${sm.cls}">${esc(sm.text)}</span>
            ${ni.is_partial_disclosure ? `<span class="s5-ht-badge partial-warn">……等 部分示药</span>` : ""}
          </div>
        </div>
        <div class="muted-line">${esc(f.category)}</div>
        <div class="s5-ht-layer s5-ht-layer-ni">
          <span class="s5-ht-layer-label">【倪氏原论 · 汉唐百方】</span>
          <div><b>主治适应证：</b>${esc(ni.indications)}</div>
          <div><b>核心病机：</b>${esc(ni.pathogenesis)}</div>
          <div><b>部分公开药味：</b>${esc(ni.partial_herbs)}</div>
          <div><b>服法/量度：</b>${esc(ni.dosage_method)}</div>
          <div><b>原书禁忌：</b>${esc(ni.contraindications)}</div>
        </div>
        <div class="s5-ht-layer s5-ht-layer-ziji">
          <span class="s5-ht-layer-label">【紫极讲者按语 · 孤立标示】</span>
          <div>${esc(zj.commentary)}</div>
          ${renderHtEntityChips(zj.linked_classical_formulas, zj.linked_acupoints)}
        </div>
        <div class="s5-ht-ops">
          <div class="muted-line">${esc((f.clinical_tags || []).slice(0, 4).join(" · "))}</div>
          ${renderAnchorBtn(f.source_anchor, "原文对照")}
        </div>
      </article>
    `;
  }

  function renderHtSubContent(ov, formulaRes) {
    const sub = st.htSubTab || "formulas";
    if (sub === "formulas") {
      const cats = ov.categories || [];
      const items = formulaRes?.items || [];
      return `
        <div class="s5-ht-filter-row">
          <button type="button" class="s5-ht-pill ${st.htCategory === "all" ? "active" : ""}" data-ht-cat="all">全部 (${ov.formula_count}方)</button>
          ${cats
            .map(
              (c) => `<button type="button" class="s5-ht-pill ${st.htCategory === c.id ? "active" : ""}" data-ht-cat="${esc(c.id)}">${esc(c.short)} (${c.count})</button>`
            )
            .join("")}
        </div>
        <div class="s5-ht-filter-row">
          <span class="muted-line">风险分级：</span>
          ${[
            ["all", "全部级别"],
            ["standard", "常规"],
            ["high_risk", "峻药高危"],
            ["practitioner_only", "重证仅限执业"],
          ]
            .map(
              ([k, lbl]) => `<button type="button" class="s5-ht-pill ${st.htSafety === k ? "active" : ""}" data-ht-safety="${k}">${lbl}</button>`
            )
            .join("")}
          <span class="muted-line">原书未公开缺号：HT-${esc((ov.missing_numbers || []).join(", "))}</span>
        </div>
        <div class="muted-line">当前显示 <strong>${items.length}</strong> 方${st.s5Query ? `（检索：${esc(st.s5Query)}）` : ""}</div>
        <div class="s5-ht-grid">
          ${items.length ? items.map(renderHtFormulaCard).join("") : `<div class="s5-empty-guide"><p>未找到匹配的汉唐方剂，请换关键词（如 HT-40、胆切除、白带、疼痛）或切换分类。</p></div>`}
        </div>
      `;
    }
    if (sub === "spine_palp") {
      return `
        <h4>一、督脉第 3 / 5 / 6 / 9 / 13 椎压痛早期预警系统</h4>
        <div class="s5-ht-grid">
          ${(ov.du_spine_diagnostics || [])
            .map(
              (d) => `<article class="s5-ht-card">
                <div class="s5-ht-card-head">
                  <span class="s5-ht-card-title">${esc(d.location)}</span>
                  <span class="s5-ht-badge safety-high_risk">${esc(d.organ)}</span>
                </div>
                <div><b>预警目标：</b>${esc(d.warning_target)}</div>
                <div><b>伴随印证：</b>${esc(d.companion_cue)}</div>
                <div class="s5-ht-ops">
                  ${d.acupoint_id ? `<button type="button" class="entity-jump-chip badge-acup" data-jump-module="acupuncture" data-jump-id="${esc(d.acupoint_id)}">督脉定位穴 · ${esc(d.acupoint)}</button>` : `<span>穴：${esc(d.acupoint)}</span>`}
                  ${renderAnchorBtn(d.anchor, "《汉唐医案集》原文")}
                </div>
              </article>`
            )
            .join("")}
        </div>
        <h4 style="margin-top:16px;">二、临床特异压痛点与头足冷热鉴诊指标</h4>
        <div class="s5-ht-grid">
          ${(ov.special_palpation_points || [])
            .map(
              (p) => `<article class="s5-ht-card">
                <div class="s5-ht-card-title">${esc(p.name)}</div>
                <div class="s5-ht-layer s5-ht-layer-ni">${esc(p.differential)}</div>
                <div class="s5-ht-ops"><span></span>${renderAnchorBtn(p.anchor, "原书对照")}</div>
              </article>`
            )
            .join("")}
        </div>
      `;
    }
    if (sub === "western") {
      return `
        <div class="s5-ht-grid">
          ${(ov.western_history_rules || [])
            .map(
              (w) => `<article class="s5-ht-card">
                <div class="s5-ht-card-title">${esc(w.title)}</div>
                <div class="muted-line">触发史关键词：${esc((w.triggers || []).join(" / "))}</div>
                <div class="s5-ht-layer s5-ht-layer-ni">
                  <div><b>经方病机演变：</b>${esc(w.pathogenesis_shift)}</div>
                  <div><b>禁用警戒：</b>${esc(w.forbidden)}</div>
                  <div><b>善后替代思路：</b>${esc(w.guidance)}</div>
                </div>
                <div>
                  ${(w.linked_ht || []).map((ht) => `<button type="button" class="s5-ht-pill" data-hantang-focus="${esc(ht)}">${esc(ht)}</button>`).join(" ")}
                </div>
                ${renderHtEntityChips(w.linked_classical_items, [])}
                <div class="s5-ht-ops"><span></span>${renderAnchorBtn(w.anchor, "原书详述")}</div>
              </article>`
            )
            .join("")}
        </div>
      `;
    }
    if (sub === "redlines") {
      const prog = ov.prognosis_and_recovery_criteria || {};
      return `
        <h4>一、汉唐百方十大高频高危禁忌红线</h4>
        <div class="s5-ht-grid">
          ${(ov.clinical_redlines || [])
            .map(
              (r) => `<article class="s5-ht-card">
                <div class="s5-ht-card-head">
                  <span class="s5-ht-card-title">${esc(r.title)}</span>
                  <span class="s5-ht-badge safety-practitioner_only">${esc(r.ref)}</span>
                </div>
                <div class="s5-ht-layer s5-ht-layer-ni">${esc(r.rule)}</div>
                <div class="s5-ht-ops">
                  ${r.anchor?.q ? `<button type="button" class="s5-ht-pill" data-hantang-focus="${esc(r.anchor.q.split(" ")[0])}">查看对应方卡</button>` : "<span></span>"}
                  ${renderAnchorBtn(r.anchor, "《汉唐百方》原文")}
                </div>
              </article>`
            )
            .join("")}
        </div>
        <h4 style="margin-top:16px;">二、倪氏治病六准则 &amp; 七大好转指针 &amp; 凶险逆证警讯</h4>
        <article class="s5-ht-card">
          <div><b>倪氏治病六准则（正常人金标）：</b></div>
          <ul>${(prog.ni_six_criteria || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          <div><b>七大攻邪向愈体征：</b></div>
          <ul>${(prog.seven_recovery_signs || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          <div style="color:#8f1d14;"><b>⚠️ 凶险逆证将脱警讯：</b></div>
          <ul style="color:#8f1d14;">${(prog.danger_reversal_signs || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
          <div class="s5-ht-layer s5-ht-layer-ziji"><span class="s5-ht-layer-label">【紫极五通总纲 · 讲者整理】</span>${esc(prog.five_passages_ziji)}</div>
          <div class="s5-ht-ops"><span></span>${renderAnchorBtn(prog.anchor, "《汉唐医案集》原文")}</div>
        </article>
      `;
    }
    return `
      <div class="s5-ht-grid">
        ${(ov.cases_index || [])
          .map(
            (cs) => `<article class="s5-ht-card">
              <div class="s5-ht-card-head">
                <span class="s5-ht-card-title">${esc(cs.title)}</span>
                <span class="s5-ht-badge safety-standard">${esc(cs.date)}</span>
              </div>
              <div class="s5-ht-layer s5-ht-layer-ni">${esc(cs.summary)}</div>
              <div>
                ${(cs.formulas || [])
                  .filter((fn) => fn.startsWith("HT-"))
                  .map((ht) => `<button type="button" class="s5-ht-pill" data-hantang-focus="${esc(ht)}">${esc(ht)}</button>`)
                  .join(" ")}
              </div>
              ${renderHtEntityChips(cs.linked_formula_items, cs.linked_acupoint_items)}
              <div class="s5-ht-ops"><span></span>${renderAnchorBtn(cs.anchor, "原书医案参照")}</div>
            </article>`
          )
          .join("")}
      </div>
    `;
  }

  async function renderHantangStudio(q = "") {
    const host = $("#s5-workspace-body");
    if (!host) return;
    host.innerHTML = `<div class="muted-line">正在加载汉唐 91 方、督脉触诊、西医介入禁忌与医案索引...</div>`;
    if (!st.htOverview) {
      st.htOverview = await api("/api/hantang/overview");
    }
    const ov = st.htOverview;
    let formulaRes = null;
    if (st.htSubTab === "formulas") {
      formulaRes = await api(
        `/api/hantang/formulas?category=${encodeURIComponent(st.htCategory)}&safety=${encodeURIComponent(st.htSafety)}&q=${encodeURIComponent(q)}`
      );
    }
    const subTabs = [
      ["formulas", `汉唐百方 (${ov.formula_count}方)`],
      ["spine_palp", `督脉5椎 & 特异触诊 (${(ov.du_spine_diagnostics || []).length + (ov.special_palpation_points || []).length})`],
      ["western", `七大西医介入善后 (${(ov.western_history_rules || []).length})`],
      ["redlines", `十大红线 & 向愈判标 (${(ov.clinical_redlines || []).length})`],
      ["cases", `重点临床医案 (${(ov.cases_index || []).length}案)`],
    ];
    host.innerHTML = `
      <div class="s5-ht-epistemic">${esc(ov.epistemic_notice)}</div>
      <div class="s5-ht-subtabs">
        ${subTabs
          .map(
            ([k, lbl]) => `<button type="button" class="s5-ht-pill ${st.htSubTab === k ? "active" : ""}" data-ht-subtab="${k}">${esc(lbl)}</button>`
          )
          .join("")}
      </div>
      ${renderHtSubContent(ov, formulaRes)}
    `;
  }

  function installBacklinkObservers() {
    if (typeof window.__tcmRenderFormulaDetail === "function" && !window.__tcmRenderFormulaWrapped) {
      const orig = window.__tcmRenderFormulaDetail;
      window.__tcmRenderFormulaWrapped = true;
      window.__tcmRenderFormulaDetail = function (item) {
        orig(item);
        if (item?.id) {
          const panel = $("#formula-detail");
          if (panel) panel.dataset.activeFormulaId = item.id;
          setTimeout(() => hydrateEntityInto($("#formula-detail"), item.id, true), 40);
        }
      };
    }
    window.addEventListener("hashchange", () => {
      if (location.hash.startsWith("#/library") || location.hash.startsWith("#/stage5")) {
        handleHash(location.hash).catch(() => {});
        return;
      }
      if (st.activeView) clearExtraViews();
      setTimeout(() => hydrateCurrentDetailLibraryLinks(false), 260);
    });
    ["#formula-detail", "#bc-detail", "#acup-detail", "#nj-detail", "#six-detail"].forEach((sel) => {
      const el = $(sel);
      if (!el) return;
      const obs = new MutationObserver((muts) => {
        const selfOnly = muts.every((m) => Array.from(m.addedNodes).every((n) => n.classList?.contains("lib-xref-panel")));
        if (selfOnly) return;
        setTimeout(() => hydrateCurrentDetailLibraryLinks(false), 180);
      });
      obs.observe(el, { childList: true });
    });
  }

  // -------------------- Hash Router & Global Event Binding --------------------
  async function handleHash(hashStr) {
    const mLib = hashStr.match(/^#\/library(?:\/([^/]+)(?:\/(\d+))?)?/);
    if (mLib) {
      activateTopView("library", true);
      if (!st.libBooks.length) await loadLibraryBooks("");
      const bid = mLib[1] ? decodeURIComponent(mLib[1]) : st.selectedBookId;
      const pno = mLib[2] ? Number(mLib[2]) : 1;
      await selectBook(bid, pno, true);
      return true;
    }
    const mS5 = hashStr.match(/^#\/stage5(?:\/(compose|diagnose|ground|syndromes))?/);
    if (mS5) {
      activateTopView("stage5", true);
      await activateStage5(mS5[1] || "compose", true);
      return true;
    }
    return false;
  }

  function bindEvents() {
    // Switching between 4 core module tabs and Stage 5 / Standalone Book Library
    document.querySelectorAll(".module-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        clearExtraViews();
        setTimeout(() => hydrateCurrentDetailLibraryLinks(true), 240);
      });
    });

    document.querySelectorAll(".top-utility-tab").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const view = btn.dataset.stage5View;
        activateTopView(view, false);
        if (view === "library") {
          if (!st.libBooks.length) await loadLibraryBooks("");
          if (!st.selectedBook) await selectBook(st.selectedBookId, st.currentPageNo, true);
        } else if (view === "stage5") {
          await activateStage5(st.s5Mode, true);
        }
      });
    });

    // Global delegated clicks across Stage 5, Library, Context Drawer & Backlink panels
    document.addEventListener("click", async (e) => {
      const ctxLocBtn = e.target.closest("[data-ctx-loc]");
      if (ctxLocBtn) {
        e.preventDefault();
        await openContextDrawer({
          bookId: ctxLocBtn.dataset.ctxBook || "",
          pageNo: Number(ctxLocBtn.dataset.ctxPage || 0),
          line: Number(ctxLocBtn.dataset.ctxLine || 0),
          bookHint: ctxLocBtn.dataset.ctxHint || "",
          q: ctxLocBtn.dataset.ctxQ || "",
        });
        return;
      }
      if (e.target.closest("#ctx-close-btn") || e.target === $("#ctx-drawer-backdrop")) {
        closeContextDrawer();
        return;
      }
      if (e.target.closest("#ctx-open-lib-btn")) {
        const bid = ctxSt.bookId;
        const pno = ctxSt.activePageNo;
        const hl = ctxSt.highlightQuery;
        closeContextDrawer();
        if (bid) await openBookPageFromAnywhere(bid, pno || 1, hl);
        return;
      }
      if (e.target.closest("#ctx-toggle-index")) {
        const keepPage = ctxSt.activePageNo;
        ctxSt.showIndex = !ctxSt.showIndex;
        renderContextDrawer();
        scrollCtxToTarget(keepPage, false);
        return;
      }
      const ctxJump = e.target.closest("[data-ctx-jump-page]");
      if (ctxJump) {
        await jumpCtxToPage(Number(ctxJump.dataset.ctxJumpPage), ctxJump.dataset.ctxJumpHl || "");
        return;
      }
      if (e.target.closest("#ctx-index-search-btn")) {
        await searchInsideCtxBook($("#ctx-index-search")?.value || "");
        return;
      }
      if (e.target.closest("#ctx-index-reset-btn")) {
        ctxSt.indexSearchQuery = "";
        ctxSt.indexSearchHits = null;
        ctxSt.indexFilter = "";
        const inp = $("#ctx-index-search");
        if (inp) inp.value = "";
        updateCtxIndexDomOnly();
        return;
      }
      if (e.target.id === "ctx-jump-go") {
        await jumpCtxToPage(Number($("#ctx-jump-inp")?.value || 1));
        return;
      }
      const ctxVmode = e.target.closest("[data-ctx-vmode]");
      if (ctxVmode) {
        const keepPage = ctxSt.activePageNo;
        ctxSt.viewMode = ctxVmode.dataset.ctxVmode;
        renderContextDrawer();
        scrollCtxToTarget(keepPage, false);
        return;
      }
      const ctxReflow = e.target.closest("[data-ctx-reflow]");
      if (ctxReflow) {
        const keepPage = ctxSt.activePageNo;
        ctxSt.reflowText = ctxReflow.dataset.ctxReflow === "true";
        renderContextDrawer();
        scrollCtxToTarget(keepPage, false);
        return;
      }
      if (e.target.closest("#ctx-load-prev")) {
        await loadCtxDirection("up");
        return;
      }
      if (e.target.closest("#ctx-load-next")) {
        await loadCtxDirection("down");
        return;
      }
      const ctxSync = e.target.closest("[data-ctx-sync-scan]");
      if (ctxSync) {
        const pno = Number(ctxSync.dataset.ctxSyncScan) || ctxSt.activePageNo;
        const pg = ctxSt.pages.find((p) => p.page_no === pno);
        if (pg) {
          updateCtxSyncedScan(pg);
          syncCtxActivePage(pno, { updateScan: false });
        }
        return;
      }
      if (e.target.id === "ctx-scan-prev" || e.target.id === "ctx-scan-next") {
        const isPrev = e.target.id === "ctx-scan-prev";
        const targetP = Math.max(1, Math.min(ctxSt.totalUnits, ctxSt.activePageNo + (isPrev ? -1 : 1)));
        if (targetP !== ctxSt.activePageNo) {
          if (targetP < ctxSt.startPage) await loadCtxDirection("up");
          else if (targetP > ctxSt.endPage) await loadCtxDirection("down");
          const pg = ctxSt.pages.find((p) => p.page_no === targetP);
          if (pg) {
            updateCtxSyncedScan(pg);
            syncCtxActivePage(targetP, { updateScan: false });
            scrollCtxToTarget(targetP, false);
          }
        }
        return;
      }
      const shelfBtn = e.target.closest("#lib-shelf-tabs [data-lib-shelf]");
      if (shelfBtn) {
        await loadLibraryBooks(shelfBtn.dataset.libShelf || "");
        return;
      }
      const bookBtn = e.target.closest("[data-lib-select-book]");
      if (bookBtn) {
        await selectBook(bookBtn.dataset.libSelectBook, 1, false);
        return;
      }
      const tocPageBtn = e.target.closest("[data-lib-go-page]");
      if (tocPageBtn) {
        await loadBookPage(st.selectedBookId, Number(tocPageBtn.dataset.libGoPage), false);
        return;
      }
      const libOpenBtn = e.target.closest("[data-lib-open]");
      if (libOpenBtn) {
        const [bid, pstr] = libOpenBtn.dataset.libOpen.split(":");
        await openBookPageFromAnywhere(bid, Number(pstr) || 1, libOpenBtn.dataset.libHl || "");
        return;
      }
      const jumpBtn = e.target.closest("[data-jump-module][data-jump-id]");
      if (jumpBtn) {
        if (ctxSt.open) closeContextDrawer();
        await jumpToModuleEntity(jumpBtn.dataset.jumpModule, jumpBtn.dataset.jumpId);
        return;
      }
      if (e.target.closest("#lib-back-to-search-btn")) {
        const panel = $("#lib-search-results-panel");
        const ws = $("#lib-reader-workspace");
        if (panel && panel.innerHTML.trim()) {
          st.searchActive = true;
          panel.classList.remove("hidden");
          ws?.classList.add("hidden");
        } else if (st.lastSearchQuery) {
          await runLibrarySearch(st.lastSearchQuery);
        }
        return;
      }
      const layoutBtn = e.target.closest("[data-lib-layout]");
      if (layoutBtn) {
        const nextLayout = layoutBtn.dataset.libLayout === "single" ? "single" : "continuous";
        if (nextLayout !== st.readLayout) {
          st.readLayout = nextLayout;
          st.loadedPages = [];
          await loadBookPage(st.selectedBookId, st.currentPageNo, true);
        }
        return;
      }
      if (e.target.closest("#lib-load-prev-chunk")) {
        await loadContextDirection("up");
        return;
      }
      if (e.target.closest("#lib-load-next-chunk")) {
        await loadContextDirection("down");
        return;
      }
      const syncBtn = e.target.closest("[data-lib-sync-scan]");
      if (syncBtn) {
        const pno = Number(syncBtn.dataset.libSyncScan) || st.currentPageNo;
        const pg = st.loadedPages.find((p) => p.page_no === pno) || st.pageData;
        if (pg) {
          updateSyncedScanImage(pg);
          syncActivePageIndicators(pno, { updateScan: false });
        }
        return;
      }
      if (e.target.id === "lib-prev-btn" || e.target.id === "lib-scan-prev") {
        const cur = st.currentPageNo || st.pageData?.page_no || 1;
        if (cur > 1) await loadBookPage(st.selectedBookId, cur - 1, false);
        return;
      }
      if (e.target.id === "lib-next-btn" || e.target.id === "lib-scan-next") {
        const cur = st.currentPageNo || st.pageData?.page_no || 1;
        const total = st.pageData?.total_units || st.selectedBook?.total_units || cur;
        if (cur < total) await loadBookPage(st.selectedBookId, cur + 1, false);
        return;
      }
      if (e.target.id === "lib-jump-go") {
        const val = Number($("#lib-jump-input")?.value || 1);
        await loadBookPage(st.selectedBookId, val, false);
        return;
      }
      const vmodeBtn = e.target.closest("[data-lib-vmode]");
      if (vmodeBtn) {
        const keepPage = st.currentPageNo;
        st.viewMode = vmodeBtn.dataset.libVmode;
        renderReaderPage();
        if (st.readLayout === "continuous") scrollToPageAnchor(keepPage, false);
        return;
      }
      const reflowBtn = e.target.closest("[data-lib-reflow]");
      if (reflowBtn) {
        const keepPage = st.currentPageNo;
        st.reflowText = reflowBtn.dataset.libReflow === "true";
        renderReaderPage();
        if (st.readLayout === "continuous") scrollToPageAnchor(keepPage, false);
        return;
      }
      const s5ModeBtn = e.target.closest("[data-s5-mode]");
      if (s5ModeBtn) {
        await activateStage5(s5ModeBtn.dataset.s5Mode, false);
        return;
      }
      const composePreset = e.target.closest("[data-compose-preset]");
      if (composePreset) {
        const q = composePreset.dataset.composePreset || "";
        const pulseStr = composePreset.dataset.composePulse || "";
        const pulseList = pulseStr.split(/\s+/).filter(Boolean);
        await runStage5Compose(q, pulseList);
        return;
      }
      const pulseBtn = e.target.closest("[data-toggle-pulse]");
      if (pulseBtn) {
        const pid = pulseBtn.dataset.togglePulse;
        const nextPulses = st.s5Pulses.includes(pid) ? st.s5Pulses.filter((x) => x !== pid) : [...st.s5Pulses, pid];
        await runStage5Compose($("#s5-query-input")?.value || st.s5Query, nextPulses);
        return;
      }
      const symBtn = e.target.closest("[data-toggle-symptom]");
      if (symBtn) {
        const tok = symBtn.dataset.toggleSymptom || "";
        let cur = ($("#s5-query-input")?.value || st.s5Query || "").trim();
        const parts = tok.split(/\s+/).filter(Boolean);
        const allPresent = parts.every((p) => cur.includes(p));
        if (allPresent) {
          parts.forEach((p) => {
            cur = cur.replaceAll(p, "");
          });
          cur = cur.replace(/^[，,\s、]+|[，,\s、]+$/g, "").replace(/[，,\s、]{2,}/g, "，");
        } else {
          const toAdd = parts.filter((p) => !cur.includes(p));
          cur = cur ? `${cur}，${toAdd.join("，")}` : toAdd.join("，");
        }
        await runStage5Compose(cur, st.s5Pulses);
        return;
      }
      const entryBtn = e.target.closest("[data-entry-query]");
      if (entryBtn) {
        const q = entryBtn.dataset.entryQuery || "";
        const drawer = entryBtn.closest(".s5-catalog-drawer");
        if (drawer) drawer.open = false;
        await runStage5Compose(q, st.s5Pulses);
        return;
      }
      const catTab = e.target.closest("[data-s5-cat-tab]");
      if (catTab) {
        st.s5CatFilter = catTab.dataset.s5CatTab || "全部";
        updateS5CatalogDomOnly();
        return;
      }
      const rmSymBtn = e.target.closest("[data-remove-symptom]");
      if (rmSymBtn) {
        const sym = rmSymBtn.dataset.removeSymptom || "";
        const cur = ($("#s5-query-input")?.value || st.s5Query || "").trim();
        const nextQ = removeSymptomFromQuery(cur, sym, st.s5Data);
        await runStage5Compose(nextQ, st.s5Pulses);
        return;
      }
      const copyRxBtn = e.target.closest("[data-copy-rx]");
      if (copyRxBtn && st.s5Data) {
        const d = st.s5Data;
        const reg = (d.compound_regimens || [])[0];
        const rxLines = [
          `【辨证主诉】${st.s5Query || (d.recognized_symptoms || []).join("、")}`,
          ...(reg?.formulas_detail || []).map((fd) => {
            const herbs = (fd.ingredients || []).map((i) => `${i.name}${i.dose ? "(" + i.dose + (i.processing ? "·" + i.processing : "") + ")" : ""}`).join(" ");
            return `【参考经方】${fd.name}（${fd.book || ""} · ${fd.six_meridian || ""}）\n  组成与原量：${herbs || fd.composition_raw}\n  煎服法：${fd.decoction || "见原典"}`;
          }),
          `【针灸配穴】${(d.acupoint_protocol?.primary || []).map((p) => `${p.name}(${p.role})`).join("、") || "无"}`,
          "※ 以上仅供中医经典研习参考，抓药临床使用前务必经执业医师四诊合参并核对剂量。",
        ].join("\n");
        const stEl = $("#s5-rx-copy-status");
        try {
          if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(rxLines);
          } else {
            const ta = document.createElement("textarea");
            ta.value = rxLines;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
          }
          if (stEl) stEl.textContent = "✓ 已复制处方与原典剂量文本";
        } catch (_err) {
          if (stEl) stEl.textContent = "剪贴板受限，请直接查看上方处方药味";
        }
        return;
      }
      const sendAiBtn = e.target.closest("[data-send-to-ai]");
      if (sendAiBtn && st.s5Data) {
        const d = st.s5Data;
        const pulseStr = (d.recognized_pulses || st.s5Pulses || []).map((p) => "脉" + p).join(" ");
        const tongueStr = (d.recognized_tongues || []).join(" ");
        const rawQ = (st.s5Query || (d.recognized_symptoms || []).join(" ")).trim();
        const fullPrompt = [rawQ, pulseStr, tongueStr].filter(Boolean).join(" ").trim();
        if (window.niAI?.startConsultation) {
          clearExtraViews();
          location.hash = "#/ai";
          window.scrollTo({ top: 0, behavior: "instant" });
          await window.niAI.startConsultation(fullPrompt);
        } else if (window.niAI) {
          await window.niAI.activate();
          if (typeof window.__tcmSetView === "function") window.__tcmSetView("ai");
          clearExtraViews();
          location.hash = "#/ai";
          window.scrollTo({ top: 0, behavior: "instant" });
          await window.niAI.createNewSession({ clearPinned: true });
          const aiInp = $("#ai-query-input");
          if (aiInp) aiInp.value = fullPrompt;
          await window.niAI.submitConsultation(fullPrompt);
        }
        return;
      }
      const fqBtn = e.target.closest("[data-followup-token], [data-followup-pulse]");
      if (fqBtn) {
        const pid = (fqBtn.dataset.followupPulse || "").trim();
        const tok = (fqBtn.dataset.followupToken || "").trim();
        let nextPulses = [...st.s5Pulses];
        let cur = ($("#s5-query-input")?.value || st.s5Query || "").trim();
        if (pid) {
          nextPulses = nextPulses.includes(pid) ? nextPulses : [...nextPulses, pid];
        } else if (tok) {
          const parts = tok.split(/\s+/).filter(Boolean);
          const toAdd = parts.filter((p) => !cur.includes(p));
          if (toAdd.length) {
            cur = cur ? `${cur} ${toAdd.join(" ")}` : toAdd.join(" ");
          }
        }
        await runStage5Compose(cur, nextPulses);
        return;
      }
      const s5Chip = e.target.closest("[data-s5-chip]");
      if (s5Chip) {
        const q = s5Chip.dataset.s5Chip;
        st.s5Query = q;
        const inp = $("#s5-query-input");
        if (inp) inp.value = q;
        if (st.s5Mode === "ground") await runStage5Ground(q);
        else if (st.s5Mode === "compose") await runStage5Compose(q, st.s5Pulses);
        else if (st.s5Mode === "hantang") {
          st.htSubTab = "formulas";
          await renderHantangStudio(q);
        } else await runStage5Diagnose(q);
        return;
      }
      const htSubBtn = e.target.closest("[data-ht-subtab]");
      if (htSubBtn) {
        st.htSubTab = htSubBtn.dataset.htSubtab || "formulas";
        await renderHantangStudio(st.s5Query);
        return;
      }
      const htCatBtn = e.target.closest("[data-ht-cat]");
      if (htCatBtn) {
        st.htCategory = htCatBtn.dataset.htCat || "all";
        await renderHantangStudio(st.s5Query);
        return;
      }
      const htSafeBtn = e.target.closest("[data-ht-safety]");
      if (htSafeBtn) {
        st.htSafety = htSafeBtn.dataset.htSafety || "all";
        await renderHantangStudio(st.s5Query);
        return;
      }
      const htFocusBtn = e.target.closest("[data-hantang-focus]");
      if (htFocusBtn) {
        const q = htFocusBtn.dataset.hantangFocus || "";
        st.s5Query = q;
        st.htSubTab = "formulas";
        st.htCategory = "all";
        st.htSafety = "all";
        const inp = $("#s5-query-input");
        if (inp) inp.value = q;
        await activateStage5("hantang", false);
        return;
      }
      const s5Drill = e.target.closest("[data-s5-drill]");
      if (s5Drill) {
        st.s5Query = s5Drill.dataset.s5Drill;
        await activateStage5("diagnose", false);
        return;
      }
      const s5SynJump = e.target.closest("[data-s5-jump-syndrome]");
      if (s5SynJump) {
        activateTopView("stage5", false);
        st.s5Query = s5SynJump.dataset.s5JumpSyndrome.replace(/[（(].*$/, "");
        await activateStage5("diagnose", false);
        return;
      }
      const copyAiBtn = e.target.closest("[data-copy-ai]");
      if (copyAiBtn && st.s5Data?.ai_ready_case_packet) {
        const pkt = st.s5Data.ai_ready_case_packet;
        const mode = copyAiBtn.dataset.copyAi;
        const payload =
          mode === "json"
            ? JSON.stringify(pkt, null, 2)
            : [
                "你是一位严守《伤寒论》《金匮要略》《黄帝内经》《神农本草经》与倪海厦人纪辨证体系的中医学术研习助手（严禁超越学术范畴直接代客开具临床处方）。",
                `【四诊采集】症状：${(pkt.recognized_symptoms || []).join("、") || "无"}；已排空否定：${(pkt.negated_terms || []).join("、") || "无"}；脉象：${(pkt.recognized_pulses || []).join(" ") || "未定"}；舌象：${(pkt.recognized_tongues || []).join("、") || "未定"}`,
                `【主轴推演】候选合方/单方：${(pkt.proposed_compound || []).join(" + ") || "暂无"}；同步取穴：${(pkt.proposed_acupoints || []).join("、") || "暂无"}`,
                `【已拦截误治与红线】排除方：${(pkt.excluded_pitfalls || []).map((x) => `${x.name}（${x.why_excluded}）`).join("；") || "无"}；红线：${(pkt.classical_redlines || []).map((r) => r.title).join("、") || "无"}`,
                `【循证引用约束】仅可引用以下原文 SHA-256 锚点阐述病机与鉴别：${(pkt.grounded_citations || []).map((c) => `《${c.book}》${c.unit} [${String(c.sha256 || "").slice(0, 10)}]`).join("；")}`,
              ].join("\n");
        const statusEl = $("#s5-ai-copy-status");
        try {
          if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(payload);
          } else {
            const ta = document.createElement("textarea");
            ta.value = payload;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
          }
          if (statusEl) statusEl.textContent = mode === "json" ? "✓ 已复制结构化 JSON 病案包" : "✓ 已复制大模型循证提问词模板";
        } catch (_err) {
          if (statusEl) statusEl.textContent = "浏览器剪贴板受限，请展开下方 JSON 手动复制";
        }
        return;
      }
      if (e.target.closest("#s5-clear-selected-btn")) {
        $("#s5-reset-btn")?.click();
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && ctxSt.open) {
        closeContextDrawer();
        return;
      }
      if (e.key === "Enter" && e.target?.id === "lib-jump-input") {
        e.preventDefault();
        $("#lib-jump-go")?.click();
        return;
      }
      if (e.key === "Enter" && e.target?.id === "ctx-jump-inp") {
        e.preventDefault();
        $("#ctx-jump-go")?.click();
        return;
      }
      if (e.key === "Enter" && e.target?.id === "ctx-index-search") {
        e.preventDefault();
        searchInsideCtxBook(e.target.value);
      }
    });

    document.addEventListener("input", (e) => {
      if (e.target?.id === "ctx-index-search") {
        ctxSt.indexFilter = e.target.value;
        ctxSt.indexSearchHits = null;
        updateCtxIndexDomOnly();
        return;
      }
      if (e.target?.id === "s5-sym-cat-search") {
        st.s5CatSearch = e.target.value;
        updateS5CatalogDomOnly();
      }
    });

    $("#lib-toc-filter")?.addEventListener("input", (e) => {
      if (st.selectedBook) renderBookToc(st.selectedBook, e.target.value);
    });
    $("#lib-global-search-btn")?.addEventListener("click", () => runLibrarySearch($("#lib-global-search-input")?.value));
    $("#lib-global-search-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runLibrarySearch(e.target.value);
    });
    $("#lib-global-clear-btn")?.addEventListener("click", () => {
      const inp = $("#lib-global-search-input");
      if (inp) inp.value = "";
      runLibrarySearch("");
    });

    let composeDebounceTimer = null;
    const scheduleLiveCompose = () => {
      if (st.s5Mode !== "compose") return;
      clearTimeout(composeDebounceTimer);
      composeDebounceTimer = setTimeout(() => {
        const val = $("#s5-query-input")?.value || "";
        runStage5Compose(val, st.s5Pulses);
      }, 320);
    };
    $("#s5-query-input")?.addEventListener("input", (e) => {
      if (e.isComposing || st.s5Mode !== "compose") return;
      scheduleLiveCompose();
    });
    $("#s5-query-input")?.addEventListener("compositionend", () => {
      if (st.s5Mode !== "compose") return;
      scheduleLiveCompose();
    });

    $("#s5-submit-btn")?.addEventListener("click", async () => {
      clearTimeout(composeDebounceTimer);
      const q = $("#s5-query-input")?.value || "";
      st.s5Query = q;
      if (st.s5Mode === "compose") await runStage5Compose(q, st.s5Pulses);
      else if (st.s5Mode === "ground") await runStage5Ground(q);
      else if (st.s5Mode === "syndromes") await renderSyndromesAtlas(q);
      else if (st.s5Mode === "hantang") {
        st.htSubTab = "formulas";
        await renderHantangStudio(q);
      } else await runStage5Diagnose(q);
    });
    $("#s5-query-input")?.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        clearTimeout(composeDebounceTimer);
        $("#s5-submit-btn")?.click();
      }
    });
    $("#s5-reset-btn")?.addEventListener("click", async () => {
      clearTimeout(composeDebounceTimer);
      st.s5Query = "";
      st.s5Pulses = [];
      st.htCategory = "all";
      st.htSafety = "all";
      const inp = $("#s5-query-input");
      if (inp) inp.value = "";
      await activateStage5(st.s5Mode, false);
    });

    installBacklinkObservers();
  }

  bindEvents();
  syncSyndromeTabCount();
  window.libraryStage5 = {
    handleHash,
    openBookPage: openBookPageFromAnywhere,
    openContextDrawer,
    closeContextDrawer,
    jumpToEntity: jumpToModuleEntity,
    hydrateBacklinks: hydrateCurrentDetailLibraryLinks,
  };
})();
