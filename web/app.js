"use strict";

// Minimal single-page controller for the debrief tool. Talks to the local
// JSON API exposed by debrief/server.py.

const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw await toError(res);
    return res.headers.get("content-type")?.includes("application/json")
      ? res.json()
      : res.text();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = res.headers.get("content-type")?.includes("application/json")
      ? await res.json()
      : await res.text();
    if (!res.ok) throw { status: res.status, data };
    return data;
  },
  async del(path) {
    const res = await fetch(path, { method: "DELETE" });
    if (!res.ok) throw await toError(res);
    return res.json();
  },
};

async function toError(res) {
  let data;
  try { data = await res.json(); } catch (_) { data = await res.text(); }
  return { status: res.status, data };
}

const $ = (id) => document.getElementById(id);
const state = { sessionId: null, config: null };

const STATUS_DOT = {
  Complete: "ok",
  "Needs more detail": "warn",
  "Not addressed": "miss",
};

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  $("btn-home").classList.toggle("hidden", name === "home");
}

// ------------------------------------------------------------------ //
// Init
// ------------------------------------------------------------------ //
async function init() {
  try {
    state.config = await api.get("/api/config");
    const badge = $("engine-badge");
    if (state.config.llm_active) {
      badge.textContent = "engine: LLM (" + state.config.model + ")";
      badge.classList.add("badge-live");
    } else {
      badge.textContent = "engine: rule-based (offline)";
    }
    populateMissionTypes(state.config.mission_types || []);
  } catch (e) {
    console.error(e);
  }
  bindEvents();
  await refreshSessions();
  showView("home");
}

function populateMissionTypes(types) {
  const sel = $("mission-type");
  types.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  });
}

function bindEvents() {
  $("btn-new").addEventListener("click", startNew);
  $("btn-home").addEventListener("click", async () => {
    await refreshSessions();
    showView("home");
  });
  $("meta-form").addEventListener("submit", submitMetadata);
  $("btn-next").addEventListener("click", submitAnswer);
  $("btn-skip").addEventListener("click", skipQuestion);
  $("btn-report").addEventListener("click", viewReport);
  $("btn-download").addEventListener("click", downloadReport);
}

// ------------------------------------------------------------------ //
// Home / sessions
// ------------------------------------------------------------------ //
async function refreshSessions() {
  const list = $("session-list");
  try {
    const { sessions } = await api.get("/api/sessions");
    if (!sessions.length) {
      list.innerHTML = '<p class="empty">No saved debriefs yet.</p>';
      return;
    }
    list.innerHTML = "";
    sessions.forEach((s) => list.appendChild(sessionRow(s)));
  } catch (e) {
    list.innerHTML = '<p class="empty">Could not load saved debriefs.</p>';
  }
}

function sessionRow(s) {
  const row = document.createElement("div");
  row.className = "session-item";
  const done = s.state === "complete";
  row.innerHTML = `
    <div>
      <div class="s-name">${escapeHtml(s.mission_name || "Untitled")}</div>
      <div class="s-meta">${escapeHtml(s.unit || "-")} · ${escapeHtml(s.date_time || "-")}
        · ${done ? "complete" : "in progress"} · ${s.overall_score}/100</div>
    </div>
    <div class="session-actions"></div>`;
  const actions = row.querySelector(".session-actions");

  const openBtn = document.createElement("button");
  openBtn.className = "btn btn-ghost";
  openBtn.textContent = done ? "Review" : "Resume";
  openBtn.addEventListener("click", () => resumeSession(s.id));
  actions.appendChild(openBtn);

  const delBtn = document.createElement("button");
  delBtn.className = "btn btn-ghost";
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", async () => {
    await api.del("/api/session/" + s.id);
    await refreshSessions();
  });
  actions.appendChild(delBtn);
  return row;
}

async function resumeSession(id) {
  state.sessionId = id;
  const step = await api.get("/api/session/" + id + "/current");
  if (step.state === "complete") return showSummary();
  if (step.state === "metadata") return showView("metadata");
  renderStep(step);
  await refreshSidebar();
  showView("debrief");
}

// ------------------------------------------------------------------ //
// New debrief + metadata
// ------------------------------------------------------------------ //
async function startNew() {
  const step = await api.post("/api/session");
  state.sessionId = step.session_id;
  $("meta-form").reset();
  $("meta-errors").classList.add("hidden");
  showView("metadata");
}

async function submitMetadata(ev) {
  ev.preventDefault();
  const form = new FormData($("meta-form"));
  const payload = {
    mission_name: form.get("mission_name"),
    date_time: form.get("date_time"),
    unit: form.get("unit"),
    location: form.get("location"),
    mission_type: form.get("mission_type"),
    participants: String(form.get("participants") || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  };
  try {
    const step = await api.post(
      "/api/session/" + state.sessionId + "/metadata",
      payload
    );
    renderStep(step);
    await refreshSidebar();
    showView("debrief");
  } catch (e) {
    const box = $("meta-errors");
    const errs = (e.data && e.data.errors) || ["Could not start debrief."];
    box.innerHTML = "<strong>Fix the following:</strong><ul>" +
      errs.map((x) => "<li>" + escapeHtml(x) + "</li>").join("") + "</ul>";
    box.classList.remove("hidden");
  }
}

// ------------------------------------------------------------------ //
// Question flow
// ------------------------------------------------------------------ //
function renderStep(step) {
  if (step.state === "complete") return showSummary();
  const q = step.question;
  const p = step.prompt;
  $("q-phase").textContent = q ? q.phase : "";
  $("q-prompt").textContent = p ? p.text : "";
  $("q-intent").textContent = q ? q.intent : "";

  const fu = $("q-followup");
  const reason = $("q-reason");
  if (p && p.is_follow_up) {
    fu.classList.remove("hidden");
    reason.textContent = p.reason || "";
    reason.classList.toggle("hidden", !p.reason);
  } else {
    fu.classList.add("hidden");
    reason.classList.add("hidden");
  }
  $("q-optional").classList.toggle("hidden", !q || q.required);

  $("answer").value = "";
  $("answer").focus();
  updateProgress(step.progress);
}

async function submitAnswer() {
  const text = $("answer").value.trim();
  const step = await api.post("/api/session/" + state.sessionId + "/answer", {
    text,
  });
  renderFeedback(step.evaluation);
  renderStep(step);
  await refreshSidebar();
}

async function skipQuestion() {
  const step = await api.post("/api/session/" + state.sessionId + "/skip");
  $("feedback").classList.add("hidden");
  renderStep(step);
  await refreshSidebar();
}

function renderFeedback(ev) {
  const box = $("feedback");
  if (!ev) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.classList.toggle("pass", ev.passed);
  box.classList.toggle("fail", !ev.passed);
  const issues = (ev.issues || []).map((i) => "<li>" + escapeHtml(i) + "</li>").join("");
  box.innerHTML = `
    <div class="fb-head">
      <span class="fb-score">${ev.score}/100</span>
      <span class="fb-level">${escapeHtml(ev.level)}${ev.passed ? " · accepted" : " · needs detail"}</span>
    </div>
    ${issues ? '<ul class="fb-issues">' + issues + "</ul>" : ""}
    ${ev.coaching ? '<div class="fb-coach">' + escapeHtml(ev.coaching) + "</div>" : ""}`;
}

function updateProgress(progress) {
  if (!progress) return;
  $("progress-pct").textContent = progress.percent + "%";
  $("progress-fill").style.width = progress.percent + "%";
}

async function refreshSidebar() {
  try {
    const score = await api.get("/api/session/" + state.sessionId + "/score");
    const list = $("section-list");
    list.innerHTML = "";
    const currentPhase = $("q-phase").textContent;
    score.sections.forEach((s) => {
      const li = document.createElement("li");
      if (s.phase === currentPhase) li.classList.add("active");
      li.innerHTML = `<span class="dot ${STATUS_DOT[s.status] || ""}"></span>
        <span>${escapeHtml(s.phase)}</span>`;
      list.appendChild(li);
    });
  } catch (_) { /* non-fatal */ }
}

// ------------------------------------------------------------------ //
// Summary + report
// ------------------------------------------------------------------ //
async function showSummary() {
  const score = await api.get("/api/session/" + state.sessionId + "/score");
  $("overall-score").textContent = score.overall;
  $("score-summary").textContent =
    `${score.answered} of ${score.total} questions answered. ` +
    "Review the section breakdown below and export the full report.";
  const ring = document.querySelector(".score-ring");
  ring.style.borderColor = score.overall >= 75
    ? "var(--ok)" : score.overall >= 50 ? "var(--warn)" : "var(--miss)";

  const list = $("summary-sections");
  list.innerHTML = "";
  score.sections.forEach((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<span><span class="dot ${STATUS_DOT[s.status] || ""}"></span>
      ${escapeHtml(s.phase)}</span>
      <span class="s-status">${escapeHtml(s.status)} · ${s.score}/100</span>`;
    list.appendChild(li);
  });
  $("report-view").classList.add("hidden");
  showView("summary");
}

async function viewReport() {
  const md = await api.get("/api/session/" + state.sessionId + "/report");
  $("report-text").textContent = md;
  $("report-view").classList.remove("hidden");
  $("report-view").scrollIntoView({ behavior: "smooth" });
}

async function downloadReport() {
  const md = await api.get("/api/session/" + state.sessionId + "/report");
  const blob = new Blob([md], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "debrief-" + state.sessionId.slice(0, 8) + ".md";
  a.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

window.addEventListener("DOMContentLoaded", init);
