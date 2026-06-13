# Display refresh stalls

Symptom: the panel freezes on one image and further refreshes have no visible
effect, even though the controller runs without error and every SPI transaction
completes. This is almost always a **power** fault inside the display's driver
IC, not a software bug — the controller is faithfully sending commands that the
IC is silently ignoring.

## The driver IC boosts its own high voltages

The driver IC contains an internal DC-DC converter that steps the low VDD
supply up to the high voltages needed to physically move the electrophoretic
particles. On the UC8159 (the 4"–7.3" Impression panels) the datasheet figures
are:

- VDD input: 2.3–3.6 V
- Source voltages: ±15 V (VSH/VSL) and ±3–15 V (VSH_LV/VSL_LV)
- Gate voltages: VGH/VGL ±17–20 V

The 13.3" Spectra 6 uses a different controller (EL133UF1) but the same class
of architecture, and the same failure mode below. The Pi only supplies 3.3 V;
the IC boosts the rest internally, and the refresh is the peak-current moment
where an inadequate supply gives out.

## An undervoltage event strands the refresh

The UC8159 datasheet exposes a Low Power Detection register (R51H): `LPD: 0`
signals "low power input (VDD < 2.5 V)". When the supply sags under the refresh
current spike, three things follow:

1. **The DC-DC converter collapses.** It can no longer hold ±15 V/±19 V
   mid-refresh, so the LUT-driven waveform stalls partway through and the
   particles are left stranded between states — the frozen image.
2. **BUSY_N stays low.** After the Display Refresh command (DRF, R12H) the IC
   holds BUSY_N at 0 until the update finishes. If the waveform never completes,
   the internal state machine never reaches idle and BUSY_N never returns high.
   SRAM and registers survive (VDD stays above the retention threshold), so the
   IC is still alive on SPI — just permanently "mid-refresh".
3. **Further writes are ignored.** All write commands are unavailable while
   BUSY_N is asserted. The Pi-side SPI writes still succeed, but the IC discards
   every new refresh command because it believes the previous one is still
   running.

This matches the documented EPD failure mode: a low supply voltage leaves the
BUSY pin stuck busy and the IC unable to accept new work.

## Why a full-power supply clears it

Two things happen once the panel has enough current again:

1. **A clean reset plus a completed refresh.** Every `show()` begins with an
   RST_N pulse, which the datasheet defines as a full reset ("all registers
   reset to default, all driver functions disabled"). That forces the IC out of
   the stuck-BUSY state; the waveform then runs to completion at full voltage,
   BUSY_N returns high, and the state machine reaches idle.
2. **Incidental Pi glitches.** A Pi Zero 2 W can trip its own undervoltage
   detection on current spikes, which may glitch the RST_N GPIO and reset the IC
   by accident — sometimes helping, sometimes not, depending on timing.

The official PSU is not magic; it simply supplies enough current for the IC to
take the reset and finish one full refresh cycle, which re-enables command
processing.

## How the controller handles it

The Inky library does not raise on a stall — and the two panel families fail
differently, so the controller's `InkyDisplay` wrapper
([display.py](../packages/controller/src/inky_image_display_controller/display.py))
watches for both:

- **UC8159 (4–7.3")**: its busy-wait emits a Python `warnings.warn("… timed
  out …")` and returns. The controller captures that warning (it otherwise goes
  to stderr, never the logs) and treats it as a failed refresh.
- **EL133UF1 (13.3")**: its busy-wait is *silent* — when BUSY reads high it just
  `time.sleep()`s a fixed duration and returns, so a refresh that never ran
  looks identical to a good one. The controller instead **watches the BUSY GPIO
  directly** (through the driver's own gpiod handle, sampled in a background
  thread for the duration of `show()`): a healthy refresh drives BUSY low then
  high; if it never goes low, no waveform ran, and if it's still low afterwards
  it stalled mid-update.

On either signal the refresh is treated as failed. Recovery reuses the driver's
own reset: re-running `show()` calls `setup()`, which pulses RST_N, so each retry
restarts the waveform from a clean state. It retries up to three times with a
short delay; if every attempt still fails it raises instead of acking, and the
API records the failure so the UI surfaces the stuck device rather than
reporting a refresh that never physically happened.

One failure the host *cannot* see: a **partial refresh**, where the 13.3 updates
only one of its two SPI-driven halves. BUSY cycles normally and both chip-selects
toggle, so the fault is downstream of any signal the Pi can observe — it shows as
a successful refresh even though half the panel is stale. That's a hardware
(panel/ribbon) fault, not something the controller can detect.

## Practical fix

Power the panel from a supply with enough current headroom — the official
Raspberry Pi PSU, or an equivalent that holds 5 V under the refresh spike. Long
or thin USB cables, shared hubs, and underspecced supplies are the usual
culprits.
