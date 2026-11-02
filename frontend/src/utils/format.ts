// تواريخ عربية بأرقام لاتينية، كما تعرضها المنصة
const LOCALE = "ar-QA-u-nu-latn";
const DAY = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });
const SHORT = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });
const STAMP = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const RELATIVE = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });

/** تاريخ بلا وقت (YYYY-MM-DD) يُقرأ بالتوقيت المحلي لا UTC */
const local = (iso: string) => new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);

export const fmtDay = (iso?: string | null) => (iso ? DAY.format(local(iso)) : "بلا تاريخ");
export const fmtShort = (iso?: string | null) => (iso ? SHORT.format(local(iso)) : "-");
export const fmtStamp = (iso?: string | null) => (iso ? STAMP.format(local(iso)) : "-");

export function ago(iso?: string | null): string {
  if (!iso) return "لم يحدث بعد";
  const sec = Math.round((Date.parse(iso) - Date.now()) / 1000);
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of steps) if (Math.abs(sec) >= size) return RELATIVE.format(Math.round(sec / size), unit);
  return "الآن";
}
