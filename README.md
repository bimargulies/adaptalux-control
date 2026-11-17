# adaptalux-control

Control an Adaptalux Control Pod 3.0 from Python on macOS, in place of the
Adaptalux iPhone app. It talks to the pod over Bluetooth LE using
[bleak](https://github.com/hbldh/bleak) (CoreBluetooth; no extra hardware).

It can:

- set the brightness (0-100 %) of each of the five lighting arms, or ramp it smoothly;
- switch the pod's global **boost** on and off, and read it back;
- set the power level (1-5) of Gen 2 **Xenon flash arms**;
- tell several pods apart on one Mac, with names you choose.

Firing a flash is done by the Adaptalux trigger, not by this library.

## Install

Requires macOS and Python 3.13+. With [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

## Connecting

1. Close the iPhone app. A pod talks to one device at a time.
2. Put the pod in Bluetooth mode: with at least one arm attached, hold its top
   button until the blue light comes on. Hold it for 2 seconds to leave
   Bluetooth mode.

The pod advertises as `Adaptalux3` only while it is in Bluetooth mode. If a pod
can't be found, put it in Bluetooth mode again.

```python
import asyncio
from adaptalux_control import Pod


async def main():
    async with await Pod.connect() as pod:
        await pod.set_arms({1: 25, 2: 50})  # arm number -> percent
        await pod.ramp({1: 100}, duration=2)


asyncio.run(main())
```

Levels persist on the pod after you disconnect.

## Arms

Arms are numbered as in the iPhone app, looking at the pod's holes:

```
     +-------+   +-------+
     | arm 1 |   | arm 2 |
     +-------+   +-------+

  +-------+   +-------+   +-------+
  | arm 3 |   | arm 4 |   | arm 5 |
  +-------+   +-------+   +-------+
```

The pod cannot be told to leave an arm alone, so a `Pod` remembers every arm's
level (adopted from the pod when you connect) and resends all five with each
command. Empty ports report 50 %, and that value is sent back to them; it has no
effect.

## Brightness

```python
await pod.set_arms({1: 25, 3: 80})  # only these change
await pod.set_all(0)  # everything off
await pod.ramp({2: 100}, duration=1.5)  # smooth change
print(pod.arms)  # {1: 25.0, 2: 100.0, ...}
```

Values outside 0-100 raise `ValueError` and nothing is sent. Nothing above 100 %
is ever sent to the pod.

## Turning everything off and back on

`lights_off` switches arms off and remembers how they were; `restore` puts it back.

```python
saved = await pod.lights_off()  # all five arms to 0 %; returns a Lighting
...
await pod.restore()  # arms and boost as they were
```

`saved` is a `Lighting`: the brightness of arms 1-5 and the boost flag. To come back
in a later run, keep it in a file:

```python
saved.save(path)  # then, later, after connecting:
await pod.restore(Lighting.load(path))
```

- `lights_off(arms=[1, 2])` turns off only those arms. `restore` still puts all five
  arms back to the saved levels.
- Calling `lights_off` again while everything is dark keeps the original; if you
  changed the lights in between, the new configuration is the one remembered.
- Boost is left alone by `lights_off` and is restored by `restore`.
- Flash arm levels can't be read from the pod, so they are not saved.
- `examples/lights.py off` and `... on` do this across runs.

## Boost

Boost is one global flag that makes every arm brighter. It is read from the pod
when you connect, so ordinary commands leave it as it was.

```python
await pod.set_boost(True)
on = await pod.read_boost()  # asks the pod, so it also sees changes made at the pod
```

## Flash arms

Gen 2 Xenon flash arms take a power level from 1 (shortest flash) to 5 (most
power):

```python
await pod.set_boost(True)
await pod.set_flash_level(2, 3)  # arm 2, level 3
```

- Boost must be on. `set_flash_level` reads the pod's real boost state and raises
  `BoostOff` (a `ValueError`) without sending anything if it is off.
- The arm's port is left at 100 % power, which flash arms need. You never set that
  yourself.
- The call returns once the command is sent. The arm's lights then show it
  reaching the level: nearly at once for small changes, up to about a minute for a
  big jump up.
- The pod cannot report a flash arm's level. Keep track of what you set.
- Do not use `set_arms`, `ramp` or `wink` on a port holding a flash arm.

## Several pods

Every pod advertises the same name and carries no serial number, and macOS hides
a pod's real Bluetooth address behind an identifier that is specific to that Mac.
So each Mac learns once which pod is which. For every pod that is advertising and
has no name yet, `identify` flashes its arms and asks what to call it:

```sh
uv run adaptalux-control identify    # run once per Mac, with the pods in Bluetooth mode
uv run adaptalux-control list        # show the saved names
```

The answers are saved in `~/.config/adaptalux-control/pods.yaml`:

```yaml
pods:
  bench: 11111111-2222-3333-4444-555555555555
  studio: 66666666-7777-8888-9999-AAAAAAAAAAAA
```

From then on:

```python
async with await Pod.connect(label="bench") as pod:
    ...
```

- A pod that already has a name is skipped, so you can rerun `identify` after adding
  a pod. A pod connected to a phone does not advertise, so it can't be identified
  until it is free.
- Winking only shows on a pod that has arms plugged in.
- The saved identifiers only work on the Mac that wrote them. If macOS ever changes
  one, run `identify` again. On a new Mac, run it there.
- You can also call `scan_pods()`, `identify_pods()` and `PodRegistry` directly.
- Without `label` (or `address=`), `Pod.connect()` takes the first pod it finds, so
  use a label whenever more than one pod is advertising.

## Sessions

A `Pod` is a session, from `connect` until `close` (use `async with`). While it is
open the library asks the pod for its status every 30 seconds. Change that with
`Pod.connect(keepalive_interval=...)`, or pass `None` to turn it off. A failed
request is recorded in `pod.keepalive_error` and `pod.status_age` is the time since
the pod last answered; neither raises on its own, but your next command will.

## API summary

| | |
|---|---|
| `Pod.connect(label=None, address=None, timeout=10, keepalive_interval=30)` | open a session |
| `pod.set_arms({arm: percent})`, `pod.set_all(percent)` | brightness |
| `pod.ramp({arm: percent}, duration)` | smooth brightness change |
| `pod.set_boost(on)`, `await pod.read_boost()`, `pod.boost` | global boost |
| `pod.set_flash_level(arm, level)` | flash arm power, 1-5 |
| `pod.lights_off(arms=None)`, `pod.restore(lighting=None)`, `pod.snapshot()` | turn off and restore |
| `Lighting(arms, boost)`, `.save(path)`, `Lighting.load(path)` | a saved configuration |
| `pod.wink()` | flash all arms so you can see which pod this is |
| `pod.arms`, `pod.status_age`, `pod.keepalive_error` | state |
| `await pod.close()` | end the session |
| `PodRegistry`, `identify_pods()`, `scan_pods()` | naming pods |
| exceptions | `PodNotFound`, `UnknownPod` (no such name), `BoostOff`, `NothingToRestore` |

## Protocol

The pod's Bluetooth module exposes a Microchip Transparent UART service
(`49535343-fe7d-4ae5-8fa9-9fafd205e455`). Commands are written, with response, to
the RX characteristic (`49535343-8841-43f4-a8d4-ecbe34729bb3`). Replies arrive as
notifications on the TX characteristic (`49535343-1e4d-4bd9-ba61-23c647249616`).
The iPhone app opens with `23` then `24` and sends every command twice; the
library does the same and then sends each packet two or three times.

| Command | Meaning |
|---|---|
| `23` | status request; reply is 11 bytes (below) |
| `24` | sent by the app after connecting |
| `77 c0 c1 c2 c3 c4 FLAG` | set all five arms and boost |

In a `77` packet each arm byte is inverted: `ff` = 0 %, `80` = 50 %, `40` = 75 %,
`00` = 100 %. `FLAG` is boost, `01` on and `00` off. The bytes map to arms like this:

```
arm 1 = c1    arm 2 = c0
arm 3 = c3    arm 4 = c4    arm 5 = c2
```

The status reply is 11 bytes and may arrive split across notifications. Bytes 0-4
are the five arm bytes in the same encoding, and byte 9 is boost (`00`/`01`). The
other bytes are not used.

**Flash arm level** is sent as a timed pulse on the arm's byte, with the other bytes
unchanged: `ff` for about 0.2 s, then `8d` for a time that sets the level, then `00`.
The time from the first `8d` write to the first `00` write is 0.52, 0.76, 1.03,
1.30 and 1.58 s for levels 1 to 5. Choosing flash mode in the iPhone app sends
nothing by itself. The iPhone traces this was decoded from are in `captures/`.

## Development

```sh
uv run pytest          # no hardware needed
uv run ruff check .
```

`examples/` has small scripts that use a real pod: `scan.py` and `status.py` (raw
Bluetooth), and `set_arms.py`, `ramp.py`, `boost.py`, `flash.py` and `lights.py`, which use the
`Pod` class and take `--label NAME`.
