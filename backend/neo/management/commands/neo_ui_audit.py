"""
python manage.py neo_ui_audit                     → تدقيق الواجهة الحية: axe (WCAG 2.2 AA) + تجاوز أفقي، صفحات التطبيق وصفحة نظام التصميم
                                                    × ثيمان × عرض 320 و375 و1024، ويقارن لقطات صفحة نظام التصميم بالمرجع
python manage.py neo_ui_audit --update-baseline   → يعتمد اللقطات الحالية مرجعًا (frontend/tests/baseline)
متصفح Edge بلا واجهة وبسياق نظيف (لا ملف الدخول)، قراءة فقط، ولا يكتب شيئًا على المنصة.
لا لقطات ولا HTML لصفحات التطبيق (فيها أسماء طلاب): يُبلَّغ بقاعدة axe ومحدد العنصر وعدد المخالفات فقط؛
اللقطات المرجعية لصفحة نظام التصميم وحدها لأنها ثابتة بلا بيانات شخصية.
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from playwright.sync_api import sync_playwright

ROUTES = ["/app/", "/app/review", "/app/lessons", "/app/content", "/app/live", "/app/log", "/app/swot", "/app/usage"]
DESIGN_SYSTEM = "/docs/design-system.html"
VIEWPORTS = [(320, 700), (375, 812), (1024, 768)]
THEMES = ["light", "dark"]
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
BLOCKING = {"serious", "critical"}
MAX_DIFF = 0.002  # نسبة البكسلات المختلفة المسموحة في اللقطة المرجعية (تنعيم الحواف)

AXE = settings.PROJECT_ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
BASELINE = settings.PROJECT_ROOT / "frontend" / "tests" / "baseline"
OUT = settings.PROJECT_ROOT / ".local" / "ui_audit"


def _target(n: dict) -> str:
    return re.sub(r'\[([\w-]+)="[^"]*"\]', r'[\1]', str(n['target'][0]))  # قيم السمات قد تحمل أسماء


def judge(violations: list[dict], overflow: int, width: int) -> list[str]:
    """مخالفات تُفشل التدقيق: axe الجسيمة، وتجاوز أفقي. لا ينقل HTML (قد يحمل أسماء)."""
    problems = [f"{v['id']} [{v['impact']}] × {len(v['nodes'])}: {', '.join(_target(n) for n in v['nodes'][:3])}"
                for v in violations if v["impact"] in BLOCKING]
    if overflow > 1:
        problems.append(f"تجاوز أفقي: عرض المستند أكبر من الشاشة بـ {overflow}px (العرض {width})")
    return problems


def diff_ratio(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops

    with Image.open(a).convert("RGB") as x, Image.open(b).convert("RGB") as y:
        if x.size != y.size:
            return 1.0
        box = ImageChops.difference(x, y).convert("L").point(lambda v: 255 if v > 8 else 0)
        changed = box.histogram()[255]
        return changed / (x.size[0] * x.size[1])


class Command(BaseCommand):
    help = "تدقيق الواجهة الحية: وصول (axe) وتجاوب ولقطات مرجعية لنظام التصميم."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default="http://127.0.0.1:8777")
        parser.add_argument("--update-baseline", action="store_true")

    def handle(self, *args, base_url, update_baseline, **opts):
        if not AXE.is_file():
            raise CommandError("axe-core غير مثبّت: cd frontend && npm ci")
        BASELINE.mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
        failures, checked = [], 0
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel=settings.NEO_BROWSER_CHANNEL, headless=True)
            try:
                for theme in THEMES:
                    for width, height in VIEWPORTS:
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      locale="ar-QA")
                        context.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}') }} catch (e) {{}}")
                        page = context.new_page()
                        for route in [*ROUTES, DESIGN_SYSTEM]:
                            checked += 1
                            failures += self._audit(page, base_url, route, theme, width, update_baseline)
                        context.close()
            finally:
                browser.close()
        for line in failures:
            self.stdout.write(self.style.ERROR(line))
        if failures:
            raise CommandError(f"{len(failures)} مخالفة في {checked} فحصًا")
        self.stdout.write(self.style.SUCCESS(f"سليم: {checked} فحصًا (صفحات × ثيمان × 3 أعراض)"
                                             + (" · حُدّث المرجع" if update_baseline else "")))

    def _audit(self, page, base: str, route: str, theme: str, width: int, update: bool) -> list[str]:
        tag = f"{route} · {theme} · {width}"
        page.goto(base + route, wait_until="networkidle")
        page.wait_for_timeout(1200)  # الواجهة تجلب بياناتها بعد التحميل
        page.add_script_tag(path=str(AXE))
        result = page.evaluate("""async (tags) => {
            const r = await axe.run(document, { runOnly: { type: 'tag', values: tags } });
            return { violations: r.violations.map(v => ({ id: v.id, impact: v.impact,
                     nodes: v.nodes.map(n => ({ target: n.target })) })),
                     overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
        }""", TAGS)
        problems = [f"{tag} → {p}" for p in judge(result["violations"], result["overflow"], width)]
        if route == DESIGN_SYSTEM:
            problems += self._baseline(page, tag, theme, width, update)
        return problems

    def _baseline(self, page, tag: str, theme: str, width: int, update: bool) -> list[str]:
        name = f"ds-{theme}-{width}.png"
        ref, new = BASELINE / name, OUT / name
        page.screenshot(path=str(new), full_page=True)
        if update or not ref.exists():
            if not update:
                return [f"{tag} → لا لقطة مرجعية؛ شغّل --update-baseline مرة بعد مراجعتها"]
            ref.write_bytes(new.read_bytes())
            return []
        ratio = diff_ratio(ref, new)
        if ratio > MAX_DIFF:
            return [(f"{tag} → اختلفت اللقطة عن المرجع بنسبة {ratio:.2%} (الجديدة في .local/ui_audit/{name}؛ "
                     "إن كان التغيير مقصودًا فشغّل --update-baseline)")]
        return []
