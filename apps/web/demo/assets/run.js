"use strict";
// Live run page: polls the run status every second and draws the rail, leaderboard, log and result.
// Server text is only ever written with textContent / attributes, never as markup.
(function () {
  const $ = (id) => document.getElementById(id);
  const runId = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
  const STAGES = ["Profile", "Leakage", "Train", "Compare", "Review", "Explain"];
  const STAGE_OF = {
    profile_dataset: 0, detect_leakage: 1, decide_leakage: 1, train_model: 2, tune_model: 2,
    compare_models: 3, review: 4, refit_full: 5, predict: 5, explain_model: 5, report: 5,
  };
  const HIGHER = { roc_auc: 1, pr_auc: 1, f1_macro: 1 };
  const rail = $("rail"), lb = $("lb"), logEl = $("log"), errEl = $("err");
  const pills = STAGES.map((n) => { const p = document.createElement("span"); p.className = "st"; p.textContent = n; rail.append(p); return p; });
  const layers = Array.from(document.querySelectorAll(".ly"));
  const rows = new Map(), tuned = new Set(), seen = new Set();
  let info = null, t0 = Date.now(), timer = null, finalSecs = null;

  function h(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = text; return el; }
  function mmss(s) { s = Math.max(0, Math.round(s)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); }
  function tick() { $("timer").textContent = mmss(finalSecs != null ? finalSecs : (Date.now() - t0) / 1000); }
  timer = setInterval(tick, 500); tick();

  function paintRail(prog, status) {
    const last = prog && prog.last_step in STAGE_OF ? STAGE_OF[prog.last_step] : -1;
    const done = status === "done";
    pills.forEach((p, i) => {
      const state = done || i < last ? "done" : (i === last ? "cur" : "");
      p.className = "st" + (state ? " " + state : "");
      p.textContent = STAGES[i] + (i === 1 && prog && prog.leakage_skipped ? " (skipped)" : "");
    });
    layers.forEach((l, i) => l.classList.toggle("lit", done || i < last || (i === last && status !== "running")));
  }

  function paintBoard(models, metric) {
    if (!models || !models.length) return;
    const higher = !!HIGHER[metric];
    for (const m of models) { // the second model of a family is the tuned one
      if (tuned.has(m.model_id) || seen.has(m.model_id)) continue;
      seen.add(m.model_id);
      if (models.some((o) => o !== m && o.family === m.family && seen.has(o.model_id))) tuned.add(m.model_id);
    }
    const vals = models.map((m) => m.val_score);
    const top = Math.max(...vals), best = Math.min(...vals);
    const sorted = models.slice().sort((a, b) => (higher ? b.val_score - a.val_score : a.val_score - b.val_score));
    if (lb.querySelector(".dim")) lb.textContent = "";
    sorted.forEach((m, rank) => {
      let r = rows.get(m.model_id);
      if (!r) {
        const li = h("li"), name = h("span", null, (m.family || m.model_id) + (tuned.has(m.model_id) ? " (tuned)" : "")), bar = h("span", "bar"), fill = h("i"), val = h("span");
        bar.append(fill); li.append(name, bar, val); lb.append(li);
        r = { li, fill, val }; rows.set(m.model_id, r);
      }
      const frac = higher ? (top > 0 ? m.val_score / top : 0) : (m.val_score > 0 ? best / m.val_score : 0);
      requestAnimationFrame(() => { r.fill.style.width = Math.max(3, Math.round(frac * 100)) + "%"; });
      r.val.textContent = Number(m.val_score).toPrecision(4);
      r.li.className = rank === 0 ? "best" : "";
      r.li.style.order = rank;
    });
    lb.style.display = "flex"; lb.style.flexDirection = "column";
  }

  function paintLog(log) {
    if (!log) return;
    logEl.textContent = "";
    for (const e of log) {
      const d = h("div");
      d.append(h("span", "t", e.tool + (e.family ? " · " + e.family : "")), document.createTextNode("  " + (e.ok ? "" : "FAILED ") + e.s + " s  " + (e.reason || "")));
      logEl.append(d);
    }
  }

  function finish(st) {
    clearInterval(timer);
    if (st.started && st.finished) finalSecs = st.finished - st.started;
    tick();
    const res = $("res");
    if (st.status === "done" && st.result && st.result.sentence) {
      $("sentence").textContent = st.result.sentence;
      const s = st.summary || {};
      const kv = $("kv"); kv.textContent = "";
      const parts = [["model", s.chosen_family], ["reviewer", s.review], ["run time", s.latency_s != null ? Number(s.latency_s).toFixed(0) + " s" : null]];
      kv.textContent = parts.filter((p) => p[1] != null).map((p) => p[0] + ": " + p[1]).join("   ·   ");
      $("rep").href = "/demo/api/runs/" + encodeURIComponent(runId) + "/report";
      res.hidden = false;
    } else if (st.status === "done") {
      $("sentence").textContent = "The run finished without a scored model.";
      $("rep").href = "/demo/api/runs/" + encodeURIComponent(runId) + "/report";
      res.hidden = false;
    } else {
      errEl.textContent = st.message || "The run did not finish.";
    }
  }

  async function poll() {
    let st = null;
    try {
      const r = await fetch("/demo/api/runs/" + encodeURIComponent(runId));
      if (r.status === 404) { errEl.textContent = "This run is unknown or has expired."; clearInterval(timer); $("title").textContent = "Run not found"; return; }
      if (r.status === 429) { setTimeout(poll, 3000); return; }
      st = await r.json();
    } catch (e) { setTimeout(poll, 2000); return; }
    const sample = info && (info.samples || []).find((x) => x.key === st.sample);
    $("title").textContent = sample ? sample.name : st.sample;
    document.title = (sample ? sample.name : "Run") + " · Junior ML Dev";
    const prog = st.progress || null;
    if (st.status === "queued") $("sub").textContent = "Queued, position " + st.queue_position + ". One run executes at a time.";
    else if (st.status === "running") $("sub").textContent = "Running. The agent usually needs about a minute on this free CPU.";
    else if (st.status === "done") $("sub").textContent = "Finished. Run " + runId + " (keep this link; it is the only way back to it).";
    else $("sub").textContent = "Run " + runId;
    paintRail(prog, st.status);
    paintBoard(prog && prog.models, sample && sample.metric);
    paintLog(prog && prog.log);
    if (["done", "failed", "timeout", "interrupted"].includes(st.status)) { finish(st); return; }
    setTimeout(poll, 1000);
  }

  fetch("/demo/api/info").then((r) => r.json()).then((i) => { info = i; }, () => {}).finally(poll);
})();
