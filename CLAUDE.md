# Adaptalux Control Pod — BLE protocol reverse engineering

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
- Scripts: experiments/00_scan.py, 01_status.py, 02_wiggle.py [ports],
  03_ramp_down.py and 04_sweep.py (both write port 1 only: need a port arg).

## Protocol decoded from the 5-arm captures (2026-11-16) — supersedes hypotheses above
- Slot bytes are INVERTED: `0xFF` = 0 % (off), `0x80` = 50 %, `0x40` = 75 %, `0x00` = 100 %
  (byte = 256*(100-pct)/100, clamped to 255). `0xFF` is NOT "leave unchanged"; every `77`
  packet sets all five slots. This explains "OFF NOT FOUND" and the "0x80|level" hypothesis
  being wrong (`adaptalux.brightness_cmd` is based on it and is wrong).
- Last byte of `77 ... FLAG` = boost switch (01 on, 00 off). Boost is a single GLOBAL flag for the whole pod
  (not per arm); it brightens all arms at every level.
- App arm order -> slot byte: arm1=byte1, arm2=byte0, arm3=byte3, arm4=byte4 (verified from
  captures/four-arms); arm5=byte2. All five verified on hardware 2026-11-16 (experiments 06-08, user confirmed visually).
- Library: `protocol.py` (pure, tested) and `pod.py` (`Pod`, bleak). Not yet run against hardware.
- Hardware-verified: inverted encoding, off at 0xFF, per-arm independence, smooth ramp, all five arms.
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
  pods with arms plugged in. Not yet run against real hardware.
