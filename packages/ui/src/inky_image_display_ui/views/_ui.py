"""Design-system primitives for the Inky UI.

Holds the global stylesheet (CSS variables, font import, utility classes used
by the bento grid) and tiny Python wrappers so views compose tiles, stats and
badges without sprinkling Tailwind soup everywhere.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal

from nicegui import events, ui

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


_GLOBAL_CSS = """
:root {
  --ink-bg: #FAFBFC;
  --ink-surface: #FFFFFF;
  --ink-border: #E6E8EC;
  --ink-text: #0B1220;
  --ink-muted: #5B6478;
  --ink-accent: #3D5AFE;
  --ink-accent-soft: #EEF1FF;
  --ink-success: #10B981;
  --ink-warn: #F59E0B;
  --ink-danger: #EF4444;
}

html, body, .q-page, .nicegui-content {
  background: var(--ink-bg) !important;
  color: var(--ink-text);
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  -webkit-font-smoothing: antialiased;
}

.q-page-container, .nicegui-content { padding: 0 !important; }

/* Hide the default NiceGUI header padding gap */
.q-layout, .q-page-container > .q-page { background: var(--ink-bg); }

.ink-muted { color: var(--ink-muted); }
.ink-numeric { font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }

/* Bento grid + tiles */
.bento-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 16px;
  width: 100%;
}
@media (max-width: 768px) {
  .bento-grid { grid-template-columns: 1fr; }
  .bento-grid > * { grid-column: span 1 / span 1 !important; grid-row: auto !important; }
}

.bento-tile {
  background: var(--ink-surface);
  border: 1px solid var(--ink-border);
  border-radius: 20px;
  padding: 20px;
  box-shadow: 0 1px 2px rgba(11, 18, 32, 0.04);
  transition: box-shadow 180ms ease-out, transform 180ms ease-out, border-color 180ms ease-out;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.bento-tile.is-clickable { cursor: pointer; }
.bento-tile.is-clickable:hover {
  box-shadow: 0 4px 16px rgba(11, 18, 32, 0.06);
  transform: translateY(-2px);
  border-color: #D7DBE2;
}
@media (prefers-reduced-motion: reduce) {
  .bento-tile { transition: none; }
  .bento-tile.is-clickable:hover { transform: none; }
}

.ink-eyebrow {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-muted);
}

.ink-h1 { font-size: 40px; line-height: 1.1; font-weight: 600; letter-spacing: -0.02em; }
.ink-h2 { font-size: 28px; line-height: 1.2; font-weight: 600; letter-spacing: -0.01em; }
.ink-h3 { font-size: 20px; line-height: 1.3; font-weight: 600; }
.ink-body { font-size: 16px; line-height: 1.55; }
.ink-small { font-size: 13px; line-height: 1.5; color: var(--ink-muted); }

/* Stat tile body */
.ink-stat-value { font-size: 44px; line-height: 1; font-weight: 600; letter-spacing: -0.02em; }
.ink-stat-label { font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--ink-muted); }
.ink-stat-hint { font-size: 13px; color: var(--ink-muted); }

/* Badges */
.ink-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 500;
  padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--ink-border); background: var(--ink-surface);
  color: var(--ink-text);
}
.ink-badge::before {
  content: ''; width: 6px; height: 6px; border-radius: 999px; background: currentColor;
}
.ink-badge.ok {
  color: var(--ink-success);
  border-color: rgba(16, 185, 129, 0.25);
  background: rgba(16, 185, 129, 0.08);
}
.ink-badge.warn {
  color: var(--ink-warn);
  border-color: rgba(245, 158, 11, 0.25);
  background: rgba(245, 158, 11, 0.08);
}
.ink-badge.muted { color: var(--ink-muted); }
.ink-badge.accent {
  color: var(--ink-accent);
  border-color: rgba(61, 90, 254, 0.25);
  background: var(--ink-accent-soft);
}

/* Top nav */
.ink-nav {
  position: sticky; top: 0; z-index: 40;
  display: flex; align-items: center; gap: 24px;
  padding: 14px 24px;
  background: rgba(250, 251, 252, 0.85);
  backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--ink-border);
}
.ink-nav-brand {
  display: flex; align-items: center; gap: 10px;
  font-weight: 600; letter-spacing: -0.01em; cursor: pointer;
}
.ink-nav-brand-dot { width: 10px; height: 10px; border-radius: 3px; background: var(--ink-accent); }
.ink-nav-links { display: flex; gap: 6px; align-items: center; }
.ink-nav-link {
  position: relative;
  padding: 8px 12px; border-radius: 10px;
  font-size: 14px; font-weight: 500; color: var(--ink-muted);
  text-decoration: none; cursor: pointer;
  transition: color 120ms ease-out, background 120ms ease-out;
}
.ink-nav-link:hover { color: var(--ink-text); background: var(--ink-accent-soft); }
.ink-nav-link.is-active { color: var(--ink-text); }
.ink-nav-link.is-active::after {
  content: ''; position: absolute; left: 12px; right: 12px; bottom: -14px; height: 2px;
  background: var(--ink-accent); border-radius: 2px;
}
@media (max-width: 768px) {
  .ink-nav-links { display: none; }
}
.ink-nav-mobile-toggle { display: none; }
@media (max-width: 768px) {
  .ink-nav-mobile-toggle { display: inline-flex; }
}

/* Buttons (custom — flat over Quasar primaries) */
.ink-btn {
  display: inline-flex; align-items: center; gap: 8px;
  height: 40px; padding: 0 16px; border-radius: 10px;
  font-size: 14px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent;
  transition: background 120ms ease-out, border-color 120ms ease-out, color 120ms ease-out;
}
.ink-btn-primary { background: var(--ink-accent); color: white; }
.ink-btn-primary:hover { background: #2F4AE0; }
.ink-btn-ghost { background: transparent; color: var(--ink-text); border-color: var(--ink-border); }
.ink-btn-ghost:hover { background: var(--ink-accent-soft); border-color: var(--ink-accent); color: var(--ink-accent); }
.ink-btn-icon { width: 40px; padding: 0; justify-content: center; }

/* Action cards (used inside the "Quick actions" tile) */
.ink-action-card {
  padding: 16px;
  border: 1px solid var(--ink-border);
  border-radius: 14px;
  background: var(--ink-surface);
  display: flex; gap: 12px; align-items: center;
  cursor: pointer;
  transition: border-color 120ms ease-out, background 120ms ease-out;
  flex: 1; min-width: 220px;
}
.ink-action-card:hover { border-color: var(--ink-accent); background: var(--ink-accent-soft); }
.ink-action-icon {
  width: 40px; height: 40px; border-radius: 10px;
  background: var(--ink-accent-soft); color: var(--ink-accent);
  display: inline-flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}

/* Thumbnails (recent activity strip) */
.ink-thumb {
  cursor: pointer; overflow: hidden;
  border-radius: 14px; border: 1px solid var(--ink-border); background: var(--ink-surface);
  transition: border-color 120ms ease-out, transform 180ms ease-out;
}
.ink-thumb:hover { border-color: var(--ink-accent); transform: translateY(-2px); }
@media (prefers-reduced-motion: reduce) {
  .ink-thumb { transition: none; }
  .ink-thumb:hover { transform: none; }
}

/* Device mini-card (devices tile + devices page) */
.ink-device-card {
  border: 1px solid var(--ink-border);
  border-radius: 14px;
  background: var(--ink-surface);
  overflow: hidden;
  display: flex; flex-direction: column;
  cursor: pointer;
  transition: border-color 120ms ease-out, transform 180ms ease-out;
}
.ink-device-card:hover { border-color: var(--ink-accent); transform: translateY(-2px); }
@media (prefers-reduced-motion: reduce) {
  .ink-device-card { transition: none; }
  .ink-device-card:hover { transform: none; }
}
.ink-device-image {
  width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: #F1F3F6;
}

/* Page content container */
.ink-page {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
  display: flex; flex-direction: column; gap: 20px;
}
@media (max-width: 640px) {
  .ink-page { padding: 16px; gap: 16px; }
  .ink-h1 { font-size: 30px; }
  .ink-h2 { font-size: 22px; }
  .ink-stat-value { font-size: 34px; }
}

/* ---------- Quasar overrides --------------------------------------------- */
/* Re-skin Quasar primitives so legacy ui.button / ui.input / ui.slider blend
   with the design system without rewriting every view. */

.q-card {
  border-radius: 16px !important;
  box-shadow: 0 1px 2px rgba(11, 18, 32, 0.04) !important;
  border: 1px solid var(--ink-border) !important;
  background: var(--ink-surface) !important;
}

/* Buttons — kill the uppercase Material look, soften the corners, swap the
   accent colour for our indigo. */
.q-btn {
  text-transform: none !important;
  font-weight: 500 !important;
  letter-spacing: 0 !important;
  border-radius: 10px !important;
  min-height: 36px;
}
.q-btn .q-btn__content { font-size: 14px; gap: 6px; }
.q-btn--rectangle, .q-btn--standard { padding: 6px 14px; }
.q-btn--round { border-radius: 999px !important; }

/* Primary buttons (color=primary, unelevated/standard) — solid indigo */
.q-btn--standard.text-primary, .q-btn--unelevated.bg-primary,
.q-btn--standard.bg-primary, .q-btn.bg-primary {
  background: var(--ink-accent) !important;
  color: white !important;
  box-shadow: none !important;
}
.q-btn--standard.text-primary:hover, .q-btn--unelevated.bg-primary:hover,
.q-btn.bg-primary:hover { background: #2F4AE0 !important; }

/* Flat buttons — neutral text, soft hover */
.q-btn--flat { color: var(--ink-text) !important; }
.q-btn--flat:hover .q-focus-helper { background: var(--ink-accent-soft) !important; opacity: 1 !important; }
.q-btn--flat.text-primary { color: var(--ink-accent) !important; }
.q-btn--flat.text-negative { color: var(--ink-danger) !important; }

/* FAB at bottom-right (upload) */
.q-btn--fab, .q-btn--fab-mini {
  background: var(--ink-accent) !important;
  color: white !important;
  box-shadow: 0 6px 20px rgba(61, 90, 254, 0.35) !important;
}

/* Inputs / textareas / selects — replace the underline with a soft bordered
   surface so they feel like part of a card. */
.q-field--standard .q-field__control::before { border-bottom: 0 !important; }
.q-field--standard .q-field__control::after { border-bottom: 0 !important; }
.q-field__control {
  border-radius: 10px !important;
  background: #F4F5F7 !important;
  padding: 0 12px !important;
  min-height: 44px;
  transition: background 120ms ease-out, box-shadow 120ms ease-out;
}
.q-field__control:hover { background: #EEF0F3 !important; }
.q-field--focused .q-field__control {
  background: var(--ink-surface) !important;
  box-shadow: 0 0 0 2px var(--ink-accent-soft), inset 0 0 0 1px var(--ink-accent) !important;
}
.q-field__native, .q-field__input, textarea.q-field__native {
  color: var(--ink-text);
  font-size: 14px;
}
.q-field__label {
  color: var(--ink-muted) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
}
.q-field--float .q-field__label { transform: translateY(-32%) scale(0.78); }
.q-field--filled .q-field__control { background: #F4F5F7 !important; }
.q-field--filled .q-field__control::before { background: transparent !important; }

/* Toggle (switch) — use indigo when active */
.q-toggle__inner--truthy .q-toggle__track { background: var(--ink-accent) !important; opacity: 1 !important; }
.q-toggle__inner--truthy .q-toggle__thumb { color: white; }

/* Sliders — indigo track + thumb, slimmer */
.q-slider__track { background: var(--ink-border) !important; }
.q-slider__selection, .q-slider__inner-track { background: var(--ink-accent) !important; }
.q-slider__thumb { color: var(--ink-accent) !important; }
.q-slider__pin { color: var(--ink-accent) !important; }
.q-slider__pin-text { color: white !important; font-weight: 600; }

/* Expansion item — flatter chevron, no big icon circle */
.q-expansion-item .q-item {
  padding: 8px 4px !important;
  min-height: 40px !important;
}
.q-expansion-item .q-item__section--avatar {
  min-width: 28px !important;
  padding-right: 8px !important;
}
.q-expansion-item .q-item__section--avatar .q-icon {
  font-size: 18px !important;
  color: var(--ink-muted) !important;
}
.q-expansion-item .q-item__label, .q-expansion-item .q-item__section--main {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.q-expansion-item--expanded .q-item__label,
.q-expansion-item--expanded .q-item__section--main { color: var(--ink-text); }
.q-expansion-item__content { padding: 4px 0 0 0 !important; }

/* Dialogs — soft surface, rounded */
.q-dialog__inner > .q-card {
  border-radius: 20px !important;
  border: 1px solid var(--ink-border) !important;
  box-shadow: 0 24px 64px rgba(11, 18, 32, 0.18) !important;
}

/* Notifications (ui.notify) — match the muted, rounded look */
.q-notification {
  border-radius: 12px !important;
  box-shadow: 0 12px 32px rgba(11, 18, 32, 0.16) !important;
}

/* Form sections used by image detail + sync-job form */
.ink-form-section { display: flex; flex-direction: column; gap: 14px; }
.ink-form-row { display: flex; gap: 12px; flex-wrap: wrap; }
.ink-form-row > * { flex: 1; min-width: 180px; }

/* Anchor tiles (ui.link styled as a card) — strip the default underline/colour. */
a.bento-tile, a.ink-action-card, a.ink-thumb, a.ink-device-card,
a.ink-nav-link, a.ink-nav-brand, a.ink-btn {
  text-decoration: none !important;
  color: inherit !important;
}
a.bento-tile *, a.ink-action-card *, a.ink-thumb *, a.ink-device-card *,
a.ink-nav-link *, a.ink-nav-brand *, a.ink-btn * {
  text-decoration: none !important;
}
/* NiceGUI's ui.link adds q-link styles; reset them everywhere we use them. */
a.q-link, a.q-link:visited, a.q-link:hover, a.q-link:focus {
  color: inherit;
  text-decoration: none;
}
/* Keep the visible accent on the inline "All images →" link. */
a.ink-nav-link.is-active { color: var(--ink-text) !important; }

/* Bottom action bar — sits flush at end of form, full width */
.ink-action-bar {
  display: flex; align-items: center; justify-content: flex-end; gap: 10px;
  padding: 14px 20px;
  background: var(--ink-surface);
  border: 1px solid var(--ink-border);
  border-radius: 16px;
  box-shadow: 0 1px 2px rgba(11, 18, 32, 0.04);
}

/* Slider with inline value label (no floating tooltip) */
.ink-slider-row {
  display: flex; align-items: center; gap: 12px;
}
.ink-slider-row .q-slider { flex: 1; }
.ink-slider-value {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 13px; font-weight: 500;
  color: var(--ink-text);
  min-width: 32px; text-align: right;
}
"""

_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">
"""


def install_global_styles() -> None:
    """Inject the design-system CSS + Google Fonts once per page.

    Safe to call from every ``@ui.page`` handler — NiceGUI dedupes by content.
    """
    ui.add_head_html(_HEAD_HTML)
    ui.add_css(_GLOBAL_CSS)


# --------------------------------------------------------------------------- #
# Composition helpers
# --------------------------------------------------------------------------- #


@contextmanager
def bento_grid() -> Iterator[ui.element]:
    """Yield a 12-column bento grid that collapses to one column on mobile."""
    grid = ui.element("div").classes("bento-grid")
    with grid:
        yield grid


@contextmanager
def tile(
    *,
    span: str = "col-span-6",
    row_span: str | None = None,
    href: str | None = None,
    on_click: Callable[[events.GenericEventArguments], object] | Callable[[], object] | None = None,
    extra_classes: str = "",
) -> Iterator[ui.element]:
    """Yield a bento tile with consistent surface styling.

    ``span`` accepts Tailwind grid utilities (``col-span-3``..``col-span-12``).
    Pass ``href`` to make the tile a real ``<a>`` anchor (recommended for plain
    navigation — clicks happen client-side, no websocket round-trip). Pass
    ``on_click`` only when the action isn't a URL navigation.
    """
    classes = f"bento-tile {span}"
    if row_span:
        classes += f" {row_span}"
    if href or on_click is not None:
        classes += " is-clickable"
    if extra_classes:
        classes += f" {extra_classes}"

    if href is not None:
        container = ui.link(target=href).classes(classes)
    else:
        container = ui.column().classes(classes)
        if on_click is not None:
            container.on("click", on_click)
    with container:
        yield container


def link_card(*, href: str, classes: str = "") -> ui.link:
    """Create an ``<a href>`` anchor (NiceGUI ``ui.link``) styled as a card.

    Use as a context manager to render children inside. Clicks navigate
    client-side, so there is no websocket round-trip and no flicker.
    """
    return ui.link(target=href).classes(classes)


def stat(*, label: str, value: str | int, hint: str | None = None) -> None:
    """Render a label/value/hint stack for a stat tile."""
    ui.label(label).classes("ink-stat-label")
    ui.label(str(value)).classes("ink-stat-value ink-numeric")
    if hint:
        ui.label(hint).classes("ink-stat-hint")


def badge(text: str, tone: Literal["ok", "warn", "muted", "accent", "neutral"] = "neutral") -> None:
    """Render a small pill badge with a tone-specific accent dot."""
    tone_class = "" if tone == "neutral" else tone
    ui.html(f'<span class="ink-badge {tone_class}">{text}</span>')


def section_title(text: str, *, eyebrow: str | None = None) -> None:
    """Render an eyebrow + H2 section header."""
    if eyebrow:
        ui.label(eyebrow).classes("ink-eyebrow")
    ui.label(text).classes("ink-h2")
