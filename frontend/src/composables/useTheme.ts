import { ref } from "vue";

// المنطق كله في docs/assets/theme.js (يُدمج في index.html قبل الرسم)؛ هنا ربطه بـ Vue فقط
export type Theme = "auto" | "light" | "dark";
interface NeoThemeApi { label: Record<Theme, string>; get(): Theme; next(): void }
const core = (window as unknown as { NeoTheme: NeoThemeApi }).NeoTheme;

export const THEME_LABEL = core.label;

const theme = ref<Theme>(core.get());
document.addEventListener("neo-theme", (e) => {
  theme.value = (e as CustomEvent<Theme>).detail;
});

export function useTheme() {
  return { theme, next: () => core.next() };
}
