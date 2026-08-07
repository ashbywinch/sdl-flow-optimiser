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
const VERSION = "v11-chat";

const state = {
  session: null, // {id, transcript, runs, tool_calls}
  rendered: 0,
  sessionsList: [],
  sessionIdx: -1,
  selected: [],
  associations: [],
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

function textBubble(kind, text) {
  // Chat bubbles: user right (accent), agent left (paper). Long messages
  // collapse to a chip; expanded, they are a bounded scrollable box with a
  // sticky collapse bar — the control stays in reach from anywhere inside.
  const b = el("div", `bubble ${kind}`);
  b.appendChild(el("div", "bubble-who", kind === "you" ? "You" : "Agent"));
  const body = el("div", "bubble-body");
  b.appendChild(body);
  const chip = () => {
    b.classList.remove("expanded");
    body.textContent = text.slice(0, 100);
    if (text.length > COLLAPSE_AT) {
      const meta = el("span", "expand", ` (${Math.round(text.length / 1000)}k chars — tap to expand)`);
      body.appendChild(meta);
    }
  };
  const full = () => {
    b.classList.add("expanded");
    body.textContent = "";
    const bar = el("div", "collapsebar");
    const btn = el("button", "", "✕ collapse");
    btn.onclick = (ev) => { ev.stopPropagation(); chip(); };
    bar.appendChild(btn);
    body.appendChild(bar);
    body.appendChild(document.createTextNode(text));
  };
  if (text.length <= COLLAPSE_AT) {
    body.textContent = text;
  } else {
    chip();
    b.onclick = () => (b.classList.contains("expanded") ? chip() : full());
  }
  return b;
}

// ---------- activity runs (the unit the user judges) ----------

function runBlock(run, sessionId, calls) {
  const box = el("div", "run");
  box.id = `run-${run.start}`;
  const head = el("div", "r-head");
  head.appendChild(el("span", "", `${run.call_count} tool calls · my guess: `));
  head.appendChild(el("b", "", `${PHASE_UI[run.phase]} (${run.confidence.toFixed(2)})`));
  box.appendChild(head);

  // your answer, defaulting to my guess (or your previous verdict)
  let pickPhase = run.verdict ? run.verdict.phase : run.phase;
  let comment = run.verdict ? run.verdict.comment : "";
  const pick = el("div", "r-pick");
  for (const [id, name] of Object.entries(PHASE_UI)) {
    const b = el("button", "", name);
    if (Number(id) === run.phase) b.classList.add("guess"); // dashed = my guess
    if (Number(id) === pickPhase) b.classList.add("sel");
    b.onclick = () => {
      pickPhase = Number(id);
      pick.querySelectorAll("button").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    };
    pick.appendChild(b);
  }
  box.appendChild(pick);

  const actions = el("div", "r-actions");
  const commentEl = el("input", "r-comment");
  commentEl.placeholder = "comment (optional)";
  commentEl.value = comment;
  const ok = el("button", "r-ok", run.verdict ? "Update" : "Confirm");
  const save = async () => {
    await api(`/api/runs/${encodeURIComponent(run.run_id)}/verdict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: pickPhase, comment: commentEl.value }),
    });
    toast(`Saved: this stretch was ${PHASE_UI[pickPhase]}`, async () => {
      await api(`/api/runs/${encodeURIComponent(run.run_id)}/verdict`, { method: "DELETE" });
      showSession(sessionId);
    });
    showSession(sessionId);
  };
  ok.onclick = save;
  actions.appendChild(ok);
  actions.appendChild(commentEl);
  box.appendChild(actions);

  if (run.verdict) {
    box.appendChild(el("div", "r-verdict", `you said: ${PHASE_UI[run.verdict.phase]} — tap Update to change`));
  }

  const callsBox = el("div", "r-calls");
  callsBox.hidden = true;
  const toggle = el("button", "more", "show calls");
  toggle.onclick = () => {
    if (callsBox.hidden) {
      callsBox.textContent = "";
      for (const c of calls) {
        if (c.kind !== "tool_call") continue;
        callsBox.appendChild(el("div", "", `${c.tool} — ${c.intent || ""}`));
      }
      callsBox.hidden = false;
      toggle.textContent = "hide calls";
    } else {
      callsBox.hidden = true;
      toggle.textContent = "show calls";
    }
  };
  box.appendChild(toggle);
  box.appendChild(callsBox);
  return box;
}

// ---------- sessions pane ----------

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
  const left = state.session.transcript.length - state.rendered;
  document.getElementById("sess-more").textContent = left > 0 ? `Show more (${left} left)` : "All shown";
  document.getElementById("sess-more").disabled = left <= 0;
  document.getElementById("sess-end").textContent = "Jump to end";
}

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

// ---------- session as a chat ----------

function renderTranscript(wrap) {
  const detail = state.session;
  [...wrap.querySelectorAll(".bubble,.run")].forEach((n) => n.remove());
  const t = detail.transcript;
  const runs = detail.runs;
  let runIdx = 0;
  const end = Math.min(state.rendered, t.length);
  for (let i = 0; i < end; i++) {
    const it = t[i];
    if (it.kind === "user") {
      wrap.appendChild(textBubble("you", it.text));
    } else if (it.kind === "assistant") {
      wrap.appendChild(textBubble("agent", it.text));
    } else if (it.kind === "tool_call") {
      while (runIdx < runs.length && runs[runIdx].start < i) runIdx++;
      const run = runs[runIdx];
      if (run && run.start === i) {
        wrap.appendChild(runBlock(run, detail.id, t.slice(run.start, run.end + 1)));
        i = run.end;
      }
    }
  }
  updateSessionBar();
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
    const counts = {};
    for (const r of detail.runs) counts[r.phase] = (counts[r.phase] || 0) + 1;
    const chips = el("div", "chips");
    for (const [ph, c] of Object.entries(counts)) {
      const chip = el("button", "", `${PHASE_UI[Number(ph)]} ${c}`);
      chip.onclick = () => {
        const run = detail.runs.find((r) => r.phase === Number(ph));
        if (run) {
          if (run.end >= state.rendered) {
            state.rendered = run.end + 1;
            renderTranscript(wrap);
          }
          const node = document.getElementById(`run-${run.start}`);
          if (node) node.scrollIntoView({ behavior: "smooth" });
        }
      };
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
    wrap.classList.add("chat");
    renderTranscript(wrap);
  });
}

// ---------- boot ----------

document.getElementById("tab-sessions").onclick = () => {
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

loadSessions();
document.getElementById("ver").textContent = VERSION;
