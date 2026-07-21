const chatEl = document.getElementById("chat");
const chatScroll = document.getElementById("chatScroll");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
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
let defaultPlaceholder =
  input?.getAttribute("placeholder") || input?.placeholder || "发消息…";


function scrollToBottom() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function appendMessage(role, text, className) {
  removeEmptyState();
  const el = document.createElement("div");
  el.className = `msg ${className || role}`;
  if (role === "assistant" || className === "answer" || className === "assistant") {
    setAnswerContent(el, text || "");
  } else {
    el.textContent = text;
  }
  chatEl.appendChild(el);
  scrollToBottom();
  return el;
}

function createThinkingBox() {
  removeEmptyState();
  const wrap = document.createElement("div");
  wrap.className = "thinking-wrap";
  wrap.innerHTML = `
    <div class="thinking-head"><span class="thinking-title">深度思考中…</span><span class="thinking-toggle">收起</span></div>
    <div class="thinking-body"></div>
  `;
  const head = wrap.querySelector(".thinking-head");
  const body = wrap.querySelector(".thinking-body");
  const title = wrap.querySelector(".thinking-title");
  const toggle = wrap.querySelector(".thinking-toggle");
  head.addEventListener("click", () => {
    body.classList.toggle("collapsed");
    toggle.textContent = body.classList.contains("collapsed") ? "展开" : "收起";
  });
  chatEl.appendChild(wrap);
  scrollToBottom();
  return { wrap, head, body, title };
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
  wrap.innerHTML = `
    <p class="brand-name">Atlas</p>
    <h1>制度优先，也能答一般问题</h1>
    <p>直接提问；或点「导入文件」/ 回形针，把 PDF、Word、图片拖进对话区。</p>
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

function renderMarkdown(text) {
  const raw = String(text || "");
  const blocks = [];
  let src = raw.replace(/```([\s\S]*?)```/g, (_, code) => {
    const i = blocks.length;
    blocks.push(`<pre class="md-code"><code>${escapeHtml(code.replace(/^\n/, ""))}</code></pre>`);
    return `\u0000BLOCK${i}\u0000`;
  });

  src = escapeHtml(src);
  src = src.replace(/^###\s+(.+)$/gm, "<h4>$1</h4>");
  src = src.replace(/^##\s+(.+)$/gm, "<h3>$1</h3>");
  src = src.replace(/^#\s+(.+)$/gm, "<h3>$1</h3>");
  src = src.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  src = src.replace(/\*(.+?)\*/g, "<em>$1</em>");
  src = src.replace(/`([^`]+)`/g, "<code>$1</code>");
  src = src.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Lists
  src = src.replace(/^(?:- |\* )(.+)(?:\n(?:- |\* ).+)*/gm, (block) => {
    const items = block
      .split("\n")
      .map((line) => line.replace(/^(?:- |\* )/, "").trim())
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return `<ul>${items}</ul>`;
  });
  src = src.replace(/^(?:\d+\.\s).+(?:\n\d+\.\s.+)*/gm, (block) => {
    const items = block
      .split("\n")
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
      if (t.startsWith("<h") || t.startsWith("<ul") || t.startsWith("<ol") || t.startsWith("\u0000BLOCK")) {
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

/* T8-1 v2: 纯文本阶段切分，分段渲染 */
function renderAnswerSections(rawText) {
  const markers = [
    { key: "**制度依据**", cls: "as-policy",  icon: "📋" },
    { key: "**推理分析**", cls: "as-reasoning", icon: "💭" },
    { key: "**结论**",     cls: "as-conclusion", icon: "✅" },
    { key: "**补充说明**", cls: "as-note",  icon: "⚠️" },
  ];

  // 找所有 marker 在原文中的位置
  let positions = [];
  for (const m of markers) {
    let idx = rawText.indexOf(m.key);
    if (idx >= 0) {
      positions.push({ idx, ...m });
    }
  }
  if (!positions.length) {
    return renderMarkdown(rawText);
  }

  positions.sort((a, b) => a.idx - b.idx);

  let result = "";

  // 第一个 marker 之前的普通文本
  if (positions[0].idx > 0) {
    const prefix = rawText.slice(0, positions[0].idx).trim();
    if (prefix) result += renderMarkdown(prefix);
  }

  // 每个 section
  for (let i = 0; i < positions.length; i++) {
    const p = positions[i];
    const contentStart = p.idx + p.key.length;
    const contentEnd = i + 1 < positions.length ? positions[i + 1].idx : rawText.length;
    const body = rawText.slice(contentStart, contentEnd).trim();
    const bodyHtml = renderMarkdown(body);
    const title = p.key.replace(/\*\*/g, "");
    result +=
      `<div class="answer-section ${p.cls}">` +
      `<div class="as-head"><span class="as-badge">${p.icon}</span>${title}</div>` +
      `<div class="as-body">${bodyHtml}</div>` +
      `</div>`;
  }

  return result;
}

async function refreshMeta() {
  try {
    const res = await fetch("/api/health");
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

async function loadKnowledge() {
  try {
    const res = await fetch("/api/documents");
    const docs = await res.json();
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
      item.innerHTML = `<strong></strong><p></p><span class="meta"></span>`;
      item.querySelector("strong").textContent = doc.title;
      item.querySelector("p").textContent =
        doc.content.slice(0, 80) + (doc.content.length > 80 ? "…" : "");
      item.querySelector(".meta").textContent = type;
      knowledgeList.appendChild(item);
    }
    updateSysBar(docs.length);
  } catch {
    knowledgeList.innerHTML = '<p class="knowledge-empty">知识库加载失败</p>';
  }
}

async function loadConversation(id) {
  const res = await fetch(`/api/conversations/${id}/messages`);
  if (!res.ok) {
    localStorage.removeItem(STORAGE_KEY);
    conversationId = null;
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
  const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error("删除失败");
  }
  if (String(conversationId) === String(id)) {
    conversationId = null;
    localStorage.removeItem(STORAGE_KEY);
    lastAssistantText = "";
    showEmptyState();
  }
  await loadConversations();
}

async function loadConversations() {
  if (!convList) return;
  try {
    const res = await fetch("/api/conversations", {
      headers: { Accept: "application/json; charset=utf-8" },
    });
    const items = await res.json();
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
        localStorage.setItem(STORAGE_KEY, conversationId);
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
    convList.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "knowledge-empty";
    empty.textContent = "对话列表加载失败";
    convList.appendChild(empty);
  }
}

function startNewChat() {
  conversationId = null;
  localStorage.removeItem(STORAGE_KEY);
  lastAssistantText = "";
  showEmptyState();
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
  history.push({ role: "user", content: userText });
  appendMessage("user", userText);

  const toolNote = appendMessage("tool", "处理中…", "tool");
  let thinkingBox = null;
  let thinkingText = "";
  const botEl = appendMessage("assistant", "");
  botEl.classList.add("answer");
  let assistantText = "";

  sendBtn.disabled = true;
  try {
    const body = {
      messages: history.filter(
        (m) => m.content && m.content !== "（无内容）" && m.content !== "（无内容返回）"
      ),
      use_tools: true,
      deep_think: deepThinkToggle.checked,
    };
    if (conversationId) body.conversation_id = Number(conversationId);

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
    });

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
        toolNote.textContent = `规划 · ${p.intent || "?"}：${steps || "作答"}`;
      } else if (event === "trace") {
        const t = payload.trace || {};
        const spans = (t.spans || [])
          .map((s) => `${s.name} ${s.duration_ms}ms`)
          .join(" · ");
        toolNote.textContent = `trace ${t.run_id || ""} · ${t.duration_ms || "?"}ms${
          spans ? " · " + spans : ""
        }`;
      } else if (event === "rag_context") {
        const titles = (payload.hits || []).map((h) => `《${h.title}》`).join("、");
        toolNote.textContent = titles ? `已检索 ${titles}` : "知识库无直接匹配";
        if (titles) appendMessage("rag", `来源 ${titles}`, "rag");
      } else if (event === "thinking_start") {
        toolNote.textContent = "深度思考中…";
        if (!thinkingBox) thinkingBox = createThinkingBox();
      } else if (event === "thinking_token") {
        thinkingText += payload.content || "";
        if (thinkingBox) {
          thinkingBox.body.textContent = thinkingText;
          scrollToBottom();
        }
      } else if (event === "thinking_done") {
        if (thinkingBox) {
          thinkingBox.title.textContent = "思考过程";
          thinkingBox.body.classList.add("collapsed");
          const toggle = thinkingBox.wrap.querySelector(".thinking-toggle");
          if (toggle) toggle.textContent = "展开";
        }
        toolNote.textContent = "生成回答…";
      } else if (event === "answer_start") {
        /* keep existing text; do not clear mid-stream */
      } else if (event === "tool_start") {
        const labels = {
          research_topics: "多方面检索并自主学习…",
          web_search: "联网搜索中…",
          search_knowledge: "查阅知识库…",
          learn_knowledge: "写入知识库…",
          get_current_time: "获取时间…",
          calculator: "计算中…",
        };
        toolNote.textContent = labels[payload.name] || `工具 · ${payload.name}`;
      } else if (event === "tool_result") {
        if (payload.name === "research_topics") {
          try {
            const data = JSON.parse(payload.content || "{}");
            const n = data.learned_count ?? (data.learned || []).length;
            const c = data.count ?? (data.hits || []).length;
            toolNote.textContent = `已自主学习 ${n} 条，可用材料 ${c} 条`;
          } catch {
            toolNote.textContent = "完成 · 自主学习";
          }
        } else if (payload.name === "web_search") {
          try {
            const data = JSON.parse(payload.content || "{}");
            const c = data.count ?? (data.hits || []).length;
            toolNote.textContent = c ? `联网找到 ${c} 条网页` : "联网未找到结果";
          } catch {
            toolNote.textContent = "完成 · 联网搜索";
          }
        } else {
          toolNote.textContent = `完成 · ${payload.name}`;
        }
      } else if (event === "token") {
        assistantText += payload.content || "";
        setAnswerContent(botEl, assistantText);
        scrollToBottom();
      } else if (event === "error") {
        assistantText += `\n[错误] ${payload.content || "未知错误"}`;
        setAnswerContent(botEl, assistantText);
      } else if (event === "done") {
        if (payload.mode === "guard_blocked") {
          if (toolNote.isConnected) toolNote.remove();
          botEl.className = "msg guard-warn";
          return;
        }
        if (payload.conversation_id) {
          conversationId = String(payload.conversation_id);
          localStorage.setItem(STORAGE_KEY, conversationId);
        }
        if ((!assistantText || !assistantText.trim()) && payload.answer) {
          assistantText = payload.answer;
          setAnswerContent(botEl, assistantText);
        }
        if (!assistantText || !assistantText.trim()) {
          assistantText = "暂时没有生成回答，请再试一次。";
          setAnswerContent(botEl, assistantText);
        }
        if (toolNote.isConnected) toolNote.remove();
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
      assistantText = "暂时没有生成回答，请再试一次。";
      setAnswerContent(botEl, assistantText);
    }
    if (toolNote.isConnected) toolNote.remove();
    lastAssistantText = assistantText;
    history.push({ role: "assistant", content: assistantText });
  } catch (err) {
    setAnswerContent(botEl, `请求失败：${err.message}`);
    if (toolNote.isConnected) toolNote.remove();
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

learnForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = learnTitle.value.trim();
  const content = learnContent.value.trim();
  if (!title || !content) return;
  try {
    const res = await fetch("/api/knowledge/learn", {
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

input.addEventListener("input", autoResize);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

newChatBtn.addEventListener("click", startNewChat);
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
  const res = await fetch("/api/knowledge/upload", { method: "POST", body: fd });
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
  const files = [...(fileList || [])].filter(Boolean);
  if (!files.length) return;
  removeEmptyState();
  const okTitles = [];
  const failMsgs = [];
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    setUploadStatus(`正在导入（${i + 1}/${files.length}）${file.name}…`);
    try {
      const doc = await uploadKnowledgeFile(file);
      okTitles.push(doc.title || file.name);
    } catch (err) {
      failMsgs.push(`${file.name}：${err.message || err}`);
    }
  }
  if (fileCaption) fileCaption.value = "";
  if (fileInput) fileInput.value = "";
  await loadKnowledge();
  if (okTitles.length) {
    setUploadStatus(`已导入 ${okTitles.length} 个文件`);
    appendMessage(
      "assistant",
      `已导入并写入知识库：\n${okTitles.map((t) => `- 《${t}》`).join("\n")}\n\n可以直接提问相关内容。`,
    );
  }
  if (failMsgs.length) {
    setUploadStatus(`部分失败：${failMsgs[0]}`);
    appendMessage("assistant", `导入失败：\n${failMsgs.map((m) => `- ${m}`).join("\n")}`);
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
  }
});

// 拖拽导入：主聊天区
const chatScroll = document.getElementById("chatScroll");
const dropOverlay = document.getElementById("dropOverlay");
let dragDepth = 0;

function isFileDrag(e) {
  return [...(e.dataTransfer?.types || [])].includes("Files");
}

function showDrop(on) {
  if (!chatScroll || !dropOverlay) return;
  chatScroll.classList.toggle("drag-over", on);
  dropOverlay.hidden = !on;
}

["dragenter", "dragover"].forEach((ev) => {
  window.addEventListener(ev, (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
  });
});

chatScroll?.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth += 1;
  showDrop(true);
});
chatScroll?.addEventListener("dragleave", (e) => {
  if (!isFileDrag(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) showDrop(false);
});
chatScroll?.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
});
chatScroll?.addEventListener("drop", async (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  showDrop(false);
  const files = e.dataTransfer?.files;
  if (!files?.length) return;
  try {
    await uploadKnowledgeFiles(files);
  } catch (err) {
    setUploadStatus(`导入失败：${err.message}`);
  }
});

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
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
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
  const res = await fetch("/api/stt", { method: "POST", body: fd });
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
  voiceBtn.classList.remove("listening");
  voiceBtn.title = sttReady ? "点击开始语音输入" : "本地语音识别未就绪";
  input.placeholder = msg || defaultPlaceholder;
}

async function stopRecordingAndRecognize() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    finishRecordingUi();
    releaseMediaStream();
    return;
  }
  input.placeholder = "正在识别语音…";
  await new Promise((resolve) => {
    mediaRecorder.addEventListener("stop", resolve, { once: true });
    try {
      mediaRecorder.stop();
    } catch {
      resolve();
    }
  });
  releaseMediaStream();
  mediaRecorder = null;
  listening = false;
  voiceBtn.classList.remove("listening");

  const mime = recordedChunks[0]?.type || "audio/webm";
  const blob = new Blob(recordedChunks, { type: mime });
  recordedChunks = [];
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
    input.value = input.value ? `${input.value.trim()} ${text}` : text;
    autoResize();
    finishRecordingUi();
    input.focus();
  } catch (err) {
    finishRecordingUi();
    appendMessage("assistant", `语音识别失败：${err.message}`);
  }
}

async function startRecording() {
  stopSideAudio();
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    appendMessage("assistant", "当前浏览器不支持录音，请使用 Chrome / Edge。");
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (err) {
    appendMessage(
      "assistant",
      `无法打开麦克风：${err.message || err}。请在浏览器地址栏允许麦克风权限。`
    );
    return;
  }

  recordedChunks = [];
  const mime = pickRecorderMime();
  try {
    mediaRecorder = mime
      ? new MediaRecorder(mediaStream, { mimeType: mime })
      : new MediaRecorder(mediaStream);
  } catch (err) {
    releaseMediaStream();
    appendMessage("assistant", `无法开始录音：${err.message || err}`);
    return;
  }

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.start(200);
  listening = true;
  listenIntent = true;
  voiceBtn.classList.add("listening");
  voiceBtn.title = "点击结束并识别";
  input.placeholder = "正在录音…说完再点一次麦克风";
}

function initSpeech() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    voiceBtn.title = "当前浏览器不支持录音";
    voiceBtn.disabled = true;
  }
}

voiceBtn.addEventListener("click", async () => {
  if (listening || (mediaRecorder && mediaRecorder.state === "recording")) {
    listenIntent = false;
    await stopRecordingAndRecognize();
    return;
  }
  await startRecording();
});

if (voiceSampleBtn && voiceSampleInput) {
  voiceSampleBtn.addEventListener("click", () => voiceSampleInput.click());
  voiceSampleInput.addEventListener("change", async () => {
    const file = voiceSampleInput.files && voiceSampleInput.files[0];
    if (!file) return;
    if (voiceSampleStatus) voiceSampleStatus.textContent = `正在处理 ${file.name}…`;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/voice/sample", { method: "POST", body: fd });
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
      const res = await fetch("/api/tts", {
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
  initTraceModal();
  await refreshMeta();
  await loadKnowledge();
  await loadConversations();
  if (conversationId) {
    const loaded = await loadConversation(conversationId);
    if (loaded) {
      lastAssistantText = [...history].reverse().find((m) => m.role === "assistant")?.content || "";
      return;
    }
  }
  showEmptyState();
  updateSysBar();
}

/* T8-3: 系统状态栏 */
async function updateSysBar(docCount) {
  const sysModel = document.getElementById("sysModel");
  const sysDot = document.getElementById("sysDot");
  const sysKB = document.getElementById("sysKB");
  if (!sysModel || !sysDot || !sysKB) return;
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    sysModel.textContent = data.mode === "mock" ? "Mock 模式" : (data.model || "在线");
    sysDot.className = "sys-dot " + (data.mode === "mock" ? "warn" : "ok");
  } catch {
    sysModel.textContent = "未连接";
    sysDot.className = "sys-dot err";
  }
  if (docCount !== undefined) {
    sysKB.textContent = `知识库 ${docCount} 篇`;
  }
}

/* T8-2: Trace 查看面板 */
function initTraceModal() {
  const btn = document.getElementById("traceBtn");
  if (!btn) return;
  btn.addEventListener("click", openTraceModal);
}

async function openTraceModal() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-head">
        <span>📊 最近运行记录</span>
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
    const res = await fetch("/api/runs");
    const runs = await res.json();
    if (!runs || !runs.length) {
      body.innerHTML = '<div class="ti-empty">暂无运行记录</div>';
      return;
    }
    body.innerHTML = runs.slice(0, 12).map((r, i) => {
      const spans = (r.spans || []).map(s =>
        `<span>${s.name} ${s.duration_ms || "?"}ms</span>`
      ).join("");
      const modeTag = r.mode ? ` · ${r.mode}` : "";
      return `<div class="trace-item" style="animation-delay:${i*30}ms">
        <div class="ti-head"><span class="ti-intent">${r.intent || "?"}${modeTag}</span><span class="ti-meta">${r.duration_ms || "?"}ms · ${r.run_id || ""}</span></div>
        <div class="ti-query">${escapeHtml((r.query || "").slice(0, 80))}</div>
        <div class="ti-spans">${spans || "无记录"}</div>
      </div>`;
    }).join("");
  } catch {
    body.innerHTML = '<div class="ti-empty">无法加载运行记录</div>';
  }
}

/* T8-4: 暗色模式 */
function initTheme() {
  const saved = localStorage.getItem("atlas_theme");
  if (saved === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    const btn = document.getElementById("themeBtn");
    if (btn) btn.textContent = "☀️";
  }
  const btn = document.getElementById("themeBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("atlas_theme", "light");
      btn.textContent = "🌙";
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem("atlas_theme", "dark");
      btn.textContent = "☀️";
    }
  });
}

bootstrap();
