"use strict";
// Report page: play each chart's animation once, when it first scrolls into view.
(function () {
  const root = document.documentElement;
  const cards = document.querySelectorAll(".rv");
  if (!("IntersectionObserver" in window)) return;
  root.classList.add("js");
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { threshold: 0.2 });
  cards.forEach((c) => io.observe(c));
})();
