"use strict";
// Demo page: pick a bundled sample, start a run, poll it, show the summary and the report.
// All server text is written with textContent / attributes, never as markup.
(function () {
  const $ = (id) => document.getElementById(id);
  const samplesEl = $("samples"), go = $("go"), msg = $("msg"), steps = $("steps");
  const resultEl = $("result"), report = $("report"), limitsEl = $("limits");
  let chosen = null, timer = null;

  function say(text, isErr) {
    msg.textContent = text || "";
    msg.className = isErr ? "msg err" : "msg";
  }

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let body = null;
    try { body = await r.json(); } catch (e) { body = null; }
    if (!r.ok) {
      const d = body && body.detail;
      throw new Error(typeof d === "string" ? d : "request failed (" + r.status + ")");
    }
    return body;
  }

  function pick(card, key) {
    chosen = key;
    for (const c of samplesEl.children) c.setAttribute("aria-checked", String(c === card));
    go.disabled = false;
  }

  function renderSamples(list) {
    samplesEl.textContent = "";
    for (const s of list) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "sample"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", "false");
      const t = document.createElement("b"); t.textContent = s.title;
      const d = document.createElement("span");
      d.textContent = s.blurb + " (" + s.rows + " rows, " + s.task_type + ", " + s.metric + ")";
      b.append(t, d);
      b.addEventListener("click", () => pick(b, s.key));
      samplesEl.append(b);
    }
    if (!list.length) say("No samples are installed on this server.", true);
  }

  function showResult(st) {
    resultEl.textContent = "";
    const dl = document.createElement("dl");
    const s = st.summary || {};
    const rows = [
      ["Status", st.status + (s.status && s.status !== st.status ? " (" + s.status + ")" : "")],
      ["Chosen model", s.chosen_family || "none"],
      ["Validation score", s.val_score == null ? "n/a" : Number(s.val_score).toFixed(4)],
      ["Reviewer verdict", s.review || "n/a"],
      ["Steps", s.n_steps == null ? "n/a" : String(s.n_steps)],
      ["Wall time", s.latency_s == null ? "n/a" : Number(s.latency_s).toFixed(1) + " s"],
    ];
    if (s.dropped && s.dropped.length) rows.push(["Columns dropped for leakage", s.dropped.join(", ")]);
    for (const [k, v] of rows) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }
    resultEl.append(dl);
    resultEl.hidden = false;
    if (s.has_report) {
      report.src = "/demo/api/runs/" + encodeURIComponent(st.run_id) + "/report";
      report.hidden = false;
    }
  }

  async function poll(runId) {
    try {
      const st = await api("/demo/api/runs/" + encodeURIComponent(runId));
      if (st.status === "queued") {
        say("Queued, position " + st.queue_position + ".");
      } else if (st.status === "running") {
        say("Running. The agent is profiling, checking leakage, training and reviewing...");
      } else {
        go.disabled = false;
        if (st.status === "done") { say("Finished."); showResult(st); }
        else { say(st.message || "The run did not finish.", true); }
        return;
      }
    } catch (e) {
      say(e.message, true);
    }
    timer = setTimeout(() => poll(runId), 1500);
  }

  go.addEventListener("click", async () => {
    if (!chosen) return;
    clearTimeout(timer);
    go.disabled = true; resultEl.hidden = true; report.hidden = true; steps.hidden = true;
    say("Submitting...");
    try {
      const r = await api("/demo/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample: chosen }),
      });
      poll(r.run_id);
    } catch (e) {
      say(e.message, true);
      go.disabled = false;
    }
  });

  api("/demo/api/info").then((info) => {
    renderSamples(info.samples || []);
    const l = info.limits || {};
    limitsEl.textContent = "Limits: " + l.max_wall_s + " s per run, " + l.flaml_s +
      " s AutoML, " + l.ip_runs + " runs per " + Math.round(l.ip_window_s / 60) +
      " minutes per address, queue of " + l.queue_max + ".";
  }).catch((e) => say(e.message, true));
})();
