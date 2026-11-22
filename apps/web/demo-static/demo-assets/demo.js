"use strict";
// Landing page: dataset cards, the dataset picker dialog, starting a run. Server text is only ever
// written with textContent / attributes, never as markup.
(function () {
  const $ = (id) => document.getElementById(id);
  const dlg = $("picker"), dgrid = $("dgrid"), cards = $("cards"), perr = $("pk-err");
  let samples = [], runtimes = {}, busy = false, maxWall = 60;
  try { runtimes = JSON.parse($("runtimes").dataset.v) || {}; } catch (e) { runtimes = {}; }

  function h(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }
  function kb(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function kind(s) { return s.task_kind === "regression" ? "Regression" : "Classification"; }
  function runtime(s) {
    return runtimes[s.key] ? "about " + Math.round(runtimes[s.key]) + " s here (measured)" : "capped at " + maxWall + " s";
  }
  function say(text) { perr.textContent = text || ""; $("limits").classList.toggle("err", !!text); if (text) $("limits").textContent = text; }

  const API = (window.JMD_API || "").replace(/\/$/, "");  // "" = same origin
  const CAP_MS = 240000;  // measured: wake ~35 s + warm-up run ~2.5 min after idle (docs/ws/R.md)

  async function api(path, opts) {
    const r = await fetch(API + path, opts);
    let body = null;
    try { body = await r.json(); } catch (e) { body = null; }
    if (!r.ok) {
      const d = body && body.detail;
      const err = new Error(typeof d === "string" ? d : "request failed (" + r.status + ")");
      err.warming = r.status === 503 && body && body.status === "warming_up";
      throw err;
    }
    return body;
  }

  const hero = document.getElementById("hero");
  const dev = document.querySelector("#hero .jd");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  // Server status: poll /health (never loads anything) until the run worker is ready.
  const sp = $("sp"), spT = $("sp-t"), spRetry = $("sp-retry");
  let ready = false, pending = null, t0 = Date.now();
  function status(state, text) { sp.dataset.state = state; spT.textContent = text; spRetry.hidden = state !== "slow"; }
  function runButtons() { return document.querySelectorAll("[data-sample], .card .btn.pri, .ds .btn.pri"); }
  function markButtons() {
    for (const b of runButtons()) {
      b.classList.toggle("wait", !ready);
      if (ready) { b.removeAttribute("aria-disabled"); b.removeAttribute("title"); }
      else { b.setAttribute("aria-disabled", "true"); b.title = "Starts as soon as the server is ready"; }
    }
  }
  async function probe() {
    if (ready) return;
    try {
      const r = await fetch(API + "/health", { cache: "no-store", signal: AbortSignal.timeout(60000) });
      const d = await r.json();
      if (r.ok && d.model_loaded !== false) { ready = true; status("ready", "Ready"); markButtons(); if (pending) start(pending.key, pending.btn, true); return; }
    } catch (e) { /* asleep or waking: keep polling */ }
    if (Date.now() - t0 > CAP_MS) { status("slow", "The server is slow to wake up."); return; }
    setTimeout(probe, 3000);
  }
  spRetry.addEventListener("click", () => { t0 = Date.now(); status("waking", "Waking up the server… (can take about 3 min on the free plan)"); probe(); });

  async function start(key, btn, fromQueue) {
    if (busy && !fromQueue) return;
    say("");
    const s = samples.find((x) => x.key === key);
    const nm = s ? (s.name || s.title) : key;
    const tpl = (window.JrAvatar && window.JrAvatar.data.listening) || "On it! Opening the {name} data now.";
    if (dlg.open) dlg.close();
    if (hero) hero.scrollIntoView({ block: "center" });
    if (!ready) {  // queue it: sent by probe() the moment the server is ready
      pending = { key, btn };
      if (dev && dev.jr) { dev.jr.state("listening"); dev.jr.say("Got it: " + nm + ". I'll start as soon as the server is awake."); }
      return;
    }
    busy = true; pending = null; if (btn) btn.disabled = true;
    if (dev && dev.jr) { dev.jr.state("listening"); dev.jr.say(tpl.replace("{name}", nm)); }
    const post = async () => {
      for (let delay = 2000, t = Date.now(); ; delay = Math.min(delay * 2, 15000)) {
        try {
          return await api("/demo/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample: key }) });
        } catch (e) {
          if (!e.warming || Date.now() - t > CAP_MS) throw e;
          status("waking", "The run worker is still warming up…");
          await wait(delay);
        }
      }
    };
    try {
      const [r] = await Promise.all([post(), wait(1300)]);  // let the listening pose play before the page changes
      location.href = "/runs/" + encodeURIComponent(r.run_id);
    } catch (e) {
      say(e.message); busy = false; if (btn) btn.disabled = false;
      if (dev && dev.jr) { dev.jr.state("error"); dev.jr.say(e.message); }
    }
  }

  function card(s) {
    const c = h("div", "card");
    c.append(h("span", "k", kind(s)), h("h3", null, s.name || s.title), h("p", null, s.predicts || s.blurb));
    c.append(h("div", "meta", s.rows + " rows × " + s.cols + " columns · " + kb(s.bytes) + " · " + runtime(s)));
    const row = h("div", "row2"); row.style.marginTop = "16px";
    const run = h("button", "btn pri sm", s.action || "Run the agent on this"); run.type = "button";
    run.addEventListener("click", () => start(s.key, run));
    const view = h("button", "btn gho sm", "Preview data"); view.type = "button";
    view.addEventListener("click", () => openPicker());
    row.append(run, view); c.append(row);
    return c;
  }

  function previewTable(s) {
    const wrap = h("div", "pv"), t = h("table"), thead = h("thead"), tr = h("tr");
    for (const col of s.preview.columns) {
      const th = h("th", null, col.label);
      if (col.label !== col.raw) th.append(h("i", null, col.raw));
      tr.append(th);
    }
    thead.append(tr); t.append(thead);
    const tb = h("tbody");
    for (const r of s.preview.rows) {
      const row = h("tr");
      for (const v of r) row.append(h("td", null, v));
      tb.append(row);
    }
    t.append(tb); wrap.append(t);
    return wrap;
  }

  function dsCard(s) {
    const c = h("div", "ds");
    c.append(h("span", "tag", kind(s) + " · predicts " + (s.target_label || s.target)));
    c.append(h("h3", null, s.name || s.title), h("p", null, s.predicts));
    c.append(h("div", "meta", s.rows + " × " + s.cols + " · " + kb(s.bytes) + " · "));
    const src = h("a", null, "OpenML dataset " + s.openml_id); src.href = s.openml_url; src.rel = "noopener"; src.target = "_blank";
    c.lastChild.append(src);
    c.append(previewTable(s));
    const sha = h("div", "sha"); sha.append(h("span", null, "SHA-256 " + s.sha12 + "…"));
    const cp = h("button", null, "copy"); cp.type = "button"; cp.setAttribute("aria-label", "Copy the full SHA-256");
    cp.addEventListener("click", () => {
      const done = () => { cp.textContent = "copied"; setTimeout(() => { cp.textContent = "copy"; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(s.sha256).then(done, () => {});
    });
    sha.append(cp); c.append(sha);
    const row = h("div", "row2");
    const run = h("button", "btn pri sm", s.action || "Run the agent on this"); run.type = "button";
    run.addEventListener("click", () => start(s.key, run));
    const dl = h("a", "btn gho sm", "Download CSV"); dl.href = (s.download || "").startsWith("/") ? API + s.download : s.download; dl.setAttribute("download", s.key + ".csv");
    row.append(run, dl); c.append(row);
    return c;
  }

  function openPicker() {
    if (!samples.length) { say("No datasets are installed on this server."); return; }
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }

  for (const b of document.querySelectorAll("[data-open-picker]")) b.addEventListener("click", openPicker);
  for (const b of document.querySelectorAll("[data-sample]")) b.addEventListener("click", () => start(b.dataset.sample, b));
  $("pk-x").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  function show(info) {
    samples = info.samples || [];
    const l = info.limits || {};
    maxWall = l.max_wall_s || maxWall;
    cards.textContent = ""; dgrid.textContent = "";
    for (const s of samples) { cards.append(card(s)); dgrid.append(dsCard(s)); }
    const d = samples.find((s) => s.key === "diabetes");
    if (d) $("cap-profile").textContent = d.rows + " rows · " + d.cols + " cols";
    $("limits").textContent = "Limits: " + l.max_wall_s + " s per run, " + l.ip_runs + " runs per " +
      Math.round(l.ip_window_s / 60) + " minutes per address, a queue of " + l.queue_max + ".";
    markButtons();
  }

  let built = null;  // the static frontend ships /demo/api/info, so the page works before the backend wakes
  try { built = JSON.parse($("info").dataset.v || "null"); } catch (e) { built = null; }
  if (built) show(built);
  probe();
  api("/demo/api/info").then(show).catch((e) => { if (!built) say(e.message); });
})();
