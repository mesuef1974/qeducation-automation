"""رسم صورة بطاقة الدرس (500×375 كما توصي المنصة) بلون الوحدة وعنوان الدرس، بخط عربي مشكّل."""
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

SIZE = (500, 375)
FONT_CANDIDATES = ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/tahomabd.ttf", "DejaVuSans-Bold.ttf")


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


def render(spec: dict, out: Path) -> Path:
    img = Image.new("RGB", SIZE, spec["color"])
    d = ImageDraw.Draw(img)
    d.rectangle((0, SIZE[1] - 56, SIZE[0], SIZE[1]), fill=(0, 0, 0))  # شريط الوحدة
    d.rounded_rectangle((SIZE[0] - 92, 24, SIZE[0] - 24, 84), radius=14, fill="white")
    d.text((SIZE[0] - 58, 54), str(spec["number"]), fill=spec["color"], font=_font(34), anchor="mm")
    title_font = _font(36)
    lines = _wrap(d, spec["title"], title_font, SIZE[0] - 60)[:3]
    y = 190 - 22 * len(lines)
    for line in lines:
        d.text((SIZE[0] / 2, y), _ar(line), fill="white", font=title_font, anchor="mm")
        y += 46
    d.text((SIZE[0] / 2, SIZE[1] - 28), _ar(spec["unit"]), fill="white", font=_font(20), anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out
