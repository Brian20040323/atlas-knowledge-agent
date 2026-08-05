const chatEl = document.getElementById("chat");
const chatScroll = document.getElementById("chatScroll");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stopGen");
const navChatBtn = document.getElementById("navChat");
const modeBadge = document.getElementById("modeBadge");
const statusDot = document.getElementById("statusDot");
const deepThinkToggle = document.getElementById("deepThink");
const learnForm = document.getElementById("learnForm");
const learnTitle = document.getElementById("learnTitle");
const learnContent = document.getElementById("learnContent");
const knowledgeList = document.getElementById("knowledgeList");
const newChatBtn = document.getElementById("newChatBtn");
const menuBtn = document.getElementById("menuBtn");
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const convList = document.getElementById("convList");
const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const fileCaption = document.getElementById("fileCaption");
const uploadStatus = document.getElementById("uploadStatus");
const voiceBtn = document.getElementById("voiceBtn");
const speakBtn = document.getElementById("speakBtn");
const ttsHint = document.getElementById("ttsHint");
const voiceSampleInput = document.getElementById("voiceSampleInput");
const voiceSampleBtn = document.getElementById("voiceSampleBtn");
const voiceSampleStatus = document.getElementById("voiceSampleStatus");
let ttsReady = false;
let ttsAudio = null;
let chatAbort = null;
let generating = false;
/** Docs imported in this browser session — shown as composer chips */
let sessionDocs = [];

const STORAGE_KEY = "ai_fullstack_conversation_id";
const history = [];
let conversationId = localStorage.getItem(STORAGE_KEY);
let showingEmpty = false;
let lastAssistantText = "";
let recognition = null; // unused legacy
let listening = false;
let listenIntent = false;
let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let sttReady = false;
/** Prevent overlapping start/stop/recognize (same tab). */
let voiceBusy = false;
/** Cross-tab lock so only one Atlas tab records at a time. */
const VOICE_LOCK_KEY = "atlas_voice_lock";
const VOICE_LOCK_TTL_MS = 120000;
const voiceTabId = `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
let defaultPlaceholder =
  input?.getAttribute("placeholder") || input?.placeholder || "询问制度、文档或业务问题…";
let currentUser = null;
let authMode = "login";
let lastHealthMeta = { model: "—", mode: "", kb: 0 };

async function apiFetch(url, options = {}) {
  const opts = { ...options, credentials: "include" };
  const headers = { ...(options.headers || {}) };
  if (!headers.Accept) headers.Accept = "application/json; charset=utf-8";
  opts.headers = headers;
  const res = await fetch(url, opts);
  if (res.status === 401 && !String(url).includes("/api/auth/")) {
    showAuthOverlay();
  }
  return res;
}

function storageKeyForUser() {
  if (currentUser && currentUser.id) return `${STORAGE_KEY}:u${currentUser.id}`;
  return STORAGE_KEY;
}

function loadStoredConversationId() {
  conversationId = localStorage.getItem(storageKeyForUser());
}

function saveStoredConversationId(id) {
  conversationId = id == null ? null : String(id);
  if (conversationId) localStorage.setItem(storageKeyForUser(), conversationId);
  else localStorage.removeItem(storageKeyForUser());
  syncNavActive();
}

function showAuthOverlay() {
  const el = document.getElementById("authOverlay");
  if (el) el.hidden = false;
}

function hideAuthOverlay() {
  const el = document.getElementById("authOverlay");
  if (el) el.hidden = true;
}

function setAuthMode(mode) {
  authMode = mode === "register" ? "register" : "login";
  const sub = document.getElementById("authSub");
  const submit = document.getElementById("authSubmit");
  const switchBtn = document.getElementById("authSwitch");
  const display = document.getElementById("authDisplay");
  const invite = document.getElementById("authInvite");
  const pwd = document.getElementById("authPassword");
  if (authMode === "register") {
    if (sub) sub.textContent = "注册账号后，对话和知识库仅自己可见";
    if (submit) submit.textContent = "注册并登录";
    if (switchBtn) switchBtn.textContent = "已有账号？登录";
    if (display) display.hidden = false;
    if (invite) invite.hidden = false;
    if (pwd) pwd.autocomplete = "new-password";
  } else {
    if (sub) sub.textContent = "登录后，每人拥有独立对话和知识库";
    if (submit) submit.textContent = "登录";
    if (switchBtn) switchBtn.textContent = "没有账号？注册";
    if (display) display.hidden = true;
    if (invite) invite.hidden = true;
    if (pwd) pwd.autocomplete = "current-password";
  }
}

function renderUserChip() {
  const chip = document.getElementById("userChip");
  const nameEl = document.getElementById("userName");
  if (!chip || !nameEl) return;
  if (currentUser) {
    nameEl.textContent = currentUser.display_name || currentUser.username;
    chip.hidden = false;
  } else {
    chip.hidden = true;
  }
}

async function ensureAuth() {
  try {
    const res = await apiFetch("/api/auth/me");
    if (!res.ok) {
      showAuthOverlay();
      return false;
    }
    const data = await res.json();
    if (!data.auth_required) {
      currentUser = null;
      hideAuthOverlay();
      renderUserChip();
      return true;
    }
    if (!data.user) {
      currentUser = null;
      showAuthOverlay();
      renderUserChip();
      return false;
    }
    currentUser = data.user;
    hideAuthOverlay();
    renderUserChip();
    loadStoredConversationId();
    return true;
  } catch {
    showAuthOverlay();
    return false;
  }
}

function initAuthUi() {
  const formEl = document.getElementById("authForm");
  const switchBtn = document.getElementById("authSwitch");
  const logoutBtn = document.getElementById("logoutBtn");
  const errEl = document.getElementById("authErr");
  setAuthMode("login");
  if (switchBtn) {
    switchBtn.addEventListener("click", () => {
      setAuthMode(authMode === "login" ? "register" : "login");
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
    });
  }
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      await apiFetch("/api/auth/logout", { method: "POST" });
      currentUser = null;
      saveStoredConversationId(null);
      history.length = 0;
      renderUserChip();
      showEmptyState();
      showAuthOverlay();
      setAuthMode("login");
    });
  }
  if (!formEl) return;
  formEl.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("authUsername")?.value?.trim() || "";
    const password = document.getElementById("authPassword")?.value || "";
    const display_name = document.getElementById("authDisplay")?.value?.trim() || "";
    const invite_code = document.getElementById("authInvite")?.value?.trim() || "";
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = "";
    }
    const path = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const body =
      authMode === "register"
        ? { username, password, display_name, invite_code }
        : { username, password };
    try {
      const res = await apiFetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (errEl) {
          errEl.textContent = data.detail || `失败（${res.status}）`;
          errEl.hidden = false;
        }
        return;
      }
      currentUser = data;
      saveStoredConversationId(null);
      history.length = 0;
      chatEl.innerHTML = "";
      hideAuthOverlay();
      renderUserChip();
      showEmptyState();
      await Promise.all([loadKnowledge(), loadConversations()]);
    } catch (err) {
      if (errEl) {
        errEl.textContent = String(err.message || err);
        errEl.hidden = false;
      }
    }
  });
}

function setGenerating(on) {
  generating = Boolean(on);
  form?.classList.toggle("generating", generating);
  if (sendBtn) sendBtn.disabled = generating;
  if (stopBtn) stopBtn.hidden = !generating;
}

function renderComposerAttach() {
  const el = document.getElementById("composerAttach");
  if (!el) return;
  if (!sessionDocs.length) {
    el.hidden = true;
    el.replaceChildren();
    return;
  }
  el.hidden = false;
  el.replaceChildren();
  for (const doc of sessionDocs) {
    const chip = document.createElement("span");
    chip.className = "attach-chip";
    chip.title = doc.title;
    chip.innerHTML =
      `<span class="attach-ico" aria-hidden="true">PDF</span>` +
      `<span class="attach-name"></span>` +
      `<button type="button" class="attach-x" aria-label="移除显示">×</button>`;
    chip.querySelector(".attach-name").textContent = doc.title;
    chip.querySelector(".attach-x").addEventListener("click", () => {
      sessionDocs = sessionDocs.filter((d) => String(d.id) !== String(doc.id));
      renderComposerAttach();
    });
    el.appendChild(chip);
  }
}

function addSessionDoc(doc) {
  if (!doc) return;
  const id = doc.id != null ? String(doc.id) : `t-${Date.now()}`;
  const title = (doc.title || "未命名文档").trim();
  if (sessionDocs.some((d) => String(d.id) === id || d.title === title)) {
    renderComposerAttach();
    return;
  }
  sessionDocs.unshift({ id, title });
  if (sessionDocs.length > 8) sessionDocs.length = 8;
  renderComposerAttach();
}

function enrichQueryWithSessionDocs(text) {
  const q = String(text || "").trim();
  if (!q || !sessionDocs.length) return q;
  const vague =
    /^(这个|这份|该文档|刚才|上面|导入的|它|这是).{0,12}$/.test(q) ||
    /(这个|这份|刚导入|刚才导入|该文档).{0,8}(什么|做|干|讲|说|内容|用途)/.test(q);
  const titles = sessionDocs
    .slice(0, 3)
    .map((d) => `《${d.title}》`)
    .join("、");
  if (vague) return `${q}\n（指刚导入的文档：${titles}）`;
  // 具体问题也挂上附件提示，配合后端 document_ids 优先检索
  return `${q}\n（请优先查阅已附加文档：${titles}）`;
}

function syncNavActive() {
  const onNew = !conversationId;
  navChatBtn?.classList.toggle("active", onNew);
}

function attachCopyButton(msgEl) {
  if (!msgEl || msgEl.querySelector(".msg-actions")) return;
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-copy";
  btn.textContent = "复制";
  btn.addEventListener("click", async () => {
    const raw = msgEl.dataset.raw || msgEl.textContent || "";
    try {
      await navigator.clipboard.writeText(raw);
      btn.textContent = "已复制";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = "复制";
        btn.classList.remove("copied");
      }, 1200);
    } catch {
      btn.textContent = "失败";
    }
  });
  actions.appendChild(btn);
  msgEl.appendChild(actions);
}

let _scrollQueued = false;
let _stickToBottom = true;
function scrollToBottom(force) {
  if (force) _stickToBottom = true;
  if (!_stickToBottom) return;
  if (_scrollQueued) return;
  _scrollQueued = true;
  requestAnimationFrame(() => {
    _scrollQueued = false;
    chatScroll.scrollTop = chatScroll.scrollHeight;
  });
}

// Don't yank the view to the bottom while the user is reading scrollback.
chatScroll.addEventListener(
  "scroll",
  () => {
    const gap =
      chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight;
    _stickToBottom = gap < 80;
  },
  { passive: true }
);

/** rAF-batched streaming render: many tokens per frame collapse into one paint. */
let _answerRenderQueued = false;
let _answerRenderState = null;
function scheduleAnswerRender(el, text) {
  _answerRenderState = { el, text };
  if (_answerRenderQueued) return;
  _answerRenderQueued = true;
  requestAnimationFrame(() => {
    _answerRenderQueued = false;
    const s = _answerRenderState;
    _answerRenderState = null;
    if (s) setAnswerContent(s.el, s.text);
  });
}
function flushAnswerRender(el, text) {
  _answerRenderQueued = false;
  _answerRenderState = null;
  setAnswerContent(el, text);
}

function appendMessage(role, text, className) {
  removeEmptyState();
  if (role === "user") {
    const row = document.createElement("div");
    row.className = "msg-row msg-row-user";
    row.innerHTML = `<div class="user-bubble-text"></div>`;
    row.querySelector(".user-bubble-text").textContent = text;
    chatEl.appendChild(row);
    scrollToBottom();
    return row;
  }

  const row = document.createElement("div");
  row.className = "msg-row msg-row-assistant";
  const el = document.createElement("div");
  el.className = `msg ${className || role}`;
  if (role === "assistant" || className === "answer" || className === "assistant") {
    setAnswerContent(el, text || "");
    if (text) attachCopyButton(el);
  } else {
    el.textContent = text;
  }
  row.appendChild(el);
  chatEl.appendChild(row);
  scrollToBottom();
  return el;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setThinkingBody(box, text) {
  if (!box?.body) return;
  const lines = String(text || "")
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (!lines.length) {
    box.body.textContent = "";
    return;
  }
  box.body.innerHTML = lines
    .map((line) => {
      const isAction = /^(→|规划|检索|路由|理解|本地|将补充|将做)/.test(line);
      return `<div class="think-step${isAction ? " think-step-action" : ""}">${escapeHtml(line)}</div>`;
    })
    .join("");
}

function createThinkingBox(beforeEl) {
  removeEmptyState();
  const wrap = document.createElement("div");
  wrap.className = "thinking-wrap";
  wrap.innerHTML = `
    <div class="thinking-head">
      <span class="thinking-title">分析过程</span>
      <span class="thinking-toggle">收起</span>
    </div>
    <div class="thinking-body"></div>
  `;
  const head = wrap.querySelector(".thinking-head");
  const body = wrap.querySelector(".thinking-body");
  const title = wrap.querySelector(".thinking-title");
  const toggle = wrap.querySelector(".thinking-toggle");
  head.addEventListener("click", () => {
    const collapsed = body.classList.toggle("collapsed");
    toggle.textContent = collapsed ? "展开" : "收起";
  });
  insertBeforeAnswer(wrap, beforeEl);
  scrollToBottom();
  return { wrap, head, body, title, toggle };
}

function insertBeforeAnswer(node, beforeEl) {
  const row = beforeEl?.closest?.(".msg-row-assistant") || beforeEl?.parentElement;
  if (row && row.parentElement === chatEl) {
    chatEl.insertBefore(node, row);
  } else {
    chatEl.appendChild(node);
  }
}

function createAgentTrail(beforeEl) {
  removeEmptyState();
  const wrap = document.createElement("div");
  wrap.className = "agent-trail";
  wrap.setAttribute("aria-label", "Agent activity");
  wrap.innerHTML =
    `<div class="trail-steps"></div>` +
    `<div class="run-graph" hidden></div>` +
    `<div class="run-graph-detail" hidden></div>`;
  insertBeforeAnswer(wrap, beforeEl);
  scrollToBottom();
  return wrap;
}

function upsertTrailStep(trail, key, { label, status }) {
  if (!trail) return;
  const host = trail.querySelector(".trail-steps") || trail;
  const safeKey = String(key || "step");
  let item = null;
  try {
    item = host.querySelector(`[data-key="${CSS.escape(safeKey)}"]`);
  } catch {
    item = Array.from(host.querySelectorAll(".trail-step")).find(
      (el) => el.dataset.key === safeKey
    );
  }
  if (!item) {
    item = document.createElement("div");
    item.className = "trail-step";
    item.dataset.key = safeKey;
    item.innerHTML =
      `<span class="trail-dot" aria-hidden="true"></span>` +
      `<span class="trail-tool"></span>` +
      `<span class="trail-label"></span>`;
    host.appendChild(item);
  }
  item.dataset.status = status || "running";
  item.querySelector(".trail-tool").textContent = safeKey;
  item.querySelector(".trail-label").textContent = label || "";
  scrollToBottom();
}

function stageForNodeType(t) {
  if (t === "input" || t === "start") return "input";
  if (t === "plan" || t === "guard") return "reason";
  if (t === "tool" || t === "retrieve" || t === "step" || t === "span") return "execute";
  return "answer";
}

function normalizeClientGraph(graph) {
  if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length) return null;
  const nodes = graph.nodes.map((n, i) => {
    let type = n.type || "step";
    if (type === "start") type = "input";
    if (type === "final" || type === "llm") type = type === "final" ? "answer" : "step";
    let status = n.status || "success";
    if (status === "ok" || status === "done") status = "success";
    if (status === "fail") status = "error";
    const stage = ["input", "reason", "execute", "answer"].includes(n.stage)
      ? n.stage
      : stageForNodeType(type);
    return {
      ...n,
      id: n.id || `n${i}`,
      type,
      stage,
      status,
      duration_ms: n.duration_ms != null ? n.duration_ms : n.ms,
      label: n.label || n.id || `n${i}`,
    };
  });
  const ids = new Set(nodes.map((n) => n.id));
  const edges = (graph.edges || [])
    .map((e) => {
      if (Array.isArray(e) && e.length >= 2) {
        return { source: e[0], target: e[1], relation: "sequence" };
      }
      return {
        source: e.source,
        target: e.target,
        relation: e.relation || "sequence",
      };
    })
    .filter((e) => ids.has(e.source) && ids.has(e.target));
  const toolCount =
    graph.summary?.tool_count ??
    nodes.filter((n) => n.type === "tool" || n.type === "retrieve").length;
  const failed =
    graph.summary?.failed_count ?? nodes.filter((n) => n.status === "error").length;
  return {
    schema_version: "1.0",
    run: {
      id: graph.run?.id || graph.run_id || "",
      status: graph.run?.status || (failed ? "error" : "success"),
      duration_ms: graph.run?.duration_ms ?? graph.duration_ms,
      stop_reason: graph.run?.stop_reason || graph.mode || "",
    },
    summary: { tool_count: toolCount, failed_count: failed },
    nodes,
    edges,
  };
}

function renderRunGraph(host, graph, { selectable = true } = {}) {
  const g = normalizeClientGraph(graph);
  if (!host || !g) return;
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const stageOrder = ["input", "reason", "execute", "answer"];
  const stageLabel = { input: "Input", reason: "Reason", execute: "Execute", answer: "Answer" };
  const buckets = { input: [], reason: [], execute: [], answer: [] };
  for (const n of g.nodes) {
    const s = stageOrder.includes(n.stage) ? n.stage : stageForNodeType(n.type);
    buckets[s].push(n);
  }
  const statusClass = g.run.status === "error" ? "err" : "ok";
  const stagesHtml = stageOrder
    .filter((sid) => buckets[sid].length)
    .map((sid) => {
      const nodes = buckets[sid];
      const parallel =
        sid === "execute" && nodes.length > 1 && nodes.some((n) => n.group_id);
      const nodeHtml = nodes
        .map((n) => {
          const ms =
            n.duration_ms != null && n.duration_ms !== ""
              ? `<span class="rg-ms">${escapeHtml(String(n.duration_ms))}ms</span>`
              : "";
          return `<button type="button" class="rg-node" data-id="${escapeHtml(n.id)}" data-type="${escapeHtml(n.type || "")}" data-status="${escapeHtml(n.status || "")}">
            <span class="rg-type">${escapeHtml(n.type || "node")}</span>
            <span class="rg-label">${escapeHtml(String(n.label || n.id).slice(0, 80))}</span>
            ${ms}
          </button>`;
        })
        .join("");
      return `<div class="rg-stage">
        <div class="rg-stage-name">${escapeHtml(stageLabel[sid])}</div>
        <div class="rg-stage-nodes ${parallel ? "parallel" : ""}">${nodeHtml}</div>
      </div>`;
    })
    .join("");

  host.hidden = false;
  host.innerHTML = `
    <div class="rg-metrics">
      <span class="rg-metric ${statusClass}">${escapeHtml(g.run.status || "—")}</span>
      <span class="rg-metric">${escapeHtml(String(g.summary.tool_count))} tools</span>
      <span class="rg-metric">${escapeHtml(String(g.summary.failed_count))} failed</span>
      <span class="rg-metric">${escapeHtml(String(g.run.duration_ms ?? "—"))}ms</span>
      <span class="rg-metric">${escapeHtml(g.run.stop_reason || "—")}</span>
    </div>
    <div class="rg-stages">${stagesHtml}</div>
  `;

  if (!selectable) return;
  const detail =
    host.parentElement?.querySelector?.(".run-graph-detail") ||
    host.nextElementSibling;
  const show = (id) => {
    host.querySelectorAll(".rg-node").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === id);
    });
    const n = byId[id];
    if (!detail || !n) return;
    detail.hidden = false;
    const d = n.detail && typeof n.detail === "object" ? n.detail : {};
    const lines = [];
    if (d.query_summary) lines.push(`query: ${d.query_summary}`);
    if (d.result_count != null) lines.push(`result_count: ${d.result_count}`);
    if (d.model) lines.push(`model: ${d.model}`);
    if (d.fallback != null) lines.push(`fallback: ${d.fallback}`);
    if (d.error_type) lines.push(`error_type: ${d.error_type}`);
    if (!lines.length) lines.push(n.label || "");
    detail.innerHTML =
      `<div class="rg-detail-head">${escapeHtml(n.type || "")} · ${escapeHtml(String(n.label || id).slice(0, 60))}</div>` +
      `<pre>${escapeHtml(lines.join("\n").slice(0, 1200))}</pre>`;
  };
  host.querySelectorAll(".rg-node").forEach((el) => {
    el.addEventListener("click", () => show(el.dataset.id));
  });
}

function clearChat() {
  chatEl.innerHTML = "";
  history.length = 0;
  showingEmpty = false;
}

function showEmptyState() {
  clearChat();
  showingEmpty = true;
  const wrap = document.createElement("div");
  wrap.className = "empty-state";
  wrap.id = "emptyState";
  const who = (
    currentUser?.display_name ||
    currentUser?.username ||
    ""
  ).trim();
  const greeting = who ? `你好，${who}` : "你好";
  const model =
    lastHealthMeta.mode === "mock"
      ? "本地演示"
      : lastHealthMeta.model || "—";
  const kb = Number(lastHealthMeta.kb) || 0;
  wrap.innerHTML = `
    <p class="welcome-hi"></p>
    <p class="welcome-sub">制度与知识问答助手。对话与知识库仅保存在你的账号下。</p>
    <div class="welcome-meta" aria-label="当前状态">
      <span data-k="model"></span>
      <span class="wm-dot" aria-hidden="true">·</span>
      <span data-k="kb"></span>
    </div>
    <h1>今天要查什么？</h1>
    <div class="suggestions">
      <button type="button" class="suggestion" data-fill="差旅住宿费上限是多少？">
        差旅住宿标准
        <small>差旅住宿费上限是多少？</small>
      </button>
      <button type="button" class="suggestion" data-fill="差旅报销需要哪些附件？">
        报销材料
        <small>差旅报销需要哪些附件？</small>
      </button>
      <button type="button" class="suggestion" id="emptyImportHint" data-fill="">
        导入文件
        <small>PDF / Word / 图片 → 知识库</small>
      </button>
    </div>
  `;
  wrap.querySelector(".welcome-hi").textContent = greeting;
  wrap.querySelector('[data-k="model"]').textContent = model;
  wrap.querySelector('[data-k="kb"]').textContent =
    kb > 0 ? `知识库 ${kb} 篇` : "知识库为空，可先导入";
  chatEl.appendChild(wrap);
  wrap.querySelector("#emptyImportHint")?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    openFilePicker();
  });
  wrap.querySelectorAll(".suggestion[data-fill]").forEach((btn) => {
    if (btn.id === "emptyImportHint") return;
    const fill = btn.dataset.fill || "";
    if (!fill) return;
    btn.addEventListener("click", () => {
      input.value = fill;
      input.focus();
      autoResize();
    });
  });
}

function removeEmptyState() {
  if (!showingEmpty) return;
  const empty = document.getElementById("emptyState");
  if (empty) empty.remove();
  showingEmpty = false;
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeAnswerBreaks(text) {
  let t = String(text || "").replace(/\r\n/g, "\n");

  // **橘子洲：** / **湖南省博物馆:** 挤在同一段 → 各自成段
  t = t.replace(
    /([^\n])[ \t]*(\*\*[^*\n]{1,48}?[：:]\s*\*\*)/g,
    "$1\n\n$2"
  );
  // **橘子洲**： 冒号在加粗外
  t = t.replace(
    /([^\n])[ \t]*(\*\*[^*\n]{1,48}?\*\*[ \t]*[：:])/g,
    "$1\n\n$2"
  );
  // 句读后紧跟加粗小标题（带冒号）
  t = t.replace(
    /([。！？；;])[ \t]*(\*\*[^*\n]{1,48}?(?:[：:]\s*\*\*|\*\*[ \t]*[：:]))/g,
    "$1\n\n$2"
  );
  // 无加粗的「地名：说明」连续堆叠：在「。xxx：」处拆开
  t = t.replace(
    /([。！？])[ \t]*([\u4e00-\u9fffA-Za-z0-9（）()]{2,24}[：:])/g,
    "$1\n\n$2"
  );
  // 同一段内多个「**标题：**」之间若仍粘连，再扫一遍
  t = t.replace(
    /(\*\*[^*\n]+?[：:]\s*\*\*[^\n]*?)[ \t]+(?=\*\*[^*\n]+?[：:])/g,
    "$1\n\n"
  );

  t = t.replace(/^\n+/, "");
  t = t.replace(/\n{3,}/g, "\n\n");
  return t;
}

function normalizeMarkdownLists(text) {
  let t = String(text || "").replace(/\r\n/g, "\n");
  // 中文编号：1、 1． 1） → 1.
  t = t.replace(/(^|\n)\s*(\d+)\s*[、．)）]\s*/g, "$1$2. ");
  // 行首「1.公司」无空格 →「1. 公司」
  t = t.replace(/(^|\n)(\d+)\.(\S)/g, "$1$2. $3");
  // 冒号/句号后挤在一起的编号拆行
  t = t.replace(/([：:。！？；;!?])\s*(\d+)\.\s*/g, "$1\n$2. ");
  // 「事项1.制度」挤在同一段
  t = t.replace(/([^\n\d.])(\d+)\.(?=[\u4e00-\u9fffA-Za-z*「【])/g, "$1\n$2. ");
  t = t.replace(
    /([^\n])[ \t]+(\d+)\.\s*(?=[\u4e00-\u9fffA-Za-z*「【])/g,
    "$1\n$2. "
  );
  // 再次补空格（上一行拆出的 1.公司）
  t = t.replace(/(^|\n)(\d+)\.(\S)/g, "$1$2. $3");

  // 连续编号项收成同一列表，并强制重排成 1、2、3…
  const itemRe = /^\s*\d+\.\s+(.*)$/;
  const lines = t.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    if (!itemRe.test(lines[i])) {
      out.push(lines[i]);
      i += 1;
      continue;
    }
    const items = [];
    while (i < lines.length) {
      if (lines[i].trim() === "") {
        let j = i + 1;
        while (j < lines.length && lines[j].trim() === "") j += 1;
        if (j < lines.length && itemRe.test(lines[j])) {
          i = j;
          continue;
        }
        break;
      }
      const m = lines[i].match(itemRe);
      if (!m) break;
      items.push(m[1].trim());
      i += 1;
    }
    if (out.length && out[out.length - 1] !== "") out.push("");
    items.forEach((body, idx) => out.push(`${idx + 1}. ${body}`));
  }
  return out.join("\n");
}

/** Expand jammed markdown tables like |a|b||---|---||c|d| into real rows. */
function normalizeMarkdownTables(text) {
  let t = String(text || "").replace(/\r\n/g, "\n");
  // 去掉行首装饰冒号，避免破坏表格首行
  t = t.replace(/(^|\n)[：:\s]+(\|)/g, "$1$2");
  // || before a separator row or next row → line break
  t = t.replace(/\|\|(?=\s*\|?\s*:?-{3,})/g, "|\n|");
  t = t.replace(/\|\|(?=[^\n|])/g, "|\n|");
  // Trailing || at EOL → single |
  t = t.replace(/\|\|\s*$/gm, "|");
  // Ensure blank line before a table for paragraph splitter
  t = t.replace(/([^\n|])\n(\|[^\n]+\|)/g, "$1\n\n$2");
  return t;
}

function parseMarkdownTableBlock(block) {
  const lines = String(block || "")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.includes("|"));
  if (lines.length < 2) return null;

  const splitRow = (line) => {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map((c) => escapeHtml(c.trim()));
  };

  const isSep = (line) =>
    /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);

  let header = null;
  let sepIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (isSep(lines[i])) {
      sepIdx = i;
      if (i > 0) header = splitRow(lines[i - 1]);
      break;
    }
  }
  if (!header || sepIdx < 0) return null;

  const body = lines
    .slice(sepIdx + 1)
    .filter((l) => !isSep(l))
    .map(splitRow)
    .filter((cells) => cells.some((c) => c.length));

  const cols = header.length;
  const renderCells = (cells, tag) =>
    cells
      .slice(0, cols)
      .concat(Array(Math.max(0, cols - cells.length)).fill(""))
      .map((c) => `<${tag}>${c}</${tag}>`)
      .join("");

  let html = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
  html += renderCells(header, "th");
  html += "</tr></thead><tbody>";
  for (const row of body) {
    html += `<tr>${renderCells(row, "td")}</tr>`;
  }
  html += "</tbody></table></div>";
  return html;
}

function renderMarkdown(text) {
  const raw = normalizeMarkdownTables(
    normalizeMarkdownLists(normalizeAnswerBreaks(text))
  );
  const blocks = [];
  let src = raw.replace(/```([\s\S]*?)```/g, (_, code) => {
    const i = blocks.length;
    blocks.push(`<pre class="md-code"><code>${escapeHtml(code.replace(/^\n/, ""))}</code></pre>`);
    return `\u0000BLOCK${i}\u0000`;
  });

  // Extract markdown tables before escaping
  src = src.replace(
    /(?:^|\n)((?:[ \t]*\|[^\n]*\|[ \t]*(?:\n|$))+)/g,
    (m, tableBlock) => {
      const html = parseMarkdownTableBlock(tableBlock.trim());
      if (!html) return m;
      const i = blocks.length;
      blocks.push(html);
      return `\n\u0000BLOCK${i}\u0000\n`;
    }
  );

  src = escapeHtml(src);
  src = src.replace(/^###\s+(.+)$/gm, "<h4>$1</h4>");
  src = src.replace(/^##\s+(.+)$/gm, "<h3>$1</h3>");
  src = src.replace(/^#\s+(.+)$/gm, "<h3>$1</h3>");
  src = src.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  src = src.replace(/\*(.+?)\*/g, "<em>$1</em>");
  src = src.replace(/`([^`]+)`/g, "<code>$1</code>");
  src = src.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Unordered lists
  src = src.replace(/^(?:- |\* )(.+)(?:\n(?:- |\* ).+)*/gm, (block) => {
    const items = block
      .split("\n")
      .map((line) => line.replace(/^(?:- |\* )/, "").trim())
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return `<ul>${items}</ul>`;
  });
  // Ordered lists（允许项间空行；序号由 <ol> 自动递增，不信源文本里的数字）
  src = src.replace(/^(?:\d+\.\s).+(?:\n+(?:\d+\.\s).+)*/gm, (block) => {
    const items = block
      .split(/\n+/)
      .map((line) => line.replace(/^\d+\.\s*/, "").trim())
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return `<ol>${items}</ol>`;
  });

  src = src
    .split(/\n{2,}/)
    .map((para) => {
      const t = para.trim();
      if (!t) return "";
      if (
        t.startsWith("<h") ||
        t.startsWith("<ul") ||
        t.startsWith("<ol") ||
        t.startsWith("\u0000BLOCK")
      ) {
        return t.replace(/\n/g, "");
      }
      return `<p>${t.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");

  src = src.replace(/\u0000BLOCK(\d+)\u0000/g, (_, i) => blocks[Number(i)] || "");
  return src;
}

function setAnswerContent(el, text) {
  el.dataset.raw = text;
  const display = String(text || "").replace(/（document_id=\d+）/g, "");
  el.innerHTML = renderAnswerSections(display);
}

/** Strip leaked DeepSeek DSML / tool-call markup from streamed assistant text. */
function sanitizeAssistantText(text) {
  let t = String(text || "");
  t = t.replace(/<\s*\|\s*DSML\s*\|[\s\S]*?(?:<\/\s*\|\s*DSML\s*\|?>|$)/gi, " ");
  t = t.replace(/<\/?\s*\|\s*DSML\s*\|[^>\n]*>/gi, " ");
  t = t.replace(/<\/?tool_calls?>/gi, " ");
  t = t.replace(/<tool_calls?>[\s\S]*?(?:<\/tool_calls?>|$)/gi, " ");
  t = t.replace(/<tool_call>[\s\S]*?(?:<\/tool_call>|$)/gi, " ");
  t = t.replace(/invoke\s+name\s*=\s*"[^"]+"/gi, " ");
  t = t.replace(/parameter\s+name\s*=\s*"[^"]+"[^>\n]*>/gi, " ");
  t = t.replace(/name\s*=\s*"(?:web_search|search_knowledge|research_topics)"/gi, " ");
  t = t.replace(/(?:max_results|fetch_top|top_k)\s*=\s*"?\d+"?/gi, " ");
  t = t.replace(/<\s*\|\s*[\s\S]*$/g, "");
  t = t.replace(/<tool_calls?[\s\S]*$/gi, "");
  t = t.replace(/invoke\s+name\s*=[\s\S]*$/gi, "");
  t = t.replace(/\n{3,}/g, "\n\n").trim();
  const compact = t.replace(/\s+/g, "");
  if (
    !compact ||
    (compact.length < 40 &&
      /search_knowledge|web_search|top_k|invoke|parameter name|dsml|tool_calls/i.test(t))
  ) {
    return "";
  }
  return t;
}

function looksLikeToolLeak(text) {
  const low = String(text || "").toLowerCase();
  const markers = [
    "<|dsml|",
    "< | dsml",
    "invoke name=",
    "parameter name=",
    "search_knowledge",
    "<tool_calls>",
    'name="web_search"',
    "max_results=",
  ];
  const hits = markers.filter((m) => low.includes(m)).length;
  return (
    hits >= 2 ||
    (low.includes("dsml") && low.includes("invoke")) ||
    (low.includes("tool_calls") && (low.includes("web_search") || low.includes("search_knowledge")))
  );
}

/* T8-1 v2: 纯文本阶段切分，分段渲染（无 emoji，降低 AI 感） */
function renderAnswerSections(rawText) {
  const markers = [
    { key: "**制度依据**", cls: "as-policy" },
    { key: "**推理分析**", cls: "as-reasoning" },
    { key: "**结论**", cls: "as-conclusion" },
    { key: "**补充说明**", cls: "as-note" },
  ];

  let positions = [];
  for (const m of markers) {
    const idx = rawText.indexOf(m.key);
    if (idx >= 0) positions.push({ idx, ...m });
  }
  if (!positions.length) {
    return renderMarkdown(rawText);
  }

  positions.sort((a, b) => a.idx - b.idx);

  let result = "";
  if (positions[0].idx > 0) {
    const prefix = rawText.slice(0, positions[0].idx).trim();
    if (prefix) result += renderMarkdown(prefix);
  }

  for (let i = 0; i < positions.length; i++) {
    const p = positions[i];
    const contentStart = p.idx + p.key.length;
    const contentEnd = i + 1 < positions.length ? positions[i + 1].idx : rawText.length;
    let body = rawText.slice(contentStart, contentEnd).trim();
    // 模型常在小节后多写一个全角冒号
    body = body.replace(/^[：:\s]+/, "");
    const bodyHtml = renderMarkdown(body);
    const title = p.key.replace(/\*\*/g, "");
    result +=
      `<div class="answer-section ${p.cls}">` +
      `<div class="as-head">${title}</div>` +
      `<div class="as-body">${bodyHtml}</div>` +
      `</div>`;
  }

  return result;
}

async function refreshMeta() {
  try {
    const res = await apiFetch("/api/health");
    const data = await res.json();
    modeBadge.textContent = data.mode === "mock" ? "本地 Mock" : data.model;
    statusDot.className = `status-dot ${data.mode === "mock" ? "warn" : "ok"}`;
    ttsReady = Boolean(data.tts_ready);
    sttReady = Boolean(data.stt_ready);
    if (ttsHint) {
      ttsHint.textContent = ttsReady
        ? "已启用克隆音色。录音粗糙会直接影响听感——可在下方重新上传 10–30 秒清晰中文。"
        : "尚未启用克隆音色。上传一段清晰中文录音即可。";
    }
    if (speakBtn) {
      speakBtn.title = ttsReady ? "用我的音色朗读（首次稍慢）" : "朗读回答（系统音色）";
    }
    if (voiceBtn) {
      voiceBtn.disabled = false;
      voiceBtn.title = sttReady
        ? "按住/点击开始录音，再说一次结束"
        : "本地语音识别未就绪";
    }
    updateSysBar();
  } catch {
    modeBadge.textContent = "未连接";
    statusDot.className = "status-dot";
    updateSysBar();
  }
}

let _knowledgeSig = null;
async function loadKnowledge() {
  try {
    const res = await apiFetch("/api/documents");
    const docs = await res.json();
    const sig = JSON.stringify(
      (docs || []).map((d) => [d.id, d.title, d.source_type, (d.content || "").length])
    );
    if (sig === _knowledgeSig) {
      updateSysBar(docs.length); // no change → refresh count only, skip DOM churn
      return;
    }
    _knowledgeSig = sig;
    knowledgeList.innerHTML = "";
    if (!docs.length) {
      knowledgeList.innerHTML = '<p class="knowledge-empty">还没有知识。可手写保存或导入 PDF/图片。</p>';
      updateSysBar(0);
      return;
    }
    for (const doc of docs) {
      const item = document.createElement("div");
      item.className = "knowledge-item";
      const type = doc.source_type || "text";
      item.innerHTML = `<div class="knowledge-head"><strong></strong><button type="button" class="knowledge-delete" title="删除文档" aria-label="删除文档">×</button></div><p></p><span class="meta"></span>`;
      item.querySelector("strong").textContent = doc.title;
      item.querySelector("p").textContent =
        doc.content.slice(0, 80) + (doc.content.length > 80 ? "…" : "");
      item.querySelector(".meta").textContent = type;
      item.querySelector(".knowledge-delete").addEventListener("click", async () => {
        if (!window.confirm(`删除《${doc.title}》？此操作不可恢复。`)) return;
        try {
          const delRes = await apiFetch(`/api/documents/${doc.id}`, { method: "DELETE" });
          if (!delRes.ok) throw new Error(`HTTP ${delRes.status}`);
          sessionDocs = sessionDocs.filter((d) => String(d.id) !== String(doc.id));
          renderComposerAttach();
          await loadKnowledge();
        } catch (err) {
          window.alert(`删除失败：${err.message || err}`);
        }
      });
      knowledgeList.appendChild(item);
    }
    updateSysBar(docs.length);
  } catch {
    _knowledgeSig = null;
    knowledgeList.innerHTML = '<p class="knowledge-empty">知识库加载失败</p>';
  }
}

async function loadConversation(id) {
  const res = await apiFetch(`/api/conversations/${id}/messages`);
  if (!res.ok) {
    saveStoredConversationId(null);
    return false;
  }
  const messages = await res.json();
  clearChat();
  if (!messages.length) return false;
  for (const msg of messages) {
    history.push({ role: msg.role, content: msg.content });
    appendMessage(msg.role, msg.content);
  }
  return true;
}

function displayTitle(raw, fallbackId) {
  const t = (raw == null ? "" : String(raw)).trim();
  if (!t) return `对话 ${fallbackId}`;
  // 防止异常控制字符；用 textContent 渲染，不做二次编解码
  return t.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
}

async function deleteConversation(id) {
  const res = await apiFetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error("删除失败");
  }
  if (String(conversationId) === String(id)) {
    conversationId = null;
    saveStoredConversationId(null);
    lastAssistantText = "";
    showEmptyState();
  }
  await loadConversations();
}

let _convSig = null;
async function loadConversations() {
  if (!convList) return;
  try {
    const res = await apiFetch("/api/conversations", {
      headers: { Accept: "application/json; charset=utf-8" },
    });
    const items = await res.json();
    const sig = JSON.stringify({
      active: conversationId || "",
      items: (items || []).slice(0, 20).map((c) => [c.id, c.title]),
    });
    if (sig === _convSig) return; // same list + active highlight → skip rebuild
    _convSig = sig;
    convList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "knowledge-empty";
      empty.textContent = "暂无历史对话";
      convList.appendChild(empty);
      return;
    }
    for (const c of items.slice(0, 20)) {
      const row = document.createElement("div");
      row.className =
        "conv-row" + (String(c.id) === String(conversationId) ? " active" : "");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "conv-item";
      const title = displayTitle(c.title, c.id);
      btn.title = title;
      btn.lang = "zh-CN";

      const titleEl = document.createElement("span");
      titleEl.className = "conv-title";
      titleEl.lang = "zh-CN";
      titleEl.textContent = title;
      btn.appendChild(titleEl);

      btn.addEventListener("click", async () => {
        conversationId = String(c.id);
        saveStoredConversationId(conversationId);
        syncNavActive();
        const ok = await loadConversation(c.id);
        if (ok) {
          lastAssistantText =
            [...history].reverse().find((m) => m.role === "assistant")?.content || "";
        } else {
          showEmptyState();
        }
        loadConversations();
        closeSidebar();
      });

      const del = document.createElement("button");
      del.type = "button";
      del.className = "conv-delete";
      del.title = "删除对话";
      del.setAttribute("aria-label", `删除对话：${title}`);
      del.textContent = "×";
      del.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!window.confirm(`删除「${title}」？此操作不可恢复。`)) return;
        try {
          await deleteConversation(c.id);
        } catch {
          window.alert("删除失败，请稍后重试");
        }
      });

      row.appendChild(btn);
      row.appendChild(del);
      convList.appendChild(row);
    }
  } catch {
    _convSig = null;
    convList.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "knowledge-empty";
    empty.textContent = "对话列表加载失败";
    convList.appendChild(empty);
  }
}

function startNewChat() {
  conversationId = null;
  saveStoredConversationId(null);
  lastAssistantText = "";
  showEmptyState();
  syncNavActive();
  loadConversations();
  closeSidebar();
  input.focus();
}

function openSidebar() {
  sidebar.classList.add("open");
  sidebarBackdrop.hidden = false;
}

function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarBackdrop.hidden = true;
}

async function streamChat(userText) {
  if (generating) return;
  const sendText = enrichQueryWithSessionDocs(userText);
  history.push({ role: "user", content: sendText });
  appendMessage("user", userText);

  let thinkingBox = null;
  let thinkingText = "";
  let agentTrail = null;
  const botEl = appendMessage("assistant", "");
  botEl.classList.add("answer");
  let assistantText = "";
  let aborted = false;
  let hadHits = false;
  let draftStarted = false;

  resetPetAgents();
  setPetStatus("协作中", "busy");
  setPetAgent("retrieve", "running");

  chatAbort = new AbortController();
  setGenerating(true);
  try {
    const body = {
      messages: history.filter(
        (m) => m.content && m.content !== "（无内容）" && m.content !== "（无内容返回）"
      ),
      use_tools: true,
      deep_think: deepThinkToggle.checked,
    };
    if (conversationId) body.conversation_id = Number(conversationId);
    if (sessionDocs.length) {
      body.document_ids = sessionDocs
        .map((d) => Number(d.id))
        .filter((n) => Number.isFinite(n) && n > 0)
        .slice(0, 8);
    }

    const res = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal: chatAbort.signal,
    });

    if (res.status === 401) {
      showAuthOverlay();
      throw new Error("请先登录");
    }
    if (res.status === 429) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || "当前使用人数较多，请稍后再试");
    }
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const handleEvent = (eventName, payload) => {
      const event = payload.type || eventName;

      if (event === "plan") {
        const p = payload.plan || {};
        const steps = (p.steps || []).join(" → ");
        if (!agentTrail) agentTrail = createAgentTrail(botEl);
        upsertTrailStep(agentTrail, "plan", {
          status: "done",
          label: `${p.intent || "?"} · ${steps || "synthesize"}`,
        });
        if (!thinkingBox) thinkingBox = createThinkingBox(botEl);
        thinkingText += `规划意图：${p.intent || "?"}\n步骤：${steps || "作答"}\n`;
        setThinkingBody(thinkingBox, thinkingText);
        setPetStatus("规划中", "busy");
        setPetAgent("retrieve", "running");
      } else if (event === "trace") {
        const tr = payload.trace || payload;
        const graph = tr.graph;
        if (graph && graph.nodes && graph.nodes.length) {
          if (!agentTrail) agentTrail = createAgentTrail(botEl);
          const graphEl = agentTrail.querySelector(".run-graph");
          if (graphEl) renderRunGraph(graphEl, graph);
        }
      } else if (event === "rag_context") {
        const hits = payload.hits || [];
        hadHits = hits.length > 0;
        const titles = hits.map((h) => `《${h.title}》`).join("、");
        if (!agentTrail) agentTrail = createAgentTrail(botEl);
        upsertTrailStep(agentTrail, "retrieve", {
          status: "done",
          label: titles || "知识库无直接匹配",
        });
        if (!thinkingBox) thinkingBox = createThinkingBox(botEl);
        thinkingText += titles ? `检索材料：${titles}\n` : "检索：知识库无直接匹配\n";
        setThinkingBody(thinkingBox, thinkingText);
        setPetAgent("retrieve", "done");
        setPetStatus(hadHits ? "已取到材料" : "材料有限", "busy");
      } else if (event === "thinking_start") {
        if (!thinkingBox) thinkingBox = createThinkingBox(botEl);
        thinkingBox.title.textContent = "分析过程";
        thinkingBox.body.classList.remove("collapsed");
        if (thinkingBox.toggle) thinkingBox.toggle.textContent = "收起";
      } else if (event === "thinking_token") {
        thinkingText += payload.content || "";
        if (thinkingBox) {
          setThinkingBody(thinkingBox, thinkingText);
          scrollToBottom();
        }
      } else if (event === "thinking_done") {
        if (thinkingBox) {
          thinkingBox.title.textContent = "分析过程";
          thinkingBox.body.classList.add("collapsed");
          if (thinkingBox.toggle) thinkingBox.toggle.textContent = "展开";
        }
      } else if (event === "answer_start") {
        /* keep existing text; do not clear mid-stream */
      } else if (event === "tool_start") {
        const labels = {
          research_topics: "多方面检索并自主学习…",
          web_search: "联网搜索中…",
          search_knowledge: "查阅知识库…",
          search_graph: "图谱检索…",
          learn_knowledge: "写入知识库…",
          get_current_time: "获取时间…",
          calculator: "计算中…",
        };
        const name = payload.name || "tool";
        const label = labels[name] || `运行中…`;
        if (!agentTrail) agentTrail = createAgentTrail(botEl);
        upsertTrailStep(agentTrail, name, { status: "running", label });
        if (!thinkingBox) thinkingBox = createThinkingBox(botEl);
        thinkingText += `→ ${label}\n`;
        setThinkingBody(thinkingBox, thinkingText);
        thinkingBox.body.classList.remove("collapsed");
        setPetAgent("retrieve", "running");
        setPetStatus(label.replace(/…$/, ""), "busy");
      } else if (event === "tool_result") {
        const name = payload.name || "tool";
        let doneLabel = `Completed`;
        if (payload.name === "research_topics") {
          try {
            const data = JSON.parse(payload.content || "{}");
            const n = data.learned_count ?? (data.learned || []).length;
            const c = data.count ?? (data.hits || []).length;
            doneLabel = `已自主学习 ${n} 条，可用材料 ${c} 条`;
          } catch {
            doneLabel = "Completed";
          }
        } else if (payload.name === "web_search") {
          try {
            const data = JSON.parse(payload.content || "{}");
            const c = data.count ?? (data.hits || []).length;
            doneLabel = c ? `联网找到 ${c} 条网页` : "联网未找到结果";
          } catch {
            doneLabel = "Completed";
          }
        } else if (payload.name === "search_knowledge") {
          try {
            const data = JSON.parse(payload.content || "{}");
            const c = data.count ?? (data.results || []).length;
            doneLabel = c ? `命中 ${c} 条` : "无命中";
          } catch {
            doneLabel = "Completed";
          }
        } else {
          doneLabel = "Completed";
        }
        if (!agentTrail) agentTrail = createAgentTrail(botEl);
        upsertTrailStep(agentTrail, name, { status: "done", label: doneLabel });
        if (thinkingBox) {
          thinkingText += `  ${doneLabel}\n`;
          setThinkingBody(thinkingBox, thinkingText);
        }
        if (
          payload.name === "search_knowledge" ||
          payload.name === "web_search" ||
          payload.name === "research_topics" ||
          payload.name === "search_graph"
        ) {
          try {
            const data = JSON.parse(payload.content || "{}");
            const c =
              data.count ??
              (data.results || data.hits || data.learned || []).length ??
              0;
            if (c > 0) hadHits = true;
          } catch {
            /* ignore */
          }
          setPetAgent("retrieve", "done");
        }
      } else if (event === "token") {
        if (!draftStarted) {
          draftStarted = true;
          setPetAgent("retrieve", "done");
          setPetAgent("draft", "running");
          setPetStatus("作答中", "busy");
        }
        assistantText += payload.content || "";
        if (looksLikeToolLeak(assistantText)) {
          assistantText = sanitizeAssistantText(assistantText);
        } else {
          const cleaned = sanitizeAssistantText(assistantText);
          if (cleaned.length < assistantText.length) assistantText = cleaned;
        }
        scheduleAnswerRender(botEl, assistantText);
        scrollToBottom();
      } else if (event === "error") {
        assistantText += `\n[错误] ${payload.content || "未知错误"}`;
        setAnswerContent(botEl, assistantText);
        setPetStatus("出错", "idle");
      } else if (event === "done") {
        if (payload.mode === "guard_blocked") {
          botEl.className = "msg guard-warn";
          setPetStatus("已拦截", "idle");
          return;
        }
        if (payload.conversation_id) {
          saveStoredConversationId(payload.conversation_id);
          syncNavActive();
        }
        if (
          payload.mode === "tool_leak_refuse" ||
          looksLikeToolLeak(assistantText) ||
          !sanitizeAssistantText(assistantText)
        ) {
          if (payload.answer) {
            assistantText = String(payload.answer);
          } else {
            assistantText = sanitizeAssistantText(assistantText) || "";
          }
          setAnswerContent(botEl, assistantText);
        } else if ((!assistantText || !assistantText.trim()) && payload.answer) {
          assistantText = payload.answer;
          setAnswerContent(botEl, assistantText);
        }
        if (!assistantText || !assistantText.trim()) {
          assistantText = "暂时没有生成回答，请再试一次。";
          setAnswerContent(botEl, assistantText);
        }
        setPetAgent("draft", "done");
        if (collabEnabled()) {
          setPetAgent("review", "running");
          setPetStatus("复核中", "review");
          appendCollabReviewNote(botEl, assistantText, hadHits);
          setPetAgent("review", "done");
          setPetStatus("协作完成", "idle");
        } else {
          setPetStatus("完成", "idle");
        }
        loadKnowledge();
        loadConversations();
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        if (!part.trim() || part.trim().startsWith(":")) continue;
        const lines = part.split("\n");
        let event = "message";
        const dataLines = [];
        for (const raw of lines) {
          const line = raw.trimEnd();
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        let payload;
        try {
          payload = JSON.parse(dataLines.join("\n"));
        } catch {
          continue;
        }
        handleEvent(event, payload);
      }
    }

    if ((!assistantText || !assistantText.trim()) && buffer.trim()) {
      const lines = buffer.replace(/\r\n/g, "\n").split("\n");
      let event = "message";
      const dataLines = [];
      for (const raw of lines) {
        const line = raw.trimEnd();
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) {
        try {
          handleEvent(event, JSON.parse(dataLines.join("\n")));
        } catch {
          /* ignore */
        }
      }
    }

    if (!assistantText || !assistantText.trim()) {
      assistantText = aborted ? "已停止生成。" : "暂时没有生成回答，请再试一次。";
    }
    // Ensure the final answer is painted even if a throttled frame was pending.
    flushAnswerRender(botEl, assistantText);
    lastAssistantText = assistantText;
    history.push({ role: "assistant", content: assistantText });
    attachCopyButton(botEl);
  } catch (err) {
    if (err?.name === "AbortError") {
      aborted = true;
      if (!assistantText.trim()) {
        assistantText = "已停止生成。";
        setAnswerContent(botEl, assistantText);
      } else {
        assistantText += "\n\n（已停止）";
        setAnswerContent(botEl, assistantText);
      }
      lastAssistantText = assistantText;
      history.push({ role: "assistant", content: assistantText });
      attachCopyButton(botEl);
    } else {
      setAnswerContent(botEl, `请求失败：${err.message}`);
      attachCopyButton(botEl);
    }
  } finally {
    chatAbort = null;
    setGenerating(false);
    if (aborted) setPetStatus("已停止", "idle");
    else if (document.getElementById("atlasPet")?.dataset.state === "busy") {
      setPetStatus("待命", "idle");
    }
    input.focus();
  }
}

learnForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = learnTitle.value.trim();
  const content = learnContent.value.trim();
  if (!title || !content) return;
  try {
    const res = await apiFetch("/api/knowledge/learn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    learnTitle.value = "";
    learnContent.value = "";
    await loadKnowledge();
    appendMessage("assistant", `已写入知识库：《${title}》。可以直接提问相关内容。`);
  } catch (err) {
    appendMessage("assistant", `保存失败：${err.message}`);
  }
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autoResize();
  streamChat(text);
});

stopBtn?.addEventListener("click", () => {
  if (chatAbort) chatAbort.abort();
});

input.addEventListener("input", autoResize);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

newChatBtn.addEventListener("click", startNewChat);
document.getElementById("navChat")?.addEventListener("click", startNewChat);
menuBtn.addEventListener("click", openSidebar);
sidebarBackdrop.addEventListener("click", closeSidebar);

const ALLOWED_UPLOAD_EXT = new Set([
  ".pdf",
  ".doc",
  ".docx",
  ".pptx",
  ".xlsx",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".bmp",
  ".tif",
  ".tiff",
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".html",
  ".htm",
  ".rtf",
  ".zip",
]);

function fileExt(name) {
  const m = /\.[^.]+$/.exec(name || "");
  return (m ? m[0] : "").toLowerCase();
}

function setUploadStatus(msg) {
  if (uploadStatus) uploadStatus.textContent = msg || "";
}

async function uploadKnowledgeFile(file, caption = "") {
  const ext = fileExt(file.name);
  if (ext && !ALLOWED_UPLOAD_EXT.has(ext)) {
    throw new Error(`不支持的类型 ${ext || "(未知)"}`);
  }
  const fd = new FormData();
  fd.append("file", file);
  const titleEl = document.getElementById("learnTitle");
  fd.append(
    "title",
    (titleEl && titleEl.value.trim()) || file.name.replace(/\.[^.]+$/, "") || "未命名文件",
  );
  fd.append("caption", caption || (fileCaption && fileCaption.value.trim()) || "");
  const res = await apiFetch("/api/knowledge/upload", { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    throw new Error(
      typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `HTTP ${res.status}`,
    );
  }
  return res.json();
}

async function uploadKnowledgeFiles(fileList) {
  if (document.getElementById("authOverlay") && !document.getElementById("authOverlay").hidden) {
    appendMessage("assistant", "请先登录后再导入文件。");
    showAuthOverlay();
    return;
  }
  if (!currentUser && (await ensureAuth()) === false) {
    appendMessage("assistant", "请先登录后再导入文件。");
    return;
  }
  const files = [...(fileList || [])].filter(Boolean);
  if (!files.length) return;
  removeEmptyState();
  appendMessage("tool", `正在读取 ${files.length} 个文件…`, "tool");
  const progressNote = chatEl.lastElementChild;
  const okTitles = [];
  const failMsgs = [];
  const okDocs = [];
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const label = `正在导入（${i + 1}/${files.length}）${file.name}…`;
    setUploadStatus(label);
    if (progressNote) progressNote.textContent = label;
    try {
      const doc = await uploadKnowledgeFile(file);
      okTitles.push(doc.title || file.name);
      okDocs.push(doc);
      addSessionDoc(doc);
    } catch (err) {
      failMsgs.push(`${file.name}：${err.message || err}`);
    }
  }
  if (fileCaption) fileCaption.value = "";
  if (fileInput) fileInput.value = "";
  if (progressNote?.isConnected) progressNote.remove();
  await loadKnowledge();
  if (okTitles.length) {
    setUploadStatus(`已导入 ${okTitles.length} 个文件`);
    appendMessage(
      "assistant",
      `已导入并写入知识库：\n${okTitles.map((t) => `- 《${t}》`).join("\n")}\n\n输入框上方已显示文档标签，可直接问「这份文档讲什么」。`,
    );
  }
  if (failMsgs.length) {
    setUploadStatus(`部分失败：${failMsgs[0]}`);
    appendMessage("assistant", `导入失败：\n${failMsgs.map((m) => `- ${m}`).join("\n")}`);
  }
  if (!okTitles.length && !failMsgs.length) {
    showEmptyState();
  }
}

function openFilePicker() {
  if (!fileInput) return;
  fileInput.click();
}

uploadBtn?.addEventListener("click", openFilePicker);
document.getElementById("importBtn")?.addEventListener("click", openFilePicker);
document.getElementById("attachBtn")?.addEventListener("click", openFilePicker);

fileInput?.addEventListener("change", async () => {
  const files = fileInput.files;
  if (!files || !files.length) return;
  try {
    await uploadKnowledgeFiles(files);
  } catch (err) {
    setUploadStatus(`导入失败：${err.message}`);
    appendMessage("assistant", `导入失败：${err.message}`);
  }
});

// 拖拽导入：覆盖整个主区域（聊天 + 输入框），并阻止浏览器直接打开文件
const mainEl = document.querySelector(".main");
const dropOverlay = document.getElementById("dropOverlay");
let dragHideTimer = null;

function isFileDrag(e) {
  return [...(e.dataTransfer?.types || [])].includes("Files");
}

function showDrop(on) {
  if (!mainEl || !dropOverlay) return;
  mainEl.classList.toggle("drag-over", on);
  dropOverlay.hidden = !on;
}

function clearDragHide() {
  if (dragHideTimer) {
    clearTimeout(dragHideTimer);
    dragHideTimer = null;
  }
}

window.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
});
window.addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault(); // 防止拖到页面外区域时浏览器直接打开文件
});

if (mainEl) {
  mainEl.addEventListener("dragenter", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    clearDragHide();
    showDrop(true);
  });
  mainEl.addEventListener("dragover", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    clearDragHide();
    showDrop(true);
  });
  mainEl.addEventListener("dragleave", (e) => {
    if (!isFileDrag(e)) return;
    const next = e.relatedTarget;
    if (next && mainEl.contains(next)) return;
    clearDragHide();
    dragHideTimer = setTimeout(() => showDrop(false), 60);
  });
  mainEl.addEventListener("drop", async (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    clearDragHide();
    showDrop(false);
    const files = e.dataTransfer?.files;
    if (!files?.length) return;
    try {
      await uploadKnowledgeFiles(files);
    } catch (err) {
      setUploadStatus(`导入失败：${err.message}`);
      appendMessage("assistant", `导入失败：${err.message}`);
    }
  });
}
function stopSideAudio() {
  if (ttsAudio) {
    ttsAudio.pause();
    ttsAudio = null;
    speakBtn?.classList.remove("speaking");
  }
  if (window.speechSynthesis?.speaking) {
    speechSynthesis.cancel();
    speakBtn?.classList.remove("speaking");
  }
}

function releaseMediaStream() {
  if (mediaStream) {
    try {
      mediaStream.getTracks().forEach((t) => {
        try {
          t.stop();
        } catch {
          /* ignore */
        }
      });
    } catch {
      /* ignore */
    }
    mediaStream = null;
  }
}

function clearVoiceLock() {
  try {
    const cur = localStorage.getItem(VOICE_LOCK_KEY);
    if (!cur) return;
    const data = JSON.parse(cur);
    if (data && data.tab === voiceTabId) {
      localStorage.removeItem(VOICE_LOCK_KEY);
    }
  } catch {
    try {
      localStorage.removeItem(VOICE_LOCK_KEY);
    } catch {
      /* ignore */
    }
  }
}

function acquireVoiceLock() {
  try {
    const raw = localStorage.getItem(VOICE_LOCK_KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (
        data &&
        data.tab &&
        data.tab !== voiceTabId &&
        Date.now() - (data.at || 0) < VOICE_LOCK_TTL_MS
      ) {
        return false;
      }
    }
    localStorage.setItem(
      VOICE_LOCK_KEY,
      JSON.stringify({ tab: voiceTabId, at: Date.now() })
    );
    return true;
  } catch {
    return true;
  }
}

function pickRecorderMime() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  if (!window.MediaRecorder?.isTypeSupported) return "";
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

async function transcribeBlob(blob) {
  const fd = new FormData();
  const ext = (blob.type || "").includes("mp4") ? "mp4" : "webm";
  fd.append("file", blob, `speech.${ext}`);
  const res = await apiFetch("/api/stt", { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `识别失败 HTTP ${res.status}`);
  }
  const data = await res.json();
  return (data.text || "").trim();
}

function finishRecordingUi(msg) {
  listening = false;
  listenIntent = false;
  voiceBusy = false;
  voiceBtn?.classList.remove("listening");
  if (voiceBtn) {
    voiceBtn.disabled = false;
    voiceBtn.title = sttReady ? "点击开始语音输入" : "本地语音识别未就绪";
  }
  if (input) input.placeholder = msg || defaultPlaceholder;
  clearVoiceLock();
}

function hardResetRecorder() {
  try {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.ondataavailable = null;
      mediaRecorder.onerror = null;
      mediaRecorder.onstop = null;
      try {
        mediaRecorder.stop();
      } catch {
        /* ignore */
      }
    }
  } catch {
    /* ignore */
  }
  mediaRecorder = null;
  recordedChunks = [];
  releaseMediaStream();
}

async function stopRecordingAndRecognize() {
  if (voiceBusy && !listening) return;
  voiceBusy = true;
  if (voiceBtn) voiceBtn.disabled = true;

  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    hardResetRecorder();
    finishRecordingUi();
    return;
  }

  if (input) input.placeholder = "正在识别语音…";

  const chunks = [];
  const recorder = mediaRecorder;
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  await new Promise((resolve) => {
    const done = () => resolve();
    recorder.addEventListener("stop", done, { once: true });
    try {
      if (recorder.state === "recording") recorder.requestData?.();
      recorder.stop();
    } catch {
      done();
    }
    // Safety timeout — never hang forever
    setTimeout(done, 4000);
  });

  releaseMediaStream();
  mediaRecorder = null;
  listening = false;
  voiceBtn?.classList.remove("listening");

  // Merge any chunks collected during timeslice + final
  const all = chunks.length ? chunks : recordedChunks;
  recordedChunks = [];
  const mime = all[0]?.type || "audio/webm";
  const blob = new Blob(all, { type: mime });

  if (blob.size < 800) {
    finishRecordingUi("录音太短，请多说一两秒");
    return;
  }
  try {
    const text = await transcribeBlob(blob);
    if (!text) {
      finishRecordingUi("没听清，请靠近麦克风再说一次");
      return;
    }
    if (input) {
      input.value = input.value ? `${input.value.trim()} ${text}` : text;
      autoResize();
      input.focus();
    }
    finishRecordingUi();
  } catch (err) {
    finishRecordingUi();
    appendMessage("assistant", `语音识别失败：${err.message || err}`);
  }
}

async function startRecording() {
  if (voiceBusy || listening) return;
  stopSideAudio();

  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    appendMessage("assistant", "当前浏览器不支持录音，请使用 Chrome / Edge。");
    return;
  }

  if (!acquireVoiceLock()) {
    finishRecordingUi("其他标签页正在录音，请先结束那边的录音");
    appendMessage("assistant", "检测到其他窗口正在使用麦克风，请先在那边点一次麦克风结束，再重试。");
    return;
  }

  voiceBusy = true;
  hardResetRecorder();

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (err) {
    clearVoiceLock();
    voiceBusy = false;
    appendMessage(
      "assistant",
      `无法打开麦克风：${err.message || err}。请在浏览器地址栏允许麦克风权限。`
    );
    finishRecordingUi();
    return;
  }

  recordedChunks = [];
  const mime = pickRecorderMime();
  try {
    mediaRecorder = mime
      ? new MediaRecorder(mediaStream, { mimeType: mime })
      : new MediaRecorder(mediaStream);
  } catch (err) {
    hardResetRecorder();
    clearVoiceLock();
    voiceBusy = false;
    appendMessage("assistant", `无法开始录音：${err.message || err}`);
    finishRecordingUi();
    return;
  }

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.onerror = () => {
    hardResetRecorder();
    finishRecordingUi("录音出错，请重试");
  };

  try {
    mediaRecorder.start(250);
  } catch (err) {
    hardResetRecorder();
    finishRecordingUi();
    appendMessage("assistant", `无法开始录音：${err.message || err}`);
    return;
  }

  listening = true;
  listenIntent = true;
  voiceBusy = false; // allow stop click
  voiceBtn?.classList.add("listening");
  if (voiceBtn) {
    voiceBtn.disabled = false;
    voiceBtn.title = "点击结束并识别";
  }
  if (input) input.placeholder = "正在录音…说完再点一次麦克风";
}

function initSpeech() {
  if (!voiceBtn) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    voiceBtn.title = "当前浏览器不支持录音";
    voiceBtn.disabled = true;
  }
  window.addEventListener("beforeunload", () => {
    hardResetRecorder();
    clearVoiceLock();
  });
  window.addEventListener("storage", (ev) => {
    if (ev.key !== VOICE_LOCK_KEY) return;
    // Another tab took the mic — ensure we are not half-recording
    if (listening && mediaRecorder) {
      /* keep our lock while we hold it */
    }
  });
}

if (voiceBtn) {
  voiceBtn.addEventListener("click", async () => {
    if (voiceBusy) return;
    if (listening || (mediaRecorder && mediaRecorder.state === "recording")) {
      listenIntent = false;
      await stopRecordingAndRecognize();
      return;
    }
    await startRecording();
  });
}

if (voiceSampleBtn && voiceSampleInput) {
  voiceSampleBtn.addEventListener("click", () => voiceSampleInput.click());
  voiceSampleInput.addEventListener("change", async () => {
    const file = voiceSampleInput.files && voiceSampleInput.files[0];
    if (!file) return;
    if (voiceSampleStatus) voiceSampleStatus.textContent = `正在处理 ${file.name}…`;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await apiFetch("/api/voice/sample", { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (voiceSampleStatus) voiceSampleStatus.textContent = data.hint || "音色样本已更新";
      await refreshMeta();
    } catch (err) {
      if (voiceSampleStatus) voiceSampleStatus.textContent = `失败：${err.message}`;
    } finally {
      voiceSampleInput.value = "";
    }
  });
}

speakBtn.addEventListener("click", async () => {
  const raw =
    lastAssistantText ||
    [...chatEl.querySelectorAll(".msg.assistant, .msg.answer")]
      .map((el) => el.dataset.raw || el.textContent)
      .filter(Boolean)
      .pop();
  const text = String(raw || "")
    .replace(/（document_id=\d+）/g, "")
    .replace(/\*\*/g, "")
    .trim();
  if (!text) return;

  // Stop current playback
  if (ttsAudio) {
    ttsAudio.pause();
    ttsAudio = null;
    speakBtn.classList.remove("speaking");
    return;
  }
  if (window.speechSynthesis?.speaking) {
    speechSynthesis.cancel();
    speakBtn.classList.remove("speaking");
    return;
  }

  // Prefer custom cloned voice via backend
  if (ttsReady) {
    speakBtn.classList.add("speaking");
    const prevTitle = speakBtn.title;
    speakBtn.title = "正在用你的音色合成…";
    try {
      const res = await apiFetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.slice(0, 600) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "自定义音色朗读失败");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      ttsAudio = new Audio(url);
      ttsAudio.onended = () => {
        speakBtn.classList.remove("speaking");
        speakBtn.title = prevTitle;
        URL.revokeObjectURL(url);
        ttsAudio = null;
      };
      ttsAudio.onerror = () => {
        speakBtn.classList.remove("speaking");
        speakBtn.title = prevTitle;
        ttsAudio = null;
      };
      await ttsAudio.play();
      speakBtn.title = "点击停止朗读";
      return;
    } catch (err) {
      speakBtn.classList.remove("speaking");
      speakBtn.title = prevTitle;
      appendMessage("assistant", `自定义音色失败，改用系统朗读：${err.message}`);
      // fall through to browser TTS
    }
  }

  if (!window.speechSynthesis) {
    appendMessage("assistant", "当前浏览器不支持语音朗读。");
    return;
  }
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "zh-CN";
  utter.onstart = () => speakBtn.classList.add("speaking");
  utter.onend = () => speakBtn.classList.remove("speaking");
  utter.onerror = () => speakBtn.classList.remove("speaking");
  speechSynthesis.speak(utter);
});

async function bootstrap() {
  initSpeech();
  initTheme();
  initSidebarCollapse();
  initSysClock();
  initKbTabs();
  initAtlasPet();
  initTraceModal();
  initAuthUi();
  showEmptyState();
  const ok = await ensureAuth();
  if (!ok) {
    updateSysBar();
    return;
  }
  await Promise.all([refreshMeta(), loadKnowledge(), loadConversations()]);
  syncNavActive();
  if (conversationId) {
    const loaded = await loadConversation(conversationId);
    if (loaded) {
      lastAssistantText =
        [...history].reverse().find((m) => m.role === "assistant")?.content || "";
      syncNavActive();
      updateSysBar();
      return;
    }
  }
  showEmptyState();
  syncNavActive();
  updateSysBar();
}

function initSidebarCollapse() {
  const app = document.getElementById("appShell");
  const toggle = document.getElementById("sidebarToggle");
  const expand = document.getElementById("railExpandBtn");
  if (!app || !toggle) return;
  const apply = (collapsed) => {
    app.classList.toggle("sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.title = collapsed ? "展开侧栏" : "收起侧栏";
    if (expand) expand.hidden = !collapsed;
    localStorage.setItem("atlas_sidebar", collapsed ? "collapsed" : "expanded");
  };
  apply(localStorage.getItem("atlas_sidebar") === "collapsed");
  toggle.addEventListener("click", () => {
    apply(!app.classList.contains("sidebar-collapsed"));
  });
  expand?.addEventListener("click", () => apply(false));
}

function initSysClock() {
  const el = document.getElementById("sysClock");
  if (!el) return;
  const tick = () => {
    const d = new Date();
    el.textContent = d.toLocaleTimeString("en-GB", { hour12: false });
  };
  tick();
  setInterval(tick, 1000);
}

function initKbTabs() {
  const toggle = document.getElementById("kbToggle");
  const drawer = document.getElementById("kbDrawer");
  if (toggle && drawer) {
    toggle.addEventListener("click", () => {
      const open = drawer.hidden;
      drawer.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.classList.toggle("open", open);
    });
  }
  document.querySelectorAll(".kb-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const panel = tab.dataset.panel;
      document.querySelectorAll(".kb-tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".kb-panel").forEach((p) => {
        const on = p.id === `panel-${panel}`;
        p.classList.toggle("active", on);
        p.hidden = !on;
      });
    });
  });
}

/* T8-3: 系统状态（欢迎页 meta；输入框上方状态条已移除） */
async function updateSysBar(docCount) {
  try {
    const res = await apiFetch("/api/health");
    const data = await res.json();
    lastHealthMeta.mode = data.mode || "";
    lastHealthMeta.model = data.mode === "mock" ? "mock · local" : (data.model || "online");
  } catch {
    lastHealthMeta.model = "offline";
    lastHealthMeta.mode = "";
  }
  if (docCount !== undefined) {
    lastHealthMeta.kb = Number(docCount) || 0;
  }
  const empty = document.getElementById("emptyState");
  if (empty && showingEmpty) {
    const modelEl = empty.querySelector('[data-k="model"]');
    const kbEl = empty.querySelector('[data-k="kb"]');
    if (modelEl) modelEl.textContent = lastHealthMeta.model || "—";
    if (kbEl) {
      const kb = Number(lastHealthMeta.kb) || 0;
      kbEl.textContent = kb > 0 ? `知识库 ${kb} 篇` : "知识库为空，可先导入";
    }
  }
}

/* T8-2: Trace 查看面板 */
function initTraceModal() {
  const btn = document.getElementById("traceBtn");
  if (!btn) return;
  btn.addEventListener("click", openTraceModal);
}

function initAtlasPet() {
  const pet = document.getElementById("atlasPet");
  const face = document.getElementById("petFace");
  const panel = document.getElementById("petPanel");
  const bubble = document.getElementById("petBubble");
  const bubbleText = document.getElementById("petBubbleText");
  if (!pet || !face || !panel) return;

  const PET_POS_KEY = "atlas_pet_pos";
  const idleLines = [
    "有据才说，无据就明说。",
    "制度、流程、报销——先查库再开口。",
    "Atlas：检索 → 综合作答 → 复核。",
    "我是制度导航员，不是瞎编助手。",
    "导入 PDF / Word / zip，我来记。",
  ];
  const pokeLines = [
    "嘿，我在。有制度问题尽管问。",
    "戳我干嘛？拖我可以换个角落。",
    "双击打开协作面板。",
    "知识库空了就导入文档给我。",
    "问差旅、报销、流程——我最熟。",
    "别光戳，发个问题来。",
  ];
  let idleIdx = 0;
  let pokeIdx = 0;
  let bubbleTimer = null;
  let clickTimer = null;
  let dragMoved = false;
  let dragging = false;
  let suppressClick = false;
  let startX = 0;
  let startY = 0;
  let originLeft = 0;
  let originTop = 0;
  let activePointer = null;

  const showBubble = (text, ms = 4200) => {
    if (!bubble || !bubbleText) return;
    bubbleText.textContent = text;
    bubble.hidden = false;
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => {
      if (pet.dataset.state === "idle" && panel.hidden) bubble.hidden = true;
    }, ms);
  };

  const playAnim = (cls) => {
    face.classList.remove("pet-poke", "pet-happy");
    void face.offsetWidth;
    face.classList.add(cls);
    const onEnd = () => {
      face.classList.remove(cls);
      face.removeEventListener("animationend", onEnd);
    };
    face.addEventListener("animationend", onEnd);
  };

  const clampPos = (left, top) => {
    const pad = 8;
    const w = pet.offsetWidth || 72;
    const h = pet.offsetHeight || 96;
    const maxL = Math.max(pad, window.innerWidth - w - pad);
    const maxT = Math.max(pad, window.innerHeight - h - pad);
    return {
      left: Math.min(maxL, Math.max(pad, left)),
      top: Math.min(maxT, Math.max(pad, top)),
    };
  };

  const applyPos = (left, top) => {
    const p = clampPos(left, top);
    pet.style.left = `${p.left}px`;
    pet.style.top = `${p.top}px`;
    pet.style.right = "auto";
    pet.style.bottom = "auto";
    return p;
  };

  const savePos = () => {
    try {
      const left = parseFloat(pet.style.left);
      const top = parseFloat(pet.style.top);
      if (Number.isFinite(left) && Number.isFinite(top)) {
        localStorage.setItem(PET_POS_KEY, JSON.stringify({ left, top }));
      }
    } catch {
      /* ignore */
    }
  };

  const restorePos = () => {
    try {
      const raw = localStorage.getItem(PET_POS_KEY);
      if (!raw) return;
      const { left, top } = JSON.parse(raw);
      if (Number.isFinite(left) && Number.isFinite(top)) applyPos(left, top);
    } catch {
      /* ignore */
    }
  };

  const poke = () => {
    playAnim("pet-poke");
    pokeIdx = (pokeIdx + 1) % pokeLines.length;
    showBubble(pokeLines[pokeIdx], 3200);
  };

  face.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;
    activePointer = e.pointerId;
    face.setPointerCapture?.(e.pointerId);
    dragging = true;
    dragMoved = false;
    startX = e.clientX;
    startY = e.clientY;
    const rect = pet.getBoundingClientRect();
    originLeft = rect.left;
    originTop = rect.top;
    pet.classList.add("pet-dragging");
    e.preventDefault();
  });

  face.addEventListener("pointermove", (e) => {
    if (!dragging || activePointer !== e.pointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!dragMoved && dx * dx + dy * dy > 36) dragMoved = true;
    if (dragMoved) applyPos(originLeft + dx, originTop + dy);
  });

  const endDrag = (e) => {
    if (!dragging) return;
    if (e && activePointer != null && e.pointerId !== activePointer) return;
    dragging = false;
    activePointer = null;
    pet.classList.remove("pet-dragging");
    if (dragMoved) {
      savePos();
      suppressClick = true;
      showBubble("位置记住了，刷新还在这儿。", 2600);
      playAnim("pet-happy");
      setTimeout(() => {
        suppressClick = false;
      }, 0);
    }
  };

  face.addEventListener("pointerup", endDrag);
  face.addEventListener("pointercancel", endDrag);

  face.addEventListener("click", (e) => {
    e.stopPropagation();
    if (suppressClick || dragMoved) {
      dragMoved = false;
      return;
    }
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => poke(), 240);
  });

  face.addEventListener("dblclick", (e) => {
    e.stopPropagation();
    e.preventDefault();
    clearTimeout(clickTimer);
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      playAnim("pet-happy");
      showBubble("三角色协作面板已打开。", 2800);
    } else {
      showBubble("面板收起啦。", 1800);
    }
  });

  face.addEventListener("mouseenter", () => {
    if (dragging || pet.dataset.state !== "idle") return;
    if (!bubble.hidden) return;
    showBubble("拖我移动，点我说话，双击开面板。", 2400);
  });

  document.addEventListener("click", (e) => {
    if (panel.hidden) return;
    if (pet.contains(e.target)) return;
    panel.hidden = true;
  });

  window.addEventListener("resize", () => {
    if (!pet.style.left) return;
    const left = parseFloat(pet.style.left);
    const top = parseFloat(pet.style.top);
    if (Number.isFinite(left) && Number.isFinite(top)) {
      applyPos(left, top);
      savePos();
    }
  });

  setInterval(() => {
    if (pet.dataset.state !== "idle" || !panel.hidden || dragging) return;
    if (Math.random() > 0.4) return;
    idleIdx = (idleIdx + 1) % idleLines.length;
    showBubble(idleLines[idleIdx], 3800);
  }, 14000);

  restorePos();
  setTimeout(() => showBubble("拖我可以挪位置～", 4000), 900);
  pet._showBubble = showBubble;
  pet._playAnim = playAnim;
}

function setPetStatus(text, state) {
  const pet = document.getElementById("atlasPet");
  const status = document.getElementById("petStatus");
  if (status) status.textContent = text || "待命";
  if (pet) pet.dataset.state = state || "idle";
  const lines = {
    busy: "正在规划与取证…",
    review: "复核官对照材料中…",
    idle: null,
  };
  if (pet?._showBubble && state && lines[state]) {
    pet._showBubble(lines[state], 2800);
  }
}

function setPetAgent(role, state) {
  const el = document.querySelector(`.pet-agent[data-role="${role}"]`);
  if (!el) return;
  el.dataset.state = state || "";
}

function resetPetAgents() {
  ["retrieve", "draft", "review"].forEach((r) => setPetAgent(r, ""));
  setPetStatus("待命", "idle");
}

function collabEnabled() {
  const el = document.getElementById("collabToggle");
  return !el || el.checked;
}

function appendCollabReviewNote(botEl, assistantText, hadHits) {
  if (!collabEnabled() || !botEl) return;
  const note = document.createElement("div");
  note.className = "collab-note";
  const ok = Boolean((assistantText || "").trim()) && !looksLikeToolLeak(assistantText || "");
  note.textContent = ok
    ? hadHits
      ? "复核：已对照检索材料核对结论与引用，未发现明显冲突。"
      : "复核：本轮材料有限，结论已按「无据不编造」原则收敛表述。"
    : "复核：回答不完整，建议换个问法或补充制度文档后再问。";
  const host = botEl.closest(".msg-row-assistant") || botEl.parentElement;
  host?.appendChild(note);
}

async function openTraceModal() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-wide">
      <div class="modal-head">
        <span>最近运行 · 执行图</span>
        <button id="closeTrace">✕</button>
      </div>
      <div class="modal-body" id="traceBody">加载中…</div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("#closeTrace").onclick = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  const body = overlay.querySelector("#traceBody");
  try {
    const res = await apiFetch("/api/runs");
    const data = await res.json();
    const runs = Array.isArray(data) ? data : data.runs || [];
    if (!runs.length) {
      body.innerHTML = '<div class="ti-empty">暂无运行记录</div>';
      return;
    }
    body.innerHTML = runs
      .slice(0, 12)
      .map((r, i) => {
        const modeTag = r.mode ? ` · ${r.mode}` : "";
        const rid = escapeHtml(r.run_id || String(i));
        return `<div class="trace-item" data-run-id="${rid}" style="animation-delay:${i * 30}ms">
        <div class="ti-head"><span class="ti-intent">${escapeHtml(r.intent || "?")}${escapeHtml(modeTag)}</span><span class="ti-meta">${escapeHtml(String(r.duration_ms ?? "?"))}ms · ${rid}</span></div>
        <div class="ti-query">${escapeHtml((r.query || "").slice(0, 80))}</div>
        <div class="run-graph ti-graph" data-graph-host></div>
        <div class="run-graph-detail" hidden></div>
      </div>`;
      })
      .join("");

    body.querySelectorAll(".trace-item").forEach((el, idx) => {
      const r = runs[idx];
      const host = el.querySelector("[data-graph-host]");
      const graph =
        r.graph && r.graph.nodes
          ? r.graph
          : {
              run_id: r.run_id,
              nodes: [
                { id: "q", type: "start", label: (r.query || "").slice(0, 80) },
                ...(r.intent
                  ? [{ id: "intent", type: "plan", label: r.intent }]
                  : []),
                ...(r.spans || []).map((s, i) => ({
                  id: `s${i}`,
                  type: "span",
                  label: s.name,
                  ms: s.duration_ms,
                  status: s.error ? "fail" : "ok",
                  detail: s.error || s.meta,
                })),
                { id: "final", type: "final", label: r.mode || "done" },
              ],
              edges: [],
            };
        if (!graph.edges || !graph.edges.length) {
          const ids = graph.nodes.map((n) => n.id);
          graph.edges = ids.slice(0, -1).map((_, i) => [ids[i], ids[i + 1]]);
        }
      if (host) renderRunGraph(host, graph);
    });
  } catch {
    body.innerHTML = '<div class="ti-empty">无法加载运行记录</div>';
  }
}

/* 主题：强制默认深色 Codex；可手动切浅色 */
function initTheme() {
  const btn = document.getElementById("themeBtn");
  // 清掉误存的 light，统一深色基线（用户仍可再点切换）
  const saved = localStorage.getItem("atlas_theme");
  if (saved === "light") {
    localStorage.setItem("atlas_theme", "dark");
  }
  document.documentElement.removeAttribute("data-theme");
  localStorage.setItem("atlas_theme", "dark");
  if (!btn) return;
  btn.title = "切换浅色/深色";
  btn.addEventListener("click", () => {
    const light = document.documentElement.getAttribute("data-theme") === "light";
    if (light) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("atlas_theme", "dark");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem("atlas_theme", "light");
    }
  });
}

bootstrap();
