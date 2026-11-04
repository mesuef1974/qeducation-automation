// تواريخ عربية بأرقام لاتينية، كما تعرضها المنصة
const LOCALE = "ar-QA-u-nu-latn";
const HM = { hour: "2-digit", minute: "2-digit" } as const;
const HMS = { ...HM, second: "2-digit" } as const;
const DAY = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });
const SHORT = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });
const STAMP = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", ...HM });
const STAMP_Y = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", ...HM });
const STAMP_SEC = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", ...HMS });
const STAMP_SEC_Y = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", ...HMS });
const CLOCK_SEC = new Intl.DateTimeFormat(LOCALE, HMS);
const SLOT = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "short", ...HM });
const SLOT_Y = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "short", year: "numeric", ...HM });
const RELATIVE = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });

/** تاريخ بلا وقت (YYYY-MM-DD) يُقرأ بالتوقيت المحلي لا UTC */
const local = (iso: string) => new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);

/** يكتب اللحظة بتاريخها ووقتها؛ وتُضاف السنة إن لم تكن الحالية. القاعدة: لا يظهر وقت دون تاريخه. */
function stamp(iso: string | null | undefined, plain: Intl.DateTimeFormat, withYear: Intl.DateTimeFormat): string {
  if (!iso) return "-";
  const d = local(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return (d.getFullYear() === new Date().getFullYear() ? plain : withYear).format(d);
}

export const fmtDay = (iso?: string | null) => (iso ? DAY.format(local(iso)) : "بلا تاريخ");
export const fmtShort = (iso?: string | null) => (iso ? SHORT.format(local(iso)) : "-");

/** التاريخ والوقت: «4 نوفمبر، 04:57 م» */
export const fmtStamp = (iso?: string | null) => stamp(iso, STAMP, STAMP_Y);

/** التاريخ والوقت بالثواني: «4 نوفمبر، 04:57:23 م»، لسجل البث */
export const fmtStampSec = (iso?: string | null) => stamp(iso, STAMP_SEC, STAMP_SEC_Y);

/** موعد بيومه وتاريخه ووقته: «الخميس 5 نوفمبر، 02:00 م»، للدورة الأسبوعية */
export const fmtSlot = (iso?: string | null) => stamp(iso, SLOT, SLOT_Y);

/** الساعة بالثواني «04:57:23 م»؛ لا تُعرض إلا وتاريخها بجوارها (fmtShort) */
export function fmtClock(iso?: string | null): string {
  if (!iso) return "-";
  const d = local(iso);
  return Number.isNaN(d.getTime()) ? "-" : CLOCK_SEC.format(d);
}

const QA_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Qatar" });
/** رقم اليوم في التقويم بتوقيت قطر: «أمس» يعني اليوم السابق في التقويم لا 24–48 ساعة */
const dayNo = (t: number) => Math.round(Date.parse(QA_DAY.format(t)) / 86_400_000);

export function ago(iso?: string | null): string {
  if (!iso) return "لم يحدث بعد";
  const t = Date.parse(iso);
  const sec = Math.round((t - Date.now()) / 1000);
  const days = dayNo(t) - dayNo(Date.now());
  // قبل ست ساعات فأقل بالساعات والدقائق؛ وما زاد بأيام التقويم («أمس»، «قبل 3 أيام»)
  if (Math.abs(sec) >= 6 * 3600 && days !== 0) return RELATIVE.format(days, "day");
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [["hour", 3600], ["minute", 60]];
  for (const [unit, size] of steps) if (Math.abs(sec) >= size) return RELATIVE.format(Math.round(sec / size), unit);
  return "الآن";
}

/** اللحظة بتاريخها ووقتها ثم بُعدها عن الآن: «4 نوفمبر، 04:57 م (قبل ساعتين)». «قبل ساعتين» وحدها لا تكفي. */
export function fmtWhen(iso?: string | null, empty = "لم يحدث بعد"): string {
  return iso ? `${fmtStamp(iso)} (${ago(iso)})` : empty;
}
