let finding;
let tasks = [];
const taskDialog = $("#task-dialog");

function fleetSummary() {
  const point = state.trace?.points[state.index];
  const engine = state.engine;
  const horizon = Number($("#rul-horizon").value);
  const pumpTasks = tasks.filter(
    (task) =>
      task.asset_id === state.trace?.asset_id && !["completed", "cancelled"].includes(task.status),
  );
  const engineTasks = tasks.filter(
    (task) =>
      task.asset_id === engine?.asset_id && !["completed", "cancelled"].includes(task.status),
  );
  $("#fleet-pump").textContent = point
    ? `${state.trace.source} · ${point.time} · ${pumpAssessment().reason} · ${pumpTasks.length} active tasks`
    : "Pump evidence unavailable. Open Command center to retry.";
  $("#fleet-engine").textContent = engine
    ? `${engineAsset(engine)} · cycle ${engine.observed_cycles} · ${fmt(engine.predicted_rul, 1)} cycles remaining · ${engineAssessment().reason} · ${engineTasks.length} active tasks`
    : "Forecast unavailable. Reload LineGuard to retry.";
  const slots = Math.max(1, Math.min(20, Number($("#inspection-capacity").value) || 1));
  const candidates = (state.forecast?.engine_predictions || [])
    .filter(
      (engine) =>
        engine.predicted_rul <= horizon &&
        !tasks.some(
          (task) =>
            task.asset_id === "fd001-test:" + engine.engine_id &&
            !["completed", "cancelled"].includes(task.status),
        ),
    )
    .sort((a, b) => a.predicted_rul - b.predicted_rul);
  $("#fleet-counts").textContent =
    `${state.forecast?.engine_predictions.filter((e) => e.predicted_rul <= horizon).length || 0} / 100 benchmark engines within ${horizon} cycles · ${tasks.filter((t) => !["completed", "cancelled"].includes(t.status)).length} active tasks · ${candidates.length} eligible · ${Math.max(0, candidates.length - slots)} beyond capacity`;
  const checks = [pumpAssessment(), engineAssessment()].filter(
    (item) => item.status === "Verify data",
  ).length;
  $("#fleet-clock").textContent = checks
    ? `${checks} selected profile${checks > 1 ? "s" : ""} need data verification before acting.`
    : "";
  $("#inspection-plan").innerHTML = candidates.length
    ? candidates
        .slice(0, slots)
        .map(
          (engine) =>
            `<li><button class="pill-button" data-planned-engine="${engine.engine_id}">TF–${engine.engine_id}<span>${fmt(engine.predicted_rul, 1)} cycles</span></button></li>`,
        )
        .join("")
    : "<li>No available benchmark engines within the selected horizon.</li>";
}

function engineAsset(engine) {
  if (!engine) return "";
  return `${engine.actual_rul === null ? "Uploaded engine" : "Turbofan TF–"}${engine.actual_rul === null ? " " : ""}${engine.engine_id}`;
}

function evidenceSnapshot(profile) {
  const engine = profile === "forecast";
  const key = engine ? "engine" : "pump";
  const evidence = engine ? state.engine : state.trace;
  if (!evidence || state[key + "Loading"] || state[key + "Error"]) {
    throw new Error("Load valid evidence before saving a task.");
  }
  return {
    inference_id: evidence.inference_id,
    index: engine ? state.engineIndex : state.index,
    horizon: Number($("#rul-horizon").value),
  };
}
function openTask(profile) {
  try {
    finding = evidenceSnapshot(profile);
    $("#task-assessment").textContent =
      profile === "forecast"
        ? `${engineAsset(state.engine)} · ${fmt(state.engine.predicted_rul, 1)} cycles · ${engineAssessment().reason}`
        : `Pump P–01 · sample ${state.index} · ${pumpAssessment().reason}`;
    $("#task-notes").value = "";
    $("#task-error").textContent = "";
    taskDialog.showModal();
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshTasks() {
  try {
    tasks = await api("/api/tasks");
    renderTasks();
    fleetSummary();
  } catch (error) {
    $("#task-list").textContent = "Local tasks unavailable. Reload LineGuard to retry.";
  }
}
function renderTasks() {
  const visible = tasks.filter(
    (t) =>
      (!$("#task-filter").value || t.status === $("#task-filter").value) &&
      (!$("#task-search").value ||
        [t.asset, t.notes, t.observation, t.outcome]
          .join(" ")
          .toLowerCase()
          .includes($("#task-search").value.toLowerCase())),
  );
  $("#task-list").innerHTML = visible.length
    ? visible
        .map(
          (task) => `
      <article class="task-row"><h3>${esc(task.asset)} · ${esc(task.status)}</h3>
      <p>${esc(task.observation)} · ${esc(task.priority)} · ${esc(task.reading)}</p>
      <p class="muted">${task.verified ? "Server-preserved inference evidence" : "Legacy operator-supplied evidence · unverified"}</p>
      <p>${esc([task.notes, task.outcome].filter(Boolean).join(" · "))}</p>
      <div class="fleet-actions">
      ${!["completed", "cancelled"].includes(task.status) ? `<form data-cancel="${task.id}"><label>Cancellation reason <input name="reason" required maxlength="2000"></label><button>Cancel task</button></form>` : ""}
      <a href="/api/tasks/${task.id}/report" download>Download evidence</a>
      ${task.status === "open" ? `<button data-ack="${task.id}">Acknowledge</button>` : ""}
      ${
        task.status === "acknowledged"
          ? `<form data-complete="${task.id}"><label for="outcome-${task.id}">Inspection outcome</label>
        <input id="outcome-${task.id}" name="outcome" required maxlength="2000"><button>Complete inspection</button></form>`
          : ""
      }
      </div></article>`,
        )
        .join("")
    : tasks.length
      ? "<p>No tasks match this search or filter.</p>"
      : "<p>No maintenance tasks saved.</p>";
}

async function advanceTask(id, status, outcome = "") {
  try {
    await api("/api/tasks/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, outcome }),
    });
    await refreshTasks();
  } catch (error) {
    toast(error.message, true);
  }
}

$("#task-list").addEventListener("click", (event) => {
  const ack = event.target.closest("[data-ack]");
  if (ack) advanceTask(ack.dataset.ack, "acknowledged");
});
$("#task-list").addEventListener("submit", (event) => {
  event.preventDefault();
  const cancelled = event.target.dataset.cancel;
  advanceTask(
    cancelled || event.target.dataset.complete,
    cancelled ? "cancelled" : "completed",
    new FormData(event.target).get(cancelled ? "reason" : "outcome"),
  );
});
$("#task-cancel").onclick = () => taskDialog.close();
$("#task-form").onsubmit = async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  submit.disabled = true;
  try {
    await api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...finding, notes: $("#task-notes").value }),
    });
    taskDialog.close();
    view("fleet");
    toast("Inspection task saved.");
  } catch (error) {
    $("#task-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
};
for (const [profile, anchor] of [
  ["forecast", "#engine-decision"],
  ["monitor", "#feedback-btn"],
]) {
  const target = $(anchor) || $("#" + profile);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inspection-action" + (profile === "monitor" ? " button full secondary" : "");
  button.textContent = "Save inspection task";
  button.onclick = () => openTask(profile);
  if (target.id === profile) target.prepend(button);
  else target.after(button);
}
$$("[data-open-profile]").forEach(
  (button) => (button.onclick = () => view(button.dataset.openProfile)),
);
$("#inspection-capacity").oninput = fleetSummary;
$("#inspection-plan").onclick = async (event) => {
  const planned = event.target.closest("[data-planned-engine]");
  if (!planned) return;
  if (await selectEngine(Number(planned.dataset.plannedEngine))) view("forecast");
};
$("#guide-engine").onclick = async () => {
  const candidate = state.forecast?.engine_predictions
    .filter((engine) => engine.predicted_rul <= Number($("#rul-horizon").value))
    .sort((a, b) => a.predicted_rul - b.predicted_rul)[0];
  if (!candidate) return toast("No benchmark engine falls within the selected horizon.", true);
  if (!(await selectEngine(candidate.engine_id))) return;
  view("forecast");
  toast("Illustrative example: review the forecast and save an inspection task.");
};
async function guidePump(scenario) {
  $("#scenario-select").value = scenario;
  if (!(await loadScenario(scenario))) return;
  const point = state.trace.points.find((point) =>
    scenario === "flatline"
      ? point.index >= 159 && point.sensor_flags.flatline.length
      : point.grouped_alert && point.label && !point.sensor_flags.sensor_suspect,
  );
  state.index = point?.index ?? 0;
  renderCurrent();
  view("monitor");
  toast("Illustrative example: review the sensor evidence and save an inspection task.");
}
$("#guide-pump").onclick = () => guidePump("recorded");
$("#guide-sensor").onclick = () => guidePump("flatline");
$("#reset-demo").onclick = async () => {
  pause();
  $("#scenario-select").value = "recorded";
  await loadScenario("recorded");
  await selectEngine(24);
  fleetSummary();
  $("#guide-message").textContent = "Replay reset. Saved maintenance tasks are available below.";
};
document.addEventListener("fleet-view", refreshTasks);
document.addEventListener("profiles-ready", fleetSummary);
refreshTasks();

function showPumpPolicy() {
  const point = state.trace?.points[state.index];
  if (point)
    $("#pump-operational-status").textContent = point.grouped_alert
      ? "Grouped alert active · " + pumpAssessment().reason
      : "No grouped alert at this sample.";
}
const policyStatus = document.createElement("p");
policyStatus.id = "pump-operational-status";
policyStatus.className = "muted";
$("#current-state").closest("div").after(policyStatus);
document.addEventListener("profiles-ready", showPumpPolicy);
$("#scrubber").addEventListener("input", showPumpPolicy);
document.addEventListener("observation-rendered", () => {
  showPumpPolicy();
  const assessment = pumpAssessment();
  $("#decision-brief .diagnosis-title").textContent = assessment.reason;
  $("#decision-brief .diagnosis-status").textContent = assessment.status;
  $("#timeline-caption").textContent = state.showTruth
    ? "Retrospective labels shown through the replay clock · x-axis: sample index"
    : "Observed history only · retrospective labels hidden · x-axis: sample index";
});
async function showOperationsEvidence() {
  const panel = document.createElement("article");
  panel.className = "panel fleet-panel";
  panel.innerHTML = "<h2>Pump alert policy and drift</h2><p>Loading comparison…</p>";
  $("#evidence").append(panel);
  try {
    const report = await api("/api/operations/evidence");
    const rows = Object.entries(report.policies)
      .map(
        ([name, row]) =>
          `<tr><th scope="row">${esc(name)}</th><td>${row.hits}/${row.events}</td><td>${row.alerts}</td>
       <td>${fmt(row.false_events_per_observed_hour, 1)}</td><td>${pct(row.false_alarm_fraction_of_normal_time)}</td><td>${pct(row.alert_occupancy)}</td><td>${row.median_delay_seconds === null ? "Unavailable" : fmt(row.median_delay_seconds, 1)}</td></tr>`,
      )
      .join("");
    const drift = report.run_drift
      .map(
        (run) =>
          `<tr><th scope="row">${esc(run.run)}</th><td>${esc(run.role)}</td><td>${fmt(run.median_normal_ratio, 2)}×</td><td>${pct(run.normal_raw_alert_rate)}</td></tr>`,
      )
      .join("");
    const drivers = Object.entries(report.normal_alert_driver_counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([name, count]) => `${esc(name)} (${count})`)
      .join(", ");
    panel.innerHTML = `<h2>Pump alert policy and drift</h2><p>${esc(report.protocol)}</p>
      <p>${fmt(report.observed_hours, 2)} observed test hours. Grouping changes operational events while the raw pointwise scores stay the same.</p>
      <div class="operations-table"><table><thead><tr><th>Policy</th><th>Events caught</th><th>Alerts</th><th>Unmatched alerts / observed hour</th><th>Normal time in alarm</th><th>All-time occupancy</th><th>Detected-event median delay (s)</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p>Missing intervals above 1.5 seconds reset the grouped policy and are excluded from time occupancy. On ${report.common_event_delays.count} commonly detected events, median delay: raw ${fmt(report.common_event_delays.raw_median_s, 1)} s; grouped ${fmt(report.common_event_delays.grouped_median_s, 1)} s. ${report.common_event_delays.excluded} events excluded from this paired comparison. Overlap counts do not establish early warning.</p>
      <details><summary>Every labelled event, including misses</summary><div class="operations-table"><table><thead><tr><th>Run</th><th>Start sample</th><th>Raw delay (s)</th><th>Grouped delay (s)</th></tr></thead><tbody>${report.events.map((e) => `<tr><td>${esc(e.run)}</td><td>${e.start_sample}</td><td>${e.raw_delay_s === null ? "Missed" : fmt(e.raw_delay_s, 1)}</td><td>${e.grouped_delay_s === null ? "Missed" : fmt(e.grouped_delay_s, 1)}</td></tr>`).join("")}</tbody></table></div></details>
      <p>Most common top residuals among normal samples flagged in test: ${drivers}.</p>
      <details><summary>Normal-score drift by run</summary><div class="operations-table"><table><thead><tr><th>Run</th><th>Split</th><th>Median normal score</th><th>Normal raw alert rate</th></tr></thead><tbody>${drift}</tbody></table></div></details>`;
  } catch {
    panel.querySelector("p").textContent =
      "Comparison unavailable. Restart LineGuard and try again.";
  }
}

function forecastReliability() {
  if (!state.forecast || $("#forecast-reliability")) return;
  const rows = state.forecast.engine_predictions;
  const errors = rows.map((row) => row.predicted_rul - row.actual_rul);
  const max = Math.max(...rows.map((row) => Math.max(row.actual_rul, row.predicted_rul)));
  const x = (value) => 30 + (value / max) * 360;
  const y = (value) => 220 - (value / max) * 200;
  const points = rows
    .map(
      (row) =>
        `<circle cx="${x(row.actual_rul)}" cy="${y(row.predicted_rul)}" r="3" fill="#79e5c3" opacity=".65"><title>Engine ${row.engine_id}: actual ${row.actual_rul}, predicted ${fmt(row.predicted_rul, 1)}</title></circle>`,
    )
    .join("");
  const bands = [
    [0, 30],
    [31, 60],
    [61, 125],
    [126, Infinity],
  ]
    .map(([low, high]) => {
      const values = errors
        .filter((_, i) => rows[i].actual_rul >= low && rows[i].actual_rul <= high)
        .map(Math.abs);
      const label = Number.isFinite(high) ? `${low}–${high}` : `${low}+`;
      return `<li><span>${label} actual cycles <small>${values.length} engines</small></span><b>${values.length ? fmt(values.reduce((a, b) => a + b, 0) / values.length, 1) + " cycles MAE" : "No examples"}</b></li>`;
    })
    .join("");
  const worst = rows
    .map((row, i) => ({ ...row, error: Math.abs(errors[i]) }))
    .sort((a, b) => b.error - a.error)
    .slice(0, 3)
    .map(
      (row) =>
        `<li><button class="pill-button" data-error-engine="${row.engine_id}">TF–${row.engine_id}</button><b>${fmt(row.error, 1)} cycles abs. error</b></li>`,
    )
    .join("");
  const distribution = [
    [0, 10],
    [10, 20],
    [20, 40],
    [40, Infinity],
  ]
    .map(([low, high]) => {
      const count = errors.filter(
        (error) => Math.abs(error) >= low && Math.abs(error) < high,
      ).length;
      return `<li><span>${Number.isFinite(high) ? low + " to &lt;" + high : low + "+"} cycles</span><b>${count} engines</b></li>`;
    })
    .join("");
  const panel = document.createElement("article");
  panel.id = "forecast-reliability";
  panel.className = "panel fleet-panel";
  panel.innerHTML = `<div class="eyebrow">FORECAST RELIABILITY</div><h2>Predicted vs actual remaining life</h2><p class="muted fine">Official simulated test endpoints. Training targets are capped at 125 cycles.</p>
    <svg class="reliability-chart" viewBox="0 0 420 248" role="img" aria-label="Predicted versus actual remaining cycles, with an equality line">
    <path d="M30 20V220H390" stroke="#2f4658" fill="none"/><path d="M30 220L390 20" stroke="#657c8c" stroke-dasharray="4 4" fill="none"/>${points}${[
      150,
    ]
      .filter((v) => v <= max)
      .map(
        (v) =>
          `<text x="${x(v)}" y="233" class="axis-label" text-anchor="middle">${v}</text><text x="25" y="${y(v) + 3}" class="axis-label" text-anchor="end">${v}</text>`,
      )
      .join("")}
    <text x="220" y="244" class="axis-label" text-anchor="middle">ACTUAL CYCLES →</text><text x="32" y="12" class="axis-label">PREDICTED CYCLES ↑</text></svg>
    <p class="muted fine">${errors.filter((value) => value > 0).length} overpredictions · ${errors.filter((value) => value < 0).length} underpredictions.</p>
    <div class="fleet-grid"><div><h3>Error by actual life</h3><ul class="stat-rows">${bands}</ul><h3>Largest errors</h3><ul class="stat-rows">${worst}</ul></div>
    <div><h3>Absolute-error distribution</h3><ul class="stat-rows">${distribution}</ul></div></div>`;
  $("#forecast").append(panel);
  panel.onclick = (event) => {
    const hit = event.target.closest("[data-error-engine]");
    if (hit) selectEngine(Number(hit.dataset.errorEngine));
  };
}
document.addEventListener("profiles-ready", forecastReliability);
forecastReliability();
showOperationsEvidence();

function pumpAssessment() {
  if (state.pumpLoading) return { status: "Loading", reason: "Loading pump evidence." };
  if (state.pumpError)
    return { status: "Unavailable", reason: "Reload pump evidence before acting." };
  return (
    state.trace?.points[state.index]?.assessment || {
      status: "Unavailable",
      reason: "Load an observation.",
    }
  );
}
function engineAssessment() {
  if (state.engineLoading) return { status: "Loading", reason: "Loading engine evidence." };
  if (state.engineError)
    return { status: "Unavailable", reason: "Reload engine evidence before acting." };
  if (state.engine?.domain_warnings?.length)
    return {
      status: "Verify data",
      reason: "Verify equipment compatibility and sensor units before acting.",
    };
  const urgent = state.engine?.predicted_rul <= Number($("#rul-horizon").value);
  return {
    status: urgent ? "Inspect" : "Monitor",
    reason: urgent
      ? "Review the engine within the planning horizon."
      : "Review the estimate at the next scheduled inspection.",
  };
}
function syncAssessments() {
  $("#engine-decision").textContent = engineAssessment().reason;
  const assessment = pumpAssessment();
  const title = $("#decision-brief .diagnosis-title");
  if (title) title.textContent = assessment.reason;
  const status = $("#decision-brief .diagnosis-status");
  if (status) status.textContent = assessment.status;
  $$(".inspection-action").forEach(
    (button) =>
      (button.disabled = button.closest("#forecast")
        ? !!(state.engineLoading || state.engineError)
        : !!(state.pumpLoading || state.pumpError)),
  );
  fleetSummary();
}
document.addEventListener("profiles-ready", syncAssessments);
$("#rul-horizon").addEventListener("input", syncAssessments);

let engineTimer;
function stopEngineReplay() {
  clearInterval(engineTimer);
  engineTimer = null;
  if ($("#engine-play")) $("#engine-play").textContent = "Play engine replay";
}
function setEngineObservation(index) {
  const full = state.engineFull;
  if (!full || state.engineLoading) return;
  state.engineIndex = Math.max(0, Math.min(index, full.points.length - 1));
  const point = full.points[state.engineIndex];
  state.engine = {
    ...full,
    points: full.points.slice(0, state.engineIndex + 1),
    observed_cycles: point.cycle,
    predicted_rul: point.predicted_rul,
    actual_rul: point.actual_rul,
  };
  renderEngine();
  document.dispatchEvent(new Event("profiles-ready"));
}
document.addEventListener("profiles-ready", () => {
  if (!state.engineFull) return;
  $("#engine-scrubber").max = state.engineFull.points.length - 1;
  $("#engine-scrubber").value = state.engineIndex;
  $("#engine-clock").textContent =
    `Observed cycle ${state.engine.observed_cycles} / ${state.engineFull.observed_cycles}`;
});
$("#engine-scrubber").oninput = (event) => {
  stopEngineReplay();
  setEngineObservation(Number(event.target.value));
};
$("#engine-restart").onclick = () => {
  stopEngineReplay();
  setEngineObservation(0);
};
$("#engine-play").onclick = () => {
  if (engineTimer) return stopEngineReplay();
  if (!state.engineFull || state.engineLoading || state.engineError) return;
  if (state.engineIndex >= state.engineFull.points.length - 1) setEngineObservation(0);
  $("#engine-play").textContent = "Pause engine replay";
  engineTimer = setInterval(() => {
    setEngineObservation(state.engineIndex + 1);
    if (state.engineIndex >= state.engineFull.points.length - 1) stopEngineReplay();
  }, 250);
};
$$(".truth-toggle").forEach(
  (toggle) =>
    (toggle.onchange = (event) => {
      state.showTruth = event.target.checked;
      $$(".truth-toggle").forEach((item) => (item.checked = state.showTruth));
      renderCurrent();
      renderEngine();
      syncAssessments();
    }),
);
$("#engine-search").oninput = () => {
  renderHorizon();
  syncAssessments();
};
$("#task-filter").onchange = renderTasks;
$("#task-search").oninput = renderTasks;
