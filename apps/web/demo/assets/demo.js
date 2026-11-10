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

  const hero = document.getElementById("hero");
  const dev = document.querySelector("#hero .jd");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function start(key, btn) {
    if (busy) return;
    busy = true; if (btn) btn.disabled = true; say("");
    const s = samples.find((x) => x.key === key);
    const nm = s ? (s.name || s.title) : key;
    const tpl = (window.JrAvatar && window.JrAvatar.data.listening) || "On it! Opening the {name} data now.";
    if (dlg.open) dlg.close();
    if (hero) hero.scrollIntoView({ block: "center" });
    if (dev && dev.jr) { dev.jr.state("listening"); dev.jr.say(tpl.replace("{name}", nm)); }
    try {
      const [r] = await Promise.all([
        api("/demo/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample: key }) }),
        wait(1300),  // let the listening pose play before the page changes
      ]);
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
    const dl = h("a", "btn gho sm", "Download CSV"); dl.href = s.download; dl.setAttribute("download", s.key + ".csv");
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

  api("/demo/api/info").then((info) => {
    samples = info.samples || [];
    const l = info.limits || {};
    maxWall = l.max_wall_s || maxWall;
    cards.textContent = ""; dgrid.textContent = "";
    for (const s of samples) { cards.append(card(s)); dgrid.append(dsCard(s)); }
    const d = samples.find((s) => s.key === "diabetes");
    if (d) $("cap-profile").textContent = d.rows + " rows · " + d.cols + " cols";
    $("limits").textContent = "Limits: " + l.max_wall_s + " s per run, " + l.ip_runs + " runs per " +
      Math.round(l.ip_window_s / 60) + " minutes per address, a queue of " + l.queue_max + ".";
  }).catch((e) => say(e.message));
})();
