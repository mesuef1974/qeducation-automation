/*
 * مناطق التمرير (.table-wrap و.scroll و.log): تصبح قابلة للتركيز بلوحة المفاتيح ما دام محتواها أعرض منها (WCAG 2.1.1)
 * وتُسمّى لقارئ الشاشة. مصدر واحد لصفحات docs ولواجهة Vue (تُدمج في index.html وتستدعي NeoScroll.mark عند تغيّر الصفحة).
 */
(function () {
  var SELECTOR = ".table-wrap, .scroll, .log", NAME = "منطقة قابلة للتمرير";
  function mark(root) {
    (root || document).querySelectorAll(SELECTOR).forEach(function (el) {
      if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
        el.tabIndex = 0;
        if (!/^(UL|OL|TABLE)$/.test(el.tagName)) el.setAttribute("role", "group"); // لا نغيّر دور القوائم والجداول
        if (!el.getAttribute("aria-label")) el.setAttribute("aria-label", NAME);
      } else if (el.getAttribute("aria-label") === NAME) {
        el.removeAttribute("tabindex");
        el.removeAttribute("role");
        el.removeAttribute("aria-label");
      }
    });
  }
  window.NeoScroll = { mark: mark };
  document.addEventListener("DOMContentLoaded", function () { mark(); });
  window.addEventListener("resize", function () { mark(); });
})();
