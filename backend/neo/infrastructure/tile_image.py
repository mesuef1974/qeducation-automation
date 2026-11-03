"""
رسم صورة بطاقة الدرس (500×375 كما توصي المنصة): لون الوحدة، ورقم الدرس، وعنوانه،
ورسم بياني يعبّر عن موضوعه (قطع مكافئ بما يميّز الدرس: رأس، محور تناظر، جذور، تقاطع، منطقة متباينة).
"""
import math
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

SIZE = (500, 375)
FONT_CANDIDATES = ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/tahomabd.ttf", "DejaVuSans-Bold.ttf")
BAR = 56  # شريط الوحدة أسفل الصورة
# لوحة الرسم البياني: منطقة فاتحة في النصف السفلي من البطاقة
PLOT = (40, 150, 460, 300)
INK = (30, 30, 30)
SOFT = (255, 255, 255)
ACCENT = (255, 196, 0)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _ar(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(_ar(trial), font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + [cur]


class _Plot:
    """إحداثيات رياضية x∈[-4,4], y∈[-3,5] ← بكسل داخل PLOT."""

    def __init__(self, d: ImageDraw.ImageDraw, color):
        self.d, self.color = d, color
        self.x0, self.y0, self.x1, self.y1 = PLOT
        self.sx = (self.x1 - self.x0) / 8
        self.sy = (self.y1 - self.y0) / 8

    def px(self, x: float, y: float) -> tuple[float, float]:
        return self.x0 + (x + 4) * self.sx, self.y1 - (y + 3) * self.sy

    def axes(self):
        self.d.rounded_rectangle((self.x0 - 14, self.y0 - 12, self.x1 + 14, self.y1 + 12), radius=12, fill=SOFT)
        ox, oy = self.px(0, 0)
        self.d.line((self.x0, oy, self.x1, oy), fill=INK, width=2)
        self.d.line((ox, self.y0, ox, self.y1), fill=INK, width=2)
        for t in range(-3, 4):  # علامات على محور x
            tx, _ = self.px(t, 0)
            self.d.line((tx, oy - 3, tx, oy + 3), fill=INK, width=1)

    def parabola(self, a: float, h: float, k: float, width: int = 4):
        pts = []
        for i in range(0, 161):
            x = -4 + i / 20
            y = a * (x - h) ** 2 + k
            if -3.2 <= y <= 5.2:
                pts.append(self.px(x, y))
        self.d.line(pts, fill=self.color, width=width, joint="curve")

    def dot(self, x: float, y: float, fill=ACCENT, r: int = 6):
        cx, cy = self.px(x, y)
        self.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=INK, width=2)

    def dashed_vertical(self, x: float):
        px, _ = self.px(x, 0)
        for y in range(self.y0, self.y1, 10):
            self.d.line((px, y, px, min(y + 5, self.y1)), fill=INK, width=2)

    def shade_between_roots(self, a, h, k, r1, r2):
        pts = [self.px(x / 20, a * (x / 20 - h) ** 2 + k) for x in range(int(r1 * 20), int(r2 * 20) + 1)]
        base = [self.px(r2, 0), self.px(r1, 0)]
        self.d.polygon(pts + base, fill=(255, 196, 0, 120))


MOTIF_DRAWERS = {}


def _motif(name):
    def wrap(fn):
        MOTIF_DRAWERS[name] = fn
        return fn
    return wrap


@_motif("parabola")
def _parabola(p: _Plot):
    p.parabola(0.5, 0, -1)


@_motif("features")
def _features(p: _Plot):
    p.parabola(0.5, 1, -2)
    p.dashed_vertical(1)
    p.dot(-1, 0)
    p.dot(3, 0)
    p.dot(1, -2, fill=(255, 255, 255))


@_motif("vertex")
def _vertex(p: _Plot):
    p.parabola(-0.6, -1, 3)
    p.dashed_vertical(-1)
    p.dot(-1, 3, fill=(255, 255, 255), r=7)


@_motif("intercept")
def _intercept(p: _Plot):
    p.parabola(0.5, 1.5, 0.5)
    p.dot(0, 0.5 * 1.5 ** 2 + 0.5)


@_motif("roots")
def _roots(p: _Plot):
    p.parabola(0.7, 0.5, -2)
    for r in (0.5 - (2 / 0.7) ** 0.5, 0.5 + (2 / 0.7) ** 0.5):
        p.dot(r, 0)


@_motif("inequality")
def _inequality(p: _Plot):
    a, h, k = 0.6, 0, -2.4
    r = (2.4 / a) ** 0.5
    p.shade_between_roots(a, h, k, -r, r)
    p.parabola(a, h, k)


def _curve(p: _Plot, fn, lo: float, hi: float, width: int = 4):
    pts = [p.px(lo + i * (hi - lo) / 80, fn(lo + i * (hi - lo) / 80)) for i in range(81)]
    p.d.line([q for q in pts if p.y0 - 20 <= q[1] <= p.y1 + 20], fill=p.color, width=width, joint="curve")


@_motif("limit")
def _limit(p: _Plot):
    f = lambda x: 0.25 * (x + 1) ** 2 - 1  # noqa: E731
    _curve(p, f, -4, 0.85)
    _curve(p, f, 1.15, 3.6)
    p.dot(1, f(1), fill=SOFT, r=6)  # فجوة عند x = 1
    p.dashed_vertical(1)
    for x, dx in ((-0.6, 0.35), (2.6, -0.35)):  # سهما الاقتراب
        x0, y0 = p.px(x, f(x))
        x1, y1 = p.px(x + dx, f(x + dx))
        p.d.line((x0, y0, x1, y1), fill=INK, width=3)
        p.d.ellipse((x1 - 4, y1 - 4, x1 + 4, y1 + 4), fill=INK)


@_motif("continuity")
def _continuity(p: _Plot):
    _curve(p, lambda x: 0.5 * x + 1, -4, 0)
    _curve(p, lambda x: 0.5 * x - 1.5, 0, 3.8)
    p.dot(0, 1, fill=p.color, r=6)
    p.dot(0, -1.5, fill=SOFT, r=6)


@_motif("tangent")
def _tangent(p: _Plot):
    f = lambda x: 0.3 * x ** 2 - 1  # noqa: E731
    _curve(p, f, -3.6, 3.6)
    x0, m = 1.5, 0.6 * 1.5  # مماس عند x0 بميل f′(x0)
    a, b = p.px(x0 - 2.2, f(x0) - 2.2 * m), p.px(x0 + 2.2, f(x0) + 2.2 * m)
    p.d.line((*a, *b), fill=INK, width=3)
    p.dot(x0, f(x0))


@_motif("sine")
def _sine(p: _Plot):
    _curve(p, lambda x: 2 * math.sin(1.3 * x), -4, 4)
    p.dot(0, 0, fill=SOFT, r=5)


def render(spec: dict, out: Path) -> Path:
    img = Image.new("RGBA", SIZE, spec["color"])
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((0, SIZE[1] - BAR, SIZE[0], SIZE[1]), fill=(0, 0, 0))
    d.rounded_rectangle((24, 18, 86, 72), radius=12, fill="white")  # الرقم يسارًا والعنوان يمينًا (RTL)
    d.text((55, 45), str(spec["number"]), fill=spec["color"], font=_font(30), anchor="mm")
    title_font = _font(28)
    lines = _wrap(d, spec["title"], title_font, SIZE[0] - 130)[:2]
    y = 46 if len(lines) == 1 else 30
    for line in lines:
        d.text((SIZE[0] - 24, y), _ar(line), fill="white", font=title_font, anchor="rm")
        y += 36
    plot = _Plot(d, spec["color"])
    plot.axes()
    MOTIF_DRAWERS.get(spec.get("motif", "parabola"), _parabola)(plot)
    d.text((SIZE[0] / 2, SIZE[1] - 28), _ar(spec["unit"]), fill="white", font=_font(20), anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG")
    return out
