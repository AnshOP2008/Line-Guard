"use strict";
/* Insights layer: sensor-level forecast explanation, grounded copilot, business-impact
   policy simulation and the four-subset generalisation evidence. Reuses the helpers and
   state defined in app.js / operations.js. */

const minus = (v, d = 1) => (v < 0 ? "−" : v > 0 ? "+" : "") + fmt(Math.abs(v), d);
const tfId = (id) => "TF–" + String(id).padStart(3, "0");

/* ---------- Why this forecast? ---------- */
let explainTimer,
  explainVersion = 0,
  explainKey = "";
function officialEngine() {
  const full = state.engineFull;
  return (
    !!state.engine &&
    !!full &&
    full.actual_rul !== null &&
    !String(full.source || "").startsWith("Uploaded") &&
    Number.isInteger(full.engine_id) &&
    full.engine_id >= 1 &&
    full.engine_id <= 100
  );
}
function scheduleExplain() {
  clearTimeout(explainTimer);
  explainTimer = setTimeout(loadExplain, 250);
}
async function loadExplain() {
  const panel = $("#explain-panel");
  if (!state.engine || state.engineLoading) return;
  if (!officialEngine()) {
    panel.hidden = true;
    explainKey = "";
    return;
  }
  const id = state.engineFull.engine_id,
    cycle = state.engine.observed_cycles,
    key = id + ":" + cycle;
  if (key === explainKey) return;
  panel.hidden = false;
  const version = ++explainVersion;
  try {
    const data = await api(`/api/insights/engine/${id}/explain?cycle=${cycle}`);
    if (version !== explainVersion) return;
    explainKey = key;
    renderExplain(data);
  } catch (error) {
    if (version !== explainVersion) return;
    explainKey = "";
    $("#explain-summary").textContent = "Sensor attribution is unavailable for this observation.";
    $("#explain-caveat").textContent = error.message;
    $("#explain-chart").innerHTML = "";
  }
}
function renderExplain(d) {
  const drivers = [...(d.drivers || [])].sort(
    (a, b) => a.contribution_cycles - b.contribution_cycles,
  );
  const neg = Math.max(0, ...drivers.map((r) => -r.contribution_cycles)),
    pos = Math.max(0, ...drivers.map((r) => r.contribution_cycles)),
    span = neg + pos || 1,
    zero = (neg / span) * 100;
  const healthy = Number.isFinite(d.all_healthy_prediction) ? d.all_healthy_prediction : null;
  $("#explain-summary").innerHTML =
    healthy === null
      ? "Contribution of each sensor group to the current forecast."
      : `If these sensors looked like a healthy engine, the forecast would be <strong>${fmt(healthy, 1)} cycles</strong> <span class="explain-vs">instead of ${fmt(d.base_prediction, 1)} at cycle ${esc(d.cycle)}.</span>`;
  $("#explain-caveat").textContent =
    (d.caveat || "") + (d.method ? " Method: " + d.method + "." : "");
  $("#explain-chart").innerHTML = drivers
    .map((r) => {
      const c = r.contribution_cycles,
        w = Math.max((Math.abs(c) / span) * 100, 0.6),
        left = c < 0 ? zero - w : zero;
      return `<div class="ex-row" title="${esc(r.name)} (${esc(r.unit)}) · ${esc(r.subsystem)} · ${minus(c)} cycles"><div class="ex-label"><b>${esc(r.symbol)}</b> · ${esc(r.subsystem)}</div><div class="ex-track"><i class="ex-zero" style="left:${zero.toFixed(2)}%"></i><i class="ex-bar ${c < 0 ? "neg" : "pos"}" style="left:${left.toFixed(2)}%;width:${w.toFixed(2)}%"></i></div><div class="ex-val ${c < 0 ? "neg" : "pos"}">${minus(c)}</div></div>`;
    })
    .join("");
}
document.addEventListener("profiles-ready", scheduleExplain);

/* ---------- Business impact ---------- */
const impact = { data: null, timer: null, version: 0, loaded: false };
const POLICY = {
  rtf: "Run to failure",
  fixed: "Best fixed interval",
  pred: "LineGuard predictive",
};
function pickPolicy(d, key) {
  return (
    d.policies.find((p) => p.policy === POLICY[key]) ||
    d.policies[{ rtf: 0, fixed: 1, pred: 2 }[key]]
  );
}
function impactParams() {
  const ratio = Number($("#impact-ratio").value),
    lead = Number($("#impact-lead").value);
  $("#impact-ratio-label").textContent = `${ratio} : 1`;
  $("#impact-lead-label").textContent = `${lead} cycle${lead === 1 ? "" : "s"}`;
  return `cost_preventive=1&cost_failure=${ratio}&lead=${lead}&use_lower_bound=${$("#impact-lower").checked}`;
}
function scheduleImpact() {
  impactParams();
  clearTimeout(impact.timer);
  impact.timer = setTimeout(loadImpact, 250);
}
async function loadImpact() {
  const version = ++impact.version;
  $("#impact").classList.add("busy");
  try {
    const data = await api("/api/policy?" + impactParams());
    if (version !== impact.version) return;
    impact.data = data;
    impact.loaded = true;
    renderImpact2(data);
  } catch (error) {
    if (version !== impact.version) return;
    toast("Impact simulation unavailable. " + error.message, true);
  } finally {
    if (version === impact.version) $("#impact").classList.remove("busy");
  }
}
function renderImpact2(d) {
  const rtf = pickPolicy(d, "rtf"),
    fixed = pickPolicy(d, "fixed"),
    pred = pickPolicy(d, "pred"),
    n = d.evaluation_engines ?? rtf.failures;
  const sv = d.savings_vs_fixed_pct;
  $("#kpi-savings").textContent = Number.isFinite(sv)
    ? (sv > 0 ? "−" : "+") + fmt(Math.abs(sv), 1) + "%"
    : "—";
  $("#kpi-savings-note").textContent =
    `${pred.cost_per_1000_cycles.toFixed(1)} vs ${fixed.cost_per_1000_cycles.toFixed(1)} cost units per 1,000 cycles`;
  $("#kpi-failures").innerHTML = `${pred.failures}<span class="stat-unit"> / ${n}</span>`;
  $("#kpi-failures-note").textContent =
    `Fixed schedule ${fixed.failures} · run-to-failure ${rtf.failures}`;
  $("#kpi-util").textContent = pct(pred.life_utilisation);
  $("#kpi-util-note").textContent = `Fixed schedule ${pct(fixed.life_utilisation)} of life used`;
  $("#kpi-waste").innerHTML =
    `${fmt(pred.mean_wasted_cycles, 1)}<span class="stat-unit"> cycles</span>`;
  $("#kpi-waste-note").textContent = `Fixed schedule ${fmt(fixed.mean_wasted_cycles, 1)} cycles`;
  $("#impact-tuned").textContent =
    `LineGuard alert threshold (${d.tuned_threshold} cycles) and fixed interval (${d.tuned_interval} cycles) were tuned on ${d.tuning_engines} separate engines. Every figure on this page is for the ${n} evaluation engines they never saw.`;
  const max = Math.max(...[rtf, fixed, pred].map((p) => p.cost_per_1000_cycles), 1e-9);
  $("#impact-bars").innerHTML = [
    ["Run to failure", rtf, "rtf", "Fix it when it breaks"],
    ["Best fixed interval", fixed, "fixed", `Replace every ${d.tuned_interval} cycles`],
    [
      "LineGuard predictive",
      pred,
      "pred",
      `Act at ≤ ${d.tuned_threshold} predicted cycles${d.assumptions?.use_lower_bound ? " (lower bound)" : ""}`,
    ],
  ]
    .map(
      ([name, p, cls, sub]) =>
        `<div class="cost-row ${cls}"><div class="cost-name">${esc(name)}<small>${esc(sub)}</small></div><div class="cost-track"><i style="width:${Math.max((p.cost_per_1000_cycles / max) * 100, 1.5).toFixed(1)}%"></i></div><div class="cost-val">${p.cost_per_1000_cycles.toFixed(1)}</div></div>`,
    )
    .join("");
  const avoidedFixed = d.failures_avoided_vs_fixed ?? fixed.failures - pred.failures,
    avoidedRtf = rtf.failures - pred.failures;
  $("#impact-avoided").innerHTML =
    `<strong>${avoidedRtf} of ${rtf.failures}</strong> run-to-failure breakdowns avoided. ` +
    (avoidedFixed > 0
      ? `<strong>${avoidedFixed}</strong> fewer failures than the fixed schedule.`
      : avoidedFixed === 0
        ? `The tuned fixed schedule is equally safe, but throws away <strong>${fmt(fixed.mean_wasted_cycles, 0)}</strong> cycles per replacement against <strong>${fmt(pred.mean_wasted_cycles, 0)}</strong> for LineGuard.`
        : `At this lead time the fixed schedule has <strong>${-avoidedFixed}</strong> fewer failures than LineGuard.`);
  $("#impact-protocol").textContent = d.protocol || "";
  renderPolicyTimeline(d);
}
function renderPolicyTimeline(d) {
  const panel = $("#impact-timeline-panel"),
    el = $("#impact-timeline");
  const fixed = pickPolicy(d, "fixed"),
    pred = pickPolicy(d, "pred");
  if (!Array.isArray(fixed.per_engine) || !Array.isArray(pred.per_engine)) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const fx = new Map(fixed.per_engine.map((r) => [r.engine_id, r]));
  const rows = pred.per_engine
    .map((r) => ({ ...r, fixed: fx.get(r.engine_id) }))
    .sort((a, b) => a.failure_cycle - b.failure_cycle);
  const W = Math.max(el.clientWidth || 600, 280),
    left = 44,
    right = 10,
    pitch = 9,
    H = rows.length * pitch + 26,
    maxC = Math.ceil(Math.max(...rows.map((r) => r.failure_cycle), 1) / 50) * 50,
    x = (c) => left + (c / maxC) * (W - left - right);
  let svg = "";
  for (let c = 0; c <= maxC; c += 50)
    svg += `<line x1="${x(c)}" x2="${x(c)}" y1="0" y2="${rows.length * pitch}" stroke="#1f3040" stroke-width="1"/><text x="${x(c)}" y="${rows.length * pitch + 15}" text-anchor="middle" font-size="9" fill="#658599">${c}</text>`;
  svg += `<text x="${W - right}" y="${H - 1}" text-anchor="end" font-size="8" fill="#658599" letter-spacing="1">OPERATING CYCLE →</text>`;
  rows.forEach((r, i) => {
    const y = i * pitch + pitch / 2,
      f = r.fixed,
      predFail = r.outcome === "failure",
      fixFail = f && f.outcome === "failure";
    const tip = `${tfId(r.engine_id)} · fails at cycle ${r.failure_cycle} · LineGuard ${predFail ? "failed (unplanned)" : "acts at " + r.action_cycle}${f ? " · fixed " + (fixFail ? "failed (unplanned)" : "acts at " + f.action_cycle) : ""}`;
    svg += `<g><title>${esc(tip)}</title><rect x="0" y="${i * pitch}" width="${W}" height="${pitch}" fill="transparent"/>`;
    if (i % 4 === 0)
      svg += `<text x="${left - 8}" y="${y + 3}" text-anchor="end" font-size="8" fill="#658599">${tfId(r.engine_id)}</text>`;
    svg += `<rect x="${left}" y="${y - 1.5}" width="${x(r.failure_cycle) - left}" height="3" rx="1.5" fill="#2a4256"/>`;
    if (f && !fixFail)
      svg += `<line x1="${x(f.action_cycle)}" x2="${x(f.action_cycle)}" y1="${y - 3.6}" y2="${y + 3.6}" stroke="#f4b65a" stroke-width="1.8" stroke-linecap="round"/>`;
    if (!predFail) svg += `<circle cx="${x(r.action_cycle)}" cy="${y}" r="2.7" fill="#79e5c3"/>`;
    if (predFail || fixFail) {
      const cx = x(r.failure_cycle),
        s = 3;
      svg += `<path d="M${cx - s} ${y - s}L${cx + s} ${y + s}M${cx + s} ${y - s}L${cx - s} ${y + s}" stroke="#f28579" stroke-width="1.8" stroke-linecap="round"/>`;
    }
    svg += "</g>";
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="height:${H}px">${svg}</svg>`;
}
for (const id of ["#impact-ratio", "#impact-lead"]) $(id).addEventListener("input", scheduleImpact);
$("#impact-lower").addEventListener("change", scheduleImpact);
document.addEventListener("view-changed", (e) => {
  if (e.detail === "impact") {
    if (!impact.loaded) loadImpact();
    else renderPolicyTimeline(impact.data);
  }
});
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (impact.data && $("#impact").classList.contains("active")) renderPolicyTimeline(impact.data);
  }, 150);
});

/* ---------- Generalisation across C-MAPSS subsets ---------- */
async function loadBenchmark() {
  try {
    const b = await api("/api/benchmark");
    const subsets = Object.entries(b.subsets || {});
    $("#gen-protocol").textContent = (b.protocol || "").replace(/\s*\n\s*/g, " ");
    $("#gen-table").innerHTML = subsets
      .map(([name, s]) => {
        const r = s.result || {},
          app = name === "FD001";
        return `<tr class="${app ? "is-app" : ""}"><td>${esc(name)}${app ? ' <span class="tag">INTERACTIVE APP MODEL</span>' : ""}</td><td>${s.conditions}</td><td>${s.fault_modes}</td><td>${fmt(r.test_engines, 0)}</td><td>${fmt(r.mae, 2)}</td><td>${fmt(r.rmse, 2)}</td><td>${fmt(r.rmse_capped_truth, 2)}</td><td>${fmt(r.nasa_score, 0)}</td></tr>`;
      })
      .join("");
    $("#gen-ablation").innerHTML =
      subsets
        .filter(([, s]) => s.ablation_without_regime_normalisation)
        .map(([name, s]) => {
          const a = s.ablation_without_regime_normalisation.rmse_capped_truth,
            w = s.result.rmse_capped_truth;
          return `<div class="abl-card"><div class="eyebrow">${esc(name)} · ${s.conditions} OPERATING CONDITIONS</div><div class="abl-nums"><span>${fmt(a, 1)}</span><i>→</i><strong>${fmt(w, 1)}</strong></div><small>Capped-truth RMSE in cycles, without → with per-regime sensor normalisation</small><b>${minus(((w - a) / a) * 100, 0)}% error</b></div>`;
        })
        .join("") || '<p class="muted fine">No ablation reported.</p>';
    const lit = b.literature_rmse || {},
      cell = (v) => (v === null || v === undefined ? "—" : fmt(v, 2));
    const ours = subsets
      .map(
        ([, s]) =>
          `${fmt(s.result.rmse, 2)} <small>(${fmt(s.result.rmse_capped_truth, 2)})</small>`,
      )
      .map((t) => `<td>${t}</td>`)
      .join("");
    $("#gen-lit").innerHTML =
      `<tr class="is-app"><td>LineGuard <small>uncapped (capped truth)</small></td>${ours}</tr>` +
      Object.entries(lit.rows || {})
        .map(
          ([n, v]) => `<tr><td>${esc(n)}</td>${v.map((x) => `<td>${cell(x)}</td>`).join("")}</tr>`,
        )
        .join("");
    $("#gen-lit-note").innerHTML =
      `${esc(lit.note || "")} ${lit.source ? `<a href="${esc(lit.source)}" target="_blank" rel="noopener">Source ↗</a>` : ""} The interactive app runs the FD001 model; the other subsets re-run the same recipe unchanged.`;
  } catch (error) {
    $("#gen-protocol").textContent = "Benchmark comparison unavailable. " + error.message;
  }
}
loadBenchmark();
