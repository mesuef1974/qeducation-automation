"""
عميل منصة قطر للتعليم عبر Playwright بملف تعريف دائم (.neo_profile).
الدخول يتم يدويًا من المعلم مرة واحدة (neo_login)؛ لا تُخزَّن أي كلمة مرور.
"""
import json
import logging
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from neo.domain.assessment import POINTS, TF, Question
from neo.domain.quality import ASSESSMENT_KINDS
from neo.domain.types import FileLink, ParsedSection
from neo.infrastructure.parsers import (
    is_login_page,
    is_login_url,
    parse_available_outcomes,
    parse_default_visibility,
    parse_file_links,
    parse_lesson_open,
    parse_lessons,
    parse_outcomes,
    parse_points_actions,
    parse_points_games,
    parse_question_text,
    parse_sections,
    parse_tags,
    parse_tiles,
)
from neo.services import live

log = logging.getLogger(__name__)
BASE_URL = "https://qeducation.edu.gov.qa"
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def _dt_fields(dt: datetime) -> dict:
    h12 = dt.hour % 12 or 12
    return {
        "label": f"{dt.year} {MONTHS_AR[dt.month - 1]} {dt.day:02d} {h12:02d}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}",
        "alt": f"{dt:%Y-%m-%d %H:%M}",
        "year": dt.year, "month": dt.month, "day": dt.day, "hours": dt.hour, "minutes": dt.minute,
    }


def stamp(text: str) -> tuple[int, ...] | None:
    """قيمة حقل تاريخ/وقت كما تعرضه المنصة → (سنة، شهر، يوم[، ساعة، دقيقة]) للمقارنة؛ None إن كان فارغًا."""
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    return tuple(nums[:5]) if len(nums) >= 3 else None


class NotLoggedIn(RuntimeError):
    pass


class PlatformError(RuntimeError):
    pass


class BrowserBusy(PlatformError):
    pass


def kill_orphan_browsers(profile_dir: Path | None = None) -> int:
    """يُنهي عمليات المتصفح التي تستعمل ملف تعريف الأتمتة (بقايا عامل انهار) فتقفل الملف على من بعدها.
    يُستدعى عند بدء العامل فقط، حيث لا يصحّ أن يكون متصفح آخر على الملف نفسه."""
    profile = str(Path(profile_dir or settings.NEO_PROFILE_DIR)).lower()
    killed = 0
    if sys.platform == "win32":
        script = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
                  "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        procs = json.loads(out) if out else []
        for proc in procs if isinstance(procs, list) else [procs]:
            if profile in (proc.get("CommandLine") or "").lower():
                subprocess.run(["taskkill", "/PID", str(proc["ProcessId"]), "/F"], capture_output=True, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                killed += 1
    return killed


class NeoClient:
    """استخدام: with NeoClient() as c: c.get_html(...)"""

    MIN_INTERVAL = 1.0  # ثانية بين الطلبات - لطف مع الخادم

    def __init__(self, headless: bool = True, profile_dir: Path | None = None):
        self.headless = headless
        self.profile_dir = Path(profile_dir or settings.NEO_PROFILE_DIR)
        self._last = 0.0

    def __enter__(self):
        self._pw = sync_playwright().start()
        try:
            self.context = self._pw.chromium.launch_persistent_context(
                str(self.profile_dir), channel=settings.NEO_BROWSER_CHANNEL, headless=self.headless, locale="ar-QA",
            )
        except PlaywrightError as exc:
            self._pw.stop()
            # ملف التعريف يُقفل ما دام متصفح آخر يستخدمه (neo_login أو أمر آخر قيد التشغيل)
            raise BrowserBusy("المتصفح مشغول: أمر آخر يعمل بملف الدخول نفسه (neo_login أو مهمة أخرى). "
                              "انتظر انتهاءه ثم أعد المحاولة.") from exc
        # كوكي الجلسة في المنصة غير دائم فيُفقد عند إغلاق المتصفح؛ نحفظه ونستعيده صراحةً
        if self.cookies_path.exists():
            self.context.add_cookies(json.loads(self.cookies_path.read_text(encoding="utf-8")))
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.on("response", self._on_response)  # التنقل في الصفحات يظهر في البث الحي
        return self

    @staticmethod
    def _on_response(resp) -> None:
        """صفحة واحدة لكل تنقّل: التحويلات (3xx) تُتخطى، وتُعرف الكتابة من طلب POST الذي حوّل إلى الصفحة."""
        try:
            req = resp.request
            if req.resource_type != "document" or not resp.url.startswith(BASE_URL) or 300 <= resp.status < 400:
                return
            method, first = req.method, req
            while first.redirected_from is not None:
                first = first.redirected_from
            if first.method != "GET":
                method = first.method
            path = resp.url[len(BASE_URL):]
            live.emit("net", live.page_label(path), status=resp.status, path=path.split("?")[0],
                      method=None if method == "GET" else method)
        except Exception:
            log.debug("تعذّر بث حدث الشبكة", exc_info=True)

    @staticmethod
    def _net(path: str, status: int, started: float) -> None:
        live.emit("net", live.page_label(path), status=status, path=path.split("?")[0],
                  ms=round((time.monotonic() - started) * 1000))

    @property
    def cookies_path(self) -> Path:
        return self.profile_dir / "session_cookies.json"

    def _save_cookies(self):
        cookies = [c for c in self.context.cookies() if "edu.gov.qa" in c["domain"]]
        self.cookies_path.write_text(json.dumps(cookies), encoding="utf-8")

    def __exit__(self, *exc):
        self.context.close()
        self._pw.stop()

    def _throttle(self):
        wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    SSO_PATH = "/saml_sso/sso"  # «تسجيل الدخول بالحساب الرسمي» في صفحة الدخول (الدخول الموحد)

    def login_silent(self, timeout_s: int = 45) -> bool:
        """
        الخطوة 0: دخول صامت بلا كلمة مرور: الدخول الموحد بجلسة الحساب المحفوظة في ملف متصفح الأتمتة.
        لا يُكتب شيء في أي حقل؛ إن طلب مزوّد الهوية تفاعلًا (كلمة مرور أو تحقق) ينتهي الانتظار ويعيد False.
        """
        live.stage("دخول صامت بالحساب الرسمي", "platform")
        try:
            self._throttle()
            self.page.goto(f"{BASE_URL}{self.SSO_PATH}")
            self.page.wait_for_url(
                lambda u: u.startswith(BASE_URL) and self.SSO_PATH not in u and not is_login_url(u),
                timeout=timeout_s * 1000)
            self.get_html("/user_dashboard")  # تأكيد: صفحة المعلم تفتح بلا تحويل إلى الدخول
        except (PlaywrightError, NotLoggedIn):
            return False
        self._save_cookies()
        return True

    def login_interactive(self, timeout_s: int = 600) -> None:
        live.stage("نافذة الدخول مفتوحة: سجّل الدخول فيها بنفسك", "platform")
        self.page.goto(f"{BASE_URL}/user_dashboard")
        self.page.wait_for_url("**/user_dashboard**", timeout=timeout_s * 1000)
        self._save_cookies()

    def get_html(self, path: str) -> str:
        for wait in (*self.RETRY_WAITS, None):  # الخطوة 1: ثانية على الأقل بين الطلبات، وإعادة بعد 429
            self._throttle()
            started = time.monotonic()
            resp = self.context.request.get(f"{BASE_URL}{path}")
            self._net(path, resp.status, started)
            if resp.status != 429:
                break
            if wait is None:
                raise PlatformError(f"المنصة تردّ 429 (طلبات كثيرة) على {path.split('?')[0]} "
                                    f"بعد {len(self.RETRY_WAITS)} محاولات")
            live.emit("warn", f"المنصة طلبت التمهّل (429)؛ انتظار {wait} ث ثم إعادة المحاولة", retry=wait)
            time.sleep(wait)
        html = resp.text()
        if is_login_url(resp.url) or is_login_page(html):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not resp.ok:
            raise PlatformError(f"GET {path} -> {resp.status}")
        return html

    def lesson_list_html(self, lms_id: int) -> str:
        return self.get_html(f"/teacher_lessons/list/{lms_id}")

    def lesson_page_html(self, lms_id: int, lesson_id: int) -> str:
        return self.get_html(f"/teacher_lesson/show/{lms_id}?lesson_id={lesson_id}")

    def outcomes_html(self, lms_id: int, lesson_id: int) -> str:
        return self.get_html(f"/teacher_lesson/show_competencies/{lms_id}?lesson_id={lesson_id}")

    def available_outcomes(self, lms_id: int, lesson_id: int) -> list[dict]:
        return parse_available_outcomes(
            self.get_html(f"/teacher_lesson/edit_competencies/{lms_id}?lesson_id={lesson_id}"))

    def link_outcomes(self, lms_id: int, lesson_id: int, ids: list[int]) -> list[tuple[str, str]]:
        """يعلّم مربعات النتاجات المطلوبة في نموذج الربط ويحفظه، ثم يتحقق من صفحة العرض.
        النموذج يحفظ الاختيار كاملًا، فيُستدعى لدرس بلا نتاجات فقط (يتحقق المستدعي) كي يبقى إضافةً خالصة."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit_competencies/{lms_id}?lesson_id={lesson_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        checked = self.page.evaluate("""(ids) => {
            let n = 0;
            for (const cb of document.querySelectorAll("input[name='proficiencies[]']"))
                if (ids.includes(Number(cb.value))) { cb.checked = true; n++; } else cb.checked = false;
            return n; }""", ids)
        if checked != len(ids):
            raise PlatformError(f"وُجد {checked} من {len(ids)} نتاجًا في نموذج الربط")
        with self.page.expect_navigation():
            self.page.evaluate("document.querySelector(\"form[action*='save_competencies']\").submit()")
        linked = parse_outcomes(self.outcomes_html(lms_id, lesson_id))
        if len(linked) < len(ids):
            raise PlatformError(f"بعد الحفظ ظهر {len(linked)} من {len(ids)} نتاجًا")
        return linked

    # ------------------------------------------------------------- المحتوى (المرحلة 8)

    def lesson_description(self, lms_id: int, lesson_id: int) -> str:
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit/{lms_id}?lesson_id={lesson_id}")
        self._assert_form()
        return self.page.input_value("#lesson_description")

    def set_lesson_description(self, lms_id: int, lesson_id: int, text: str) -> None:
        """يملأ الوصف في نموذج التعديل ويحفظ؛ بقية الحقول (التاريخ، الاسم) تبقى كما هي."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit/{lms_id}?lesson_id={lesson_id}")
        self._assert_form()
        self.page.wait_for_load_state("networkidle")
        self.page.fill("#lesson_description", text)
        with self.page.expect_navigation():
            self.page.click("form[action*='/teacher_lesson/save/'] [name=commit]")
        if "/teacher_lesson/edit/" in self.page.url:
            raise PlatformError("رفضت المنصة حفظ الوصف")

    def lesson_is_open(self, lms_id: int, lesson_id: int) -> bool:
        """شرط المعلم قبل أي كتابة: الدرس «مفتوح» (تبويب الإغلاق). شكل غير مألوف يوقف ولا يُعدّ مفتوحًا."""
        state = parse_lesson_open(self.get_html(f"/teacher_lesson/locked/{lms_id}?lesson_id={lesson_id}"))
        if state is None:
            raise PlatformError("شكل تبويب الإغلاق غير مألوف")
        return state

    def lesson_tags(self, lms_id: int, lesson_id: int) -> list[str]:
        html = self.get_html(f"/teacher_lesson/show_tags/{lms_id}?lesson_id={lesson_id}")
        tags = parse_tags(html)
        if not tags and "لا يوجد" not in html:  # شكل غير مألوف: لا نعدّه فارغًا فنكتب فوق كلمات المعلم
            raise PlatformError("شكل صفحة الكلمات الدلالية غير مألوف")
        return tags

    def set_lesson_tags(self, lms_id: int, lesson_id: int, tags: list[str]) -> list[str]:
        """يحفظ الكلمات عبر مسار الحفظ نفسه الذي يستدعيه زر «إضافة» (POST بالفاصلة اللاتينية)، ثم يعيد قراءتها.
        لا كتابة إلا لدرس بلا كلمات (يتحقق المستدعي)؛ الكلمة لا تحوي فاصلة."""
        if not tags or any("," in t or "،" in t for t in tags):
            raise PlatformError("كلمات دلالية غير صالحة")
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/tags/{lms_id}?lesson_id={lesson_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.wait_for_load_state("networkidle")
        # كما يفعل المعلم: «إضافة» تفتح الحقل، ثم كل كلمة + Enter ليثبّتها tagsManager، ثم دالة الحفظ في الصفحة نفسها
        self.page.click(".tag-group-0 button[onclick*='edit_tags']")
        box = self.page.wait_for_selector("input.tm-input-0", timeout=15_000)
        for t in tags:
            box.fill(t)
            box.press("Enter")
        held = self.page.input_value(".tag-group-0 input[name=hidden-tags]")
        if set(held.split(",")) != set(tags):
            raise PlatformError(f"لم يثبّت الحقل الكلمات: {len(held.split(','))} من {len(tags)}")
        self.page.evaluate(
            "(u) => window.save_tags(u, true, true, '0', false)", f"/teacher_lesson/save_tags/{lms_id}?lesson_id={lesson_id}")
        saved = self.lesson_tags(lms_id, lesson_id)
        if set(saved) != set(tags):
            raise PlatformError(f"بعد الحفظ ظهرت {len(saved)} من {len(tags)} كلمة")
        return saved

    # ------------------------------------------------------------- إنشاء درس جديد

    def find_lesson_id(self, lms_id: int, title: str, academic_year: str) -> int | None:
        """معرّف الدرس بعنوانه المطابق تمامًا في قائمة دروس الصف (لا ترقيم تلقائي)، أو None."""
        want = " ".join(title.split())
        lessons = parse_lessons(self.lesson_list_html(lms_id), academic_year)
        found = [x for x in lessons if " ".join(x.title.split()) == want]
        if len(found) > 1:
            raise PlatformError(f"أكثر من درس بعنوان «{title}» على المنصة؛ لا أعرف أيها المقصود")
        return found[0].lms_lesson_id if found else None

    def create_lesson(self, lms_id: int, title: str, description: str, academic_year: str, when: tuple[date, int],
                      before_lesson_id: int | None = None) -> tuple[int, bool]:
        """
        درس جديد بعنوانه ووصفه وتاريخه وحصته (النموذج يرفض بلا تاريخ وحصة)، في النهاية أو قبل درس.
        يعيد (معرّف الدرس، أُنشئ الآن؟). مكرر العنوان لا يُنشأ ثانيةً: الموجود يُعاد (الاستعادة بعد انقطاع).
        """
        if (existing := self.find_lesson_id(lms_id, title, academic_year)) is not None:
            return existing, False
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/new/{lms_id}", wait_until="load")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        form = "form[action*='/teacher_lesson/create/']"
        if self.page.locator(form).count() != 1:
            raise PlatformError("شكل نموذج إضافة الدرس غير مألوف")
        self.page.fill("#lesson_name", title)
        self.page.fill("#lesson_description", description)
        self.page.fill("#lesson_location", "الصف")
        d, period = when
        self.page.evaluate(  # الحقول المخفية التي يقرؤها الخادم؛ منتقي التاريخ لا يعمل في صفحة النموذج الجزئية
            """([y, m, d, period]) => {
                 const set = (id, v) => { document.getElementById(id).value = v; };
                 set('lesson_period_date_alt', `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
                 set('lesson_period_date_year', y); set('lesson_period_date_month', m); set('lesson_period_date_day', d);
                 const sel = document.getElementById('lesson_period_number');
                 const opt = [...sel.options].find(o => o.value === String(period));
                 if (!opt) throw new Error('حصة غير موجودة في النموذج');
                 opt.disabled = false; sel.value = String(period);
               }""", [d.year, d.month, d.day, period])
        if before_lesson_id is not None:
            order = [x.lms_lesson_id for x in parse_lessons(self.lesson_list_html(lms_id), academic_year)]
            if before_lesson_id not in order:
                raise PlatformError("الدرس المرجعي للترتيب غير موجود على المنصة")
            self.page.select_option("#position", str(order.index(before_lesson_id) + 1))
        with self.page.expect_navigation():
            self.page.click(f"{form} button[type=submit]")
        body = " ".join(self.page.inner_text("body").split())
        # النجاح: الخادم يرد JSON فيه رابط الدرس الجديد؛ وما سواه رفض بسببه (تاريخ وحصة، مكان…)
        m = re.search(r'"url":"[^"]*/teacher_lesson/show/\d+\?lesson_id=(\d+)"', body)
        if not m:
            raise PlatformError(f"رفضت المنصة إضافة الدرس: {body[:160]}")
        created = self.find_lesson_id(lms_id, title, academic_year)
        if created is None or created != int(m.group(1)):
            raise PlatformError("الدرس المُنشأ لا يطابق ما في قائمة الدروس")
        self.hide_lesson(lms_id, created)  # يظهر الجديد للطلاب افتراضيًا
        return created, True

    def section_names(self, lms_id: int, lesson_id: int) -> list[str]:
        return [s.title for s in parse_sections(self.lesson_page_html(lms_id, lesson_id))]

    def add_file_section(self, lms_id: int, lesson_id: int, path: Path, title: str, grade: str, term: str) -> None:
        """
        قسم «ملف» (عرض تقديمي) كما يضيفه المعلم: إضافة قسم ← ملف ← رفع ← عنوان القسم ← حفظ.
        إضافة فقط: قسم بالعنوان نفسه موجود لا يُضاف ثانيةً. الملف يبقى خاصًا بالمعلم (لا يُشارَك في المكتبة).
        """
        if title in self.section_names(lms_id, lesson_id):
            return
        self._throttle()
        page = self.page
        page.goto(f"{BASE_URL}/teacher_lesson/show/{lms_id}?lesson_id={lesson_id}", wait_until="load")
        if is_login_url(page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        page.locator("a[title='إضافة قسم']").first.click()
        page.wait_for_selector("a[onclick*='uploader/index']", state="attached", timeout=20_000)
        page.evaluate("""() => document.querySelector("a[onclick*='uploader/index']").click()""")
        page.wait_for_selector("input[type=file]", state="attached", timeout=30_000)
        page.set_input_files("input[type=file]", str(path))
        page.wait_for_selector("#resource_form", timeout=180_000)
        page.fill("#resource_form [name='resource[name]']", title)
        page.fill("#resource_form [name='resource[description]']", title)
        page.select_option("#resource_form [name=topic]", label="الرياضيات")  # المادة والوسوم إلزامية في نموذج الملف
        page.select_option("#resource_form [name='tag_groups[7]']", label=grade)
        page.select_option("#resource_form [name='tag_groups[9]']", label=term)
        scope = page.locator("#resource_form input[name=scope]:checked")
        if scope.count() and scope.first.get_attribute("value") != "User":
            page.check("#resource_form input[name=scope][value=User]")
        page.click("#resource_form button[type=submit]")
        try:
            page.wait_for_selector("#resource_form", state="detached", timeout=60_000)
        except PlaywrightTimeout as exc:
            alerts = " | ".join(page.evaluate("() => [...document.querySelectorAll('#alerts')].map(e => e.innerText.trim())"))
            raise PlatformError(f"رفضت المنصة حفظ قسم الملف: {alerts or 'بلا رسالة'}") from exc
        if title not in self.section_names(lms_id, lesson_id):
            raise PlatformError(f"لم يظهر قسم «{title}» في الدرس بعد الحفظ")

    def add_page_section(self, lms_id: int, lesson_id: int, name: str, html: str) -> None:
        """قسم «صفحة» جديد باسمه، ثم محتواه في محرر القسم (TinyMCE) ويُحفظ."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_html_section/new/{lms_id}?lesson_id={lesson_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.fill("#section_name", name)
        with self.page.expect_navigation():
            self.page.click("form[action*='/teacher_html_section/create/'] [type=submit], "
                            "form[action*='/teacher_html_section/create/'] button")
        section = next((s for s in parse_sections(self.lesson_page_html(lms_id, lesson_id)) if s.title == name), None)
        if section is None:
            raise PlatformError("لم يظهر القسم الجديد في قائمة الأقسام")
        self.fill_section(lms_id, lesson_id, section.section_id, html)

    def fill_section(self, lms_id: int, lesson_id: int, section_id: int, html: str) -> None:
        """محتوى قسم «صفحة» موجود: يُكتب في TinyMCE وفي الحقل المخفي الذي يقرؤه الخادم، ثم يُحفظ."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_html_section/edit/{lms_id}?lesson_id={lesson_id}&section_id={section_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.wait_for_function("window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized",
                                    timeout=30_000)
        self.page.evaluate(
            """(html) => { tinymce.activeEditor.setContent(html); tinymce.activeEditor.save();
                           const h = document.getElementById('content_hidden'); if (h) h.value = html; }""", html)
        with self.page.expect_navigation():
            self.page.click("form[action*='/teacher_html_section/save/'] button[type=submit]")
        if "/teacher_html_section/edit/" in self.page.url:
            raise PlatformError("رفضت المنصة حفظ محتوى القسم")

    def assessment_names(self, lms_id: int, lesson_id: int) -> list[str]:
        return [s.title for s in parse_sections(self.lesson_page_html(lms_id, lesson_id)) if s.kind in ASSESSMENT_KINDS]

    def add_quiz(self, lms_id: int, lesson_id: int, name: str, questions: list[Question]) -> int:
        """تقييم ذاتي التصحيح باسمه مربوطًا بالدرس، ثم أسئلته. متكرر التنفيذ بأمان: إن وُجد تقييم بالاسم نفسه
        (من محاولة انقطعت) استُكمل بما ينقصه من الأسئلة ولم يُنشأ ثانٍ."""
        assignment_id = self._find_quiz(lms_id, lesson_id, name) or self._create_quiz(lms_id, lesson_id, name)
        bank_id = self._bank_id(assignment_id)
        existing = self._question_texts(assignment_id, bank_id)
        for q in questions:
            if q.text not in existing:
                self._add_question(bank_id, assignment_id, q)
        n = len(self._question_texts(assignment_id, bank_id))
        if n < len(questions):
            raise PlatformError(f"في التقييم {assignment_id} {n} من {len(questions)} سؤالًا")
        return assignment_id

    def _find_quiz(self, lms_id: int, lesson_id: int, name: str) -> int | None:
        section = next((s for s in parse_sections(self.lesson_page_html(lms_id, lesson_id)) if s.title == name), None)
        if section is None:
            return None
        html = self.get_html(f"/teacher_lesson/show/{lms_id}?lesson_id={lesson_id}&section_id={section.section_id}")
        ids = set(re.findall(r"teacher_quiz_assignment/\w+/(\d+)", html))
        if len(ids) != 1:
            raise PlatformError(f"تعذّر تحديد معرّف التقييم «{name}»: {sorted(ids)}")
        return int(ids.pop())

    def _create_quiz(self, lms_id: int, lesson_id: int, name: str) -> int:
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_quiz_assignment/new/{lms_id}?class={lms_id}&lesson_id={lesson_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.fill("#assignment_name", name)
        self.page.select_option("#lesson_id", str(lesson_id))
        with self.page.expect_navigation():
            self.page.click("form[action*='/teacher_quiz_assignment/create'] [name=commit]")
        # تردّ المنصة بـ JSON فيه رابط الدرس مع معرّف التقييم الجديد، لا بتحويل
        m = re.search(r"assignment_id=(\d+)", self.page.content())
        if not m:
            raise PlatformError(f"لم تُنشئ المنصة التقييم: {self.page.url}")
        return int(m.group(1))

    def _bank_id(self, assignment_id: int) -> int:
        # صفحة إضافة الأسئلة تُنشئ بنك أسئلة التقييم عند أول فتح وتعرض روابط الأنواع بمعرّفه
        html = self.get_html(f"/quiz_question_bank/add_questions?container_id={assignment_id}")
        bank = re.search(r"/quiz_question_bank/new_question/(\d+)", html)
        if not bank:
            raise PlatformError(f"لم يُعثر على بنك أسئلة التقييم {assignment_id}")
        return int(bank.group(1))

    def _question_texts(self, assignment_id: int, bank_id: int) -> list[str]:
        html = self.get_html(f"/teacher_quiz_assignment/questions/{assignment_id}")
        texts = []
        for pos in sorted(set(re.findall(r"show_question/\d+\?container_id=\d+&amp;position=(\d+)", html)), key=int):
            q = self.get_html(f"/quiz_question_bank/show_question/{bank_id}?container_id={assignment_id}&position={pos}")
            texts.append(parse_question_text(q))
        return texts

    def _add_question(self, bank_id: int, assignment_id: int, q: Question) -> None:
        self._throttle()
        kind = "TrueOrFalse" if q.type == TF else "MultipleChoiceOneAnswer"
        self.page.goto(f"{BASE_URL}/quiz_question_bank/new_question/{bank_id}?container_id={assignment_id}&type={kind}")
        self.page.fill("#question_description", q.text)
        self.page.fill("#question_points", str(POINTS))
        if q.type == TF:
            radio = "question_true_or_false_true" if q.answer else "question_true_or_false_false"
        else:
            for i, choice in enumerate(q.choices, start=1):
                self.page.fill(f"#text_{i}", choice)
            radio = f"question_correct_{q.correct + 1}"
        self.page.evaluate("id => document.getElementById(id).click()", radio)  # الأزرار خارج نافذة العرض
        with self.page.expect_navigation():  # زر الحفظ رابط JS خارج نافذة العرض: نستدعي دالته
            self.page.evaluate("submit_new_question('commit')")
        if "/new_question/" in self.page.url or "/create_question/" in self.page.url:
            raise PlatformError(f"رفضت المنصة السؤال: {q.text[:40]}")

    def tile_is_default(self, lms_id: int, lesson_id: int) -> bool:
        tiles = parse_tiles(self.lesson_list_html(lms_id))
        return next((t.image_default for t in tiles if t.lms_lesson_id == lesson_id), True)

    def set_tile_picture(self, lms_id: int, lesson_id: int, png: Path, color: str) -> None:
        """صورة البطاقة من المحرر السريع في قائمة الدروس: نافذة رفع داخل الصفحة، ثم حفظ، ثم تحقق من البطاقة."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lessons/list/{lms_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.wait_for_load_state("networkidle")
        self.page.click(f'[id="{lesson_id}"] button.quick_edit_icon')  # المعرّف رقمي، فلا يصلح #id
        box = f'[id^="quick_edit_box_lesson_{lesson_id}"]'  # للمعرّف لاحقة عشوائية
        self.page.wait_for_selector(f"{box} #save_btn", timeout=15_000)
        self.page.click(f"{box} button.options_btn:not(.ai_tile_image)")
        self.page.wait_for_selector("input[type=file]", state="attached", timeout=10_000)
        self.page.set_input_files("input[type=file]", str(png))
        wrapper = f"#UploaderWrapperlesson_{lesson_id}"
        self.page.wait_for_function(
            f"document.querySelector('{wrapper}') && document.querySelector('{wrapper}').children.length > 0",
            timeout=60_000)
        self.page.wait_for_timeout(1500)  # اكتمال شريط الرفع
        self.page.click(f"{box} #save_btn")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
        if self.tile_is_default(lms_id, lesson_id):
            raise PlatformError("حُفظ المحرر السريع لكن الصورة لم تتغير")

    def timetable_html(self, lms_id: int) -> str:
        return self.get_html(f"/class_configure/schedule/{lms_id}")

    def lesson_has_date(self, lms_id: int, lesson_id: int) -> bool:
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit/{lms_id}?lesson_id={lesson_id}")
        self._assert_form()
        return bool(self.page.input_value("#lesson_period_date_alt"))

    def lesson_date_value(self, lms_id: int, lesson_id: int) -> tuple[str, str]:
        """قراءة بعدية (الخطوة 5): (التاريخ، الحصة) كما حفظتهما المنصة في نموذج تعديل الدرس."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit/{lms_id}?lesson_id={lesson_id}")
        self._assert_form()
        return self.page.input_value("#lesson_period_date_alt"), self.page.input_value("#lesson_period_number")

    def set_lesson_date(self, lms_id: int, lesson_id: int, d: date, period: int) -> None:
        """يفتح نموذج تعديل الدرس، يضبط التاريخ والحصة فقط، ثم يحفظ. بقية الحقول تبقى كما هي."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit/{lms_id}?lesson_id={lesson_id}")
        self._assert_form()
        # سكربتات المنصة (ومنها jQuery) تُحمَّل متأخرة؛ ننتظرها كي لا تعيد ضبط الحقول بعدنا
        self.page.wait_for_load_state("networkidle")
        # الخادم يقرأ الحقول المخفية year/month/day (Rails multi-param)؛ نضبطها مع الحقل الظاهر مباشرة
        self.page.evaluate(
            """([y, m, d, label]) => {
                const set = (id, v) => { const el = document.getElementById(id); el.value = v;
                                         el.dispatchEvent(new Event('change', {bubbles: true})); };
                const pad = n => String(n).padStart(2, '0');
                set('lesson_period_date', label);
                set('lesson_period_date_alt', `${y}-${pad(m)}-${pad(d)}`);
                set('lesson_period_date_year', y);
                set('lesson_period_date_month', m);
                set('lesson_period_date_day', d);
            }""",
            [d.year, d.month, d.day, f"{d.year} {MONTHS_AR[d.month - 1]} {d.day:02d}"],
        )
        self.page.select_option("#lesson_period_number", str(period))
        with self.page.expect_navigation():
            self.page.click("form[action*='/teacher_lesson/save/'] [name=commit]")
        if "/teacher_lesson/edit/" in self.page.url:
            raise PlatformError("رفضت المنصة الحفظ")

    # ------------------------------------------------------------- التقييمات

    def assessments_html(self, lms_id: int) -> str:
        return self.get_html(f"/teacher_assignments/list/{lms_id}")

    def _open_assessment_form(self, assignment_id: int):
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_quiz_assignment/edit/{assignment_id}?options_tab=true")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not self.page.query_selector(f"form[action*='/teacher_quiz_assignment/save/{assignment_id}']"):
            raise PlatformError(f"نموذج تعديل التقييم غير موجود: {self.page.url}")
        self.page.wait_for_load_state("networkidle")

    def assessment_window(self, assignment_id: int) -> tuple[str, str]:
        self._open_assessment_form(assignment_id)
        return (self.page.input_value("#assignment_begin_at_alt"), self.page.input_value("#assignment_end_at_alt"))

    def set_assessment_window(self, assignment_id: int, begin: datetime, end: datetime, allow_late: bool) -> None:
        """يضبط البداية والاستحقاق والسماح بالتأخير فقط ثم يحفظ؛ بقية إعدادات التقييم كما هي."""
        self._open_assessment_form(assignment_id)
        self.page.evaluate(
            """(vals) => {
                const set = (id, v) => { const el = document.getElementById(id); if (!el) throw new Error(id);
                                         el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); };
                for (const [attr, v] of Object.entries(vals)) {
                    set(`assignment_${attr}`, v.label);
                    set(`assignment_${attr}_alt`, v.alt);
                    for (const part of ['year', 'month', 'day', 'hours', 'minutes'])
                        document.querySelector(`[name="assignment[${attr}(${part})]"]`).value = v[part];
                }
            }""",
            {"begin_at": _dt_fields(begin), "end_at": _dt_fields(end)},
        )
        self.page.set_checked("[name='assignment[allow_late]']", allow_late)
        with self.page.expect_navigation():
            self.page.click(f"form[action*='/teacher_quiz_assignment/save/{assignment_id}'] [name=commit]")
        if "/teacher_quiz_assignment/edit/" in self.page.url:
            raise PlatformError("رفضت المنصة حفظ التقييم")

    def give_assessments(self, lms_id: int, assignment_ids: list[int]) -> None:
        """يحدد التقييمات في قائمة الصف وينفّذ «إسناد التقييم» كما يفعل المعلم."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_assignments/list/{lms_id}")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.wait_for_load_state("networkidle")
        # المربعات مخفية خلف تسمية مخصّصة؛ نحددها مباشرة كما يفعل نقر التسمية
        missing = self.page.evaluate(
            """(ids) => ids.filter(id => {
                const el = document.querySelector(`#assignments input[name="select[]"][value="${id}"]`);
                if (!el) return true;
                el.checked = true;
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return false;
            })""",
            [str(a) for a in assignment_ids],
        )
        if missing:
            raise PlatformError(f"تقييمات غير موجودة في القائمة: {missing}")
        with self.page.expect_navigation():
            self.page.locator(f"a[href='/teacher_assignments/give/{lms_id}']").first.click()

    # ------------------------------------------------------------- الرؤية والإنجاز

    def lesson_shown(self, lms_id: int, lesson_id: int) -> bool | None:
        return parse_default_visibility(self.get_html(f"/teacher_lesson/shown/{lms_id}?lesson_id={lesson_id}"))

    def show_lesson(self, lms_id: int, lesson_id: int) -> None:
        """ما يفعله اختيار «ظاهر» في تبويب الرؤية: الرؤية الافتراضية للجميع. استثناءات الإخفاء تبقى."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/set_shown_default/{lms_id}?lesson_id={lesson_id}&value=Show")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")

    def hide_lesson(self, lms_id: int, lesson_id: int) -> None:
        """الرؤية الافتراضية «مخفي»: الدرس المُنشأ يظهر للطلاب فور إنشائه، فيُخفى حتى يعتمد المعلم نشره."""
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/set_shown_default/{lms_id}?lesson_id={lesson_id}&value=Hide")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if self.lesson_shown(lms_id, lesson_id) is not False:
            raise PlatformError("لم يُخفَ الدرس الجديد؛ تحقّق منه على المنصة")

    def lesson_points_actions(self, lms_id: int, lesson_id: int) -> int:
        return parse_points_actions(self.get_html(f"/teacher_lesson/completion/{lms_id}?lesson_id={lesson_id}"))

    def points_games(self, lms_id: int, lesson_id: int) -> list[str]:
        return parse_points_games(self.get_html(self._points_form_path(lms_id, lesson_id)))

    @staticmethod
    def _points_form_path(lms_id: int, lesson_id: int) -> str:
        return (f"/teacher_lesson/new_rule_action/{lms_id}?lesson_id={lesson_id}"
                "&rule_action_class=AwardPointsAction&rule_class=CompletedLessonRule")

    def add_points_action(self, lms_id: int, lesson_id: int, points: int, game: str, notification: str) -> None:
        """«إجراءات الإنجاز ← إضافة ← منح النقاط» بالرسالة الجاهزة؛ يُنفَّذ عند إنجاز الطالب للدرس."""
        self._throttle()
        self.page.goto(BASE_URL + self._points_form_path(lms_id, lesson_id))
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        form = f"form[action*='/teacher_lesson/create_rule_action/{lms_id}']"
        if not self.page.query_selector(form):
            raise PlatformError(f"نموذج منح النقاط غير موجود: {self.page.url}")
        self.page.select_option(f"{form} [name='rule_action[arg2_id]']", label=game)
        self.page.fill(f"{form} [name='rule_action[points]']", str(points))
        self.page.check(f"{form} [name='rule_action[notification_type]'][value='{notification}']")
        with self.page.expect_navigation():
            self.page.click(f"{form} [name=commit]")

    # ------------------------------------------------------------- منظور الطالب

    def student_view_html(self, lms_id: int) -> str:
        """
        قائمة الدروس كما يراها «طالب عام» (عرض الصف كطالب) ثم العودة إلى عرض المعلم.
        لا يُسجَّل دخول ولا إنجاز. المنصة تبدّل كوكي الجلسة عند التبديل، فيُحفظ بعد العودة وإلا انتهت الجلسة.
        """
        self._throttle()
        back = f"{BASE_URL}/student_class/view_as_teacher/{lms_id}?from=%2Fteacher_lessons%2Flist%2F{lms_id}"
        try:
            self.page.goto(f"{BASE_URL}/teacher_class/submit_view_as_generic_student/{lms_id}"
                           f"?from=%2Fteacher_lessons%2Flist%2F{lms_id}")
            if is_login_url(self.page.url):
                raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
            if f"/student_lessons/list/{lms_id}" not in self.page.url:
                raise PlatformError(f"لم يُفتح عرض الطالب: {self.page.url}")
            self.page.wait_for_load_state("networkidle")
            return self.page.content()
        finally:
            self.page.goto(back)
            if is_login_url(self.page.url):
                raise NotLoggedIn("انتهت الجلسة بعد عرض الطالب - شغّل: python manage.py neo_login")
            self._save_cookies()
            if "/teacher_" not in self.page.url:
                raise PlatformError(f"لم تتم العودة إلى عرض المعلم: {self.page.url}")

    # ------------------------------------------------------------- حزمة التحضير (قراءة فقط)

    PREP_DELAY = (3.0, 6.0)    # ثوانٍ بين طلبات الحزمة: المنصة تردّ 429 عند السرعة
    RETRY_WAITS = (5, 20, 35)  # انتظار متزايد بعد كل 429

    def _polite_get(self, path: str):
        """GET داخل الجلسة بتمهّل 3–6 ث قبل كل طلب، وإعادة المحاولة عند 429 بانتظار 5 ثم 20 ثم 35 ث."""
        for wait in (*self.RETRY_WAITS, None):
            time.sleep(random.uniform(*self.PREP_DELAY))
            self._last = time.monotonic()
            resp = self.context.request.get(f"{BASE_URL}{path}", timeout=180_000)
            self._net(path, resp.status, self._last)
            if resp.status != 429:
                return resp
            if wait is None:
                raise PlatformError(f"المنصة تردّ 429 (طلبات كثيرة) على {path.split('?')[0]} بعد {len(self.RETRY_WAITS)} محاولات")
            live.emit("warn", f"المنصة طلبت التمهّل (429)؛ انتظار {wait} ث ثم إعادة المحاولة", retry=wait)
            time.sleep(wait)

    def _polite_html(self, path: str) -> str:
        resp = self._polite_get(path)
        html = resp.text()
        if is_login_url(resp.url) or is_login_page(html):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not resp.ok:
            raise PlatformError(f"GET {path} -> {resp.status}")
        return html

    def _upload_in_editor(self, path: Path, label: str) -> None:
        """«Upload File» في محرر TinyMCE: يرفع الملف إلى «ملفاتي» ثم يدرج رابطه في آخر المحتوى بعنوانه الظاهر."""
        page = self.page
        page.evaluate("""() => { const e = tinymce.activeEditor; e.selection.select(e.getBody(), true);
                                 e.selection.collapse(false); }""")
        before = page.evaluate("""() => { window.__known = new Set(tinymce.activeEditor.dom.select('a').map(a => a.getAttribute('href')));
                                         return window.__known.size; }""")
        page.locator("[aria-label='Upload File']").first.click()
        deadline = time.monotonic() + 30
        frame = None
        while frame is None and time.monotonic() < deadline:
            frame = next((f for f in page.frames if "uploader/file" in f.url), None)
            page.wait_for_timeout(300)
        if frame is None:
            raise PlatformError("لم تفتح نافذة رفع الملف في المحرر")
        frame.set_input_files("input[type=file]", str(path))
        frame.wait_for_function("document.body.innerText.includes('100%')", timeout=180_000)
        page.wait_for_timeout(4000)  # بعد 100% يسجّل الخادم الملف في «ملفاتي» قبل أن يقبل الإدراج
        page.locator(".tox-dialog button:has-text('حفظ'):visible").first.click()
        page.wait_for_function(f"tinymce.activeEditor.dom.select('a').length > {before}", timeout=30_000)
        page.evaluate(  # الرابط الجديد وحده (المدرَج قد لا يكون الأخير)؛ ما كتبه المعلم من روابط لا يُمس
            """(label) => { const fresh = tinymce.activeEditor.dom.select('a').filter(a => !window.__known.has(a.getAttribute('href')));
                            if (fresh.length !== 1) throw new Error('روابط جديدة غير متوقعة: ' + fresh.length);
                            fresh[0].textContent = label; }""", label)

    def add_notes_files(self, lms_id: int, lesson_id: int, files: list[tuple[Path, str]]) -> None:
        """
        ملفات «ملاحظات المعلم» (التحضير، العرض، ورقة العمل) برفعها وإدراج روابطها بعناوينها في المحرر وحفظ الملاحظات.
        إضافة فقط: ملف عنوانه موجود في الملاحظات لا يُرفع ثانيةً، وما كتبه المعلم يبقى.
        """
        self._throttle()
        self.page.goto(f"{BASE_URL}/teacher_lesson/edit_notes/{lms_id}?lesson_id={lesson_id}", wait_until="load")
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        self.page.wait_for_function("window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized",
                                    timeout=30_000)
        have = set(self.page.evaluate("tinymce.activeEditor.dom.select('a').map(a => a.textContent.trim())"))
        todo = [(path, label) for path, label in files if label not in have]
        for path, label in todo:
            self._upload_in_editor(path, label)
        if todo:
            self.page.evaluate("tinymce.activeEditor.save()")
            with self.page.expect_navigation():
                self.page.click("form[action*='/teacher_lesson/save_notes/'] button[type=submit]")
        names = {f.name.strip() for f in self.lesson_notes_files(lms_id, lesson_id)[0]}
        if missing := [label for _, label in files if label not in names]:
            raise PlatformError(f"لم تظهر الملفات في ملاحظات الدرس بعد الحفظ: {'، '.join(missing)}")

    def lesson_notes_files(self, lms_id: int, lesson_id: int) -> tuple[list[FileLink], str]:
        """ملفات «ملاحظات المعلم»: التحضير والعرض وورقة العمل (والصفحة نفسها للتشخيص)."""
        html = self._polite_html(f"/teacher_lesson/notes/{lms_id}?lesson_id={lesson_id}")
        return parse_file_links(html), html

    def section_files(self, lms_id: int, lesson_id: int, keep=None) -> list[tuple[ParsedSection, list[FileLink]]]:
        """أقسام الدرس من نوع العرض (powerpoint) بترتيبها، ولكل منها ملفات العرض التي فيه.
        keep(name, html): لحفظ الصفحات للتشخيص."""
        sections = parse_sections(self._polite_html(f"/teacher_lesson/show/{lms_id}?lesson_id={lesson_id}"))
        out = []
        for sec in (s for s in sections if s.kind == "powerpoint"):
            html = self._polite_html(f"/teacher_lesson/show/{lms_id}?lesson_id={lesson_id}&section_id={sec.section_id}")
            if keep:
                keep(f"section_{lesson_id}_{sec.section_id}.html", html)
            out.append((sec, [f for f in parse_file_links(html) if f.ext in ("pptx", "ppt")]))
        return out

    def download(self, url: str, path: Path) -> int:
        """ينزّل الملف داخل الجلسة إلى path (عبر ملف مؤقت ثم إعادة تسمية)؛ يعيد حجمه."""
        resp = self._polite_get(url)
        if is_login_url(resp.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not resp.ok:
            raise PlatformError(f"تنزيل {url.split('?')[0]} -> {resp.status}")
        body = resp.body()
        if path.suffix.lower() in (".docx", ".pptx", ".xlsx") and body[:2] != b"PK":
            raise PlatformError(f"لم يصل ملف صالح من {url.split('?')[0]} ({resp.headers.get('content-type', '?')})")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(path)
        return len(body)

    def _assert_form(self):
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not self.page.query_selector("form[action*='/teacher_lesson/save/']"):
            raise PlatformError(f"نموذج تعديل الدرس غير موجود: {self.page.url}")
