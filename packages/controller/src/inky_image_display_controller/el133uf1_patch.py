"""Runtime fix for the Inky EL133UF1 (13.3") driver's broken busy-wait.

inky 2.4.0's ``inky_el133uf1.Inky._busy_wait`` never polls the BUSY line
(pimoroni/inky#254): its leading ``if line == ACTIVE`` check blind-sleeps the
full timeout, and in the opposite case the poll loop's condition is already
false, so it returns immediately. BUSY on this panel is **active-low** — LOW
while the waveform runs, HIGH when ready (measured on hardware 2026-07-10:
LOW from power-on until ~19 s after the refresh command, HIGH once complete;
same polarity as the sibling e673 driver). Because BUSY is already LOW when
``_busy_wait(32)`` runs after the refresh (DRF) command, the driver returns
instantly and sends power-off (POF) while the refresh is still running. The
panel usually ignores commands while busy, but a mistimed POF can latch it
into a fault state — BUSY pinned HIGH, deaf to RST_N/POF/re-init — that only
physically removing power clears (docs/refresh-issues.md).

``apply_busy_wait_fix()`` monkeypatches the driver class with a
``_refresh_wait`` that genuinely polls the assert(LOW)-then-clear(HIGH) cycle
after DRF, so POF is only sent once the waveform finished. Setup/PON/POF keep
the stock ``_busy_wait``: their short blind sleeps are proven on hardware, and
after POF the line rests LOW (panel powered off), which a naive poll would
misread as busy. On a stall the fix emits a ``warnings.warn`` containing
"timed out", the same signal the UC8159 driver emits and InkyDisplay's stall
detection already captures.

Re-evaluate on any inky upgrade past 2.4.x: the patch skips itself if the
driver already has a ``_refresh_wait``, but an upstream fix shaped differently
would need this module retired.
"""

import logging
import time
import warnings
from typing import Any

logger = logging.getLogger(__name__)

# Longest healthy refresh measured on hardware is ~19 s at room temperature;
# e-paper waveforms slow down considerably when cold, so leave generous room
# before declaring a stall (the stock driver allowed 32 s and cutting a slow
# refresh short is exactly the failure this module exists to prevent).
DRF_TIMEOUT_S = 65.0
_POLL_INTERVAL_S = 0.05


def apply_busy_wait_fix() -> bool:
    """Patch inky's EL133UF1 driver class in place; True if the fix is active.

    Safe to call anywhere: returns False when the driver isn't importable
    (dev machines without the ``rpi`` extra) and is idempotent on repeat calls.
    Must run before ``inky.auto.auto()`` constructs the panel object — it
    patches the class, not an instance.
    """
    try:
        import inky.inky_el133uf1 as el133  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except Exception:
        logger.debug("EL133UF1 driver not importable; busy-wait fix not applied")
        return False

    # Typed as Any: monkeypatching adds/replaces methods on the driver class,
    # which a type checker rightly rejects on the concrete Inky type.
    cls: Any = el133.Inky
    if getattr(cls, "_refresh_wait", None) is not None:
        return True

    active = el133.Value.ACTIVE

    def _refresh_wait(self, timeout: float = DRF_TIMEOUT_S) -> None:
        """Wait for the DRF busy cycle: BUSY drops LOW, then returns HIGH."""
        t_start = time.time()
        asserted = False
        while time.time() - t_start < timeout:
            if self._gpio.get_value(self.busy_pin) != active:
                asserted = True
            elif asserted:
                return
            time.sleep(_POLL_INTERVAL_S)
        warnings.warn(
            f"Busy Wait: Timed out after {timeout:0.2f}s (busy asserted: {asserted})",
            stacklevel=2,
        )

    def _update(self, buf_a, buf_b) -> None:
        """Stock _update, except DRF is followed by a real busy wait."""
        self.setup()

        self._send_command(el133.EL133UF1_DTM, el133.CS0_SEL, buf_a)
        self._send_command(el133.EL133UF1_DTM, el133.CS1_SEL, buf_b)

        self._send_command(el133.EL133UF1_PON, el133.CS_BOTH_SEL)
        self._busy_wait(0.2)

        self._send_command(el133.EL133UF1_DRF, el133.CS_BOTH_SEL, [0x00])
        self._refresh_wait()

        self._send_command(el133.EL133UF1_POF, el133.CS_BOTH_SEL, [0x00])
        self._busy_wait(0.2)

    cls._refresh_wait = _refresh_wait
    cls._update = _update
    logger.info("Applied EL133UF1 busy-wait fix (pimoroni/inky#254)")
    return True
