"""الهوية البصرية: خطوط محلية بلا طلب خارجي، ومقياس أحجام واحد في tokens.css."""
import re
from pathlib import Path

from django.conf import settings

ROOT = settings.PROJECT_ROOT
ASSETS = ROOT / "docs" / "assets"
SRC = ROOT / "frontend" / "src"
SIZE = re.compile(r"font-size:\s*[0-9.]+px|font:\s*(?:\d+\s+)?[0-9.]+px")


def _style_files():
    yield from SRC.rglob("*.vue")
    yield from SRC.rglob("*.css")
    yield ASSETS / "pages.css"
    yield ASSETS / "admin.css"


def test_fonts_are_local_and_every_face_file_exists():
    css = (ASSETS / "tokens.css").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in css and "@import" not in css
    urls = re.findall(r'url\("\./(fonts/[^"]+\.woff2)"\)', css)
    assert len(urls) == 14
    missing = [u for u in urls if not (ASSETS / u).is_file()]
    assert not missing, missing
    assert all(Path(u).stat().st_size > 1000 for u in (ASSETS / u for u in urls))
    for lic in ("IBM-Plex-Sans-Arabic", "Reem-Kufi", "IBM-Plex-Mono"):  # رخصة OFL تُرفق مع الخطوط
        assert (ASSETS / "fonts" / f"LICENSE-{lic}.txt").is_file()


def test_no_third_party_hosts_in_pages():
    pages = [ROOT / "frontend" / "index.html", *ROOT.glob("docs/*.html"), *ROOT.glob("docs/report/*.html"),
             ASSETS / "pages.css", ASSETS / "theme.js"]
    bad = [p.name for p in pages if re.search(r"fonts\.(googleapis|gstatic)\.com", p.read_text(encoding="utf-8"))]
    assert not bad, bad


def test_no_literal_font_sizes_outside_tokens():
    """المقياس --fs-* في tokens.css وحده؛ clamp() للعناوين المرنة مستثنى، ورسم SVG بوحدات viewBox."""
    bad = []
    for path in _style_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SIZE.search(line) and "clamp(" not in line and not (path.name == "AutomationDiagram.vue" and "fill:" in line):
                bad.append(f"{path.relative_to(ROOT)}:{n}")
    assert not bad, f"font-size حرفي بدل var(--fs-*): {bad}"


def test_no_text_below_12px():
    css = (ASSETS / "tokens.css").read_text(encoding="utf-8")
    sizes = {k: int(v) for k, v in re.findall(r"--fs-(\w+):\s*(\d+)px", css)}
    assert min(sizes.values()) >= 12 and sizes["body"] == 16


def test_woff2_served_from_docs(db, client):
    assert client.get("/docs/assets/fonts/ibm-plex-sans-arabic-arabic-400-normal.woff2").status_code == 200


# ---- التدقيق الآلي وتوحيد الثيم ----

def test_ui_audit_judge_blocks_serious_and_overflow():
    from neo.management.commands.neo_ui_audit import judge

    v = [{"id": "color-contrast", "impact": "serious", "nodes": [{"target": [".pill"]}, {"target": ["td"]}]},
         {"id": "region", "impact": "moderate", "nodes": [{"target": ["div"]}]}]
    out = judge(v, overflow=0, width=375)
    assert len(out) == 1 and "color-contrast" in out[0] and ".pill" in out[0]  # المتوسط لا يُفشل، ولا HTML
    assert judge([], overflow=2, width=320) and not judge([], overflow=1, width=320)


def test_ui_audit_diff_ratio(tmp_path):
    from PIL import Image

    from neo.management.commands.neo_ui_audit import diff_ratio

    a, b, c = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    Image.new("RGB", (10, 10), "white").save(a)
    Image.new("RGB", (10, 10), "white").save(b)
    img = Image.new("RGB", (10, 10), "white")
    img.paste("black", (0, 0, 5, 10))
    img.save(c)
    assert diff_ratio(a, b) == 0 and diff_ratio(a, c) == 0.5
    Image.new("RGB", (4, 4)).save(tmp_path / "d.png")
    assert diff_ratio(a, tmp_path / "d.png") == 1.0


def test_theme_logic_has_a_single_source():
    """منطق الثيم في docs/assets/theme.js وحده؛ Vue وindex.html يستعملانه ولا يكرّرانه."""
    use = (SRC / "composables" / "useTheme.ts").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "localStorage" not in use and "NeoTheme" in use
    assert "localStorage" not in index and "<!--theme-core-->" in index
    core = (ASSETS / "theme.js").read_text(encoding="utf-8")
    assert "window.NeoTheme" in core and core.count('getItem(KEY)') == 1


def test_design_system_page_uses_only_shared_css():
    page = (ROOT / "docs" / "design-system.html").read_text(encoding="utf-8")
    for css in ("tokens.css", "pages.css", "components.css"):
        assert f"assets/{css}" in page
    assert "fonts.googleapis" not in page
    assert not re.search(r"font-size:\s*[0-9.]+px", page) and not re.search(r"#[0-9a-fA-F]{6}\b", page.split("<script>")[0])
