// OpsDesk UI v1 (M04). Plain JS, no build step, no framework.
//
// Flow: persona → POST /api/session (token) → POST /api/threads (thread id) →
// POST /api/chat, read as an SSE stream with fetch + a stream reader (EventSource
// only supports GET and cannot send the Authorization header).
//
// Every string from the server is put on screen with textContent, never innerHTML.
// Unknown event kinds and statuses render as plain rows: the event contract may add
// them within v1 (open value sets), and the UI must never crash on them.
"use strict";

const STARTERS = {
  default: ["What's the status of T-0002?", "List my tickets", "Show me T-0003", "Show ticket abc"],
  "G-001": ["List my tickets", "Show me T-0002"],
};
const KNOWN_STATUSES = new Set([
  "ok", "empty", "not_found", "invalid", "denied", "unavailable", "timeout",
  "completed", "failed", "cancelled", "blocked", "interrupted",
]);

const state = {
  personas: [],
  persona: null,   // {id, name, ...}
  token: null,
  threadId: null,
  busy: false,
  controller: null, // AbortController of the running chat request
};

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};

// ------------------------------------------------------------------ API calls

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  return fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
}

async function login(persona) {
  const res = await api("/api/session", { method: "POST", body: { employee_id: persona.id }, auth: false });
  if (!res.ok) throw new Error(`login failed (${res.status})`);
  state.token = (await res.json()).token;
}

async function newThread() {
  let res = await api("/api/threads", { method: "POST" });
  if (res.status === 401) { // token expired or server restarted (random dev secret)
    await login(state.persona);
    res = await api("/api/threads", { method: "POST" });
  }
  if (!res.ok) throw new Error(`could not create a thread (${res.status})`);
  state.threadId = (await res.json()).thread_id;
  $("thread-label").textContent = state.threadId.slice(0, 12) + "…";
  $("thread-label").title = state.threadId;
}

// ------------------------------------------------------------------ persona + thread

async function selectPersona(id) {
  stopRunning();
  state.persona = state.personas.find((p) => p.id === id);
  // Switching persona = new session + new thread.
  await login(state.persona);
  await newThread();
  $("messages").replaceChildren();
  $("timeline").replaceChildren();
  addSystem(`Signed in as ${state.persona.name} (${state.persona.id}, ${state.persona.tenant_id}) · roles: ${state.persona.roles.join(", ")}`);
  renderStarters();
}

async function reset() {
  stopRunning();
  await newThread(); // Reset = a new thread: the agent forgets the conversation
  $("messages").replaceChildren();
  $("timeline").replaceChildren();
  addSystem("New thread: the agent starts with an empty conversation.");
  renderStarters();
}

function renderStarters() {
  const list = STARTERS[state.persona?.id] || STARTERS.default;
  const box = $("starters");
  box.replaceChildren(...list.map((q) => {
    const b = el("button", "", q);
    b.type = "button";
    b.addEventListener("click", () => send(q));
    return b;
  }));
}

// ------------------------------------------------------------------ chat

function addMessage(role, text, label) {
  const wrap = el("div", `msg ${role}`);
  if (label) wrap.append(el("span", "who", label));
  const bubble = el("div", "bubble", text);
  wrap.append(bubble);
  $("messages").append(wrap);
  scrollToEnd($("messages"));
  return { wrap, bubble };
}
const addSystem = (text) => addMessage("system", text);

function stopRunning() {
  if (state.controller) state.controller.abort(); // the server cancels the run (D6)
  state.controller = null;
}

async function send(text) {
  const message = text.trim();
  if (!message || state.busy) return;
  setBusy(true);
  $("input").value = "";
  addMessage("user", message, state.persona.name);
  const assistant = addMessage("assistant", "", "…");
  assistant.wrap.classList.add("streaming");
  const turn = startTurn();

  state.controller = new AbortController();
  try {
    let res = await postChat(message);
    if (res.status === 401) { await login(state.persona); res = await postChat(message); }
    if (res.status === 404) { // thread unknown (e.g. server restarted): open a new one
      addSystem("This thread no longer exists on the server; starting a new one.");
      await newThread();
      res = await postChat(message);
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      assistant.bubble.textContent = `Request refused (${res.status}): ${formatDetail(detail.detail)}`;
      return;
    }
    await readSse(res.body, (frame) => onEvent(frame, assistant, turn));
  } catch (err) {
    if (err.name === "AbortError") addSystem("Stopped: the request was cancelled.");
    else addSystem(`Error: ${err.message}`);
  } finally {
    assistant.wrap.classList.remove("streaming");
    if (!assistant.bubble.textContent) assistant.bubble.textContent = "(no answer)";
    state.controller = null;
    setBusy(false);
  }
}

function postChat(message) {
  return fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
    body: JSON.stringify({ thread_id: state.threadId, message }),
    signal: state.controller.signal,
  });
}

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return "unknown error";
}

function setBusy(busy) {
  state.busy = busy;
  $("send").disabled = busy;
  $("input").disabled = busy;
  if (!busy) $("input").focus();
}

// ------------------------------------------------------------------ SSE parsing

// Read a text/event-stream body: frames are separated by a blank line; each has
// "event:", "id:" and "data:" lines; lines starting with ":" are keep-alive comments.
async function readSse(body, onFrame) {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const frame = parseFrame(block);
      if (frame) onFrame(frame);
    }
  }
}

function parseFrame(block) {
  let event = null;
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    const parsed = JSON.parse(data.join("\n"));
    return { ...parsed, kind: parsed.kind || event };
  } catch {
    return { kind: event || "unparsable", payload: {} };
  }
}

// ------------------------------------------------------------------ events → UI

function startTurn() {
  return { t0: null, calls: new Map() };
}

function onEvent(ev, assistant, turn) {
  const p = ev.payload || {};
  const ts = Date.parse(ev.ts);
  if (ev.kind === "run_started" || turn.t0 === null) turn.t0 = ts;
  const rel = Number.isFinite(ts) && Number.isFinite(turn.t0) ? `+${((ts - turn.t0) / 1000).toFixed(1)}s` : "";

  if (ev.kind === "token") {
    assistant.bubble.textContent += p.text ?? "";
    assistant.wrap.querySelector(".who").textContent = p.agent || "assistant";
    scrollToEnd($("messages"));
    return; // tokens are shown in the chat, not as timeline rows
  }

  const row = el("li", ev.kind);
  row.append(el("span", "t", rel), el("span", "kind", ev.kind));
  const detail = el("span", "detail");
  const right = el("span", "right");

  switch (ev.kind) {
    case "run_started":
      row.classList.add("turn");
      detail.append(el("span", "", `entrypoint ${p.entrypoint ?? ""}`));
      break;
    case "tool_started":
      detail.append(el("strong", "", p.tool ?? "?"), el("span", "args", ` ${formatArgs(p.args)}`));
      break;
    case "tool_finished":
      detail.append(el("strong", "", p.tool ?? "?"));
      if (p.summary) detail.append(el("span", "args", ` ${p.summary}`));
      right.append(badge(p.status));
      if (p.error_code) right.append(el("span", "code", p.error_code));
      if (p.duration_ms !== undefined) right.append(el("span", "muted", `${p.duration_ms} ms`));
      break;
    case "run_finished":
      right.append(badge(p.status));
      break;
    default: // a kind this UI does not know yet: show it, never crash
      detail.append(el("span", "args", JSON.stringify(p)));
  }
  row.append(detail, right);

  // Pair tool_started / tool_finished rows by call_id (hover highlights the pair).
  if (p.call_id && (ev.kind === "tool_started" || ev.kind === "tool_finished")) {
    row.dataset.call = p.call_id;
    row.addEventListener("mouseenter", () => highlight(p.call_id, true));
    row.addEventListener("mouseleave", () => highlight(p.call_id, false));
    const started = turn.calls.get(p.call_id);
    if (ev.kind === "tool_finished" && started) {
      started.after(row); // keep the pair together even if other events came between
      turn.calls.delete(p.call_id);
      scrollToEnd($("timeline"));
      return;
    }
    if (ev.kind === "tool_started") turn.calls.set(p.call_id, row);
  }

  $("timeline").append(row);
  if (ev.kind === "run_finished") {
    const secs = p.duration_ms !== undefined ? (p.duration_ms / 1000).toFixed(1) : "?";
    $("timeline").append(el("li", "summary-line", `turn ${p.status ?? "finished"} in ${secs} s`));
  }
  scrollToEnd($("timeline"));
}

function badge(status) {
  const known = KNOWN_STATUSES.has(status);
  return el("span", `badge ${known ? status : "other"}`, status ?? "?");
}

function formatArgs(args) {
  if (!args || typeof args !== "object") return "";
  return "(" + Object.entries(args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") + ")";
}

function highlight(callId, on) {
  for (const row of document.querySelectorAll(`[data-call="${CSS.escape(callId)}"]`)) {
    row.classList.toggle("paired", on);
  }
}

function scrollToEnd(node) {
  node.scrollTop = node.scrollHeight;
}

// ------------------------------------------------------------------ boot

async function boot() {
  const res = await api("/api/personas", { auth: false });
  state.personas = await res.json();
  const select = $("persona");
  select.replaceChildren(...state.personas.map((p) => {
    const option = el("option", "", `${p.name} · ${p.id} · ${p.tenant_id} · ${p.roles.join("/")}`);
    option.value = p.id;
    return option;
  }));
  select.addEventListener("change", () => selectPersona(select.value).catch(showError));
  $("reset").addEventListener("click", () => reset().catch(showError));
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); send($("input").value); });
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("input").value); }
  });
  await selectPersona(state.personas[0].id);
}

function showError(err) {
  addSystem(`Error: ${err.message}`);
}

boot().catch(showError);
