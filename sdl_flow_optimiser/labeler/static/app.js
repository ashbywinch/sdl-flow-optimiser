"use strict";

// The user's own phase names — never abbreviations, never internal names.
const PHASE_UI = {
  1: "PRD",
  2: "Tech design",
  3: "Flow design",
  4: "Tickets",
  5: "Plan",
  6: "Execute",
  7: "PR + review",
  8: "UX loop",
};

const CHUNK = 100;
const COLLAPSE_AT = 300;
const VERSION = "v10-no-popups";

const state = {
  samples: [],
  idx: 0,
  picked: null,
  batch: [],
  session: null, // {id, transcript, tool_calls}
  rendered: 0, // how many transcript items are on screen
  sessionsList: [],
  sessionIdx: -1,
  selected: [],
  associations: [],
  mode: "conversation", // conversation | all — the transcript is the conversation by default
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

function phasePills(container) {
  const pick = el("div", "phasepick");
  for (const [id, name] of Object.entries(PHASE_UI)) {
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
  t._timer = setTimeout(() => { t.style.display = "none"; }, 6000);
}

async function adjudicate(callId, predPhase, agree, phase, comment, after, undoAfter) {
  await api("/api/labels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, agree, phase, comment }),
  });
  const verdict = agree ? `Saved: agree — ${PHASE_UI[predPhase]}` : `Saved: disagree — ${PHASE_UI[predPhase]}${phase ? " → " + PHASE_UI[phase] : " (no correction)"}`;
  toast(verdict, async () => {
    await api(`/api/labels/${callId}`, { method: "DELETE" });
    undoAfter && undoAfter();
    refreshSets();
  });
  after && after();
  refreshSets();
}

function textBubble(kind, text) {
  // Long messages collapse to a chip. Expanded, the message becomes a
  // bounded scrollable box with a sticky collapse bar pinned to its top —
  // the control stays visible from anywhere inside the content, so the user
  // never has to scroll to find it again (standard expandable-text pattern).
  const who = kind === "you" ? "You:" : "Agent:";
  const b = el("div", `bubble ${kind}`);
  if (text.length <= COLLAPSE_AT) {
    b.textContent = `${who} ${text}`;
    return b;
  }
  b.setAttribute("role", "button");
  const chip = () => {
    b.classList.remove("expanded");
    b.setAttribute("aria-expanded", "false");
    b.textContent = `${who} ${text.slice(0, 100)}…`;
    const meta = el("span", "expand", ` (${Math.round(text.length / 1000)}k chars — tap to expand)`);
    b.appendChild(meta);
  };
  const full = () => {
    b.classList.add("expanded");
    b.setAttribute("aria-expanded", "true");
    b.textContent = "";
    const bar = el("div", "collapsebar");
    const btn = el("button", "", "✕ collapse");
    btn.onclick = (ev) => {
      ev.stopPropagation();
      chip();
    };
    bar.appendChild(btn);
    b.appendChild(bar);
    b.appendChild(document.createTextNode(`${who} ${text}`));
  };
  chip();
  b.onclick = () => {
    if (b.classList.contains("expanded")) {
      chip();
    } else {
      full();
    }
  };
  return b;
}

// ---------- label pane (samples) ----------

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
  activateTab("sessions");
  showSession(sample.session_id);
}

function contextList(ctx, s) {
  ctx.textContent = "";
  ctx.appendChild(el("button", "more", "show context"));
  ctx._offset = 0;
  ctx._loaded = false;
  const btn = ctx.firstChild;
  btn.onclick = async () => {
    if (!ctx._loaded) ctx._offset = 0;
    const body = await api(`/api/samples/${s.call_id}/context?offset=${ctx._offset}`);
    ctx.textContent = "";
    let prev = null, run = 0;
    for (const ev of body.events) {
      const key = `${ev.phase}|${ev.tool}|${ev.intent}`;
      if (ev.this_sample) {
        if (run > 1) ctx.appendChild(el("div", "here", `  … ×${run} identical`));
        run = 0; prev = null;
        ctx.appendChild(el("div", "here", `* ${PHASE_UI[ev.phase]} ${ev.confidence.toFixed(2)} ${ev.tool} — ${(ev.intent || "").slice(0, 50)}`));
      } else if (key === prev) {
        run += 1;
      } else {
        if (run > 1) ctx.appendChild(el("div", "", `  … ×${run} identical`));
        run = 0; prev = key;
        ctx.appendChild(el("div", "", `  ${PHASE_UI[ev.phase]} ${ev.confidence.toFixed(2)} ${ev.tool} — ${(ev.intent || "").slice(0, 50)}`));
      }
    }
    if (run > 1) ctx.appendChild(el("div", "", `  … ×${run} identical`));
    ctx._loaded = true;
    if (body.more_after) {
      const more = el("button", "more", "more ↓");
      more.onclick = () => { ctx._offset += 10; btn.onclick(); };
      ctx.appendChild(more);
    }
  };
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
    for (const b of state.batch) ul.appendChild(el("li", "", `${b.phase ? PHASE_UI[b.phase] : PHASE_UI[b.pred]} — ${b.session} — ${b.intent.slice(0, 50)}`));
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
  const phaseTxt = `${PHASE_UI[s.pred_phase]} (${s.confidence})`;
  head.appendChild(el("span", "phase", `pred ${phaseTxt}`));
  if (s.truth_phase) head.appendChild(el("span", "tag", `analyst: ${PHASE_UI[s.truth_phase]}`));
  if (s.delegation) head.appendChild(el("span", "tag", "delegation"));
  card.appendChild(head);
  card.appendChild(el("div", "intent", s.intent || s.tool));
  if (s.truth_phase && s.truth_phase !== s.pred_phase) {
    card.appendChild(el("div", "conflict", `Model says ${PHASE_UI[s.pred_phase]} (${s.confidence}) — I said ${PHASE_UI[s.truth_phase]}. Which is right?`));
  }
  if (s.label) {
    card.appendChild(el("div", "bar", `already marked: ${s.label.agree ? "agree" : "disagree"}${s.label.phase ? " → " + PHASE_UI[s.label.phase] : ""}`));
  }
  const ctx = el("div", "ctx");
  contextList(ctx, s);
  card.appendChild(ctx);
  const openBtn = el("button", "bad", "Open session →");
  openBtn.style.marginTop = "8px";
  openBtn.onclick = () => openSessionFromLabel(s);
  card.appendChild(openBtn);
  const actions = el("div", "actions");
  const comment = el("input", "comment");
  comment.placeholder = "comment (optional)";
  const ok = el("button", "ok", "✓ Agree");
  const bad = el("button", "bad", "✗ Disagree");
  const submit = async (agree, phase) => {
    await adjudicate(
      s.call_id,
      s.pred_phase,
      agree,
      phase,
      comment.value,
      () => {
        state.batch.push({ verdict: agree ? "agree" : "disagree", phase, pred: s.pred_phase, session: s.session, intent: s.intent });
        state.idx += 1;
        state.picked = null;
        renderLabel();
      },
      () => {
        // undo: return to the sample that was just marked, don't advance again
        state.idx = Math.max(0, state.idx - 1);
        state.picked = null;
        renderLabel();
      }
    );
  };
  ok.onclick = () => submit(true, null);
  bad.onclick = () => submit(false, state.picked);
  actions.appendChild(ok);
  actions.appendChild(bad);
  card.appendChild(actions);
  phasePills(card).className = "phasepick pickbtn";
  card.appendChild(comment);
  q.appendChild(card);
}

// ---------- sessions pane ----------

async function loadSessions() {
  state.sessionsList = await api("/api/sessions");
  renderSessions();
}

function updateSelectBar() {
  const bar = document.getElementById("selectbar");
  if (state.selected.length === 0) {
    bar.style.display = "none";
    return;
  }
  bar.style.display = "flex";
  document.getElementById("selectcount").textContent = `${state.selected.length} selected · ${state.associations.length} grouped`;
  document.getElementById("associate").disabled = state.selected.length !== 2;
}

function renderSessions() {
  const wrap = document.getElementById("sessions");
  wrap.textContent = "";
  const groupedIds = new Set(state.associations.flatMap((a) => [a.a, a.b]));
  const byRepo = {};
  for (const s of state.sessionsList) (byRepo[s.repo_name] = byRepo[s.repo_name] || []).push(s);
  for (const [repo, sessions] of Object.entries(byRepo)) {
    wrap.appendChild(el("div", "bar", repo));
    for (const s of sessions) {
      const row = el("div", "session");
      if (state.selected.includes(s.id)) row.classList.add("selected");
      if (groupedIds.has(s.id)) row.appendChild(el("span", "tag", "grouped"));
      if (s.agent_run) row.appendChild(el("span", "tag", "agent run — no conversation"));
      const title = el("div", "s-title", `${s.title || "(untitled)"}`);
      row.appendChild(title);
      row.appendChild(el("div", "s-meta", `${fmtRange(s.started_at, s.ended_at)} · ${s.user_messages} messages · ${Object.entries(s.tools).map(([t, c]) => `${t}×${c}`).join(" ")}`));
      row.appendChild(el("div", "s-meta", s.opening || ""));
      const rowbtns = el("div", "e-actions");
      const open = el("button", "ok", "Open session →");
      open.onclick = (ev) => {
        ev.stopPropagation();
        showSession(s.id);
      };
      rowbtns.appendChild(open);
      const pick = el("button", "pickbtn", "select for grouping");
      pick.onclick = (ev) => {
        ev.stopPropagation();
        const i = state.selected.indexOf(s.id);
        if (i >= 0) state.selected.splice(i, 1); else state.selected.push(s.id);
        renderSessions();
        updateSelectBar();
      };
      rowbtns.appendChild(pick);
      row.appendChild(rowbtns);
      row.onclick = () => showSession(s.id);
      wrap.appendChild(row);
    }
  }
  updateSelectBar();
  refreshAssociations();
}

async function refreshAssociations() {
  state.associations = await api("/api/associations");
  const byId = Object.fromEntries(state.sessionsList.map((s) => [s.id, s]));
  const wrap = document.getElementById("assoc-list");
  wrap.textContent = "";
  wrap.appendChild(el("div", "bar", `associations: ${state.associations.length}`));
  const ul = el("ul");
  for (const a of state.associations) {
    const name = (id) => (byId[id] ? byId[id].title || (byId[id].opening || "").slice(0, 30) : id.slice(0, 30));
    const li = el("li", "", `${name(a.a)} ↔ ${name(a.b)}`);
    const rm = el("button", "bad", "✕");
    rm.style.marginLeft = "10px";
    rm.onclick = async () => {
      await api(`/api/associations?`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ a: a.a, b: a.b }),
      });
      toast("Removed association");
      renderSessions();
    };
    li.appendChild(rm);
    ul.appendChild(li);
  }
  wrap.appendChild(ul);
}

// ---------- session transcript (chunked) ----------

function fmtRange(startIso, endIso) {
  if (!startIso) return "";
  const s = new Date(startIso);
  const e = endIso ? new Date(endIso) : s;
  const time = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = (d) => d.toLocaleDateString([], { day: "numeric", month: "short" });
  if (s.toDateString() === e.toDateString()) return `${date(s)} ${time(s)}–${time(e)}`;
  return `${date(s)} ${time(s)} – ${date(e)} ${time(e)}`;
}

function updateSessionBar() {
  const bar = document.getElementById("sessbar");
  if (!state.session) {
    bar.style.display = "none";
    return;
  }
  bar.style.display = "flex";
  const visible = visibleItems(state.session.transcript);
  const shown = visible.filter((it) => state.session.transcript.indexOf(it) < state.rendered).length;
  const left = visible.length - shown;
  document.getElementById("sess-more").textContent = left > 0 ? `Show more (${left} left)` : "All shown";
  document.getElementById("sess-more").disabled = left <= 0;
  document.getElementById("sess-end").textContent = "Jump to end";
}

function showSession(id) {
  state.sessionIdx = state.sessionsList.findIndex((s) => s.id === id);
  const wrap = document.getElementById("sessions");
  wrap.textContent = "";
  wrap.appendChild(el("div", "bar", "loading session…"));
  api(`/api/sessions/${id}`).then((detail) => {
    state.session = detail;
    state.rendered = CHUNK;
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
    wrap.appendChild(el("div", "s-title", `Session · ${meta.title || "(untitled)"}`));
    wrap.appendChild(el("div", "s-meta", `${meta.repo_name || ""} · ${fmtRange(meta.started_at, meta.ended_at)} · ${detail.tool_calls} tool calls`));
    const mode = el("div", "chips");
    const conv = el("button", state.mode === "conversation" ? "sel" : "", "Conversation");
    const all = el("button", state.mode === "all" ? "sel" : "", "All");
    conv.onclick = () => { state.mode = "conversation"; showSession(id); };
    all.onclick = () => { state.mode = "all"; showSession(id); };
    mode.appendChild(conv);
    mode.appendChild(all);
    wrap.appendChild(mode);
    const counts = {};
    for (const it of detail.transcript) {
      if (it.kind === "tool_call") counts[it.pred_phase] = (counts[it.pred_phase] || 0) + 1;
    }
    const chips = el("div", "chips");
    for (const [ph, c] of Object.entries(counts)) {
      const chip = el("button", "", `${PHASE_UI[Number(ph)]} ${c}`);
      chip.onclick = () => {
        const first = detail.transcript.findIndex((it) => it.kind === "tool_call" && it.pred_phase === Number(ph));
        if (first >= 0 && first >= state.rendered) {
          state.rendered = first + 1;
          renderTranscript(wrap);
        }
        const node = document.getElementById(`tc-${first}`);
        if (node) node.scrollIntoView({ behavior: "smooth" });
      };
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
    renderTranscript(wrap);
  });
}

function visibleItems(t) {
  return t.filter((it) => state.mode === "all" || (it.kind !== "tool_call" && it.kind !== "tool_result"));
}

function renderTranscript(wrap) {
  const detail = state.session;
  // remove previously rendered items except header/chips
  [...wrap.querySelectorAll(".bubble,.event")].forEach((n) => n.remove());
  const t = detail.transcript;
  const end = Math.min(state.rendered, t.length);
  for (let i = 0; i < end; i++) {
    const it = t[i];
    if (it.kind === "user") {
      wrap.appendChild(textBubble("you", it.text));
    } else if (it.kind === "assistant") {
      wrap.appendChild(textBubble("agent", it.text));
    } else if (it.kind === "tool_call" && state.mode === "all") {
      const row = el("div", "event compact");
      row.id = `tc-${i}`;
      const line = el("div", "tline");
      line.appendChild(el("span", "tag", it.tool));
      line.appendChild(el("span", "tintent", it.intent || it.tool));
      line.appendChild(el("span", "tphase", `${PHASE_UI[it.pred_phase]} ${it.confidence}`));
      if (it.analyst_phase) line.appendChild(el("span", "tanalyst", `me: ${PHASE_UI[it.analyst_phase]}`));
      if (it.delegation) line.appendChild(el("span", "tag", "delegation"));
      if (it.label) line.appendChild(el("span", "tmarked", it.label.agree ? "✓ marked" : `✗ ${it.label.phase ? PHASE_UI[it.label.phase] : "marked"}`));
      row.appendChild(line);
      const adj = el("div", "adjudicate");
      const actions = el("div", "e-actions");
      const comment = el("input", "comment");
      comment.placeholder = "comment (optional)";
      const ok = el("button", "ok", "✓ Agree");
      const bad = el("button", "bad", "✗ Disagree");
      const submit = async (agree, phase) => {
        await adjudicate(
          it.call_id,
          it.pred_phase,
          agree,
          phase,
          comment.value,
          () => showSession(detail.id),
          () => showSession(detail.id)
        );
      };
      ok.onclick = () => submit(true, null);
      bad.onclick = () => submit(false, state.picked);
      actions.appendChild(ok);
      actions.appendChild(bad);
      adj.appendChild(actions);
      phasePills(adj).className = "phasepick pickbtn";
      adj.appendChild(comment);
      adj.onclick = (e) => e.stopPropagation();
      row.appendChild(adj);
      row.onclick = () => row.classList.toggle("open");
      wrap.appendChild(row);
    }
  }
  updateSessionBar();
}

// ---------- boot ----------

function activateTab(name) {
  const labelTab = document.getElementById("tab-label");
  const sessTab = document.getElementById("tab-sessions");
  if (name === "sessions") {
    sessTab.classList.add("active");
    labelTab.classList.remove("active");
    document.getElementById("pane-sessions").hidden = false;
    document.getElementById("pane-label").hidden = true;
  } else {
    labelTab.classList.add("active");
    sessTab.classList.remove("active");
    document.getElementById("pane-label").hidden = false;
    document.getElementById("pane-sessions").hidden = true;
  }
}

document.getElementById("tab-label").onclick = () => activateTab("label");
document.getElementById("tab-sessions").onclick = () => {
  activateTab("sessions");
  if (state.session) {
    showSession(state.session.id);
  } else if (state.sessionsList.length === 0) {
    loadSessions();
  } else {
    renderSessions();
  }
};
document.getElementById("associate").onclick = async () => {
  const [a, b] = state.selected;
  await api("/api/associations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a, b }),
  });
  state.selected = [];
  toast("Associated", async () => {
    await api(`/api/associations?`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a, b }),
    });
    renderSessions();
  });
  renderSessions();
};
document.getElementById("associate-cancel").onclick = () => {
  state.selected = [];
  renderSessions();
};
document.getElementById("sess-top").onclick = () => {
  document.getElementById("sessions").scrollIntoView();
  window.scrollTo({ top: 0, behavior: "smooth" });
};
document.getElementById("sess-more").onclick = () => {
  state.rendered += CHUNK;
  renderTranscript(document.getElementById("sessions"));
};
document.getElementById("sess-end").onclick = () => {
  const wrap = document.getElementById("sessions");
  state.rendered = state.session.transcript.length;
  renderTranscript(wrap);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
};
document.getElementById("load").onclick = loadSamples;
document.getElementById("kind").onchange = () => setTimeout(loadSamples, 150);
document.getElementById("count").onchange = () => setTimeout(loadSamples, 150);

refreshSets();
loadSessions();
activateTab("sessions");
document.getElementById("ver").textContent = VERSION;
