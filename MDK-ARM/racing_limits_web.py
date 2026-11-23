"""Bridge the F411 wheel to Racing Limits (CrazyGames) keyboard controls on Windows."""
import argparse
import ctypes
import sys
import time

from wheel_test import WHEEL_INPUT, open_wheel


UP, DOWN, LEFT, RIGHT, SHIFT_UP, SHIFT_DOWN = 0x48, 0x50, 0x4B, 0x4D, 0x11, 0x20
EXTENDED = {UP, DOWN, LEFT, RIGHT}
INPUT_KEYBOARD = 1
KEYUP = 0x0002
SCANCODE = 0x0008
EXTENDEDKEY = 0x0001


class KeyboardInput(ctypes.Structure):
    _fields_ = (("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t))


class InputUnion(ctypes.Union):
    _fields_ = (("ki", KeyboardInput), ("padding", ctypes.c_byte * 32))


class Input(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong), ("union", InputUnion))


class KeyOutput:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.held = set()

    def event(self, scan, down):
        flags = SCANCODE | (EXTENDEDKEY if scan in EXTENDED else 0) | (0 if down else KEYUP)
        event = Input(INPUT_KEYBOARD, InputUnion(ki=KeyboardInput(0, scan, flags, 0, 0)))
        if self.enabled and ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError("SendInput failed; run the browser at the same privilege level as Python")

    def hold(self, scan, down):
        if down != (scan in self.held):
            self.event(scan, down)
            if down:
                self.held.add(scan)
            else:
                self.held.remove(scan)

    def tap(self, scan, duration=0.055):
        self.hold(scan, True)
        time.sleep(duration)
        self.hold(scan, False)

    def release_all(self):
        for scan in tuple(self.held):
            self.hold(scan, False)


def gear_from_buttons(buttons):
    selected = [i + 1 for i in range(6) if buttons & (1 << (10 + i))]
    return selected[0] if len(selected) == 1 else None


def main():
    parser = argparse.ArgumentParser(description="Play Racing Limits in a browser with the F411 wheel")
    parser.add_argument("--steer-deadzone", type=float, default=0.12, help="wheel fraction, default 0.12")
    parser.add_argument("--pedal-threshold", type=float, default=0.12, help="pedal fraction, default 0.12")
    parser.add_argument("--manual", action="store_true", help="H positions 1-6 emit W/D shifts")
    parser.add_argument("--start-gear", type=int, default=1, help="game gear at startup in manual mode (1-6)")
    parser.add_argument("--require-clutch", action="store_true", help="shift only with clutch over 50%%")
    parser.add_argument("--dry-run", action="store_true", help="show inputs without sending keys")
    args = parser.parse_args()
    if not 0 <= args.steer_deadzone < 1 or not 0 <= args.pedal_threshold < 1:
        parser.error("thresholds must be between 0 and 1")
    if not 1 <= args.start_gear <= 6:
        parser.error("--start-gear must be 1-6")
    if sys.platform != "win32":
        parser.error("Windows only")

    keyboard = KeyOutput(not args.dry_run)
    game_gear = args.start_gear
    last_position = None
    pending = 0
    next_shift = 0.0
    print("Open https://www.crazygames.com/game/racing-limits and click inside the game.")
    print("Focus stays on the browser. Ctrl+C here stops the bridge and releases all keys.")
    if args.manual:
        print(f"Manual mode: set the GAME to gear {game_gear} before starting. R and N have no web key.")
    try:
        with open_wheel(1) as device:
            while True:
                report = bytes(device.get_input_report(1, WHEEL_INPUT.size))
                if len(report) != WHEEL_INPUT.size or report[0] != 1:
                    raise RuntimeError("Invalid wheel input report")
                _, buttons, steering, _, throttle, brake, clutch = WHEEL_INPUT.unpack(report)
                steer = steering / 32767
                keyboard.hold(LEFT, steer < -args.steer_deadzone)
                keyboard.hold(RIGHT, steer > args.steer_deadzone)
                keyboard.hold(UP, throttle / 4095 > args.pedal_threshold)
                keyboard.hold(DOWN, brake / 4095 > args.pedal_threshold)
                position = gear_from_buttons(buttons)
                if args.manual and position != last_position:
                    if position is None:
                        last_position = None
                    elif not args.require_clutch or clutch > 2047:
                        pending = position - game_gear
                        last_position = position
                now = time.monotonic()
                if pending and now >= next_shift:
                    direction = 1 if pending > 0 else -1
                    keyboard.tap(SHIFT_UP if direction > 0 else SHIFT_DOWN)
                    pending -= direction
                    game_gear += direction
                    next_shift = time.monotonic() + 0.10
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.release_all()


if __name__ == "__main__":
    main()
