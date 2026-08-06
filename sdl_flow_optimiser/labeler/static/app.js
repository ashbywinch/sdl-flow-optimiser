"use strict";

const PHASES = { 1: "prd", 2: "tech_design", 3: "flow_design", 4: "breakdown", 5: "dev_plan", 6: "execute", 7: "pr_review", 8: "ux_loop" };
const SHORT = { 1: "prd", 2: "tech", 3: "flow", 4: "brk", 5: "plan", 6: "exec", 7: "pr", 8: "ux" };

const state = {
  samples: [],
  idx: 0,
  picked: null,
  batch: [], // {call_id, verdict, phase, session}
  session: null, // {id, events, event_count}
  sessionsList: [],
  sessionIdx: -1,
  selected: [],
};

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

function phasePills(container, onPick) {
  const pick = el("div", "phasepick");
  for (const [id, name] of Object.entries(PHASES)) {
    const b = el("button", "", name);
    b.onclick = () => {
      state.picked = Number(id);
      pick.querySelectorAll("button").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    };
    pick.appendChild(b);
  }
  container.appendChild(pick);
  return pick;
}

function toast(msg, undoFn) {
  const t = document.getElementById("toast");
  t.textContent = "";
  t.appendChild(el("span", "", msg));
  if (undoFn) {
    const u = el("button", "", "Undo");
    u.onclick = () => { t.style.display = "none"; undoFn(); };
    t.appendChild(u);
  }
  t.style.display = "flex";
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.display = "none"; }, 5000);
}

async function adjudicate(callId, predPhase, agree, phase, comment, after) {
  await api("/api/labels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, agree, phase, comment }),
  });
  const verdict = agree ? `Saved: agree — ${SHORT[predPhase]}` : `Saved: disagree — ${SHORT[predPhase]}${phase ? " → " + SHORT[phase] : " (no correction)"}`;
  toast(verdict, async () => {
    await api(`/api/labels/${callId}`, { method: "DELETE" });
    after && after();
    refreshSets();
  });
  after && after();
  refreshSets();
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
  state.samples = await api(`/api/samples?kind=${kind}&n=${n}`);
  state.idx = 0;
  state.picked = null;
  state.batch = [];
  renderLabel();
}

function openSessionFromLabel(sample) {
  showSession(sample.session_id);
}

function renderLabel() {
  const q = document.getElementById("queue");
  q.textContent = "";
  if (state.samples.length === 0) {
    q.appendChild(el("div", "done", "Nothing to adjudicate in this bucket."));
    return;
  }
  if (state.idx >= state.samples.length) {
    const s = el("div", "summary");
    s.appendChild(el("div", "s-title", "Batch complete"));
    const agrees = state.batch.filter((b) => b.verdict === "agree").length;
    const disagrees = state.batch.length - agrees;
    s.appendChild(el("div", "hint", `${state.batch.length} marked · ${agrees} agree · ${disagrees} disagree`));
    const ul = el("ul");
    for (const b of state.batch) ul.appendChild(el("li", "", `${SHORT[b.phase] || b.pred} — ${b.session} — ${b.intent.slice(0, 50)}`));
    s.appendChild(ul);
    const more = el("button", "ok", "Load more");
    more.style.marginTop = "10px";
    more.onclick = loadSamples;
    s.appendChild(more);
    q.appendChild(s);
    return;
  }
  const s = state.samples[state.idx];
  const card = el("div", "card");
  const head = el("div", "head");
  const tag = el("span", "tag", s.session);
  tag.style.cursor = "pointer";
  tag.title = "open session";
  tag.onclick = () => openSessionFromLabel(s);
  head.appendChild(tag);
  head.appendChild(el("span", "tag", `#${state.idx + 1}/${state.samples.length}`));
  const phaseTxt = `${SHORT[s.pred_phase]} (${s.confidence})`;
  head.appendChild(el("span", "phase", `pred ${phaseTxt}`));
  if (s.truth_phase) head.appendChild(el("span", "tag", `analyst: ${SHORT[s.truth_phase]}`));
  if (s.delegation) head.appendChild(el("span", "tag", "delegation"));
  card.appendChild(head);
  card.appendChild(el("div", "intent", s.intent || "(no intent)"));
  if (s.args) card.appendChild(el("div", "args", s.args));
  if (s.truth_phase && s.truth_phase !== s.pred_phase) {
    card.appendChild(el("div", "conflict", `Model says ${SHORT[s.pred_phase]} (${s.confidence}) — I said ${SHORT[s.truth_phase]}. Which is right?`));
  }
  if (s.label) {
    card.appendChild(el("div", "bar", `already marked: ${s.label.agree ? "agree" : "disagree"}${s.label.phase ? " → " + SHORT[s.label.phase] : ""}`));
  }

  const ctx = el("div", "ctx");
  ctx.appendChild(el("button", "more", "show context"));
  ctx._offset = 0;
  ctx._loaded = false;
  ctx._btn = ctx.firstChild;
  ctx._btn.onclick = async () => {
    if (!ctx._loaded) ctx._offset = 0;
    const body = await api(`/api/samples/${s.call_id}/context?offset=${ctx._offset}`);
    ctx.textContent = "";
    for (const ev of body.events) {
      ctx.appendChild(el("div", ev.this_sample ? "here" : "", `${SHORT[ev.phase]} ${ev.confidence.toFixed(2)} ${ev.tool} — ${(ev.intent || "").slice(0, 60)}`));
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
  const comment = el("input", "comment");
  comment.placeholder = "comment (optional)";
  const ok = el("button", "ok", "✓ Agree");
  const bad = el("button", "bad", "✗ Disagree");
  const submit = async (agree, phase) => {
    await adjudicate(s.call_id, s.pred_phase, agree, phase, comment.value, () => {
      state.batch.push({ verdict: agree ? "agree" : "disagree", phase, pred: s.pred_phase, session: s.session, intent: s.intent });
      state.idx += 1;
      state.picked = null;
      renderLabel();
    });
  };
  ok.onclick = () => submit(true, null);
  bad.onclick = () => submit(false, state.picked);
  actions.appendChild(ok);
  actions.appendChild(bad);
  card.appendChild(actions);
  const pick = phasePills(card, null);
  pick.className = "phasepick pickbtn";
  card.appendChild(comment);
  q.appendChild(card);
}

// ---------- sessions pane ----------

async function loadSessions() {
  state.sessionsList = await api("/api/sessions");
  renderSessions();
}

function renderSessions() {
  const wrap = document.getElementById("sessions");
  wrap.textContent = "";
  const byRepo = {};
  for (const s of state.sessionsList) (byRepo[s.repo] = byRepo[s.repo] || []).push(s);
  for (const [repo, sessions] of Object.entries(byRepo)) {
    wrap.appendChild(el("div", "bar", repo));
    for (const s of sessions) {
      const row = el("div", "session");
      const title = el("div", "s-title", `${s.title || "(untitled)"}`);
      row.appendChild(title);
      row.appendChild(el("div", "s-meta", `${s.started_at.slice(0, 16)} · ${Object.entries(s.tools).map(([t, c]) => `${t}×${c}`).join(" ")}`));
      row.appendChild(el("div", "s-meta", s.opening || ""));
      const pick = el("button", "pickbtn", state.selected.includes(s.id) ? "✓ selected" : "select for grouping");
      pick.onclick = (ev) => {
        ev.stopPropagation();
        const i = state.selected.indexOf(s.id);
        if (i >= 0) state.selected.splice(i, 1); else state.selected.push(s.id);
        renderSessions();
        document.getElementById("associate").disabled = state.selected.length !== 2;
      };
      row.appendChild(pick);
      row.onclick = () => showSession(s.id);
      wrap.appendChild(row);
    }
  }
  refreshAssociations();
}

async function refreshAssociations() {
  const list = await api("/api/associations");
  const byId = Object.fromEntries(state.sessionsList.map((s) => [s.id, s]));
  const wrap = document.getElementById("assoc-list");
  wrap.textContent = "";
  wrap.appendChild(el("div", "bar", `associations: ${list.length}`));
  const ul = el("ul");
  for (const a of list) {
    const name = (id) => (byId[id] ? byId[id].title || (byId[id].opening || "").slice(0, 30) : id.slice(0, 30));
    ul.appendChild(el("li", "", `${name(a.a)} ↔ ${name(a.b)}`));
  }
  wrap.appendChild(ul);
}

async function showSession(id) {
  state.sessionIdx = state.sessionsList.findIndex((s) => s.id === id);
  const detail = await api(`/api/sessions/${id}`);
  state.session = detail;
  const wrap = document.getElementById("sessions");
  wrap.textContent = "";
  const meta = state.sessionsList[state.sessionIdx] || {};
  const head = el("div", "shead");
  const back = el("button", "", "← Sessions");
  back.onclick = () => { state.session = null; renderSessions(); };
  head.appendChild(back);
  const prev = el("button", "", "← prev");
  prev.onclick = () => { if (state.sessionIdx > 0) showSession(state.sessionsList[state.sessionIdx - 1].id); };
  head.appendChild(prev);
  const next = el("button", "", "next →");
  next.onclick = () => { if (state.sessionIdx < state.sessionsList.length - 1) showSession(state.sessionsList[state.sessionIdx + 1].id); };
  head.appendChild(next);
  wrap.appendChild(head);
  wrap.appendChild(el("div", "s-title", meta.title || "(untitled)"));
  wrap.appendChild(el("div", "s-meta", `${meta.repo || ""} · ${(meta.opening || "").slice(0, 120)}`));
  wrap.appendChild(el("div", "hint", `${detail.event_count} tool calls — tap a phase then Disagree to correct; session opens in full`));
  for (const ev of detail.events) {
    const row = el("div", "event");
    const ehead = el("div", "e-head");
    ehead.appendChild(el("span", "phase", `pred ${SHORT[ev.pred_phase]} (${ev.confidence})`));
    if (ev.analyst_phase) ehead.appendChild(el("span", "tag", `analyst: ${SHORT[ev.analyst_phase]}`));
    if (ev.delegation) ehead.appendChild(el("span", "tag", "delegation"));
    row.appendChild(ehead);
    row.appendChild(el("div", "intent", ev.intent || "(no intent)"));
    if (ev.args) row.appendChild(el("div", "args", ev.args.slice(0, 160)));
    if (ev.label) row.appendChild(el("div", "bar", `marked: ${ev.label.agree ? "agree" : "disagree"}${ev.label.phase ? " → " + SHORT[ev.label.phase] : ""}`));
    const actions = el("div", "e-actions");
    const comment = el("input", "comment");
    comment.placeholder = "comment (optional)";
    const ok = el("button", "ok", "✓ Agree");
    const bad = el("button", "bad", "✗ Disagree");
    const submit = async (agree, phase) => {
      await adjudicate(ev.call_id, ev.pred_phase, agree, phase, comment.value, () => {
        showSession(id);
      });
    };
    ok.onclick = () => submit(true, null);
    bad.onclick = () => submit(false, state.picked);
    actions.appendChild(ok);
    actions.appendChild(bad);
    row.appendChild(actions);
    phasePills(row, null).className = "phasepick pickbtn";
    row.appendChild(comment);
    wrap.appendChild(row);
  }
}

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
  if (state.session) {
    showSession(state.session.id);
  } else if (state.sessionsList.length === 0) {
    loadSessions();
  } else {
    renderSessions();
  }
};
document.getElementById("associate").onclick = async () => {
  await api("/api/associations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a: state.selected[0], b: state.selected[1] }),
  });
  state.selected = [];
  renderSessions();
};
document.getElementById("load").onclick = loadSamples;

refreshSets();
loadSamples();
