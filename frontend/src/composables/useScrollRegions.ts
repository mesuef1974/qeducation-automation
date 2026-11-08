/** تحديث مناطق التمرير عند تغيّر الصفحة؛ المنطق في docs/assets/scroll-regions.js (مصدر واحد مع صفحات docs). */
import { onBeforeUnmount, onMounted } from "vue";

const scroll = (window as unknown as { NeoScroll: { mark(root?: ParentNode): void } }).NeoScroll;

export function useScrollRegions(): void {
  let timer: number | undefined;
  let observer: MutationObserver | undefined;
  const schedule = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => scroll.mark(), 150);
  };
  onMounted(() => {
    schedule();
    observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });
  });
  onBeforeUnmount(() => {
    window.clearTimeout(timer);
    observer?.disconnect();
  });
}
