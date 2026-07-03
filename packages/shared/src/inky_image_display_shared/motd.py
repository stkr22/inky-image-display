"""Message-of-the-day content parts and default generation prompt.

The MOTD feature decomposes one generated story into small content parts,
each rendered as a full e-ink screen. Part keys are shared between the API
(rendering, validation) and the web UI (assignment editing), so they live
in the shared package.
"""

from __future__ import annotations

# Canonical part order. Rotation on a device follows the operator's chosen
# order, but the UI offers parts in this sequence.
PART_KEYS: tuple[str, ...] = ("what", "why", "when", "image", "qr", "takeaway")

# Text parts may be combined two-per-screen ("what+when") when a setup has
# fewer screens than parts. Only text parts stack — the AI image and the QR
# code always get a full screen.
TEXT_PARTS: frozenset[str] = frozenset({"what", "why", "when", "takeaway"})


def is_valid_part(key: str) -> bool:
    """Check a part key, accepting compound ``a+b`` text-part pairs."""
    if key in PART_KEYS:
        return True
    first, sep, second = key.partition("+")
    if not sep or "+" in second:
        return False
    return first in TEXT_PARTS and second in TEXT_PARTS and first != second


# Operator-editable theme brief. The structural output contract (JSON
# fields, length limits) is appended in code by the generation call so
# edits here can't break parsing — the prompt only steers topic and tone.
DEFAULT_MOTD_PROMPT = """\
Find one uplifting, TRUE story worth sharing today, choosing the strongest \
match from these themes:
- Great science: a discovery or breakthrough that expands what humanity \
knows or can do.
- Achieved together: something people accomplished as a community or \
through collective political action.
- Positive and funny: a lighthearted story that genuinely happened and \
makes people smile.
- Everyday heroism: a small act or achievement — not world-changing, but \
still great.

Prefer stories that leave the reader encouraged. Avoid tragedy framed as \
inspiration, and avoid divisive political conflict."""
