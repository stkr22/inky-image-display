# Display refresh stalls

Symptom: the panel freezes on one image and further refreshes have no visible
effect, even though the controller runs without error and every SPI transaction
completes.

There are two distinct causes. On the 13.3" (EL133UF1) the primary cause is a
**bug in the Inky driver library** that powers the panel off mid-refresh (next
section). On the smaller UC8159 panels — and as a secondary factor on the
13.3" — it can be a **power** fault inside the display's driver IC (see "The
driver IC boosts its own high voltages" below); in both cases the controller
is faithfully sending commands that the IC is silently ignoring.

## Root cause on the 13.3": the driver's busy-wait never waits

Diagnosed on hardware 2026-07-10 (device inky-controller-1), tracked upstream
as [pimoroni/inky#254](https://github.com/pimoroni/inky/issues/254).

The panel's BUSY line is **active-low**: measured with a logic probe during a
refresh, it sits HIGH when ready, drops LOW at power-on (PON) and stays LOW
through the ~19 s refresh waveform (DRF), returns HIGH when the waveform
completes, and rests LOW again once power-off (POF) executes. But
`inky_el133uf1.Inky._busy_wait` in inky 2.4.0 never actually polls the line:

```python
if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
    time.sleep(timeout)   # blind fixed sleep
    return
while self._gpio.get_value(self.busy_pin) == Value.ACTIVE:  # already false
    ...
```

If the line reads HIGH it blind-sleeps the full timeout; otherwise the loop
condition is already false and it returns instantly. Since BUSY is already LOW
when `_busy_wait(32.0)` runs after DRF, the driver **returns immediately and
sends POF while the refresh waveform is still running — on every refresh**.
The IC usually ignores commands while busy, so most refreshes still complete,
but a mistimed POF can latch the panel into a fault state: BUSY pinned HIGH
and the IC deaf to everything — RST_N resets (including 10 s holds), POF,
deep-sleep, full re-init. A Pi reboot does not help (the HAT's 5 V rail stays
up); **only physically removing power recovers a latched panel**.

The controller ships a runtime fix
([el133uf1_patch.py](../packages/controller/src/inky_image_display_controller/el133uf1_patch.py)),
applied to the driver class before `inky.auto.auto()` constructs the panel: a
real refresh wait that polls the assert(LOW)-then-clear(HIGH) cycle after DRF
(65 s budget — measured refreshes take ~19 s warm, and e-paper slows when
cold) so POF is only ever sent after the waveform finishes. On a genuine stall
it emits the same "timed out" warning the UC8159 driver uses, feeding the
stall detection below. Verified on hardware: `show()` returns right after
BUSY clears (~29 s total) instead of after a blind 32 s sleep.

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

The Inky library does not raise on a stall, so the controller's `InkyDisplay`
wrapper
([display.py](../packages/controller/src/inky_image_display_controller/display.py))
watches two independent signals:

- **"timed out" warnings**: the UC8159 (4–7.3") driver emits a Python
  `warnings.warn("… timed out …")` when BUSY doesn't clear, and the
  controller's EL133UF1 busy-wait fix (previous section) emits the same. The
  controller captures the warning (it otherwise goes to stderr, never the
  logs) and treats it as a failed refresh.
- **the BUSY GPIO, watched directly** (through the driver's own gpiod handle,
  sampled in a background thread for the duration of `show()`): a healthy
  refresh drives BUSY low then back high; if it never goes low, no waveform
  ran — the signature of a latched panel, which sits pinned HIGH. There is
  deliberately no "still busy after show()" check: once POF executes, a
  cleanly powered-off panel rests at the same LOW level as a stuck-busy one,
  so a stuck-mid-update panel is caught by the timed-out warning instead.

On either signal the refresh is treated as failed. Recovery reuses the driver's
own reset: re-running `show()` calls `setup()`, which pulses RST_N, so each retry
restarts the waveform from a clean state. It retries up to three times with a
short delay; if every attempt still fails it raises instead of acking, and the
API records the failure so the UI surfaces the stuck device rather than
reporting a refresh that never physically happened. A panel that latched hard
(see the root-cause section) is beyond these retries — it needs its power
physically removed.

## Recovery after a failed refresh

Once the controller acks a failure, the API stops all automatic dispatch to
that device (rotation, grids, display jobs, GenAI) so the scheduler doesn't pile
images onto a panel that can't show them. Several layers then work to end
that halt, in order of preference:

1. **The controller's retry loop.** The controller re-attempts the failed
   image on a fixed cadence (`display.retry_interval_seconds`, default 300 s).
   The loop only ends once the success ack — the message that clears the
   failure state server-side — was actually published: if the panel refreshed
   fine but MQTT was down, the loop keeps re-sending the ack without
   re-driving the panel (an e-paper refresh is ~30 s of flashing). A new
   `display`/`clear` command supersedes the loop; a `status` probe does not.
2. **Re-registration resets the flag.** The controller registers exactly once
   per process start, so an incoming registration proves any recorded failure
   belongs to a controller that no longer exists (its in-memory retry died
   with it). The API resets the device's refresh health to "no ack seen" —
   this is what makes the *power cycle that recovers a latched panel* also
   resume rotation automatically.
3. **The failure flag expires.** As a backstop for every other way the retry
   can be lost, a recorded failure older than
   `API_REFRESH_ERROR_BACKOFF_SECONDS` (default 900 s) stops blocking
   dispatch. The next push settles the device's real state: success clears
   the flag, failure re-arms the backoff with a fresh timestamp — a genuinely
   stuck panel is only pinged once per backoff window, not every scheduler
   tick.

Manual pushes from the UI ("next", direct display) bypass the halt entirely
and their success ack clears the failure state immediately.

### What the operator sees

The API classifies the failure age into a `refresh_state` the UI words
differently: while the failure is younger than the backoff the device shows
"Refresh failed — retrying" (amber; the controller's loop should self-heal),
and once it outlives the backoff without a success ack it escalates to
"Refresh failing — check power" (red; retries have evidently not recovered
the panel and the fix is physical). Failing devices also appear as alerts on
the landing page. When `API_NOTIFY_URL` is configured, the ok→failed and
failed→ok *transitions* additionally push a notification (ntfy-style plain
text POST) — transitions only, so a stuck panel retrying every few minutes
doesn't send one message per attempt.

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
