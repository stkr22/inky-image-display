"""Render message-of-the-day content parts as display-ready screens.

Each part becomes a JPEG at the exact panel resolution (the controller
rejects any size mismatch), so displaying MOTD content is an ordinary
push through the existing S3 + MQTT pipeline. Text is set large on a
plain white background — Spectra 6 panels dither photos but render flat
high-contrast layouts crisply, and the kicker uses one of the panel's
native ink colours so it survives quantisation.
"""

from __future__ import annotations

import functools
from importlib import resources
from io import BytesIO
from typing import TYPE_CHECKING

import qrcode
from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

if TYPE_CHECKING:
    from inky_image_display_api.schemas import MotdRenderRequest

_BACKGROUND = "#ffffff"
_TEXT_COLOR = "#101010"
# Saturated red — a native Spectra 6 ink, so the accent stays clean on panel.
_KICKER_COLOR = "#b0201c"

_KICKERS = {
    "what": "WHAT HAPPENED?",
    "why": "WHY IT MATTERS",
    "when": "WHEN?",
    "takeaway": "TAKEAWAY",
    "qr": "MORE DETAILS",
}

# Font sizes are searched downwards from a fraction of the panel's short
# edge; the floor keeps degenerate inputs readable rather than microscopic.
_MIN_BODY_SIZE = 16


def _font_path(name: str) -> str:
    return str(resources.files("inky_image_display_api").joinpath(f"assets/fonts/{name}"))


@functools.lru_cache(maxsize=64)
def _regular(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path("DejaVuSans.ttf"), size)


@functools.lru_cache(maxsize=64)
def _bold(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path("DejaVuSans-Bold.ttf"), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word wrap using rendered widths.

    Words wider than the box get their own line rather than looping forever.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_body(
    draw: ImageDraw.ImageDraw,
    text: str,
    box_width: int,
    box_height: int,
    max_size: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Find the largest body size whose wrapped text fits the box.

    Returns (font, wrapped lines, line height). Binary search over the size
    range: wrapped height shrinks monotonically as the size drops.
    """
    lo, hi = _MIN_BODY_SIZE, max(max_size, _MIN_BODY_SIZE)
    best: tuple[ImageFont.FreeTypeFont, list[str], int] | None = None
    while lo <= hi:
        size = (lo + hi) // 2
        font = _regular(size)
        line_height = round(size * 1.3)
        lines = _wrap(draw, text, font, box_width)
        fits_width = all(draw.textlength(line, font=font) <= box_width for line in lines)
        if fits_width and len(lines) * line_height <= box_height:
            best = (font, lines, line_height)
            lo = size + 1
        else:
            hi = size - 1
    if best is None:
        font = _regular(_MIN_BODY_SIZE)
        return font, _wrap(draw, text, font, box_width), round(_MIN_BODY_SIZE * 1.3)
    return best


def _draw_section(  # noqa: PLR0913 — a layout box is inherently many scalars
    draw: ImageDraw.ImageDraw,
    kicker: str,
    body: str,
    *,
    left: int,
    top: int,
    width: int,
    height: int,
    short_edge: int,
    max_body_size: int,
) -> None:
    """Draw one kicker + body block inside the given box."""
    kicker_size = max(round(short_edge * 0.042), 14)
    kicker_font = _bold(kicker_size)
    draw.text((left, top), kicker, font=kicker_font, fill=_KICKER_COLOR)

    body_top = top + round(kicker_size * 2.0)
    body_height = height - (body_top - top)
    font, lines, line_height = _fit_body(draw, body, width, body_height, max_size=max_body_size)
    y = body_top
    for line in lines:
        draw.text((left, y), line, font=font, fill=_TEXT_COLOR)
        y += line_height


def render_text_screen(sections: list[tuple[str, str]], width: int, height: int) -> bytes:
    """Render one or two (kicker, body) sections as a full screen."""
    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    short_edge = min(width, height)
    margin = round(short_edge * 0.08)
    content_width = width - 2 * margin
    content_height = height - 2 * margin

    max_body_size = round(short_edge * 0.16)
    if len(sections) == 1:
        kicker, body = sections[0]
        _draw_section(
            draw,
            kicker,
            body,
            left=margin,
            top=margin,
            width=content_width,
            height=content_height,
            short_edge=short_edge,
            max_body_size=max_body_size,
        )
    else:
        gap = round(short_edge * 0.06)
        section_height = (content_height - gap) // 2
        kicker_offset = round(max(round(short_edge * 0.042), 14) * 2.0)
        # Fit both bodies first and share the smaller size — independently
        # fitted sections make a short body tower over a long one.
        shared_size = min(
            int(_fit_body(draw, body, content_width, section_height - kicker_offset, max_size=max_body_size)[0].size)
            for _, body in sections[:2]
        )
        for index, (kicker, body) in enumerate(sections[:2]):
            top = margin + index * (section_height + gap)
            _draw_section(
                draw,
                kicker,
                body,
                left=margin,
                top=top,
                width=content_width,
                height=section_height,
                short_edge=short_edge,
                max_body_size=shared_size,
            )
        divider_y = margin + section_height + gap // 2
        draw.line(
            [(margin, divider_y), (width - margin, divider_y)],
            fill=_TEXT_COLOR,
            width=max(short_edge // 300, 2),
        )

    return _to_jpeg(image)


def render_qr_screen(url: str, caption: str | None, width: int, height: int) -> bytes:
    """Render a centered QR code with the "more details" kicker and caption."""
    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    short_edge = min(width, height)

    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color=_TEXT_COLOR, back_color=_BACKGROUND).get_image().convert("RGB")
    # Nearest-neighbour keeps module edges sharp — a blurred QR misreads.
    qr_size = round(short_edge * 0.55)
    qr_image = qr_image.resize((qr_size, qr_size), resample=Resampling.NEAREST)

    kicker_size = max(round(short_edge * 0.05), 16)
    kicker_font = _bold(kicker_size)
    kicker = _KICKERS["qr"]
    kicker_width = draw.textlength(kicker, font=kicker_font)

    caption_font = _regular(max(round(short_edge * 0.035), 14))
    caption_text = (caption or "").strip()

    block_height = kicker_size + round(short_edge * 0.05) + qr_size
    if caption_text:
        block_height += round(short_edge * 0.05) + int(caption_font.size)
    top = max((height - block_height) // 2, 0)

    draw.text(((width - kicker_width) // 2, top), kicker, font=kicker_font, fill=_KICKER_COLOR)
    qr_top = top + kicker_size + round(short_edge * 0.05)
    image.paste(qr_image, ((width - qr_size) // 2, qr_top))
    if caption_text:
        caption_width = draw.textlength(caption_text, font=caption_font)
        caption_top = qr_top + qr_size + round(short_edge * 0.05)
        draw.text(((width - caption_width) // 2, caption_top), caption_text, font=caption_font, fill=_TEXT_COLOR)

    return _to_jpeg(image)


def render_part(
    part_key: str,
    message: MotdRenderRequest,
    width: int,
    height: int,
) -> bytes | None:
    """Render any part key (including compound ``a+b``) to screen bytes.

    Returns ``None`` when the part cannot be rendered for this story —
    QR without a source URL or empty text.
    """
    if part_key == "qr":
        if not message.source_url:
            return None
        return render_qr_screen(message.source_url, message.source_title or message.headline, width, height)

    bodies = {
        "what": message.what,
        "why": message.why,
        "when": message.when_text,
        "takeaway": message.takeaway,
    }
    sections: list[tuple[str, str]] = []
    for piece in part_key.split("+"):
        body = bodies.get(piece)
        if not body:
            return None
        sections.append((_KICKERS[piece], body))
    return render_text_screen(sections, width, height)


def _to_jpeg(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()
