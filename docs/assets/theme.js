/*
 * الثيم: المصدر الوحيد لمنطقه في المشروع كله (صفحات docs وواجهة Vue عبر window.NeoTheme، ولوحة Django بالمفتاح نفسه).
 * تلقائي ← نهاري ← ليلي. المفتاح "theme" والقيم auto | light | dark كما في لوحة إدارة Django.
 * يُحمَّل في <head> دون defer ليُطبَّق الثيم قبل الرسم؛ وفي الواجهة يُدمج داخل index.html (vite.config.ts).
 * يربط أي .theme-toggle ليس عليه data-vue (زر Vue يرسم نفسه ويستدعي NeoTheme.next).
 */
(function () {
  var KEY = "theme", ORDER = ["auto", "light", "dark"];
  var LABEL = { auto: "تلقائي", light: "نهاري", dark: "ليلي" };
  var ICONS =
    '<svg class="i-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></svg>' +
    '<svg class="i-light" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>' +
    '<svg class="i-dark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>';

  var current = "auto";
  try { var t = localStorage.getItem(KEY); if (ORDER.indexOf(t) >= 0) current = t; } catch (e) { /* بلا تخزين: تلقائي */ }

  function apply() {
    document.documentElement.setAttribute("data-theme", current);
    document.querySelectorAll(".theme-toggle:not([data-vue])").forEach(function (b) {
      b.setAttribute("data-mode", current);
      b.setAttribute("aria-label", "الثيم: " + LABEL[current] + ". اضغط للتبديل");
      var l = b.querySelector(".lbl"); if (l) l.textContent = LABEL[current];
    });
    document.dispatchEvent(new CustomEvent("neo-theme", { detail: current }));
  }

  function set(value) {
    if (ORDER.indexOf(value) < 0) return;
    current = value;
    try { localStorage.setItem(KEY, current); } catch (e) { /* يبقى للصفحة الحالية */ }
    apply();
  }

  function next() { set(ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]); }

  window.NeoTheme = { order: ORDER, label: LABEL, get: function () { return current; }, set: set, next: next };
  apply();

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".theme-toggle:not([data-vue])").forEach(function (b) {
      b.type = "button";
      b.innerHTML = ICONS + '<span class="lbl"></span>';
      b.addEventListener("click", next);
    });
    apply();
  });
})();
