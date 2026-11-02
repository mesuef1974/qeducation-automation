import { ref } from "vue";

// العقد نفسه في docs/assets/theme.js ولوحة إدارة Django: المفتاح "theme" والقيم auto | light | dark
export type Theme = "auto" | "light" | "dark";
const ORDER: Theme[] = ["auto", "light", "dark"];
export const THEME_LABEL: Record<Theme, string> = { auto: "تلقائي", light: "نهاري", dark: "ليلي" };

function saved(): Theme {
  try {
    const t = localStorage.getItem("theme") as Theme | null;
    return t && ORDER.includes(t) ? t : "auto";
  } catch {
    return "auto";
  }
}

const theme = ref<Theme>(saved());

export function useTheme() {
  function next() {
    theme.value = ORDER[(ORDER.indexOf(theme.value) + 1) % ORDER.length];
    try {
      localStorage.setItem("theme", theme.value);
    } catch {
      /* بلا تخزين يبقى الاختيار للصفحة الحالية */
    }
    document.documentElement.setAttribute("data-theme", theme.value);
  }
  return { theme, next };
}
