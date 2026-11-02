"""
عميل منصة قطر للتعليم عبر Playwright بملف تعريف دائم (.neo_profile).
الدخول يتم يدويًا من المعلم مرة واحدة (neo_login)؛ لا تُخزَّن أي كلمة مرور.
"""
import json
import time
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from neo.infrastructure.parsers import (
    parse_sections, parse_tiles,
    is_login_page,
    is_login_url,
    parse_default_visibility,
    parse_points_actions,
    parse_points_games,
)

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


class NotLoggedIn(RuntimeError):
    pass


class PlatformError(RuntimeError):
    pass


class BrowserBusy(PlatformError):
    pass


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
        return self

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

    def login_interactive(self, timeout_s: int = 600) -> None:
        self.page.goto(f"{BASE_URL}/user_dashboard")
        self.page.wait_for_url("**/user_dashboard**", timeout=timeout_s * 1000)
        self._save_cookies()

    def get_html(self, path: str) -> str:
        self._throttle()
        resp = self.context.request.get(f"{BASE_URL}{path}")
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

    def section_names(self, lms_id: int, lesson_id: int) -> list[str]:
        return [s.title for s in parse_sections(self.lesson_page_html(lms_id, lesson_id))]

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

    def _assert_form(self):
        if is_login_url(self.page.url):
            raise NotLoggedIn("انتهت الجلسة - شغّل: python manage.py neo_login")
        if not self.page.query_selector("form[action*='/teacher_lesson/save/']"):
            raise PlatformError(f"نموذج تعديل الدرس غير موجود: {self.page.url}")
