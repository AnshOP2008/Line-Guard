"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const state = { metrics: null, trace: null, index: 0, timer: null, feedback: [], loading: false };
const pct = (v) => (v * 100).toFixed(1) + "%";
const esc = (v) =>
  String(v).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const fmt = (v, d = 2) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The local engine returned an invalid response.");
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request rejected. Check the input and try again.",
    );
  return data;
}
let toastTimer;
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "show" + (error ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), 6500);
}
function view(id) {
  $$(".view").forEach((e) => e.classList.toggle("active", e.id === id));
  $$(".nav").forEach((e) => e.classList.toggle("active", e.dataset.view === id));
  if (id !== "monitor") pause();
  if (id !== "forecast") stopEngineReplay();
  if (id === "fleet") document.dispatchEvent(new Event("fleet-view"));
  document.dispatchEvent(new CustomEvent("view-changed", { detail: id }));
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$$(".nav").forEach((b) => (b.onclick = () => view(b.dataset.view)));
function pause() {
  clearInterval(state.timer);
  state.timer = null;
  $("#play-btn").textContent = "▷ Play replay";
}
function play() {
  if (!state.trace) return;
  if (state.timer) {
    pause();
    return;
  }
  if (state.index >= state.trace.points.length - 1) state.index = 0;
  $("#play-btn").textContent = "Ⅱ Pause replay";
  state.timer = setInterval(() => {
    state.index = Math.min(state.index + 3, state.trace.points.length - 1);
    renderCurrent();
    if (state.index >= state.trace.points.length - 1) pause();
  }, 160);
}
$("#play-btn").onclick = play;
$("#restart-btn").onclick = () => {
  pause();
  state.index = 0;
  renderCurrent();
  document.dispatchEvent(new Event("profiles-ready"));
};
$("#scrubber").oninput = (e) => {
  pause();
  state.index = Number(e.target.value);
  renderCurrent();
  document.dispatchEvent(new Event("profiles-ready"));
};
const requestVersion = { pump: 0, engine: 0 };
async function loadProfile(profile, url, options = {}) {
  const version = ++requestVersion[profile];
  state[profile + "Loading"] = true;
  document.dispatchEvent(new Event("profiles-ready"));
  if (profile === "engine") stopEngineReplay();
  try {
    const data = await api(url, options);
    if (version !== requestVersion[profile]) return false;
    state[profile + "Error"] = null;
    if (profile === "pump") setTrace(data);
    else {
      state.engineFull = data;
      state.engine = data;
      state.engineIndex = data.points.length - 1;
      $("#engine-select").value = data.actual_rul === null ? "" : data.engine_id;
      renderEngine();
    }
    return true;
  } catch (error) {
    if (version === requestVersion[profile]) {
      state[profile + "Error"] = error.message;
      toast("Evidence unavailable. " + error.message, true);
    }
    return false;
  } finally {
    if (version === requestVersion[profile]) {
      state[profile + "Loading"] = false;
      document.dispatchEvent(new Event("profiles-ready"));
    }
  }
}
async function loadScenario(name) {
  pause();
  return loadProfile("pump", "/api/scenario/" + name);
}
$("#scenario-select").onchange = (event) => loadScenario(event.target.value);
$("#run-select").onchange = async (event) => {
  pause();
  if (await loadProfile("pump", "/api/run?name=" + encodeURIComponent(event.target.value))) {
    $("#scenario-select").value = "recorded";
  }
};
function setTrace(data) {
  state.trace = data;
  state.index = 0;
  if (data.kind === "uploaded") $("#scenario-select").value = "uploaded";
  $("#scrubber").max = data.points.length - 1;
  $("#source-tag").textContent =
    data.kind === "simulated"
      ? "SIMULATED INJECTION"
      : data.kind === "uploaded"
        ? "UPLOADED DATA"
        : "RECORDED DATA";
  $("#source-tag").classList.toggle("amber-pill", data.kind === "simulated");
  $("#source-description").textContent =
    data.description +
    (data.domain_warnings?.length
      ? " Data-quality notes: " + data.domain_warnings.join("; ") + "."
      : "");
  $("#run-select").hidden = data.kind !== "recorded" || !data.source.endsWith(".csv");
  if (data.source.endsWith(".csv")) $("#run-select").value = data.source;
  $("#timeline-caption").textContent =
    data.kind === "simulated"
      ? "Amber band: synthetic injection interval"
      : data.kind === "recorded"
        ? "Amber band: recorded anomaly label"
        : "Uploaded data · no ground truth labels";
  renderCurrent();
  document.dispatchEvent(new Event("profiles-ready"));
}
function polyline(values, w, h, min, max) {
  const range = max - min || 1;
  return values
    .map(
      (v, i) =>
        `${((i / Math.max(values.length - 1, 1)) * w).toFixed(2)},${(h - ((v - min) / range) * h).toFixed(2)}`,
    )
    .join(" ");
}
function renderTimeline() {
  const tr = state.trace,
    points = tr.points.slice(0, state.index + 1);
  const w = 840,
    h = 225,
    pad = 28,
    plotH = 175;
  const max = Math.max(2, ...points.map((p) => p.ratio)) * 1.08;
  const x = (i) => pad + (i / Math.max(1, points.length - 1)) * (w - pad * 2),
    y = (v) => plotH + 14 - (v / max) * plotH;
  let svg = "";
  for (let tick = 0; tick <= 4; tick++) {
    const v = (max * tick) / 4;
    svg += `<line x1="${pad}" y1="${y(v)}" x2="${w - pad}" y2="${y(v)}" stroke="#243747" stroke-width=".7"/><text x="${pad - 8}" y="${y(v) + 3}" text-anchor="end" fill="#587589" font-size="8">${v.toFixed(1)}×</text>`;
  }
  let intervals = [];
  if (!state.showTruth) {
  } else if (tr.injection) intervals = [[tr.injection.start, tr.injection.end]];
  else {
    let start = null;
    points.forEach((p, i) => {
      if (p.label === 1 && start === null) start = i;
      if ((p.label !== 1 || i === points.length - 1) && start !== null) {
        intervals.push([start, i]);
        start = null;
      }
    });
  }
  for (const [s, e] of intervals.filter(([start]) => start < points.length))
    svg += `<rect x="${x(s)}" y="14" width="${x(Math.min(e, points.length - 1)) - x(s)}" height="${plotH}" fill="#f4b65a" opacity=".07"/>`;
  svg += `<line x1="${pad}" y1="${y(1)}" x2="${w - pad}" y2="${y(1)}" stroke="#f4b65a" stroke-dasharray="5 5" stroke-width="1"/><text x="${w - pad}" y="${y(1) - 6}" text-anchor="end" fill="#c69958" font-size="8">THRESHOLD</text>`;
  const coords = points.map((p, i) => `${x(i).toFixed(1)},${y(p.ratio).toFixed(1)}`).join(" ");
  svg += `<polyline points="${coords}" fill="none" stroke="#79e5c3" stroke-width="1.5" stroke-linejoin="round"/>`;
  const p = points[state.index];
  svg += `<line x1="${x(state.index)}" y1="10" x2="${x(state.index)}" y2="${plotH + 14}" stroke="#b4c9cb" opacity=".65" stroke-dasharray="3 3"/><circle cx="${x(state.index)}" cy="${y(p.ratio)}" r="4" fill="${p.alarm ? "#f4b65a" : "#79e5c3"}" stroke="#111d2b" stroke-width="2"/>`;
  for (let i = 0; i <= 4; i++) {
    const n = Math.round((i * (points.length - 1)) / 4);
    svg += `<text x="${x(n)}" y="215" text-anchor="middle" fill="#587589" font-size="8">${n}</text>`;
  }
  $("#timeline").innerHTML = svg;
}
function renderCurrent() {
  if (!state.trace) return;
  const tr = state.trace,
    p = tr.points[state.index];
  $("#scrubber").value = state.index;
  $("#sample-index").textContent = `${state.index} / ${tr.points.length - 1}`;
  $("#current-score").textContent = p.ratio.toFixed(2);
  $("#current-score").style.color = p.alarm ? "var(--amber)" : "var(--text)";
  $("#current-state").textContent = p.alarm ? "RAW ABOVE THRESHOLD" : "RAW WITHIN THRESHOLD";
  $("#current-state").className = "pill" + (p.alarm ? " warn" : "");
  $("#sample-clock").textContent = p.time;
  renderTimeline();
  const suspect = p.sensor_flags.sensor_suspect;
  let title = p.alarm
    ? suspect
      ? "Sensor integrity needs a check."
      : "The signals no longer agree."
    : suspect
      ? "A sensor may be stuck."
      : "Relationships look consistent.";
  let copy = suspect
    ? "An exact flatline or unusual jump is present. Check wiring, sensor health and the raw stream before assigning a machine fault."
    : p.alarm
      ? "Several observed readings differ from predictions based on the other signals. Inspect the process and confirm the operating mode."
      : "The model score is below its calibrated threshold. This does not establish that the machine is healthy or rule out an undetected fault.";
  $("#decision-brief").innerHTML =
    `<div class="diagnosis-status" style="color:${p.alarm || suspect ? "var(--amber)" : "var(--mint)"}"><i></i>${suspect ? "SENSOR CHECK" : p.alarm ? "RELATIONSHIP CHANGE" : "MONITORING"}</div><h3 class="diagnosis-title">${title}</h3><p class="diagnosis-copy">${copy}</p><div class="diagnosis-meta"><span>Evidence source</span><strong>${tr.kind === "simulated" ? "Injected scenario" : tr.kind === "uploaded" ? "Uploaded stream" : "Recorded test run"}</strong></div>`;
  $("#signal-cards").innerHTML = tr.features
    .map((f, j) => {
      const recent = tr.points
        .slice(Math.max(0, state.index - 34), state.index + 1)
        .map((p) => p.values[j]);
      const lo = Math.min(...recent),
        hi = Math.max(...recent);
      const flagged = p.drivers[0].sensor === f && p.alarm;
      return `<article class="signal-card${flagged ? " alert" : ""}"><div class="signal-label">${esc(tr.names[j])}<span>${String(j + 1).padStart(2, "0")}</span></div><div class="signal-reading">${fmt(p.values[j], j < 2 ? 4 : 2)}<small>${esc(tr.units[j])}</small></div><svg viewBox="0 0 65 22" aria-hidden="true"><polyline points="${polyline(recent, 65, 21, lo, hi)}" fill="none" stroke="${flagged ? "#f4b65a" : "#79e5c3"}" stroke-width="1.2"/></svg></article>`;
    })
    .join("");
  $("#relationship-evidence").innerHTML = p.drivers
    .map(
      (d) =>
        `<div class="evidence-row"><div class="evidence-name">${esc(d.name)}<small>Observed ${fmt(d.actual, 3)} · expected ${fmt(d.expected, 3)} ${esc(d.unit)}</small></div><div class="residual-track"><span style="width:${Math.min((d.strength / Math.max(5, p.drivers[0].strength)) * 100, 100)}%;background:${p.alarm ? "var(--amber)" : "var(--mint)"}"></span></div><div class="evidence-value">${d.strength.toFixed(2)}×</div></div>`,
    )
    .join("");
  document.dispatchEvent(new Event("observation-rendered"));
}
function renderEvidence() {
  const r = state.metrics,
    m = r.methods[r.primary];
  $("#event-recall").textContent = pct(m.event_recall);
  $("#event-caption").textContent =
    `${m.detected_events} of ${m.events} labelled test events detected`;
  $("#delay-stat").textContent = fmt(m.median_detection_delay_s, 1) + " s";
  $("#fpr-stat").textContent = pct(m.test_normal_fpr);
  $("#model-table").innerHTML = Object.entries(r.methods)
    .map(
      ([name, v]) =>
        `<tr class="${name === r.primary ? "primary-model" : ""}"><td>${esc(name)}${name === r.primary ? " <small>· PRIMARY</small>" : ""}</td><td>${pct(v.event_recall)}</td><td>${pct(v.event_precision)}</td><td>${pct(v.test_point_recall)}</td><td>${pct(v.test_point_precision)}</td><td>${pct(v.test_normal_fpr)}</td><td>${fmt(v.median_detection_delay_s, 1)} s</td></tr>`,
    )
    .join("");
  $("#split-info").innerHTML =
    `<div class="split-bars"><div><strong>${fmt(r.train_count, 0)}</strong><small>TRAIN / 21 RUNS</small></div><div><strong>${fmt(r.calibration_count, 0)}</strong><small>CALIBRATE / 7</small></div><div><strong>${fmt(r.test_count, 0)}</strong><small>TEST / 7</small></div></div>`;
  $("#split-contract").textContent = r.split_contract;
  $("#injection-results").innerHTML = Object.entries(r.injections)
    .map(
      ([k, v]) =>
        `<div class="injection-row"><strong>${esc(k)}</strong><span><b>${pct(v.anomaly_detection_rate)}</b>Anomaly detection</span><span><b>${pct(v.sensor_heuristic_rate)}</b>Sensor heuristic</span><span><b>${pct(v.top_sensor_attribution_rate)}</b>Top attribution</span></div>`,
    )
    .join("");
  $("#ablation-results").innerHTML = r.ablation
    .map(
      (v, j) =>
        `<div class="ablation-card"><div>${esc(r.names[j])}</div><strong>${pct(v.test_point_recall)}</strong><small>Point recall · normal FPR ${pct(v.test_normal_fpr)}</small></div>`,
    )
    .join("");
}
$("#csv-file").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  pause();
  const form = new FormData();
  form.append("file", file);
  if (await loadProfile("pump", "/api/upload", { method: "POST", body: form })) {
    view("monitor");
    toast("Uploaded pump stream ready.");
  }
  event.target.value = "";
};
$("#feedback-btn").onclick = () => {
  pause();
  $("#feedback-context").textContent =
    `${state.trace.source} · sample ${state.index} · ${state.trace.points[state.index].ratio.toFixed(2)}× threshold`;
  $("#feedback-dialog").showModal();
};
$("#close-dialog").onclick = () => $("#feedback-dialog").close();
$("#feedback-form").onsubmit = async (e) => {
  e.preventDefault();
  const submit = e.target.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    await api("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: state.trace.source,
        sample: state.index,
        verdict: $("#feedback-verdict").value,
        note: $("#feedback-note").value,
      }),
    });
    $("#feedback-dialog").close();
    $("#feedback-note").value = "";
    await loadFeedback();
    toast("Operator decision saved locally. The model has not been retrained.");
  } catch (err) {
    toast(err.message, true);
  } finally {
    submit.disabled = false;
  }
};
async function loadFeedback() {
  state.feedback = await api("/api/feedback");
  $("#feedback-count").textContent = state.feedback.length;
  $("#feedback-list").innerHTML = state.feedback.length
    ? state.feedback
        .map(
          (f) =>
            `<article class="panel feedback-card"><div class="feedback-icon">✓</div><div class="feedback-main"><h3>${esc(f.source)} · sample ${f.sample}</h3><small>${esc(new Date(f.created).toLocaleString())} · Record #${f.id}</small><p>${esc(f.note || "No inspection notes recorded.")}</p></div><span class="tag">${esc(f.verdict)}</span></article>`,
        )
        .join("")
    : '<div class="empty"><strong>No decisions recorded yet.</strong>Inspect a timeline sample, then record your assessment from the command center.</div>';
}
(async () => {
  try {
    const [metrics, data, runs] = await Promise.all([
      api("/api/metrics"),
      api("/api/scenario/recorded"),
      api("/api/runs"),
    ]);
    $("#run-select").innerHTML = runs
      .map((r) => `<option value="${esc(r.run)}">${esc(r.run)}</option>`)
      .join("");
    state.metrics = metrics;
    renderEvidence();
    if (requestVersion.pump === 0) setTrace(data);
    await loadFeedback();
  } catch (e) {
    toast("Unable to initialize: " + e.message, true);
    $("#source-description").textContent =
      "Local engine unavailable. Check that the server is running and the model has been trained.";
  }
})();
// Independent NASA simulated-turbofan prognostics profile. No pump sensor fusion.
state.forecast = null;
state.engine = null;
function historySvg(rows, key, truthKey = null, band = null) {
  const w = 800,
    h = 275,
    l = 40,
    r = 15,
    t = 16,
    b = 35,
    ph = h - t - b,
    pw = w - l - r;
  const values = rows
    .map((p) => p[key])
    .concat(band ? rows.map((p) => p[band[1]]).filter(Number.isFinite) : [])
    .concat(truthKey ? rows.filter((p) => p[truthKey] !== null).map((p) => p[truthKey]) : []);
  const max = Math.max(10, ...values) * 1.08;
  const minX = rows[0].cycle,
    maxX = rows[rows.length - 1].cycle;
  const x = (c) => l + ((c - minX) / Math.max(1, maxX - minX)) * pw,
    y = (v) => t + ph - (v / max) * ph;
  let out = "";
  for (let i = 0; i <= 4; i++) {
    let v = (max * i) / 4;
    out += `<line x1="${l}" x2="${w - r}" y1="${y(v)}" y2="${y(v)}" stroke="#263c4b" stroke-width=".7"/><text x="${l - 8}" y="${y(v) + 3}" text-anchor="end" font-size="9" fill="#658599">${Math.round(v)}</text>`;
  }
  const line = (k) => rows.map((p) => `${x(p.cycle)},${y(p[k])}`).join(" ");
  if (band && rows.every((p) => Number.isFinite(p[band[0]]) && Number.isFinite(p[band[1]]))) {
    const lo = rows.map((p) => `${x(p.cycle)},${y(p[band[0]])}`),
      hi = rows.map((p) => `${x(p.cycle)},${y(p[band[1]])}`).reverse();
    out += `<polygon class="interval-band" points="${lo.concat(hi).join(" ")}" fill="#79e5c3" fill-opacity=".16" stroke="none"><title>90% conformal interval</title></polygon>`;
  }
  if (truthKey && rows[0][truthKey] !== null)
    out += `<polyline points="${line(truthKey)}" fill="none" stroke="#f4b65a" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  out += `<polyline points="${line(key)}" fill="none" stroke="#79e5c3" stroke-width="2" stroke-linejoin="round"/>`;
  for (let i = 0; i <= 4; i++) {
    const c = minX + ((maxX - minX) * i) / 4;
    out += `<text x="${x(c)}" y="${h - 12}" text-anchor="middle" font-size="9" fill="#658599">${Math.round(c)}</text>`;
  }
  out += `<text x="${w - r}" y="${h - 1}" text-anchor="end" font-size="8" fill="#658599">OBSERVED CYCLE →</text>`;
  return out;
}
async function selectEngine(id) {
  return loadProfile("engine", "/api/prognostics/engine/" + id);
}
function renderEngine() {
  const e = state.engine;
  if (!e) return;
  $("#engine-title").textContent = e.source.startsWith("Uploaded")
    ? "Uploaded engine " + e.engine_id
    : "Test engine " + String(e.engine_id).padStart(3, "0");
  $("#engine-rul").textContent = fmt(e.predicted_rul, 1);
  $("#engine-age").textContent = e.observed_cycles + " cycles";
  $("#engine-truth").textContent =
    e.actual_rul === null
      ? "Unavailable for uploaded data"
      : state.showTruth
        ? e.actual_rul + " cycles"
        : "Hidden · enable benchmark hindsight";
  $("#engine-source").textContent =
    e.actual_rul === null ? "UPLOADED · NO GROUND TRUTH" : "SIMULATED BENCHMARK DATA";
  $("#rul-chart").innerHTML = historySvg(
    e.points,
    "predicted_rul",
    state.showTruth ? "actual_rul" : null,
    ["interval_low", "interval_high"],
  );
  const iv = state.forecast?.interval,
    cov = Number.isFinite(iv?.test_coverage) ? Math.round(iv.test_coverage * 100) + "%" : null;
  const lastPoint = e.points[e.points.length - 1] || {},
    lo = lastPoint.interval_low ?? e.interval_low,
    hi = lastPoint.interval_high ?? e.interval_high;
  $("#engine-interval").textContent =
    Number.isFinite(lo) && Number.isFinite(hi)
      ? `90% interval: ${Math.round(lo)}–${Math.round(hi)} cycles`
      : "";
  $("#interval-note").textContent =
    "90% conformal interval, calibrated on out-of-fold engines" +
    (cov ? `; measured test coverage ${cov}.` : ".");
  $("#rul-history-note").textContent =
    e.actual_rul === null
      ? "Uploaded stream: no actual RUL or performance estimate is fabricated. Predictions use only the supplied current and previous cycles. FD001 compatibility does not validate another engine type."
      : "Amber truth is benchmark hindsight: supplied final RUL plus cycles back from the final observation. It never enters inference. Predictions use current and past observations only.";
  renderHorizon();
}
function renderHorizon() {
  if (!state.forecast) return;
  const horizon = Number($("#rul-horizon").value),
    m = state.forecast.horizons.find((v) => v.horizon === horizon);
  $("#horizon-label").textContent = horizon + " cycles";
  $("#horizon-metrics").innerHTML =
    `<div><strong>${pct(m.recall)}</strong><small>FAILURES WITHIN HORIZON CAUGHT</small></div><div><strong>${pct(m.precision)}</strong><small>ALERT PRECISION</small></div><div><strong>${pct(m.false_positive_rate)}</strong><small>OUTSIDE-HORIZON ALERT RATE</small></div>`;
  $("#forecast-confusion").innerHTML = [
    ["True positives", m.tp],
    ["False positives", m.fp],
    ["Missed positives", m.fn],
    ["True negatives", m.tn],
  ]
    .map(([n, v]) => `<div><strong>${v}</strong><small>${n}</small></div>`)
    .join("");
  if (state.engine) {
    const unfamiliar = state.engine.domain_warnings?.length;
    const alert = !unfamiliar && state.engine.predicted_rul <= horizon;
    $("#engine-decision").textContent = unfamiliar
      ? "Training-range warning: " +
        state.engine.domain_warnings.join(", ") +
        ". Verify compatibility and units before acting."
      : alert
        ? "Within your planning horizon · prioritize an inspection."
        : "Beyond your planning horizon · continue scheduled review.";
    $("#engine-decision").className = "forecast-decision" + (alert ? " warn" : "");
  }
  $("#engine-fleet").innerHTML = state.forecast.engine_predictions
    .filter(
      (e) =>
        !$("#engine-search")?.value ||
        String(e.engine_id).includes(
          $("#engine-search")
            .value.trim()
            .replace(/^TF[–-]?/i, ""),
        ),
    )
    .map(
      (e) =>
        `<tr class="engine-row${state.engine && state.engine.actual_rul !== null && e.engine_id === state.engine.engine_id ? " selected" : ""}" tabindex="0" role="button" aria-label="Inspect engine ${e.engine_id}" data-engine="${e.engine_id}"><td>TF–${String(e.engine_id).padStart(3, "0")}</td><td>${e.observed_cycles}</td><td>${e.predicted_rul.toFixed(1)} cycles <span class="forecast-rul-bar"><i style="width:${(e.predicted_rul / 125) * 100}%"></i></span></td><td>${e.actual_rul} cycles</td><td>${Math.abs(e.predicted_rul - e.actual_rul).toFixed(1)}</td><td><span class="pill${e.predicted_rul <= horizon ? " warn" : ""}">${e.predicted_rul <= horizon ? "PLAN INSPECTION" : "MONITOR"}</span></td></tr>`,
    )
    .join("");
  $$(".engine-row").forEach((row) => {
    row.onkeydown = (event) => {
      if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        row.click();
      }
    };
    row.onclick = () => {
      selectEngine(Number(row.dataset.engine));
      $("#forecast").scrollIntoView({ behavior: "smooth" });
    };
  });
}
$("#rul-horizon").oninput = renderHorizon;
$("#engine-select").onchange = (e) => selectEngine(Number(e.target.value));
async function initForecast() {
  try {
    const r = await api("/api/prognostics");
    state.forecast = r;
    const score = r.test[r.selected_model],
      base = r.test["Age-only baseline"];
    $("#forecast-mae").textContent = score.mae.toFixed(2);
    $("#forecast-rmse").textContent = score.rmse.toFixed(2);
    $("#baseline-mae").textContent = base.mae.toFixed(2);
    $("#forecast-nasa").textContent = Number.isFinite(score.nasa_score)
      ? Math.round(score.nasa_score).toLocaleString("en-US")
      : "—";
    $("#forecast-nasa-note").textContent = Number.isFinite(base.nasa_score)
      ? `Lower is better · baseline ${Math.round(base.nasa_score).toLocaleString("en-US")}`
      : "Lower is better";
    $("#forecast-gain").textContent = pct(1 - score.mae / base.mae);
    $("#engine-select").innerHTML = r.engine_predictions
      .map(
        (e) =>
          `<option value="${e.engine_id}">Test engine TF–${String(e.engine_id).padStart(3, "0")}</option>`,
      )
      .join("");
    $("#forecast-validation").innerHTML = Object.entries(r.validation)
      .map(
        ([n, v]) =>
          `<div class="validation-model${n === r.selected_model ? " selected" : ""}"><span>${esc(n)}${n === r.selected_model ? " · SELECTED" : ""}<small>5-fold engine-grouped CV</small></span><span><b>${v.mae.toFixed(2)}</b><small>MAE / CYCLES</small></span></div>`,
      )
      .join("");
    await selectEngine(24);
  } catch (e) {
    toast("Forecast profile unavailable: " + e.message, true);
  }
}
$("#engine-file").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  if (await loadProfile("engine", "/api/prognostics/upload", { method: "POST", body: form })) {
    view("forecast");
    toast("Engine forecast ready. No ground-truth RUL is assumed for uploaded data.");
  }
  event.target.value = "";
};
initForecast().finally(() => document.dispatchEvent(new Event("profiles-ready")));
