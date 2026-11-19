# Adaptalux Control Pod — BLE protocol reverse engineering

## Current state (start here)
The project has moved past reverse engineering: it is a working library plus a Qt window, all hardware-verified.
The sections below record how the protocol was decoded; where they disagree with this section or with
"Protocol decoded from the 5-arm captures", the later sections win. Early "hypotheses" are superseded.
- Repo: github.com/bimargulies/adaptalux-control (public, MIT). Python 3.13, macOS only, uv + bleak.
- Code: `src/adaptalux_control/` — `protocol.py` (pure encode/decode), `pod.py` (`Pod` session), `lighting.py`,
  `registry.py` (pod names per Mac), `gui/` (PySide6 + qasync window; `model.py` has no Qt). Docs: README.md.
- Setting up on a new Mac: `uv sync --extra gui`, `uv run pytest` (no hardware needed), `uv run ruff check .`.
  macOS asks to let the terminal use Bluetooth the first time. Put each pod in Bluetooth mode (hold the top button),
  then `uv run adaptalux-control identify` (or Pods -> Identify Pods in the window) to name them: saved identifiers
  are per Mac in `~/.config/adaptalux-control/pods.yaml`, so every Mac must do this itself.
- GUI: `uv run adaptalux-gui`. Per pod: Boost, per-arm Empty/LED/Flash with slider or flash buttons 1-5, Standby
  button (LED arms only; flash arms and boost left alone), File menu saves/restores YAML configs (saves only pods
  the user has set up; restore touches only pods in the file). The pod cannot report what is plugged in or any
  flash level, so the window shows arm modes from the last saved/restored file (kept in QSettings, along with window
  geometry) and sends nothing at startup. Boost is re-read from the pod every 3 s. The app names itself
  "Adaptalux" in the macOS menu bar via pyobjc.
- Identify via the window hardware-verified 2026-11-17 (both pods named, panels appeared). Gotcha: bleak on macOS
  returns addresses as `objc.pyobjc_unicode` (a str subclass) that `yaml.safe_dump` rejects; registry stores `str()`.
  Window errors print full tracebacks to stderr; launch `adaptalux-gui` from a terminal to see them.
- Working with the user: they observe hardware, so do ONE change per step and stop to ask what they see. Never send
  levels above 100 %. Pods sometimes stop advertising right after a disconnect: ask them to push the pod's button
  again. Only one central connects at a time (the window holds the connection; quit it before running scripts).
- `scripts/make-app.sh` builds ~/Applications/Adaptalux.app, a launcher for this checkout (Info.plist has the
  Bluetooth usage string; execs .venv's python so the app keeps one PID/Dock icon; log in ~/Library/Logs/adaptalux.log;
  ad-hoc signed). Hardware-verified 2026-11-18 (Bluetooth prompt, window connected).
- Link drops: bleak raises "Service Discovery has not been performed" / "disconnected" after the pod drops the link.
  The window's 3 s check uses `Pod.is_connected` (bleak state + keepalive) and shows "link lost" with Connect;
  reconnect shows green "reconnected". Hardware-verified 2026-11-18.
- A pod can also go silent while macOS still reports it connected: writes are acknowledged but `23` gets no reply
  (read_boost TimeoutError every 3 s; seen 2026-11-18). The window now drops a pod after 2 unanswered status requests
  ("not answering") and Pods -> Reconnect All force-reconnects every pod; restarting the app cleared it. The automatic
  drop and forced reconnect are NOT yet seen on hardware. Clicks with no pod say "not sent: <pod> is not connected".
- `scripts/restart-app.sh` quits (osascript; prints "User canceled" because the window defers quit to disconnect,
  harmless) and reopens the app; the user allowed it in .claude/settings.local.json.
- Moving the repo breaks `.venv` (editable .pth and script shebangs keep the old path): `rm -rf .venv && uv sync --extra gui`.
- Standby flag is per panel and used to outlive a dropped link (2026-11-19: George reconnected with every control
  greyed out). Now Resume reaches every panel; a disconnected one unlocks at once and relights the LED arms Standby
  dimmed when it reconnects (boost untouched); File -> Restore ends standby. Fix confirmed by the user; the
  relight-on-reconnect path itself is only covered by tests.
- Not done: a standalone .app for other people's Macs (bundling + Developer ID signing/notarization); two-pod Standby unverified on hardware via the window;
  status bytes 5-8 undecoded (user does not want time spent on them).

## Goal
Control an Adaptalux Control Pod (macro photography lighting) from a Python
program on macOS, replacing the official iPhone app. Work so far: one BLE
capture of the iPhone app connecting and adjusting the brightness of one
lighting arm. Next: write small Python experiment scripts to confirm/refute
the hypotheses below, and take more targeted captures.

## Environment
- macOS, Python 3, library: `bleak` (uses CoreBluetooth; no extra hardware).
- On macOS, bleak exposes devices by a per-Mac UUID, not the MAC address.
  Find the pod by advertised name (`Adaptalux3`) or service UUID.
- The pod likely accepts only one central at a time: close the iPhone app
  (or put the phone's Bluetooth off) before connecting from the Mac.
- Pod must be in Bluetooth mode: with at least one arm attached, hold the
  pod's top button 5–7 s until the blue light flashes. Hold 2 s to exit.

## Capture workflow (iPhone side)
- Apple Bluetooth logging profile installed on the iPhone
  (developer.apple.com/bug-reporting/profiles-and-logs/).
- PacketLogger (from "Additional Tools for Xcode") → File → New iOS Trace,
  iPhone attached by USB. Save as `.pklg`; Wireshark opens it directly.
- Wireshark display filter: `btatt` (hides Apple's constant vendor HCI
  noise, e.g. opcode 0xFDF6). Narrow further with
  `bluetooth.addr == 2c:fe:8b:00:00:01`.
- Export for analysis: File → Export Packet Dissections → As Plain Text,
  "Displayed" packets, details expanded.
- Always start capturing BEFORE the app connects, and log the UI actions
  performed, in order, with pauses between them.

## Device facts (from capture)
- GAP device name: `Adaptalux3`
- BD_ADDR seen: `2c:fe:8b:00:00:01` (Microchip Technology OUI)
- BLE module: Microchip (BM70/RN487x family) running Microchip's
  "Transparent UART" service — a byte pipe; the real protocol is the
  bytes written through it.
- ATT MTU negotiated: 158

### GATT table
| Handle | What | UUID | Properties |
|---|---|---|---|
| 0x0001–0x0005 | GAP service | 0x1800 | |
| 0x000c–0x000f | GATT service (Service Changed 0x000e, CCCD 0x000f) | 0x1801 | indicate |
| 0x0010–0x0020 | Device Information service | 0x180a | read (manufacturer, model, serial, …) |
| 0x0050–0x0058 | **Transparent UART service** | `49535343-fe7d-4ae5-8fa9-9fafd205e455` | |
| 0x0052 | **TX: pod → host (notifications)** | `49535343-1e4d-4bd9-ba61-23c647249616` | indicate, notify, write, write-no-rsp |
| 0x0053 | CCCD for 0x0052 (app writes 0x0001 = notify on) | 0x2902 | |
| 0x0055 | **RX: host → pod (commands)** | `49535343-8841-43f4-a8d4-ecbe34729bb3` | write, write-no-rsp |
| 0x0057 | Microchip control/credit characteristic (unused by app) | `49535343-4c8a-39b3-2f49-511cff073b7e` | notify, write |

The app uses ATT **Write Request** (with response) on 0x0055 →
in bleak: `write_gatt_char(RX_UUID, data, response=True)`.

## Observed session (capture 1: connect + one arm brightness up then down)
Times are seconds relative to connection.

```
0.00  pod probes phone's GATT (irrelevant; phone answers Not Found)
0.48  app enables Service Changed indications
0.72  app enables notifications on 0x0052 (CCCD 0x0053 = 01 00)
0.78  W 0x0055: 23
0.84  N 0x0052: 80 80 80 80 80 00 ba 00 01 00 77
0.84  W 0x0055: 23            (sent twice)
0.90  N 0x0052: 80 80 80 80 80 00 ba 00 01 00 77
2.2   app reads GAP Device Name -> "Adaptalux3"
3.79  W 0x0055: 24
3.85  W 0x0055: 24            (sent twice)
16.7  W 0x0055: 77 83 ff ff ff ff 00   (x2)
      then ~every 60 ms while dragging slider up:
      77 85.., 77 8d.., 77 8f.., 77 94.., 77 99.., 77 9f.., 77 a4..,
      77 a9.., 77 ab.., 77 ae..  (each "77 XX ff ff ff ff 00")
      77 ae ff ff ff ff 00 repeated ~7 times (slider held / released)
25.8  slider dragged down:
      77 ab, a4, 99, 94, 92, 8d, 88, 85, 85, 85, 83, 83, 83, 85, 85, 85
```
No notifications were received in response to the `77` or `24` writes.

## Working hypotheses (UNCONFIRMED — test these)
1. `23` = status request. Reply is 11 bytes:
   `80 80 80 80 80 | 00 ba | 00 01 00 | 77`
   - bytes 0–4: one per arm port (5 ports?); 0x80 = present-but-off or
     level 0 with a flag bit? (all five were 0x80 even though only one
     arm was attached — so maybe not "present").
   - `00 ba` maybe battery (0xba = 186) or firmware/version.
   - final `77` maybe terminator/checksum (same value as the brightness
     command byte — may be coincidence).
2. `24` = enter remote/app-control mode (or "ack / start"). Sent once
   (twice for redundancy) before any brightness command.
3. `77 p1 p2 p3 p4 p5 xx` = set brightness for up to 5 ports.
   - `ff` = leave that port unchanged.
   - level byte = 0x80 | level (bit 7 = on flag?), observed levels 3..46
     (0x83..0xae). Full range unknown (maybe 0..100 → 0x80..0xe4, or
     0..127 → 0x80..0xff, which would collide with 0xff "no change").
   - The arm was most likely in port 1 (needs confirming with the user).
   - last byte `00`: unknown (mode? color? effect?).
4. The app sends every command twice; probably just redundancy.

## Open questions / next experiments
- Which physical port was the arm in during capture 1?
- Python: connect, enable notify on TX, send `23`, print the reply. Does it
  change with arms attached to different ports / battery level?
- Is `24` required before `77` works? Try `77` without `24`.
- Sweep port-1 levels: 0x80, 0x90, …, 0xe4, 0xfe; find max and whether
  0x00–0x7f turns the arm off.
- Send a value to port 2..5 with an arm moved there; confirm per-port layout.
- Vary the last byte of `77` to see what it controls.
- Further captures from the app: full min→max slider sweep; arm on/off
  toggle; color/temperature changes (if the arm supports it); multiple arms;
  any presets/effects; disconnect sequence.
- Safety: keep experiments to the known command bytes (23, 24, 77) at first;
  avoid fuzzing unknown opcodes blindly, since the Microchip module or pod
  firmware may have config/update commands.

## Code conventions for this project
- Keep UUIDs and known commands in one module (e.g. `adaptalux.py`).
- Each experiment = small script that logs every write and notification
  with timestamps and hex, so results can be compared against captures.

## Confirmed by experiments (Mac/bleak, 2026-11-16)
- Pod advertises as `Adaptalux3` only while in Bluetooth mode; pressing the top
  button mid-session drops the link. Solid blue light is normal for this pod.
- `24` then `77 ff p2 ff ff ff 00` with p2 = 0x80|level lights and dims the arm.
  The arm used so far is on the SECOND port byte (index 1), i.e. "port 2".
  Port-1 writes (`77 p1 ff ff ff ff 00`) did nothing visible in the later tests.
- CORRECTION: an earlier note said the arm was on port 1 and that `0x80` turns
  it off. The port-1 "went to 0" observation is unreliable (the arm was
  most likely just dim at level 5 on port 2); level 0 = off is UNCONFIRMED.
- Status reply `23` is 11 bytes, but may arrive split over several
  notifications; reassemble before parsing. Seen: `80 80 80 80 80 00 bf 00 01 00 77`
  (first), later `80 ff 80 80 80 01 be 00 02 00 77` (after my port-1/2 writes).
- Writes with response=True, ~0.45 s apart, no notifications returned.
- OFF NOT FOUND: on port 2, `0x80` (level 0) leaves the arm lit, and raw `0x00`
  (bit 7 clear) also leaves it lit. Needs an app capture of the arm on/off toggle.
- Not yet tested: upper level range; `77` without `24`;
  other ports; last byte of `77`.
- Scripts: the exploration scripts that were in `experiments/` (00-12) have been removed from the tree; they are in git
  history (last present in the commit titled "Read boost back from the pod; flash levels require pod boost on"). Current scripts are in `examples/`; user-facing docs are in README.md.

## Protocol decoded from the 5-arm captures (2026-11-16) — supersedes hypotheses above
- Slot bytes are INVERTED: `0xFF` = 0 % (off), `0x80` = 50 %, `0x40` = 75 %, `0x00` = 100 %
  (byte = 256*(100-pct)/100, clamped to 255). `0xFF` is NOT "leave unchanged"; every `77`
  packet sets all five slots. This explains "OFF NOT FOUND" and the "0x80|level" hypothesis
  being wrong (the old `brightness_cmd` helper was based on it and has been removed).
- Last byte of `77 ... FLAG` = boost switch (01 on, 00 off). Boost is a single GLOBAL flag for the whole pod
  (not per arm); it brightens all arms at every level.
- App arm order -> slot byte: arm1=byte1, arm2=byte0, arm3=byte3, arm4=byte4 (verified from
  captures/four-arms); arm5=byte2.
  PHYSICAL HOLES (user observed on George 2026-11-19): arm1 top left, arm2 top right, arm5 bottom left, arm4 bottom
  right, arm3 bottom middle (inferred, the one left over). The bottom row is NOT 3-4-5. The window labels rows by
  hole (`ARM_PLACES` in gui/app.py); config files keep arm numbers. All five verified on hardware 2026-11-16 (experiments 06-08, user confirmed visually).
- Library: `protocol.py` (pure, tested) and `pod.py` (`Pod`, bleak). Not yet run against hardware.
- Hardware-verified: inverted encoding, off at 0xFF, per-arm independence, all five arms.
- Quirk: the status reply reports an EMPTY slot as 50 % (0x80), so `Pod` adopts 50 % for unplugged
  arms and writes 0x80 to them; harmless. Levels persist on the pod after disconnect (no keepalive needed).
- Boost flag hardware-verified 2026-11-16 (experiments/09_boost.py, arm 1 at 50 %): last byte of `77` = 01 makes
  the arm visibly brighter, 00 returns it to normal. `Pod.set_boost()` works.
- Boost matrix verified 2026-11-16 (experiments/10_boost_matrix.py, user observed): boost brightens at every level
  tested (25/50/100 %) and on all five arms. Confirmed by the user: boost is a global flag, not per-arm.
- `24` is NOT required (experiments/11_no_24.py phase 1, user observed 2026-11-16): on a fresh connection with
  only notify enabled and no `23`/`24`, `77` lit arm 1 clearly. (An earlier run was invalid: no arm in port 1.)
  `Pod` still sends `23` + `24` like the app; harmless. What `24` actually does is unknown.
- Levels above 100 % are deliberately NOT supported: the code raises ValueError (and sends nothing) for any value outside 0..100.

## Telling pods apart (2026-11-16)
- Nothing readable on a Mac distinguishes two pods: same name, serial `0000`, system ID all zeros, advertisement
  is only the name. macOS hides the BD_ADDR behind a per-Mac UUID. A pod connected to a phone does not advertise.
- So each Mac learns once: `adaptalux-control identify` (or `identify_pods()`) winks each unlabelled visible pod,
  asks for a label, and saves label -> UUID in `~/.config/adaptalux-control/pods.yaml` (`registry.py`).
  Then `Pod.connect(label="bench")`. UUIDs are per-Mac; rerun identify if one changes. `Pod.wink()` only shows on
  pods with arms plugged in. Wink + label lookup hardware-verified on fred (2026-11-16, user observed). Labels: fred, george (both identified 2026-11-16; each verified by lighting only that pod, user observed). Both can be connected from one Mac at the same time (writes succeed). Pods sometimes stop advertising while in Bluetooth mode; cause unknown (idle timeout? keepalive?) - untested.
- The pod has a manual brightness control; bumping it changes arm levels with no command from us (seen on fred
  2026-11-16). Our remembered levels can therefore go stale; the `23` status reply may show such changes (untested).
- Soak test 2026-11-16 (experiments/12_session_soak.py, 10 min, fred keepalive OFF, george keepalive ON): both pods
  stayed connected the whole time, zero errors. So an open connection does NOT need the 30 s `23` keepalive (george's
  replies kept arriving, status_age ~30 s). The earlier "stops advertising" dropouts happened while NOT connected and
  are still unexplained. `Pod` keeps the keepalive by default (harmless; also detects a dead link).
- Flash arms (Gen 2): per Adaptalux docs they need boost on (the app turns it on when a flash arm is selected),
  levels 1-5, selected by double-tapping the port; app >= 1.4.0 (user has 1.5.0). No flash capture yet; the app
  would not enter flash mode for the user. Do NOT guess flash packets (capacitor charging); capture first.
- How to enter flash mode in the iPhone app (worked for the user 2026-11-16, app 1.5.0, Pod 3.0): not automatic.
  Double-tap the flash arm's port -> choose the Flash symbol -> bottom panel switches from the LED-brightness slider
  to presets 1-5; boost turns on by itself. Keep pod power at 100 % for flash ports.

## Flash arm power level, decoded from captures/flash-arm-2-sequence.txt (2026-11-16, george, flash arm in app port 2 = slot byte 0)
- Choosing flash mode (double-tap) sends NOTHING. Boost was already on (flag 01) the whole time and the arm stays at 100 %.
- Each level tap sends the SAME three-step pulse on that arm's slot byte, every other byte unchanged, each step written
  2-3 times (as the app always does): `ff` (0 %) for ~0.2 s -> `8d` (~45 %) for T -> `00` (100 %).
- The level is the DURATION T of the `8d` step: level 1..5 -> T ~ 0.52, 0.76, 1.03, 1.30, 1.58 s measured from the first
  `8d` write to the first `00` write (~0.27 s per level; level 3 was 1.05 s in the earlier capture). Same bytes for all levels.
- Connect sequence with flash arms was the usual `23` (status reply `00 00 80 80 69 01 a3 01 13 01 77`), `24`, then a
  `77` pair; no extra flash-selection command.
- NOT yet replayed on hardware. Whether the arm tolerates our BLE timing jitter (~50 ms) is untested.
- REPLAYED on hardware 2026-11-16 (`Pod.set_flash_level(arm, level)`, george, arm 2 = slot byte 0): level 5 and level 4
  gave the expected number of red LEDs on the arm, level 4 "more or less instantly". Our write timing matched the
  app's (level 4 pulse 1.29 s vs 1.30 s; 60 ms between packets). The app itself is fast and reliable on the same arms.
- Earlier attempts were confusing (levels 3, 3, 2 gave unclear/odd counts; right arm once showed 1 after a level-4
  command). Causes unproven: the observer mixed up which arm was which, and/or the arms were still loading from a
  previous pulse. Packets for empty ports (`80 80 80` vs the app's `ff ff 69`) are NOT the cause (level 4 worked with 80s).
- Status byte 5 = boost flag (01 on). Byte 6 (0xb2 = 178 = 69.8 %) may be battery but the app said 65 %; unproven.
- Pod 3.0 on the charger all along, so low battery is not the explanation for odd flash levels.
- Both flash ports verified 2026-11-16: arm 2 (right top hole, slot byte 0) and arm 1 (left top hole, slot byte 1)
  each took a level pulse and the other arm did not change. IMPORTANT for observing: the arm's LEDs climb while it
  CHARGES to the new level (level 5 showed 4 for a while, then 5 after ~a minute), so wait up to a minute before
  judging a result. This likely explains the confusing early readings. `set_flash_level` returns when the pulse is sent,
  not when the arm has finished charging.
- Lowering works (2026-11-16): level 1 sent to arm 2 while it was at 4 -> it blinked and landed at 1 (quickly).
  Status reply `23` is identical before/after a flash level change (`00 00 80 80 80 01 b0 01 03 01 77`), so the
  pod does NOT report flash levels; our code must remember the last level it set (and the app/arm can change it).
- All five levels verified on arm 2 (2026-11-16): 1, 2, 3, 4, 5 each landed on the right LED count, the other arm
  unchanged. CORRECTION on settling time: small/low changes (1->2, 2->3, 4->1, ->4) showed up essentially instantly
  per the user; only the left arm's 2->5 jump showed 4 for a while before 5. So the charging delay is real but
  not general (maybe large upward jumps / level 5); don't assume a fixed wait. The early odd readings remain
  not fully explained (arm mix-ups are the main suspect).
- BOOST READBACK (2026-11-16): status reply byte 9 is the boost flag (00 off / 01 on), verified on fred by toggling
  boost off/on/off and re-reading `23` each time; george (boost on) reads 01. Bytes 5-8 still unknown (george has
  byte5=01, byte7=01, fred 00/00: maybe flash arms present; byte6 maybe battery). `Pod` now adopts boost from the pod
  at connect (it used to assume off, so its first write would turn a pod's boost off!), `Pod.read_boost()` re-reads it,
  and `set_flash_level` checks the pod's real boost, raising `BoostOff` (a ValueError) without sending a pulse if it is
  off. The pulse always leaves the arm's port at 100 %, so callers never set flash-port power themselves.
- Flash arm firing with the Adaptalux trigger works (user tried it). Nothing to do in code: no way to trigger from here.
- Hardware-verified 2026-11-16: `set_boost(False)` via the API dims fred's LED arms (user observed); on george, with
  boost off, `set_flash_level` raises `BoostOff` and sends no pulse; boost restored and read back True.

## Battery and charger (2026-11-18, George, in progress)
- Status byte 5 = on-charger flag (01 plugged in, 00 on battery): verified plugged/unplugged/plugged on George and in the
  window. Fred read 00 earlier because its charger cord had worked loose; it then ran flat (fast red blink). A flat-ish
  pod keeps its Bluetooth link but its controller stops answering `23` ("not answering"), loses boost, and flash arms
  blink green. Fred recovered fully once recharged (2026-11-18).
- Status byte 6 = battery level. Pairs (app % / byte 6): 66/179, 65/178 (charging), 54/171, 53/170 (on battery, LED
  arms at 100 %), 32/155-156 (after firing the flash). Least-squares fit: pct = 1.456*byte - 194.5 (0 % ~134,
  100 % ~202), every pair within 0.5 points; `protocol.battery_percent`. Fred, charging, after several hours: app 90 %, window 89 %. George 2026-11-19: window 4 % (byte 136, fit 3.5) vs
  app 3 %, so the fit holds at the bottom end too. LED arms drain slowly
  (1 point in ~1.75 h with three arms at 100 %); flashing drains fast. Byte 6 wobbles by 1 right after flashing.
- Code: protocol `status_charging`/`status_battery_raw`/`battery_percent`, `Pod.charging`/`Pod.battery_raw`; the window
  shows "battery N %" next to Boost, plus "· charging", or "· low" in red below 20 % on battery.
- Low-battery alert (hardware-verified 2026-11-19 on George by unplugging the charger): below 20 % on battery the
  window plays Sosumi via AppKit NSSound and opens a non-modal popup, once per drop (re-arms after charging or >= 25 %).
  `QApplication.beep()` is SILENT in this app on macOS even though `osascript -e beep` works; do not go back to it.
