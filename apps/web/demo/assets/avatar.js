"use strict";
// The junior dev. Pose and words are set by the page from real events (a click, a polled run
// status); nothing here runs on a timer except cycling a tip when the avatar is clicked.
(function () {
  const STATES = ["idle", "listening", "working", "done", "error"];
  let data = { tips: [], greeting: "", cta: "" };
  const holder = document.getElementById("narr");
  try { data = JSON.parse(holder.dataset.v) || data; } catch (e) { /* defaults */ }

  function mount(root) {
    const bubble = root.querySelector(".jd-bubble");
    const say = root.querySelector(".jd-say");
    const cta = root.querySelector(".jd-cta");
    let tip = 0, last = "";
    const api = {
      root,
      state(s) {
        if (STATES.includes(s) && root.dataset.state !== s) root.dataset.state = s;
        if (s !== "working") root.dataset.sweat = "0";
      },
      sweat(on) { root.dataset.sweat = on ? "1" : "0"; },
      say(text, link) {
        if (!say) return;
        if (text !== last) {
          last = text;
          say.textContent = text;
          if (bubble) { bubble.classList.remove("pop"); void bubble.offsetWidth; bubble.classList.add("pop"); }
        }
        if (cta) {
          if (link) { cta.textContent = data.cta || "Open"; cta.href = link; cta.hidden = false; }
          else { cta.hidden = true; }
        }
      },
      tip() {
        if (!data.tips.length) return;
        api.say(data.tips[tip % data.tips.length]);
        tip += 1;
      },
    };
    const btn = root.querySelector(".jd-btn");
    if (btn) btn.addEventListener("click", () => api.tip());
    return api;
  }

  window.JrAvatar = { mount, data };
  for (const root of document.querySelectorAll(".jd")) {
    const a = mount(root);
    root.jr = a;
    if (root.dataset.greet === "1" && data.greeting) a.say(data.greeting);
  }
})();
