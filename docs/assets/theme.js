/*
 * مبدّل الثيم: تلقائي ← نهاري ← ليلي. يحفظ الاختيار بالمفتاح "theme" وبالقيم نفسها
 * التي تستعملها لوحة إدارة Django. يُحمَّل في <head> دون defer ليُطبَّق الثيم قبل الرسم.
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
    document.querySelectorAll(".theme-toggle").forEach(function (b) {
      b.setAttribute("data-mode", current);
      b.setAttribute("aria-label", "الثيم: " + LABEL[current] + ". اضغط للتبديل");
      var l = b.querySelector(".lbl"); if (l) l.textContent = LABEL[current];
    });
  }
  apply();

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".theme-toggle").forEach(function (b) {
      b.type = "button";
      b.innerHTML = ICONS + '<span class="lbl"></span>';
      b.addEventListener("click", function () {
        current = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
        try { localStorage.setItem(KEY, current); } catch (e) { /* يبقى للصفحة الحالية */ }
        apply();
      });
    });
    apply();
  });
})();
