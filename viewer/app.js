/* AI Diplomacy replay viewer.  MIT — see viewer/LICENSE.
 *
 * Reads turn-log JSON (schemas/turn_log.schema.json) and nothing else. It imports
 * no engine code, which is what keeps it on the permissive side of the licence
 * boundary described in ../NOTICE.
 *
 * No build step and no framework: a single static page that GitHub Pages serves as-is.
 */

import { POWERS, POWER_COLORS, PROVINCES, SUPPLY_CENTERS, baseProvince, parseUnit }
  from "./board.js";

const $ = (sel) => document.querySelector(sel);
const state = { log: null, phaseIndex: 0, selectedPower: null, playing: null };

// ---------------------------------------------------------------- loading

async function loadLog(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} fetching ${url}`);
  return res.json();
}

function phases(log) {
  // Turns carry our layer; game.phases carries the board. Align on phase name.
  const byName = new Map((log.game?.phases || []).map((p) => [p.name, p]));
  return (log.turns || []).map((turn) => ({
    name: turn.phase,
    turn,
    state: byName.get(turn.phase)?.state || {},
    results: byName.get(turn.phase)?.results || {},
  }));
}

// ---------------------------------------------------------------- board

function renderBoard(phase) {
  const svg = $("#board");
  const units = phase.state.units || {};
  const centers = phase.state.centers || {};

  const ownerOf = {};
  for (const [power, list] of Object.entries(centers)) {
    for (const c of list) ownerOf[baseProvince(c)] = power;
  }

  const parts = [];

  // Provinces
  for (const [prov, [x, y, kind]] of Object.entries(PROVINCES)) {
    const owner = ownerOf[prov];
    const isSC = SUPPLY_CENTERS.has(prov);
    // Switzerland is impassable: no unit ever enters it, so it must not read as
    // neutral-but-available territory.
    const impassable = kind === "x";
    const fill = impassable ? "var(--edge)"
      : kind === "w" ? "var(--water)"
      : owner ? POWER_COLORS[owner] + "44" : "var(--land)";
    const stroke = owner ? POWER_COLORS[owner] : "var(--edge)";
    parts.push(`
      <g class="prov" data-prov="${prov}">
        <rect x="${x - 21}" y="${y - 12}" width="42" height="24" rx="5"
              fill="${fill}" stroke="${stroke}" stroke-width="${owner ? 1.6 : 0.8}"/>
        ${isSC ? `<circle cx="${x + 15}" cy="${y - 8}" r="3.2"
              fill="${owner ? POWER_COLORS[owner] : "var(--edge)"}"/>` : ""}
        <text x="${x}" y="${y + 4}" class="prov-label"
              ${impassable ? 'opacity="0.45"' : ""}>${prov}</text>
      </g>`);
  }

  // Units
  for (const [power, list] of Object.entries(units)) {
    for (const u of list) {
      const { type, province } = parseUnit(u);
      const pos = PROVINCES[province];
      if (!pos) continue;
      const [x, y] = pos;
      const color = POWER_COLORS[power] || POWER_COLORS.NONE;
      parts.push(
        type === "F"
          ? `<polygon points="${x - 7},${y + 20} ${x + 7},${y + 20} ${x},${y + 12}"
                     fill="${color}" stroke="#0006"><title>${power} ${u}</title></polygon>`
          : `<rect x="${x - 6}" y="${y + 13}" width="12" height="8" rx="1.5"
                   fill="${color}" stroke="#0006"><title>${power} ${u}</title></rect>`
      );
    }
  }

  svg.innerHTML = parts.join("");
}

// ---------------------------------------------------------------- trust network

function renderTrust(phase) {
  const svg = $("#trust");
  const beliefs = phase.turn.beliefs || [];
  const present = POWERS.filter((p) => beliefs.some((b) => b.observer === p || b.subject === p));
  const powers = present.length ? present : POWERS;

  const cx = 210, cy = 195, r = 140;
  const pos = {};
  powers.forEach((p, i) => {
    const a = (i / powers.length) * Math.PI * 2 - Math.PI / 2;
    pos[p] = [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });

  const edges = [];
  for (const b of beliefs) {
    const from = pos[b.observer], to = pos[b.subject];
    if (!from || !to) continue;
    // Trust is directional: A's view of B is not B's view of A. Bow the edge so
    // both directions are visible rather than overlapping into one line.
    const [x1, y1] = from, [x2, y2] = to;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const bow = 16;
    const qx = mx - (dy / len) * bow, qy = my + (dx / len) * bow;

    const t = Math.max(0, Math.min(1, b.trust ?? 0.5));
    // Red = expects betrayal, green = trusted. Diverging around 0.5.
    const hue = t * 120;
    const width = 0.8 + Math.abs(t - 0.5) * 7;
    const alpha = 0.25 + Math.abs(t - 0.5) * 1.4;
    edges.push(`<path d="M${x1},${y1} Q${qx},${qy} ${x2},${y2}"
        fill="none" stroke="hsl(${hue} 70% 45%)" stroke-width="${width}"
        opacity="${Math.min(alpha, 1)}" class="trust-edge"
        data-pair="${b.observer}->${b.subject}">
        <title>${b.observer} trusts ${b.subject}: ${t.toFixed(2)}</title></path>`);
  }

  const nodes = powers.map((p) => {
    const [x, y] = pos[p];
    const sel = state.selectedPower === p;
    return `<g class="tnode" data-power="${p}">
      <circle cx="${x}" cy="${y}" r="${sel ? 20 : 16}" fill="${POWER_COLORS[p]}"
              stroke="var(--fg)" stroke-width="${sel ? 2.5 : 1}"/>
      <text x="${x}" y="${y + 33}" class="tlabel">${p.slice(0, 3)}</text>
    </g>`;
  });

  svg.innerHTML = edges.join("") + nodes.join("");
  svg.querySelectorAll(".tnode").forEach((n) =>
    n.addEventListener("click", () => {
      state.selectedPower = state.selectedPower === n.dataset.power ? null : n.dataset.power;
      render();
    })
  );
}

// ---------------------------------------------------------------- transcript

function renderTranscript(phase, allPhases) {
  const msgs = phase.turn.messages || [];
  const sel = state.selectedPower;

  // Outcome of a promise is only known after adjudication, so look ahead for the
  // correction that cites this message. This is the whole point of the panel:
  // prediction first, verdict later.
  const outcomes = new Map();
  for (const p of allPhases) {
    for (const c of p.turn.corrections || []) {
      if (!outcomes.has(c.message_id)) outcomes.set(c.message_id, { ...c, phase: p.name });
    }
  }

  const shown = sel ? msgs.filter((m) => m.sender === sel || m.recipient === sel) : msgs;
  if (!shown.length) {
    $("#transcript").innerHTML =
      `<p class="empty">No messages this phase${sel ? ` involving ${sel}` : ""}.</p>`;
    return;
  }

  $("#transcript").innerHTML = shown.map((m) => {
    const ev = m.evaluation;
    const oc = outcomes.get(m.message_id);
    const score = ev ? ev.predicted_truthfulness : null;

    let verdict = `<span class="pill unknown">outcome pending</span>`;
    if (oc) {
      verdict = oc.kept
        ? `<span class="pill kept">kept</span>`
        : `<span class="pill broken">BROKEN</span>`;
    }

    // Did the evaluator see it coming? Only meaningful once the outcome is known.
    let call = "";
    if (oc && score !== null) {
      const predictedKeep = score >= 0.5;
      const right = predictedKeep === oc.kept;
      call = `<span class="pill ${right ? "right" : "wrong"}">
                evaluator ${right ? "called it" : "missed it"}</span>`;
    }

    const intents = (m.stated_intent || [])
      .map((i) => `<code>${i.commitment_type}: ${escapeHtml(i.text)}</code>`).join(" ");

    return `<article class="msg">
      <header>
        <span class="who"><b style="color:${POWER_COLORS[m.sender]}">${m.sender}</b>
          → <b style="color:${POWER_COLORS[m.recipient]}">${m.recipient}</b></span>
        ${score !== null
          ? `<span class="score" title="evaluator's predicted truthfulness">
               truth ${score.toFixed(2)}
               <span class="bar"><i style="width:${score * 100}%;
                 background:hsl(${score * 120} 70% 45%)"></i></span></span>`
          : ""}
      </header>
      <p class="body">${escapeHtml(m.body)}</p>
      ${intents ? `<p class="intents">${intents}</p>` : ""}
      <footer>${verdict} ${call}
        ${ev?.rationale ? `<span class="rationale">${escapeHtml(ev.rationale)}</span>` : ""}
      </footer>
    </article>`;
  }).join("");
}

// ---------------------------------------------------------------- inspector

function renderInspector(phase, allPhases) {
  const el = $("#inspector");
  const sel = state.selectedPower;
  if (!sel) {
    el.innerHTML = `<p class="empty">Select a power in the trust network to see what it
      believes about the others — and whether those beliefs turned out to be right.</p>`;
    return;
  }

  const mine = (phase.turn.beliefs || []).filter((b) => b.observer === sel);
  if (!mine.length) {
    el.innerHTML = `<p class="empty">No belief state recorded for ${sel} this phase.</p>`;
    return;
  }

  const idx = allPhases.indexOf(phase);
  const future = allPhases.slice(idx + 1);

  el.innerHTML = `<h3>${sel} believes…</h3>` + mine.map((b) => {
    // Ground truth: did the subject actually break a promise to this observer later?
    const laterBreaks = future.reduce((n, p) =>
      n + (p.turn.corrections || []).filter(
        (c) => c.observer === sel && c.subject === b.subject && !c.kept).length, 0);
    const laterKeeps = future.reduce((n, p) =>
      n + (p.turn.corrections || []).filter(
        (c) => c.observer === sel && c.subject === b.subject && c.kept).length, 0);

    const pb = b.predicted_betrayal?.probability ?? (1 - (b.trust ?? 0.5));
    const actualRate = (laterBreaks + laterKeeps)
      ? laterBreaks / (laterBreaks + laterKeeps) : null;

    let calib = `<span class="pill unknown">nothing further happened</span>`;
    if (actualRate !== null) {
      const err = Math.abs(pb - actualRate);
      const band = err < 0.2 ? "right" : err < 0.4 ? "unknown" : "wrong";
      calib = `<span class="pill ${band}">predicted ${pb.toFixed(2)} ·
                 actual ${actualRate.toFixed(2)}</span>`;
    }

    return `<div class="belief">
      <div class="belief-head">
        <b style="color:${POWER_COLORS[b.subject]}">${b.subject}</b>
        <span class="trustval">trust ${(b.trust ?? 0).toFixed(2)}</span>
      </div>
      <div class="bar wide"><i style="width:${(b.trust ?? 0) * 100}%;
        background:hsl(${(b.trust ?? 0) * 120} 70% 45%)"></i></div>
      <div class="belief-foot">${calib}
        <span class="muted">${laterKeeps} kept / ${laterBreaks} broken afterwards</span>
      </div>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------- chrome

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderMeta() {
  const run = state.log.run || {};
  const calls = state.log.llm_calls || [];
  const cost = calls.reduce((n, c) => n + (c.usage?.cost_usd || 0), 0);
  const models = Object.entries(run.config?.models || {})
    .map(([k, v]) => `${k}=${v}`).join(", ");
  $("#meta").innerHTML = `
    <span><b>arm</b> ${run.arm ?? "?"}</span>
    <span><b>seed</b> ${run.seed ?? "?"}</span>
    <span><b>calls</b> ${calls.length}</span>
    <span><b>cost</b> $${cost.toFixed(4)}</span>
    <span class="models">${escapeHtml(models)}</span>`;
}

function render() {
  const all = phases(state.log);
  const phase = all[state.phaseIndex];
  if (!phase) return;

  $("#phase-name").textContent = phase.name;
  $("#phase-pos").textContent = `${state.phaseIndex + 1} / ${all.length}`;
  $("#scrub").max = String(all.length - 1);
  $("#scrub").value = String(state.phaseIndex);
  $("#sel-power").textContent = state.selectedPower || "none";

  renderBoard(phase);
  renderTrust(phase);
  renderTranscript(phase, all);
  renderInspector(phase, all);
}

function step(delta) {
  const n = phases(state.log).length;
  state.phaseIndex = Math.max(0, Math.min(n - 1, state.phaseIndex + delta));
  render();
}

function togglePlay() {
  if (state.playing) {
    clearInterval(state.playing);
    state.playing = null;
    $("#play").textContent = "▶ Play";
    return;
  }
  $("#play").textContent = "❚❚ Pause";
  state.playing = setInterval(() => {
    const n = phases(state.log).length;
    if (state.phaseIndex >= n - 1) return togglePlay();
    step(1);
  }, 1100);
}

async function main() {
  const params = new URLSearchParams(location.search);
  const url = params.get("log") || "./data/sample-game.json";
  try {
    state.log = await loadLog(url);
  } catch (err) {
    $("#app").innerHTML =
      `<p class="error">Could not load <code>${escapeHtml(url)}</code>: ${escapeHtml(err.message)}
       <br><br>Serve this directory over HTTP (<code>python -m http.server</code>) —
       <code>file://</code> blocks fetch.</p>`;
    return;
  }
  renderMeta();
  render();

  $("#scrub").addEventListener("input", (e) => {
    state.phaseIndex = Number(e.target.value);
    render();
  });
  $("#prev").addEventListener("click", () => step(-1));
  $("#next").addEventListener("click", () => step(1));
  $("#play").addEventListener("click", togglePlay);
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });
}

main();
