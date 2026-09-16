/* ============================================================
   VerdictAI · 应用外壳脚本
   ------------------------------------------------------------
   职责（刻意保持单一，不触碰 app-core.js / app-ui.js 的业务逻辑）：
     1. 左侧多级目录：分组展开/折叠 + 当前项高亮
     2. 目录叶子 -> 设置面板：openPane(name) 桥接 switchTab
     3. 落地页三步卡片：Step2 在有预处理结果时自动展开
     4. 侧栏折叠/展开（桌面上折叠为窄条，移动端转抽屉）
   约定：
     - 目录中映射到设置面板的叶子必须带 class="tab" + data-tab，
       因为 switchTab() 用全局 .tab / .tabpane 选择器做联动。
     - 绝不使用 .tab 之外的类名承载 switchTab 的联动职责。
   ============================================================ */
(function () {
  "use strict";

  const SIDEBAR_KEY = "vai_sidebar_collapsed";
  const NAV_OPEN_KEY = "vai_nav_open";

  const $ = (id) => document.getElementById(id);

  /* ---------- 1. 多级目录：分组展开 / 折叠 ---------- */
  window.toggleNavGroup = function (head) {
    const group = head.closest(".navgroup");
    if (!group) return;
    const open = group.classList.toggle("open");
    head.setAttribute("aria-expanded", String(open));
    saveNavState();
  };

  function saveNavState() {
    try {
      const open = Array.from(document.querySelectorAll(".navgroup.open"))
        .map((g) => g.dataset.group || g.querySelector(".navhead")?.textContent || "")
        .filter(Boolean);
      localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(open));
    } catch (e) { /* localStorage 不可用时忽略 */ }
  }

  function restoreNavState() {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem(NAV_OPEN_KEY) || "[]"); } catch (e) { saved = []; }
    if (!saved.length) return;
    document.querySelectorAll(".navgroup").forEach((g) => {
      const key = g.dataset.group || g.querySelector(".navhead")?.textContent || "";
      if (saved.includes(key)) {
        g.classList.add("open");
        g.querySelector(".navhead")?.setAttribute("aria-expanded", "true");
      }
    });
  }

  /* ---------- 2. 目录叶子 -> 设置面板 ----------
     openSettings() 内部会先 switchTab("engine") 复位，
     因此必须「先 openSettings 再 switchTab(target)」，顺序不可颠倒。
     懒加载钩子（案例库/知识库的数据刷新）原先硬编码在旧标签条的
     内联 onclick 上，随标签条移除后在此保留：
       - library: refreshCaseLibrary()（内部已调用 refreshDebates，
         因此不再单独调 refreshDebates，避免重复请求 /api/debates）
       - kb:      loadKnowledge()
       - switchTab 自身负责 board -> renderBoard / agents -> renderAgentConfig
  */
  window.openPane = function (name, anchor) {
    try { openSettings(); } catch (e) { /* 面板不存在时静默降级 */ }
    try { switchTab(name); } catch (e) { /* 同上 */ }
    if (name === "library") { try { refreshCaseLibrary(); } catch (e) {} }
    if (name === "kb") { try { loadKnowledge(); } catch (e) {} }

    highlightNav(name);
    closeDrawerOnMobile();

    if (anchor === "debates") { scrollWithinModal("debateListAnchor"); }
    if (anchor === "usage") { scrollWithinModal("usageCard"); }
    if (anchor === "preset") { scrollWithinModal("presetAnchor"); }
  };

  function scrollWithinModal(id) {
    const el = $(id);
    if (!el) return;
    // 抽屉打开后再滚动，避免布局未完成导致偏移
    setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }

  function highlightNav(name) {
    document.querySelectorAll(".navleaf.tab").forEach((b) => {
      b.classList.toggle("current", b.dataset.tab === name);
    });
  }

  // 窄屏下侧栏是覆盖式抽屉，选中导航后收起，避免遮挡后续内容
  function closeDrawerOnMobile() {
    if (window.innerWidth <= 900) toggleSidebar(true);
  }

  /* ---------- 3. 视图切换：打开工作区 ---------- */
  window.openWorkspace = function () {
    try {
      if (typeof hideLanding === "function") { hideLanding(); return; }
    } catch (e) { /* 落回手工切换 */ }
    const l = $("landing"), w = $("workspace");
    if (l) l.classList.add("hidden");
    if (w) w.classList.remove("hidden");
  };

  /* ---------- 4. 侧栏折叠 / 展开 ---------- */
  window.toggleSidebar = function (force) {
    const sb = $("sidebar");
    if (!sb) return;
    const collapsed = (force === undefined) ? !sb.classList.contains("collapsed") : !!force;
    sb.classList.toggle("collapsed", collapsed);
    try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (e) {}
  };

  /* ---------- 5. 落地页三步卡联动 ----------
     Step2 折叠时若预处理舞台出现内容，用户会看不到 AI 分析结果，
     因此用 MutationObserver 监听 #ppStage / #intakeCard 的 hidden 变化自动展开。 */
  function setupStepAutoOpen() {
    const fold = $("foldStep2");
    if (!fold) return;
    const targets = ["ppStage", "intakeCard"].map($).filter(Boolean);
    if (!targets.length) return;
    const maybeOpen = () => {
      const anyVisible = targets.some((el) => !el.classList.contains("hidden"));
      if (anyVisible) fold.open = true;
    };
    maybeOpen();
    if (typeof MutationObserver === "function") {
      const obs = new MutationObserver(maybeOpen);
      targets.forEach((el) => obs.observe(el, { attributes: true, attributeFilter: ["class", "style"] }));
    }
  }

  // 窄屏下侧栏是覆盖式抽屉：点任何导航叶子后自动收起，避免遮挡正文。
  // 用事件委托覆盖全部叶子（含 goHome / openHelp 等外部处理器），
  // 折叠按钮与分组标题除外——它们是「操作抽屉本身」而非跳转。
  function setupDrawerAutoClose() {
    const tree = document.querySelector(".navtree");
    if (!tree) return;
    tree.addEventListener("click", (e) => {
      const t = e.target;
      if (t.closest && (t.closest(".sidebar-collapse") || !t.closest(".navleaf"))) return;
      if (window.innerWidth <= 900) toggleSidebar(true);
    });
  }

  // 抽屉展开时点空白处收起（☰ 自身与侧栏内部点击除外）
  function setupOutsideClose() {
    document.addEventListener("click", (e) => {
      const sb = $("sidebar");
      if (!sb || sb.classList.contains("collapsed")) return;
      if (window.innerWidth > 900) return;
      const t = e.target;
      if (t.closest && (t.closest("#sidebar") || t.closest(".sidebar-expand"))) return;
      toggleSidebar(true);
    }, true);
  }

  /* ---------- 初始化 ---------- */
  function init() {
    restoreNavState();
    setupStepAutoOpen();
    setupDrawerAutoClose();
    setupOutsideClose();
    let pref = null;
    try { pref = localStorage.getItem(SIDEBAR_KEY); } catch (e) {}
    // 有显式偏好则沿用；窄屏首次访问默认收起，避免抽屉盖住正文
    if (pref === "1" || (pref === null && window.innerWidth <= 900)) {
      $("sidebar")?.classList.add("collapsed");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
