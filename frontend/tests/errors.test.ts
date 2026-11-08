// npm test: node --test tests/*.test.ts (بلا اعتماديات إضافية: Node يشغّل TypeScript مباشرة)
import assert from "node:assert/strict";
import { test } from "node:test";

import { explainError } from "../src/utils/errors.ts";

const cases: [string, RegExp][] = [
  ['Page.goto: Timeout 30000ms exceeded.\nCall log:\n  - navigating to "https://qeducation.edu.gov.qa/x"', /مهلة فتح صفحة.*30 ثانية/],
  ["Locator.click: Timeout 15000ms exceeded.", /مهلة انتظار عنصر.*15 ثانية/],
  ["Page.goto: net::ERR_INTERNET_DISCONNECTED at https://x", /تعذّر الاتصال/],
  ["Target page, context or browser has been closed", /أُغلق المتصفح/],
  ["BrowserType.launch: Executable doesn't exist at C:/x/msedge.exe", /تشغيل متصفح Edge/],
  ["APIRequestContext.get: getaddrinfo ENOTFOUND qeducation.edu.gov.qa", /تعذّر الاتصال/],
  ["database is locked", /قاعدة البيانات مشغولة/],
];

for (const [raw, expected] of cases) {
  test(`يشرح: ${raw.slice(0, 40)}`, () => {
    const info = explainError(raw);
    assert.match(info.summary ?? "", expected);
    assert.ok(info.hint.length > 5);
  });
}

test("الأخطاء العربية والمجهولة تمرّ كما هي", () => {
  assert.equal(explainError("توقف العامل أثناء التنفيذ").summary, null);
  assert.equal(explainError("something odd").summary, null);
  assert.equal(explainError(null).summary, null);
});

test("مهلة الصفحة تسبق المهلة العامة", () => {
  assert.match(explainError("Page.goto: Timeout 5000ms exceeded").summary ?? "", /فتح صفحة/);
});
