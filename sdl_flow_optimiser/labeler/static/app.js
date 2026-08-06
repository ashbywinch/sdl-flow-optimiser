"use strict";

const PHASES = { 1: "prd", 2: "tech_design", 3: "flow_design", 4: "breakdown", 5: "dev_plan", 6: "execute", 7: "pr_review", 8: "ux_loop" };
const SHORT = { 1: "prd", 2: "tech", 3: "flow", 4: "brk", 5: "plan", 6: "exec", 7: "pr", 8: "ux" };

let samples = [];
let idx = 0;
let pickedPhase = null;
let ctxOffset = {};

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.text()) || res.status);
  return res.json();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ---------- label pane ----------

async function refreshSets() {
  const s = await api("/api/sample-sets");
  document.getElementById("sets").textContent =
    `adjudicable: ${s.total} · low confidence: ${s.lowconf} · disagreements: ${s.disagreements} · labeled: ${s.labeled}`;
}

async function loadSamples() {
  const kind = document.getElementById("kind").value;
  const n = document.getElementById("count").value || 20;
  samples = await api(`/api/samples?kind=${kind}&n=${n}`);
  idx = 0;
  ctxOffset = {};
  render();
}

function render() {
  const q = document.getElementById("queue");
  q.textContent = "";
  if (samples.length === 0) {
    q.appendChild(el("div", "done", "Nothing to adjudicate in this bucket."));
    return;
  }
  const s = samples[idx];
  const card = el("div", "card");
  const head = el("div", "head");
  head.appendChild(el("span", "tag", s.session));
  head.appendChild(el("span", "tag", `#${idx + 1}/${samples.length}`));
  const phaseTxt = `${SHORT[s.pred_phase]} (${s.confidence})`;
  head.appendChild(el("span", "phase", `pred ${phaseTxt}`));
  if (s.truth_phase) head.appendChild(el("span", "tag", `analyst: ${SHORT[s.truth_phase]}`));
  if (s.delegation) head.appendChild(el("span", "tag", "delegation"));
  card.appendChild(head);
  card.appendChild(el("div", "intent", s.intent || "(no intent)"));
  if (s.args) card.appendChild(el("div", "args", s.args));
  if (s.label) {
    const prev = el("div", "bar", `already marked: ${s.label.agree ? "agree" : "disagree"}${s.label.phase ? " → " + SHORT[s.label.phase] : ""}`);
    card.appendChild(prev);
  }

  const ctx = el("div", "ctx");
  ctx.appendChild(el("button", "more", "show context"));
  ctx._loaded = false;
  ctx._offset = 0;
  ctx._s = s;
  ctx._btn = ctx.firstChild;
  ctx._btn.onclick = async () => {
    if (!ctx._loaded) ctx._offset = 0;
    const body = await api(`/api/samples/${s.call_id}/context?offset=${ctx._offset}`);
    ctx.textContent = "";
    for (const ev of body.events) {
      const line = el("div", ev.this_sample ? "here" : "", `${SHORT[ev.phase]} ${ev.confidence.toFixed(2)} ${ev.tool} — ${(ev.intent || "").slice(0, 60)}`);
      ctx.appendChild(line);
    }
    ctx._loaded = true;
    if (body.more_after) {
      const more = el("button", "more", "more ↓");
      more.onclick = () => { ctx._offset += 10; ctx._btn.onclick(); };
      ctx.appendChild(more);
    }
  };
  card.appendChild(ctx);

  const actions = el("div", "actions");
  const ok = el("button", "ok", "✓ Agree");
  const bad = el("button", "bad", "✗ Disagree");
  ok.onclick = () => submit(s.call_id, true, null);
  bad.onclick = () => submit(s.call_id, false, pickedPhase);
  actions.appendChild(ok);
  actions.appendChild(bad);
  card.appendChild(actions);

  const pick = el("div", "phasepick");
  for (const [id, name] of Object.entries(PHASES)) {
    const b = el("button", "", name);
    b.onclick = () => {
      pickedPhase = Number(id);
      pick.querySelectorAll("button").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    };
    pick.appendChild(b);
  }
  card.appendChild(pick);
  const comment = el("input", "comment");
  comment.placeholder = "comment (optional)";
  card.appendChild(comment);
  q.appendChild(card);

  const submit = async (callId, agree, phase) => {
    await api("/api/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ call_id: callId, agree, phase, comment: comment.value }),
    });
    idx += 1;
    pickedPhase = null;
    render();
    refreshSets();
  };
}

// ---------- sessions pane ----------

let selected = [];

async function loadSessions() {
  const list = await api("/api/sessions");
  const wrap = document.getElementById("sessions");
  wrap.textContent = "";
  const byRepo = {};
  for (const s of list) (byRepo[s.repo] = byRepo[s.repo] || []).push(s);
  for (const [repo, sessions] of Object.entries(byRepo)) {
    wrap.appendChild(el("div", "bar", repo));
    for (const s of sessions) {
      const row = el("div", "session");
      row.style.cursor = "pointer";
      const title = el("div", "s-title", `${s.title || "(untitled)"} · ${s.id.slice(0, 25)}`);
      row.appendChild(title);
      row.appendChild(el("div", "s-meta", `${s.started_at} · ${Object.entries(s.tools).map(([t, c]) => `${t}×${c}`).join(" ")}`));
      row.appendChild(el("div", "s-meta", s.opening || ""));
      row.onclick = () => {
        const i = selected.indexOf(s.id);
        if (i >= 0) selected.splice(i, 1); else selected.push(s.id);
        row.style.outline = selected.includes(s.id) ? "2px solid #4da3ff" : "";
        document.getElementById("associate").disabled = selected.length !== 2;
      };
      wrap.appendChild(row);
    }
  }
  await refreshAssociations();
}

async function refreshAssociations() {
  const list = await api("/api/associations");
  const wrap = document.getElementById("assoc-list");
  wrap.textContent = "";
  wrap.appendChild(el("div", "bar", `associations: ${list.length}`));
  const ul = el("ul");
  for (const a of list) ul.appendChild(el("li", "", `${a.a.slice(0, 30)} ↔ ${a.b.slice(0, 30)}`));
  wrap.appendChild(ul);
}

document.getElementById("associate").onclick = async () => {
  await api("/api/associations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a: selected[0], b: selected[1] }),
  });
  selected = [];
  loadSessions();
};

// ---------- boot ----------

document.getElementById("tab-label").onclick = () => {
  document.getElementById("tab-label").classList.add("active");
  document.getElementById("tab-sessions").classList.remove("active");
  document.getElementById("pane-label").hidden = false;
  document.getElementById("pane-sessions").hidden = true;
};
document.getElementById("tab-sessions").onclick = () => {
  document.getElementById("tab-sessions").classList.add("active");
  document.getElementById("tab-label").classList.remove("active");
  document.getElementById("pane-sessions").hidden = false;
  document.getElementById("pane-label").hidden = true;
  loadSessions();
};
document.getElementById("load").onclick = loadSamples;

refreshSets();
loadSamples();
