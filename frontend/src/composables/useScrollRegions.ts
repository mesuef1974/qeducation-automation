/**
 * كل منطقة قابلة للتمرير (.table-wrap و.scroll) تُصبح قابلة للتركيز بلوحة المفاتيح ما دام محتواها أعرض منها (WCAG 2.1.1)،
 * بمجموعة مسمّاة لقارئ الشاشة. تُعاد الحسبة عند تغيّر الصفحة أو حجمها.
 */
import { onBeforeUnmount, onMounted } from "vue";

const SELECTOR = ".table-wrap, .scroll";

export function markScrollRegions(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>(SELECTOR).forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
      el.tabIndex = 0;
      el.setAttribute("role", "group");
      el.setAttribute("aria-label", el.getAttribute("aria-label") ?? "منطقة قابلة للتمرير");
    } else if (el.getAttribute("aria-label") === "منطقة قابلة للتمرير") {
      el.removeAttribute("tabindex");
      el.removeAttribute("role");
      el.removeAttribute("aria-label");
    }
  });
}

export function useScrollRegions(): void {
  let timer: number | undefined;
  let observer: MutationObserver | undefined;
  const schedule = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => markScrollRegions(), 150);
  };
  onMounted(() => {
    schedule();
    observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", schedule);
  });
  onBeforeUnmount(() => {
    window.clearTimeout(timer);
    observer?.disconnect();
    window.removeEventListener("resize", schedule);
  });
}
