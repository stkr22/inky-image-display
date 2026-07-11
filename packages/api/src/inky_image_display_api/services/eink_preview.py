"""Server-side simulation of the Spectra 6 e-ink rendering.

Every preview in the UI used to be plain sRGB, but the panel can only lay
down six inks — the quantize+dither step happens on-device inside the Inky
driver, so operators discovered washed-out or muddy results only after a
~30 s refresh burned them onto the wall. This module reproduces that step
byte-for-byte so the UI can show "how it will look on paper" first.

The palettes and the quantize call are copied from
``inky.inky_el133uf1`` (inky 2.4.0, the version pinned by the controller;
verified against the installed package). All seeded device profiles are
Spectra 6 panels, so a single palette pair covers the whole lineup. Keep
in sync with the controller's driver version if it ever changes.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

# Pure colours used as the quantize targets at saturation 0.0 ...
_DESATURATED_PALETTE = [
    [0, 0, 0],
    [255, 255, 255],
    [255, 255, 0],
    [255, 0, 0],
    [0, 0, 255],
    [0, 255, 0],
]

# ... blended towards these measured ink colours as saturation rises.
# They also double as the output colours of the preview: they are the
# closest thing to what the physical inks look like, which is exactly the
# reality check the preview exists to give.
_SATURATED_PALETTE = [
    [0, 0, 0],
    [161, 164, 165],
    [208, 190, 71],
    [156, 72, 75],
    [61, 59, 94],
    [58, 91, 70],
]

# Match the driver's set_image default so "preview" and "panel" agree
# unless the caller explicitly asks otherwise.
DEFAULT_SATURATION = 0.5


def _palette_blend(saturation: float) -> list[int]:
    """Flat RGB list blending pure and measured palettes (driver copy)."""
    palette: list[int] = []
    for i in range(6):
        rs, gs, bs = (c * saturation for c in _SATURATED_PALETTE[i])
        rd, gd, bd = (c * (1.0 - saturation) for c in _DESATURATED_PALETTE[i])
        palette += [int(rs + rd), int(gs + gd), int(bs + bd)]
    return palette


def render_eink_preview(image_data: bytes, saturation: float = DEFAULT_SATURATION) -> bytes:
    """Quantize + dither like the panel driver; return a viewable PNG.

    The quantize step mirrors ``Inky.set_image`` exactly (Floyd-Steinberg
    against the saturation-blended palette). The preview then paints the
    six result classes with the measured ink colours, because the browser
    should show what the ink looks like — not the idealised pure palette
    the quantizer targets.

    PNG output: the result is flat colour classes plus dither noise, which
    JPEG would smear back into gradients and defeat the purpose.
    """
    saturation = min(1.0, max(0.0, saturation))
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(_palette_blend(saturation))

    with Image.open(BytesIO(image_data)) as original:
        quantized = original.convert("RGB").quantize(6, palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)

    ink_palette: list[int] = [channel for colour in _SATURATED_PALETTE for channel in colour]
    quantized.putpalette(ink_palette)

    output = BytesIO()
    quantized.convert("RGB").save(output, format="PNG")
    return output.getvalue()
