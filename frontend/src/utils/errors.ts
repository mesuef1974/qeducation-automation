/** أخطاء المتصفح (Playwright) والشبكة بلغة مفهومة للمعلم؛ النص التقني الأصلي يبقى للتفاصيل. */
export interface ErrorInfo {
  summary: string | null; // جملة عربية قصيرة، أو null إن لم يُعرف النوع
  hint: string;           // ما يفعله المعلم
}

const RULES: { test: RegExp; make: (m: RegExpMatchArray) => ErrorInfo }[] = [
  {
    test: /Page\.goto: Timeout (\d+)ms exceeded/,
    make: (m) => ({ summary: `انتهت مهلة فتح صفحة على المنصة (${Math.round(+m[1] / 1000)} ثانية)`,
                    hint: "المنصة بطيئة أو لم تستجب. أعد المحاولة بعد دقائق." }),
  },
  {
    test: /Timeout (\d+)ms exceeded/,
    make: (m) => ({ summary: `انتهت مهلة انتظار عنصر في صفحة المنصة (${Math.round(+m[1] / 1000)} ثانية)`,
                    hint: "قد تكون الصفحة تغيّرت أو بطؤها شديد. أعد المحاولة، فإن تكرر فراجع الصفحة على المنصة." }),
  },
  {
    test: /net::ERR_(INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|CONNECTION_\w+|NETWORK_CHANGED)|getaddrinfo (?:ENOTFOUND|EAI_AGAIN)|ECONNREFUSED|ECONNRESET/,
    make: () => ({ summary: "تعذّر الاتصال بالمنصة", hint: "تحقق من الإنترنت ثم أعد المحاولة." }),
  },
  {
    test: /Target (?:page, context or browser )?has been closed|browser has been closed/i,
    make: () => ({ summary: "أُغلق المتصفح أثناء العمل", hint: "لا تغلق نافذة Edge التي يفتحها العامل. أعد المحاولة." }),
  },
  {
    test: /Executable doesn't exist|Failed to launch|msedge/i,
    make: () => ({ summary: "تعذّر تشغيل متصفح Edge", hint: "تأكد أن Microsoft Edge مثبّت ثم أعد المحاولة." }),
  },
  {
    test: /database is locked/i,
    make: () => ({ summary: "قاعدة البيانات مشغولة لحظة", hint: "أعد المحاولة بعد ثوانٍ." }),
  },
];

/** يطابق نص الخطأ بالأنماط المعروفة. ما لا يُعرف يعود summary فيه null ليُعرض النص كما هو معزولًا. */
export function explainError(text: string | null | undefined): ErrorInfo {
  const t = text ?? "";
  for (const r of RULES) {
    const m = t.match(r.test);
    if (m) return r.make(m);
  }
  return { summary: null, hint: "" };
}
