"use strict";

// "i" buttons: plain-language explanations for every section, tile and control.
// Headings are matched by their visible text, so panels rendered later by JavaScript get help too.

const helpTopics = {
  // ---------- Fleet overview ----------
  "Fleet overview":
    "Your starting point. It shows which machines need attention soon, suggests which engines to inspect first, and keeps the inspection tasks you save.",
  "Guided walkthrough":
    "One-click demos. 'Engine approaching inspection' opens the engine closest to failure. 'Pump relationship anomaly' opens a real recorded pump fault. 'Injected sensor flatline' shows a broken sensor rather than a broken machine. 'Reset replay' puts everything back to the start (your saved tasks are kept).",
  "Pump P–01":
    "Current status of the water pump. Its data is a real recording from a pump test rig (the SKAB dataset). The model flags moments when the pump's sensors stop behaving the way they normally do together.",
  Turbofan:
    "Current status of the selected jet engine. The data is NASA's simulated engine dataset. The model estimates how many operating cycles (roughly, flights) remain before the engine fails.",
  "Inspection capacity":
    "Type how many inspections your team can do. LineGuard lists that many engines, most urgent first (shortest predicted remaining life). Engines that already have an open task are skipped. Click an engine to open its forecast.",
  "Maintenance tasks":
    "Inspections you have saved. Each task moves from Open → Acknowledged → Completed (or Cancelled with a reason). Download the report to keep the sensor readings and model version that justified the decision.",
  "Save an inspection task":
    "Save this observation as an inspection task. The readings, model version and timestamp are stored with it so the decision can be audited later. Add notes on what the technician should check.",

  // ---------- Failure forecast lab ----------
  "A forecast. Before failure.":
    "Predicts how much life an engine has left, called Remaining Useful Life (RUL), from its sensor readings so far. Life is counted in cycles: one cycle is one operating run of the engine. The model only ever sees past readings, never the future.",
  "The degradation trajectory":
    "How the prediction changed over the engine's life. The green line is the predicted cycles left at each moment; the shaded band is the 90% range. Press Play to watch it update cycle by cycle. 'Show benchmark hindsight' adds the true answer in amber, for checking only; the model never sees it.",
  "Why this forecast?":
    "Which sensors are pulling the prediction down. For each sensor we swap its readings for those of a healthy engine and re-run the model. A bar of −19 means 'if this sensor looked healthy, the engine would be predicted to last 19 cycles longer'. It shows where an engineer should look first. It explains the model, not the physical root cause.",
  "How soon would you inspect?":
    "Choose a planning window, e.g. 'inspect any engine predicted to fail within 30 cycles'. The boxes show what that rule would have done on 100 test engines. True positives: failing engines caught. False positives: healthy engines flagged by mistake. Missed positives: failing engines not caught. True negatives: healthy engines correctly left alone.",
  "Unseen engines. Real evaluation.":
    "How the model was chosen fairly. Three candidate models were compared on engines held out from training (5-fold cross-validation, splitting by whole engine). The one with the smallest average error (MAE) won. Only then was it tested once on NASA's official test engines.",
  "100 engines. One endpoint each.":
    "Every one of NASA's 100 official test engines. Each row compares our prediction at the engine's last recorded cycle with the true remaining life NASA published. 'Absolute error' is the gap. Click a row to open that engine.",
  "Predicted vs actual remaining life":
    "Each dot is one test engine: true remaining life across, our prediction up. Dots on the dashed diagonal are perfect predictions. The model is most accurate for engines close to failure, which is when accuracy matters most.",
  "Error by actual life":
    "Average error grouped by how close the engine really was to failure. Errors are small (about 2 cycles) for engines near failure and larger for healthy engines, whose end of life is still far away and harder to know.",
  "Largest errors":
    "The three engines the model got most wrong, shown openly. Click one to inspect it.",
  "Absolute-error distribution":
    "How many of the 100 test engines fall within each error range. Most predictions are within 10 cycles of the truth.",

  // ---------- Business impact ----------
  "Fewer failures. Less wasted life.":
    "Does predicting failures actually save money? We replay 40 engines (never used for tuning) from new until failure under three strategies: wait until it breaks, replace on a fixed schedule, or replace when LineGuard predicts failure is near. Then we count breakdowns, wasted part life and cost.",
  "Price your own plant":
    "Your assumptions. Cost ratio: how many times more a breakdown costs than a planned repair (10:1 means a breakdown costs as much as 10 planned jobs). Lead time: how many cycles it takes to arrange maintenance after an alert. The checkbox uses the cautious end of the forecast range.",
  "Three policies, one bill":
    "Total cost per 1,000 operating cycles for each strategy (lower is better). Run to failure: fix it only when it breaks. Best fixed interval: replace every N cycles, with N chosen as well as possible. LineGuard predictive: replace when the forecast says failure is close.",
  "When each policy acts":
    "One row per engine, sorted by when it actually failed. The grey bar is the engine's life. The orange line is when the fixed schedule replaces it (often far too early). The green dot is when LineGuard acts. A red cross would mean a breakdown happened before maintenance.",

  // ---------- Command center (pump) ----------
  "Know what changed.":
    "Live-style monitoring of a water pump with 8 sensors (vibration, current, temperature, pressure, flow, voltage). The model learns how the sensors normally move together and raises an alert when that relationship breaks, which is often the first sign of a fault.",
  "Anomaly timeline":
    "The anomaly score over time. 1.0× is the alert threshold: above the dashed line means the sensors are behaving unusually. Press Play to replay the recording, or drag the slider. A 'grouped alert' needs several unusual readings in a row, which reduces noisy one-off alarms.",
  "Decision brief":
    "The suggested next step for the moment shown: keep monitoring, inspect the machine, or check the sensor first (a stuck or jumping reading usually means the sensor itself is faulty). It is advice; a person makes the decision.",
  "Cross-sensor evidence":
    "Which sensors look wrong right now. For each sensor the model predicts what it should read from the other seven, then compares that with what it actually reads. A bigger bar means a bigger gap. 4.1× means the gap is about four times its normal size.",
  "Record operator decision":
    "Record what you concluded about this moment: real fault, false alarm, sensor issue or needs investigation, plus a note. Decisions are saved on this computer and listed under Operator feedback. They never silently change the model.",

  // ---------- Model evidence ----------
  "Evidence, not promises.":
    "Proof of how well the models work, including where they fail. All numbers come from data the models never trained on.",
  "Three models. The same test runs.":
    "Our pump detector (cross-sensor residual) compared with two simpler methods on the same 7 recordings. Event recall: share of real faults caught. Event precision: share of alarms that were real faults. Normal FPR: how often it alarms when nothing is wrong. Delay: how quickly it caught faults.",
  "The data contract":
    "How the pump data was split to keep the test honest: the earliest recordings for training, the next ones for setting the alarm threshold, and the latest ones only for the final test. No test data was used to build or tune the model.",
  "Sensor-fault stress tests":
    "We deliberately broke sensors in clean data (a sudden spike, a slow drift, a frozen 'flatline' reading) to see whether LineGuard notices and whether it correctly blames the sensor rather than the machine.",
  "If a signal disappears":
    "What happens if one sensor is lost. We replace each sensor in turn with an average value and measure how many faults are still caught. It shows which sensors the detector relies on most.",
  "Generalisation: all four NASA C-MAPSS subsets":
    "NASA's engine benchmark has four datasets of increasing difficulty (more operating conditions and fault types). We ran the same method, unchanged, on all four to show it is not tuned to one dataset. RMSE is the error in cycles (lower is better).",
  "Regime normalisation ablation":
    "In the harder datasets engines run under six different flight conditions, which shift the sensor readings. Normalising readings per condition before modelling roughly halves the error, as shown here.",
  "Literature context · RMSE":
    "Errors reported by published research models (deep learning and others) on the same NASA datasets, for context. Papers use slightly different evaluation rules, so this is a rough comparison, not a leaderboard.",
  "Pump alert policy and drift":
    "Raw alerts fire on every unusual reading; grouped alerts wait for several in a row. Grouping cuts noisy alarms a lot but catches faults a little later and can miss short ones. This panel shows that trade-off honestly.",

  // ---------- Operator feedback ----------
  "Decisions become evidence.":
    "Every decision an operator recorded on pump alerts, newest first. This is the human-in-the-loop record: it is kept for review and future retraining, not used automatically.",
};

const metricHelp = {
  "forecast-mae":
    "Mean Absolute Error: on average, how many cycles our prediction is off by, measured on 100 engines the model never saw. Lower is better.",
  "forecast-rmse":
    "Root Mean Squared Error: like MAE but big misses count extra, so it rewards models that avoid large mistakes. Lower is better.",
  "baseline-mae":
    "A simple guess for comparison: 'a typical engine lasts X cycles, so this one has X minus its age left'. Any useful model must beat this.",
  "forecast-nasa":
    "NASA's official scoring rule for this benchmark. It punishes late predictions (saying an engine is fine when it is about to fail) much more than early ones, because those cause breakdowns. Lower is better.",
  "forecast-gain":
    "How much smaller our average error is than the simple age-based guess. 67% means our predictions are about three times closer to the truth.",
  "event-recall":
    "Share of real recorded pump faults the detector caught (here 6 of 7), on recordings it never trained on.",
  "delay-stat":
    "Typical time between a fault starting and LineGuard raising the alarm, for the faults it caught.",
  "fpr-stat":
    "How often the detector alarms when the pump is actually normal. It was tuned for 1%, but later recordings ran under slightly different conditions and it rose to 14%. We show this weakness openly.",
  "kpi-savings":
    "Cost of LineGuard's predictive maintenance compared with the best fixed replacement schedule. Negative means LineGuard is cheaper.",
  "kpi-failures":
    "How many of the 40 engines broke down before maintenance happened, for LineGuard (and, in the note, for the other strategies).",
  "kpi-util":
    "How much of each engine's possible life was used before replacement. Higher means fewer good parts thrown away.",
  "kpi-waste":
    "Average number of cycles of life left unused when an engine was replaced. Lower means less waste.",
  "engine-title":
    "The big number is the predicted cycles of life left for this engine at the replay position. The 90% interval is the range the true value should fall in 9 times out of 10 (it did so 97% of the time on the test set).",
};

// Extra anchors that are not headings or KPI tiles.
const anchorHelp = [
  {
    selector: "#fleet-counts",
    title: "Fleet summary",
    text: "How many of the 100 test engines are predicted to fail within the planning window, how many inspection tasks are open, how many engines qualify for inspection and how many don't fit in your inspection slots.",
  },
  {
    selector: "#monitor .stream-toolbar .eyebrow",
    title: "Choose what to replay",
    text: "The first menu picks a scenario. Recorded pump anomaly: a real recorded fault. Recorded normal samples: normal operation. Simulated flow / load shift: a genuine-looking change in operation. Flatline, spike, drift: a sensor artificially broken (frozen, sudden jump, slow creep) to test sensor-fault detection. The second menu picks one of the 7 held-out recordings. Upload your own CSV with 'Import sensor stream'.",
  },
  {
    selector: "#signal-cards",
    title: "Sensor readings",
    text: "The 8 pump sensor values at the current replay moment, with units.",
    before: true,
  },
];

const helpDialog = document.createElement("dialog");
helpDialog.className = "feature-help-dialog";
helpDialog.setAttribute("aria-labelledby", "feature-help-title");
helpDialog.innerHTML =
  '<form method="dialog"><h2 id="feature-help-title"></h2><p></p><button class="button primary">Got it</button></form>';
document.body.append(helpDialog);
helpDialog.addEventListener("click", (event) => {
  if (event.target === helpDialog) helpDialog.close(); // click outside closes
});

function makeHelpButton(title, explanation) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "feature-help";
  button.textContent = "i";
  button.setAttribute("aria-label", "About " + title);
  button.setAttribute("aria-haspopup", "dialog");
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    helpDialog.querySelector("h2").textContent = title;
    helpDialog.querySelector("p").textContent = explanation;
    helpDialog.showModal();
  });
  return button;
}

function addFeatureHelp(anchor, title, explanation) {
  if (!anchor || anchor.querySelector(":scope > .feature-help")) return;
  anchor.append(" ", makeHelpButton(title, explanation));
}

function installFeatureHelp() {
  document
    .querySelectorAll("main h1, main h2, main h3, #task-title, #feedback-dialog h2")
    .forEach((heading) => {
      const title = heading.textContent.replace(/\s*i$/, "").trim();
      const explanation = helpTopics[title] || metricHelp[heading.id];
      if (explanation)
        addFeatureHelp(
          heading,
          heading.id === "engine-title" ? "Engine forecast" : title,
          explanation,
        );
    });
  Object.entries(metricHelp).forEach(([id, explanation]) => {
    const card = document.getElementById(id)?.closest(".stat");
    if (!card) return;
    const label = card.querySelector("div");
    if (label) addFeatureHelp(label, label.firstChild.textContent.trim(), explanation);
  });
  anchorHelp.forEach(({ selector, title, text, before }) => {
    const el = document.querySelector(selector);
    if (!el) return;
    if (before) {
      if (el.previousElementSibling?.classList.contains("help-row")) return;
      const row = document.createElement("div");
      row.className = "help-row";
      row.append(title + " ", makeHelpButton(title, text));
      el.before(row);
    } else addFeatureHelp(el, title, text);
  });
}

installFeatureHelp();
document.addEventListener("profiles-ready", installFeatureHelp);
const helpObserver = new MutationObserver(() => {
  helpObserver.disconnect();
  installFeatureHelp();
  observeHelpTargets();
});
function observeHelpTargets() {
  for (const id of ["evidence", "forecast", "fleet", "impact"]) {
    const section = document.getElementById(id);
    if (section) helpObserver.observe(section, { childList: true, subtree: true });
  }
}
observeHelpTargets();
