/* Viewer data-contract test.  MIT — see viewer/LICENSE.
 *
 * Runs in node with no browser. It checks the things that would silently produce a
 * wrong-looking page rather than an error: a province with no coordinates drops a
 * unit off the board invisibly, and a phase-alignment slip shows one phase's beliefs
 * against another's position.
 *
 *   node viewer/test-viewer.mjs [path-to-log.json]
 */

import { readFileSync } from "node:fs";
import { PROVINCES, SUPPLY_CENTERS, POWERS, POWER_COLORS, baseProvince, parseUnit }
  from "./board.js";

const logPath = process.argv[2] || "viewer/data/sample-game.json";
const log = JSON.parse(readFileSync(logPath, "utf8"));
const failures = [];

// --- 1. every province referenced by the log has coordinates ---------------
const referenced = new Set();
for (const phase of log.game.phases || []) {
  for (const list of Object.values(phase.state?.units || {})) {
    for (const u of list) referenced.add(parseUnit(u).province);
  }
  for (const list of Object.values(phase.state?.centers || {})) {
    for (const c of list) referenced.add(baseProvince(c));
  }
}
const missing = [...referenced].filter((p) => !PROVINCES[p]).sort();
console.log(`[1] ${referenced.size} provinces referenced across ${log.game.phases.length} phases`);
if (missing.length) {
  console.log(`    MISSING COORDINATES: ${missing.join(", ")}`);
  failures.push(`${missing.length} provinces would render invisibly: ${missing.join(", ")}`);
} else {
  console.log(`    all have coordinates — no unit can drop off the board`);
}

// --- 1b. diff the WHOLE list against the engine's canonical reference ------
// Checking only what one game touched misses provinces that game never visited --
// which is how a Norwegian Sea typo and a wrong supply centre both survived.
try {
  const ref = JSON.parse(readFileSync("viewer/data/provinces.json", "utf8"));
  const mine = new Set(Object.keys(PROVINCES));
  const absent = ref.provinces.filter((p) => !mine.has(p));
  const bogus = [...mine].filter((p) => !ref.provinces.includes(p));
  const scAbsent = ref.supply_centers.filter((p) => !SUPPLY_CENTERS.has(p));
  const scBogus = [...SUPPLY_CENTERS].filter((p) => !ref.supply_centers.includes(p));
  console.log(`[1b] canonical: ${ref.provinces.length} provinces, `
    + `${ref.supply_centers.length} supply centres`);
  if (absent.length) failures.push(`provinces absent from viewer: ${absent.join(", ")}`);
  if (bogus.length) failures.push(`viewer province names not in engine: ${bogus.join(", ")}`);
  if (scAbsent.length) failures.push(`supply centres not marked: ${scAbsent.join(", ")}`);
  if (scBogus.length) failures.push(`wrongly marked as supply centres: ${scBogus.join(", ")}`);
  if (!absent.length && !bogus.length && !scAbsent.length && !scBogus.length) {
    console.log(`     viewer matches the engine exactly`);
  }
} catch {
  console.log("[1b] no viewer/data/provinces.json — skipping canonical diff");
}

// --- 2. supply-centre set matches what the engine actually owns ------------
const engineCenters = new Set();
for (const phase of log.game.phases || []) {
  for (const list of Object.values(phase.state?.centers || {})) {
    for (const c of list) engineCenters.add(baseProvince(c));
  }
}
const notMarked = [...engineCenters].filter((c) => !SUPPLY_CENTERS.has(c)).sort();
console.log(`[2] engine owned ${engineCenters.size} distinct centres`);
if (notMarked.length) {
  console.log(`    NOT MARKED as supply centres: ${notMarked.join(", ")}`);
  failures.push(`supply-centre set wrong: ${notMarked.join(", ")}`);
} else {
  console.log(`    all are marked as supply centres in the viewer`);
}

// --- 3. phase alignment ----------------------------------------------------
const byName = new Map((log.game.phases || []).map((p) => [p.name, p]));
const unaligned = (log.turns || []).filter((t) => !byName.has(t.phase));
console.log(`[3] ${log.turns.length} turns, ${byName.size} game phases`);
if (unaligned.length) {
  failures.push(`${unaligned.length} turns have no matching game phase`);
} else {
  console.log(`    every turn aligns to a phase — panels cannot show mismatched state`);
}
const hashMismatch = (log.turns || []).filter(
  (t) => t.board_hash !== (byName.get(t.phase)?.state?.zobrist_hash ?? t.board_hash));
if (hashMismatch.length) failures.push(`${hashMismatch.length} turns have a stale board_hash`);

// --- 4. outcome lookahead resolves -----------------------------------------
const outcomes = new Map();
for (const t of log.turns || []) {
  for (const c of t.corrections || []) if (!outcomes.has(c.message_id)) outcomes.set(c.message_id, c);
}
const allMsgs = (log.turns || []).flatMap((t) => t.messages || []);
const resolved = allMsgs.filter((m) => outcomes.has(m.message_id));
const evaluated = allMsgs.filter((m) => m.evaluation);
console.log(`[4] ${allMsgs.length} messages, ${evaluated.length} evaluated, `
  + `${resolved.length} with a known outcome`);
if (!allMsgs.length) failures.push("no messages — transcript panel would be empty");
if (!resolved.length) failures.push("no message resolves to an outcome — verdicts never show");

// --- 5. the evaluator-scorecard maths --------------------------------------
let right = 0, wrong = 0;
for (const m of allMsgs) {
  const oc = outcomes.get(m.message_id);
  if (!oc || !m.evaluation) continue;
  const predictedKeep = m.evaluation.predicted_truthfulness >= 0.5;
  predictedKeep === oc.kept ? right++ : wrong++;
}
const total = right + wrong;
console.log(`[5] evaluator scorecard: ${right} called / ${wrong} missed`
  + (total ? ` (${((right / total) * 100).toFixed(0)}% on mock data)` : ""));
if (!total) failures.push("scorecard has nothing to score");

// --- 6. trust actually varies (else the network is a flat picture) ---------
const trusts = new Set();
for (const t of log.turns || []) for (const b of t.beliefs || []) trusts.add(b.trust);
console.log(`[6] ${trusts.size} distinct trust values across the game`);
if (trusts.size <= 1) {
  failures.push("trust never varies — the network panel would be static "
    + "(expected for a belief_off log; a bug for belief_on)");
}

// --- 7. every power in the log has a colour --------------------------------
const seen = new Set();
for (const t of log.turns || []) for (const b of t.beliefs || []) {
  seen.add(b.observer); seen.add(b.subject);
}
const uncoloured = [...seen].filter((p) => !POWER_COLORS[p]);
console.log(`[7] ${seen.size} powers appear in belief data`);
if (uncoloured.length) failures.push(`no colour for: ${uncoloured.join(", ")}`);

console.log();
if (failures.length) {
  console.log("VIEWER GATE FAILED:");
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log("VIEWER GATE PASSED — data contract holds.");
