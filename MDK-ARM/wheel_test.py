"""Inspect and calibrate the F411 wheel over its diagnostic USB HID interface."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from statistics import median
import struct
import sys
import time

VID, PID, USAGE_PAGE = 0xCAFE, 0x4111, 0xFF31
REPORT_ID = 0x30
PAYLOAD = struct.Struct("<iihHhBBBBH")
WHEEL_INPUT = struct.Struct("<BIhhHHH")
PEDAL_REPORT_ID = 0x31
PEDAL_PAYLOAD = struct.Struct("<9HBB")
PEDALS = ("throttle", "brake", "clutch")
PEDAL_MIN_SPAN = 32
ENCODER_REPORT_ID = 0x32
ENCODER_PAYLOAD = struct.Struct("<iiiiHBB")
I2C_STATUS = {
    0: "not reported",
    1: "read OK",
    2: "BUSY/stuck bus",
    3: "NACK, no response at 0x36",
    4: "timeout",
    5: "transfer error",
}
BUTTONS = ("Shift+ (unwired)", "Shift-", *(f"Fn{i}" for i in range(1, 9)),
           *(f"Gear{i}" for i in range(1, 7)), "R", "Turn up", "Turn down", "Headlight flash", "N")
JOY_REPORT_ID, MAP_REPORT_ID, EXTRA_REPORT_ID = 0x33, 0x34, 0x35
JOY_PAYLOAD = struct.Struct("<10H")
MAP_PAYLOAD = struct.Struct("<21B")
EXTRA_PAYLOAD = struct.Struct("<II12B")
DEADZONE_REPORT_ID = 0x36
DEADZONE_PAYLOAD = struct.Struct("<3B17x")
FAULTS = {
    0: "none",
    1: "outside calibrated travel",
    2: "encoder stopped under torque",
    3: "encoder moved against bench pulse",
    4: "AS5600 unavailable or magnet invalid",
    5: "Hall/AS5600 disagreement, reset or recalibrate",
}


@dataclass
class Status:
    count: int
    millidegrees: int
    axis: int
    buttons: int
    duty: int
    stage: int
    flags: int
    fault: int
    result: int
    travel: int
    physical: int = 0

    @property
    def calibration_saved(self):
        return bool(self.flags & 8)

    @property
    def ready(self):
        return bool(self.flags & 2)

    def line(self):
        angle = f"{self.millidegrees / 1000:+8.2f} deg" if self.stage == 3 else "uncalibrated"
        pressed = " ".join(name for i, name in enumerate(BUTTONS) if self.buttons & (1 << i))
        pwm = 100 * self.duty / 4200
        fault = FAULTS.get(self.fault, f"unknown {self.fault}")
        gear = next((str(i + 1) for i in range(6) if self.physical & (1 << (10 + i))),
                    "R" if self.physical & (1 << 16) else "N")
        return (f"{angle:>12} | raw {self.count:+8d} | HID X {self.axis:+6d} | "
                f"gear {gear:>1} | "
                f"buttons {pressed or '-':<41} | PWM {pwm:+5.1f}% | "
                f"cal {'saved' if self.calibration_saved else 'unsaved'} | fault {fault}")


def read_status(device):
    report = bytes(device.get_feature_report(REPORT_ID, 1 + PAYLOAD.size))
    if len(report) != 1 + PAYLOAD.size or report[0] != REPORT_ID:
        raise RuntimeError("Unexpected diagnostic report. Check the firmware version.")
    status = Status(*PAYLOAD.unpack(report[1:]))
    status.buttons |= (status.flags & 1) << 16
    try:
        status.physical, status.buttons = read_extra(device)[:2]
    except (OSError, RuntimeError):
        pass  # Older firmware only reports the first 17 buttons.
    return status


def send(device, operation, *values):
    report = (bytes((REPORT_ID, operation)) + struct.pack("<" + "H" * len(values), *values))
    report = report.ljust(1 + PAYLOAD.size, b"\0")
    if device.send_feature_report(report) <= 0:
        raise RuntimeError("USB command failed.")
    status = read_status(device)
    if status.result == 2:
        raise RuntimeError("Calibration could not be saved to flash. The previous saved record was kept.")
    if status.result:
        reasons = {
            3: "AS5600 angle unavailable. Check I2C and magnet with: python wheel_test.py encoders --once",
            4: "LEFT is too close to CENTER. Check AS5600 movement and turn to the left mark.",
            5: "Hall did not register sufficient movement. Check encoder A/B on PA6/PA7.",
            6: "LEFT and RIGHT marks must be on opposite sides of CENTER.",
            7: "Measured travel is invalid or differs from --degrees by over 10%. Check the physical marks.",
            8: "Joystick positions are too close or overlap. Check both ADC axes and capture center/up/down/pull again.",
        }
        reason = reasons.get(status.result, "Command rejected. Check calibration order and wheel position.")
        fault = FAULTS.get(status.fault, str(status.fault))
        raise RuntimeError(f"{reason} [operation {operation}, stage {status.stage}, fault {fault}]")
    return status


@contextmanager
def open_wheel(usage_page=USAGE_PAGE):
    try:
        import hid
    except ImportError as exc:
        raise RuntimeError("Install hidapi with: python -m pip install hidapi") from exc
    devices = [d for d in hid.enumerate(VID, PID) if d.get("usage_page") == usage_page]
    if not devices:
        raise RuntimeError(f"F411 HID interface {usage_page:04X} not found. Check the data cable and firmware.")
    if len(devices) != 1:
        raise RuntimeError("Connect only one F411 wheel while testing.")
    device = hid.device()
    device.open_path(devices[0]["path"])
    try:
        yield device
    finally:
        device.close()


def calibrate(device, travel):
    print("Switch off motor power and close the game before calibrating.")
    print(f"Total travel {travel} deg. Use marks at -{travel/2:g} and +{travel/2:g} deg.")
    print("Keep Hall and AS5600 connected. Move slowly through the full marked travel.")
    for command, prompt in enumerate(("CENTER", "LEFT mark", "RIGHT mark"), 1):
        input(f"Hold the wheel at {prompt} and press Enter: ")
        status = send(device, command, travel if command == 1 else 0)
        print(f"Captured raw count {status.count:+d}")
    if status.calibration_saved:
        print("Steering limits and Hall/AS5600 ratio saved to flash. Boot with the wheel centered.")
    else:
        print("Calibration complete in RAM. Update the firmware to save it in flash.")


def monitor(device):
    print("Turn the wheel and press buttons. Ctrl+C exits.")
    while True:
        status = read_status(device)
        print("\r" + status.line().ljust(190), end="", flush=True)
        time.sleep(0.05)


def read_pedal_status(device):
    report = bytes(device.get_feature_report(PEDAL_REPORT_ID, 1 + PEDAL_PAYLOAD.size))
    if len(report) != 1 + PEDAL_PAYLOAD.size or report[0] != PEDAL_REPORT_ID:
        raise RuntimeError("Pedal calibration report unavailable. Flash the current firmware.")
    return PEDAL_PAYLOAD.unpack(report[1:])


def read_feature(device, report_id, payload):
    report = bytes(device.get_feature_report(report_id, 1 + payload.size))
    if len(report) != 1 + payload.size or report[0] != report_id:
        raise RuntimeError(f"Report 0x{report_id:02X} unavailable. Flash the current firmware.")
    return payload.unpack(report[1:])


def read_joystick(device):
    return read_feature(device, JOY_REPORT_ID, JOY_PAYLOAD)


def read_mapping(device):
    return read_feature(device, MAP_REPORT_ID, MAP_PAYLOAD)


def read_extra(device):
    return read_feature(device, EXTRA_REPORT_ID, EXTRA_PAYLOAD)


def read_deadzones(device):
    return read_feature(device, DEADZONE_REPORT_ID, DEADZONE_PAYLOAD)


def capture_pedal(device, channel):
    samples = []
    for _ in range(15):
        time.sleep(0.02)
        status = read_pedal_status(device)
        if status[-1]:
            samples.append(status[channel])
    if len(samples) < 11:
        raise RuntimeError("ADC samples unavailable. Check the firmware and try again.")
    return int(median(samples))


def calibrate_pedal(device, name):
    channel = PEDALS.index(name)
    print("Switch off motor power and close the game before calibrating.")
    input(f"Release {name} completely and press Enter. Hold until captured: ")
    released = capture_pedal(device, channel)
    print(f"Released ADC: {released}")
    input(f"Press {name} fully and press Enter. Hold until captured: ")
    pressed = capture_pedal(device, channel)
    print(f"Pressed ADC: {pressed}")
    if abs(pressed - released) < PEDAL_MIN_SPAN:
        raise RuntimeError(f"ADC span is too small. Move the pedal at least {PEDAL_MIN_SPAN} ADC counts.")
    send(device, 12, channel, released, pressed)
    status = read_pedal_status(device)
    offset = len(PEDALS) + 2 * channel
    if status[offset:offset + 2] != (released, pressed) or not status[-2] & (1 << channel):
        raise RuntimeError("Could not confirm the saved pedal range.")
    print(f"{name.capitalize()} saved to flash: ADC {released} to {pressed} maps to 0 to 100%.")


def monitor_encoders(device, once=False):
    print("Reading encoder mode and steering position.")
    print("Keep motor power off for the first check. Ctrl+C exits.")
    while True:
        report = bytes(device.get_feature_report(ENCODER_REPORT_ID, 1 + ENCODER_PAYLOAD.size))
        if len(report) != 1 + ENCODER_PAYLOAD.size or report[0] != ENCODER_REPORT_ID:
            raise RuntimeError("Encoder report unavailable. Flash the BTS7960/AS5600 firmware.")
        hall, absolute, fused, scale_q16, raw, flags, magnet = ENCODER_PAYLOAD.unpack(report[1:])
        if flags & 0x80:
            status = read_status(device)
            print("\rHall-only | " + status.line().ljust(210), end="", flush=True)
            if once:
                print()
                return
            time.sleep(0.05)
            continue
        hall_angle = f"{hall * scale_q16 / 65536 * 360 / 4096:+8.2f}" if flags & 4 else "uncal"
        healthy = "OK" if flags & 2 else "FAULT"
        error = absolute - fused
        line = (f"Hall {hall:+8d} ({hall_angle} deg) | AS raw {raw:4d} "
                f"({absolute * 360 / 4096:+8.2f} deg) | Fused {fused * 360 / 4096:+8.2f} deg | "
                f"error {error * 360 / 4096:+6.2f} deg | magnet 0x{magnet:02X} | {healthy}")
        io = I2C_STATUS.get(flags >> 4, "unknown")
        if flags & 8:
            sensor = "encoder disagreement"
        elif magnet & 0x10:
            sensor = "magnet too weak"
        elif magnet & 0x08:
            sensor = "magnet too strong"
        elif magnet & 0x20:
            sensor = "magnet detected"
        else:
            sensor = "magnet not detected"
        line += f" | I2C {io} | {sensor}"
        print("\r" + line.ljust(280), end="", flush=True)
        if once:
            print()
            return
        time.sleep(0.05)


def monitor_pedals(device):
    print("Press each pedal separately. Ctrl+C exits.")
    while True:
        report = bytes(device.get_input_report(1, WHEEL_INPUT.size))
        if len(report) != WHEEL_INPUT.size or report[0] != 1:
            raise RuntimeError("Pedal input report unavailable. Flash the firmware with ADC pedals.")
        _, _, _, _, throttle, brake, clutch = WHEEL_INPUT.unpack(report)
        print(f"\rThrottle (PA0/Z) {throttle:4d}/4095 | Brake (PA1/Rz) {brake:4d}/4095 | "
              f"Clutch (PA2/Rx) {clutch:4d}/4095", end="", flush=True)
        time.sleep(0.05)


def pulse(device, direction, bench=False):
    status = read_status(device)
    if not status.ready or abs(status.axis) > 8192:
        raise RuntimeError("Calibrate, return near center and check the firmware fault status.")
    if bench:
        print(f"One bench pulse toward {direction}: up to 90% duty for up to 1 second.")
        print("Secure the unloaded motor, use a current-limited supply and keep clear of the shaft.")
        if input("Type RUN 90 to send, or Ctrl+C to cancel: ").strip() != "RUN 90":
            return
    else:
        print(f"Brief low-duty motor pulse toward {direction}. Keep clear of the wheel.")
        input("Press Enter to send the pulse, or Ctrl+C to cancel: ")

    baseline = read_status(device)
    operation = (6 if bench else 4) + (direction == "right")
    try:
        end = send(device, operation)
        peak = end.duty
        min_count, max_count = sorted((baseline.count, end.count))
        min_angle, max_angle = sorted((baseline.millidegrees, end.millidegrees))
        deadline = time.monotonic() + (1.15 if bench else 0.55)
        while time.monotonic() < deadline:
            time.sleep(0.01)
            end = read_status(device)
            min_count = min(min_count, end.count)
            max_count = max(max_count, end.count)
            min_angle = min(min_angle, end.millidegrees)
            max_angle = max(max_angle, end.millidegrees)
            if abs(end.duty) > abs(peak):
                peak = end.duty
    finally:
        if bench:
            try:
                send(device, 8)
            except (OSError, RuntimeError):
                print("\nUSB stop not confirmed. Switch off motor power.")
    final_delta = (end.millidegrees - baseline.millidegrees) / 1000
    low_delta = (min_angle - baseline.millidegrees) / 1000
    high_delta = (max_angle - baseline.millidegrees) / 1000
    print(f"PWM peak {100 * peak / 4200:+.1f}% | raw span {max_count - min_count} counts")
    print(f"Angle during test {low_delta:+.2f} to {high_delta:+.2f} deg | final {final_delta:+.2f} deg")
    print(end.line())


def spin_motor(device, direction, duty):
    before = read_status(device)
    if before.fault:
        raise RuntimeError("Switch off motor power and reset the board with the wheel centered.")
    print(f"Unloaded motor: {direction}, up to {duty}% PWM for 1 second.")
    print("Secure the motor, keep the shaft clear and use a current-limited supply.")
    if input("Type SPIN to run once, or Ctrl+C to cancel: ").strip() != "SPIN":
        return

    # Suspend saved steering calibration in RAM for this unloaded bench session.
    before = send(device, 11)
    baseline = before.count
    peak = 0
    try:
        sample = send(device, 9 if direction == "left" else 10, duty)
        minimum, maximum = sorted((baseline, sample.count))
        peak = sample.duty
        deadline = time.monotonic() + 1.15
        while time.monotonic() < deadline and not sample.fault:
            time.sleep(0.01)
            sample = read_status(device)
            minimum = min(minimum, sample.count)
            maximum = max(maximum, sample.count)
            if abs(sample.duty) > abs(peak):
                peak = sample.duty
    finally:
        try:
            send(device, 8)
        except (OSError, RuntimeError):
            print("USB stop not confirmed. Switch off motor power.")
    print(f"PWM peak {100 * peak / 4200:+.1f}% | raw span {maximum - minimum} counts")
    print(sample.line())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("monitor", help="Show encoder, steering angle, buttons and PWM")
    encoders = commands.add_parser("encoders", help="Compare Hall, AS5600 and fused steering angles")
    encoders.add_argument("--once", action="store_true", help="Read sensor health once and exit")
    commands.add_parser("pedals", help="Show calibrated throttle, brake and clutch")
    pedal = commands.add_parser("calibrate-pedal", help="Capture released and pressed ADC values and save to flash")
    pedal.add_argument("pedal", choices=PEDALS)
    calibration = commands.add_parser("calibrate", help="Capture center and the two travel marks")
    calibration.add_argument("--degrees", type=int, default=270, metavar="90..1080")
    test = commands.add_parser("pulse", help="Send a single brief motor pulse")
    test.add_argument("direction", choices=["left", "right"])
    test.add_argument("--bench-90", action="store_true", help="One bench pulse, up to 90 percent PWM for up to 1 second")
    spin = commands.add_parser("spin", help="Run an unloaded motor without steering angle limits for up to 1 second")
    spin.add_argument("direction", choices=["left", "right"])
    spin.add_argument("--duty", type=int, choices=range(15, 61), default=25, metavar="15..60")
    args = parser.parse_args()
    if args.command == "calibrate" and not 90 <= args.degrees <= 1080:
        parser.error("--degrees must be between 90 and 1080")
    try:
        if args.command == "pedals":
            with open_wheel(usage_page=1) as device:
                monitor_pedals(device)
            return 0
        with open_wheel() as device:
            if args.command == "calibrate":
                calibrate(device, args.degrees)
            elif args.command == "encoders":
                monitor_encoders(device, args.once)
            elif args.command == "calibrate-pedal":
                calibrate_pedal(device, args.pedal)
            elif args.command == "pulse":
                pulse(device, args.direction, args.bench_90)
            elif args.command == "spin":
                spin_motor(device, args.direction, args.duty)
            else:
                monitor(device)
    except KeyboardInterrupt:
        print()
    except (OSError, RuntimeError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
