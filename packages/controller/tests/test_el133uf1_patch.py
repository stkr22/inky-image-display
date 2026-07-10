"""Tests for the EL133UF1 busy-wait runtime fix (el133uf1_patch).

The real inky driver only exists on-device (optional ``rpi`` extra), so these
tests install a minimal fake ``inky.inky_el133uf1`` module and verify that the
patch (a) applies cleanly and idempotently, (b) genuinely polls the active-low
BUSY assert-then-clear cycle, and (c) only powers the panel off after the
refresh wait — the exact ordering whose violation latched panels into needing
a physical power cycle (pimoroni/inky#254).
"""

import sys
import types
import warnings
from typing import Any

import pytest
from inky_image_display_controller.el133uf1_patch import apply_busy_wait_fix


class _Value:
    """Stand-in for gpiod.line.Value — the patch only compares against ACTIVE."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class _ScriptedGpio:
    """Replays a sequence of BUSY levels, holding the last one forever."""

    def __init__(self, levels: list[str]) -> None:
        self._levels = list(levels)

    def get_value(self, pin: int) -> str:
        if len(self._levels) > 1:
            return self._levels.pop(0)
        return self._levels[0]


def _install_fake_driver(monkeypatch: pytest.MonkeyPatch) -> Any:
    # Typed as Any: the fake module is deliberately duck-typed, growing the
    # handful of attributes the patch reads off the real driver module.
    mod: Any = types.ModuleType("inky.inky_el133uf1")
    mod.Value = _Value
    mod.EL133UF1_DTM = 0x10
    mod.EL133UF1_PON = 0x04
    mod.EL133UF1_DRF = 0x12
    mod.EL133UF1_POF = 0x02
    mod.CS0_SEL = 0b01
    mod.CS1_SEL = 0b10
    mod.CS_BOTH_SEL = 0b11

    class Inky:  # fresh class per test — the patch mutates it
        pass

    mod.Inky = Inky
    pkg: Any = types.ModuleType("inky")
    pkg.inky_el133uf1 = mod
    monkeypatch.setitem(sys.modules, "inky", pkg)
    monkeypatch.setitem(sys.modules, "inky.inky_el133uf1", mod)
    return mod


def _panel(mod: Any, busy_levels: list[str]) -> Any:
    p = mod.Inky()
    p._gpio = _ScriptedGpio(busy_levels)
    p.busy_pin = 17
    return p


class TestApply:
    def test_returns_false_without_inky(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "inky", None)  # forces ImportError
        assert apply_busy_wait_fix() is False

    def test_patches_class_and_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _install_fake_driver(monkeypatch)
        assert apply_busy_wait_fix() is True
        patched_update = mod.Inky._update
        assert apply_busy_wait_fix() is True  # second call is a no-op
        assert mod.Inky._update is patched_update


class TestRefreshWait:
    """_refresh_wait must poll the active-low assert(LOW)-then-clear(HIGH) cycle."""

    def test_returns_once_busy_clears(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _install_fake_driver(monkeypatch)
        apply_busy_wait_fix()
        panel = _panel(mod, [_Value.INACTIVE, _Value.INACTIVE, _Value.ACTIVE])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            panel._refresh_wait(timeout=5.0)
        assert caught == []  # completed cycle: no timed-out warning

    def test_never_asserting_busy_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A latched panel is pinned HIGH (ready) and never runs the waveform.
        mod = _install_fake_driver(monkeypatch)
        apply_busy_wait_fix()
        panel = _panel(mod, [_Value.ACTIVE])
        with pytest.warns(UserWarning, match="[Tt]imed out"):
            panel._refresh_wait(timeout=0.2)

    def test_stuck_busy_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _install_fake_driver(monkeypatch)
        apply_busy_wait_fix()
        panel = _panel(mod, [_Value.INACTIVE])
        with pytest.warns(UserWarning, match="[Tt]imed out"):
            panel._refresh_wait(timeout=0.2)


class TestUpdateOrdering:
    def test_power_off_only_after_refresh_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _install_fake_driver(monkeypatch)
        apply_busy_wait_fix()
        panel = mod.Inky()
        events: list[tuple] = []
        panel.setup = lambda: events.append(("setup",))
        panel._send_command = lambda c, cs, _data=None: events.append(("cmd", c, cs))
        panel._busy_wait = lambda t: events.append(("busy_wait", t))
        panel._refresh_wait = lambda _timeout=None: events.append(("refresh_wait",))

        panel._update([0xAA], [0xBB])

        assert events == [
            ("setup",),
            ("cmd", mod.EL133UF1_DTM, mod.CS0_SEL),
            ("cmd", mod.EL133UF1_DTM, mod.CS1_SEL),
            ("cmd", mod.EL133UF1_PON, mod.CS_BOTH_SEL),
            ("busy_wait", 0.2),
            ("cmd", mod.EL133UF1_DRF, mod.CS_BOTH_SEL),
            ("refresh_wait",),
            ("cmd", mod.EL133UF1_POF, mod.CS_BOTH_SEL),
            ("busy_wait", 0.2),
        ]
