"""Windows DirectInput Constant Force test for the F411 DIY FFB Wheel."""
import argparse
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import math
import sys
import time
import uuid

from wheel_test import FAULTS, PID, VID, WHEEL_INPUT, open_wheel, read_status

DWORD, LONG, PTR = w.DWORD, w.LONG, c.c_void_p
HRESULT = c.c_long
PULSE_MS = 300
SIMULATION_MS = 800
SIMULATION_UPDATE_S = 0.02
DIEP_TYPESPECIFICPARAMS = 0x00000100
DIEP_NORESTART = 0x40000000
STOP_ALL, ACTUATORS_ON, ACTUATORS_OFF = 2, 16, 32


class Guid(c.Structure):
    _fields_ = [("data1", DWORD), ("tail", c.c_ubyte * 12)]


def guid(value):
    return Guid.from_buffer_copy(uuid.UUID(value).bytes_le)


DIRECT_INPUT_8W = guid("bf798031-483a-4da2-aa99-5d64ed369700")
X_AXIS = guid("a36d02e0-c9f3-11cf-bfc7-444553540000")
CONSTANT_FORCE = guid("13541c20-8e33-11d0-9ad0-00a0c9a06e35")


class DeviceInstance(c.Structure):
    # Prefix of DIDEVICEINSTANCEW used by the enumeration callback.
    _fields_ = [("size", DWORD), ("instance", Guid), ("product", Guid),
                ("type", DWORD), ("name", w.WCHAR * 260)]


class EffectInfo(c.Structure):
    _fields_ = [("size", DWORD), ("guid", Guid), ("type", DWORD),
                ("static_params", DWORD), ("dynamic_params", DWORD),
                ("name", w.WCHAR * 260)]


class AxisFormat(c.Structure):
    _fields_ = [("guid", c.POINTER(Guid)), ("offset", DWORD),
                ("type", DWORD), ("flags", DWORD)]


class DataFormat(c.Structure):
    _fields_ = [("size", DWORD), ("object_size", DWORD), ("flags", DWORD),
                ("data_size", DWORD), ("count", DWORD), ("objects", c.POINTER(AxisFormat))]


class ConstantForce(c.Structure):
    _fields_ = [("magnitude", LONG)]


class Effect(c.Structure):
    _fields_ = [
        ("size", DWORD), ("flags", DWORD), ("duration", DWORD),
        ("sample_period", DWORD), ("gain", DWORD), ("trigger_button", DWORD),
        ("trigger_repeat_interval", DWORD), ("axes_count", DWORD),
        ("axes", c.POINTER(DWORD)), ("directions", c.POINTER(LONG)), ("envelope", PTR),
        ("parameter_size", DWORD), ("parameters", PTR), ("start_delay", DWORD),
    ]


def check(hr, operation):
    if hr < 0:
        raise RuntimeError(f"{operation} failed (HRESULT 0x{hr & 0xFFFFFFFF:08X}).")


def call(obj, slot, argtypes=(), *args):
    """Invoke a COM method by its slot in the Windows SDK interface."""
    table = c.cast(obj, c.POINTER(c.POINTER(PTR)))[0]
    return c.WINFUNCTYPE(HRESULT, PTR, *argtypes)(table[slot])(obj, *args)


@contextmanager
def direct_input_device():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = (w.LPCWSTR,)
    kernel.GetModuleHandleW.restype = w.HMODULE
    instance = kernel.GetModuleHandleW(None)
    dll = c.WinDLL("dinput8")
    create = dll.DirectInput8Create
    create.argtypes = (w.HINSTANCE, DWORD, c.POINTER(Guid), c.POINTER(PTR), PTR)
    create.restype = HRESULT

    api, device = PTR(), PTR()
    check(create(instance, 0x0800, c.byref(DIRECT_INPUT_8W), c.byref(api), None),
          "DirectInput8Create")
    try:
        candidates = []
        callback_type = c.WINFUNCTYPE(w.BOOL, c.POINTER(DeviceInstance), PTR)

        @callback_type
        def find(pointer, context):
            item = pointer.contents
            if item.product.data1 == (PID << 16) | VID:
                candidates.append((Guid.from_buffer_copy(item.instance), item.name))
            return True

        # EnumDevices(DI8DEVCLASS_GAMECTRL, ..., DIEDFL_ATTACHEDONLY).
        check(call(api, 4, (DWORD, callback_type, PTR, DWORD), 4, find, None, 1),
              "EnumDevices")
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one F411 wheel in DirectInput. Found {len(candidates)}.")
        instance_guid, name = candidates[0]
        check(call(api, 3, (c.POINTER(Guid), c.POINTER(PTR), PTR),
                   c.byref(instance_guid), c.byref(device), None), "CreateDevice")
        print(f"DirectInput device: {name} (VID {VID:04X}, PID {PID:04X})")

        info = EffectInfo(size=c.sizeof(EffectInfo))
        check(call(device, 20, (c.POINTER(EffectInfo), c.POINTER(Guid)),
                   c.byref(info), c.byref(CONSTANT_FORCE)), "GetEffectInfo(Constant Force)")
        print("DirectInput reports Constant Force support.")
        yield device, instance
    finally:
        if device:
            call(device, 2)  # IUnknown::Release
        call(api, 2)


@contextmanager
def exclusive_access(device, instance):
    user = c.WinDLL("user32", use_last_error=True)
    create = user.CreateWindowExW
    create.argtypes = (DWORD, w.LPCWSTR, w.LPCWSTR, DWORD, c.c_int, c.c_int,
                       c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, PTR)
    create.restype = w.HWND
    user.DestroyWindow.argtypes = (w.HWND,)
    user.DestroyWindow.restype = w.BOOL
    hwnd = create(0, "STATIC", "F411 DirectInput test", 0, 0, 0, 1, 1,
                  None, None, instance, None)
    if not hwnd:
        raise c.WinError(c.get_last_error())

    # Map only absolute steering X to offset 0. Other controls are unused.
    axis = AxisFormat(c.pointer(X_AXIS), 0, 0x00FFFF02, 0)
    fmt = DataFormat(c.sizeof(DataFormat), c.sizeof(AxisFormat), 1, 4, 1, c.pointer(axis))
    acquired = False
    try:
        check(call(device, 11, (c.POINTER(DataFormat),), c.byref(fmt)), "SetDataFormat")
        # DISCL_EXCLUSIVE | DISCL_BACKGROUND. Allows the console to keep focus.
        check(call(device, 13, (w.HWND, DWORD), hwnd, 0x09), "SetCooperativeLevel")
        check(call(device, 7), "Acquire (close LFS and other controller apps)")
        acquired = True
        yield
    finally:
        if acquired:
            call(device, 22, (DWORD,), STOP_ALL)
            call(device, 22, (DWORD,), ACTUATORS_OFF)
            call(device, 8)  # Unacquire
        user.DestroyWindow(hwnd)


def require_ready(status):
    if status.fault:
        raise RuntimeError(f"Firmware fault: {FAULTS.get(status.fault, status.fault)}. Switch off motor power and reset at center.")
    if not status.ready or abs(status.axis) > 8192:
        raise RuntimeError("Calibrate and move near center. Check fault in wheel_test.py monitor.")


def play(device, instance, direction, strength, simulate=False):
    duration_ms = SIMULATION_MS if simulate else PULSE_MS
    duration_s = duration_ms / 1000
    with open_wheel() as diagnostic:
        require_ready(read_status(diagnostic))
        mode = "streamed" if simulate else "fixed"
        print(f"One {duration_ms} ms {mode} DirectInput effect, {direction}, up to {strength}% nominal force.")
        print("For a dry test, leave the motor's 12 V supply off. Keep clear of the shaft.")
        input("Press Enter to send the effect, or Ctrl+C to cancel: ")
        baseline = read_status(diagnostic)
        require_ready(baseline)

        axis = DWORD(0)
        cartesian_direction = LONG(0)  # Single-axis effect. Magnitude sign selects direction.
        magnitude = strength * (100 if direction == "right" else -100)
        force = ConstantForce(0 if simulate else magnitude)
        parameters = Effect(
            size=c.sizeof(Effect), flags=0x12, duration=duration_ms * 1000,
            gain=10000, trigger_button=0xFFFFFFFF, axes_count=1,
            axes=c.pointer(axis), directions=c.pointer(cartesian_direction),
            parameter_size=c.sizeof(force), parameters=c.cast(c.pointer(force), PTR),
        )
        effect = PTR()
        peak = 0
        low_count = high_count = baseline.count
        sample = baseline
        updates = 0
        with exclusive_access(device, instance):
            try:
                check(call(device, 22, (DWORD,), ACTUATORS_ON), "Enable actuators")
                check(call(device, 18, (c.POINTER(Guid), c.POINTER(Effect), c.POINTER(PTR), PTR),
                           c.byref(CONSTANT_FORCE), c.byref(parameters), c.byref(effect), None),
                      "CreateEffect(Constant Force)")
                check(call(effect, 7, (DWORD, DWORD), 1, 0), "Start effect")
                started = time.monotonic()
                next_update = 0.0
                while (elapsed := time.monotonic() - started) < duration_s + 0.12:
                    if simulate and next_update <= elapsed < duration_s:
                        force.magnitude = round(magnitude * math.sin(math.pi * elapsed / duration_s))
                        check(call(effect, 6, (c.POINTER(Effect), DWORD), c.byref(parameters),
                                   DIEP_TYPESPECIFICPARAMS | DIEP_NORESTART),
                              "SetParameters(Constant Force)")
                        next_update = elapsed + SIMULATION_UPDATE_S
                        updates += 1
                    sample = read_status(diagnostic)
                    if abs(sample.duty) > abs(peak):
                        peak = sample.duty
                    low_count = min(low_count, sample.count)
                    high_count = max(high_count, sample.count)
                    if not sample.ready:
                        break
                    time.sleep(0.01)
            finally:
                if effect:
                    call(effect, 8)   # Stop
                    call(effect, 11)  # Unload
                    call(effect, 2)   # Release

        if simulate:
            print(f"DirectInput magnitude updates: {updates}")
        print(f"Firmware PWM peak {100 * peak / 4200:+.1f}% | raw span {high_count-low_count} counts")
        print(f"Final angle change: {(sample.millidegrees - baseline.millidegrees) / 1000:+.2f} deg")
        if not sample.ready:
            raise RuntimeError(f"Motor output disabled during test. Fault: {FAULTS.get(sample.fault, sample.fault)}.")
        if peak == 0:
            raise RuntimeError("DirectInput started the effect, but no PWM was observed in the firmware.")


def watch_pid(seconds=20):
    """Observe game effects and firmware PWM without acquiring the joystick."""
    print(f"Watching FFB for {seconds} seconds. Switch to LFS and drive through a gentle turn.", flush=True)
    enabled_samples = active_samples = 0
    minimum_duty = maximum_duty = 0
    faults = set()
    with open_wheel(usage_page=1) as joystick, open_wheel() as diagnostic:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            # PID State is input report 2. Allocate room for the longest input report.
            report = bytes(joystick.get_input_report(2, WHEEL_INPUT.size))
            if len(report) < 2 or report[0] != 2:
                raise RuntimeError("Unexpected PID State report from the wheel.")
            enabled_samples += bool(report[1] & 0x02)
            active_samples += bool(report[1] & 0x10)
            status = read_status(diagnostic)
            minimum_duty = min(minimum_duty, status.duty)
            maximum_duty = max(maximum_duty, status.duty)
            if status.fault:
                faults.add(status.fault)
            time.sleep(0.05)

    print(f"Actuators enabled samples: {enabled_samples} | Active effect samples: {active_samples}")
    print(f"Firmware PWM range: {minimum_duty / 42:+.1f}% to {maximum_duty / 42:+.1f}%")
    fault_names = ", ".join(str(FAULTS.get(fault, fault)) for fault in sorted(faults))
    print(f"Faults observed: {fault_names or 'none'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pulse", choices=("left", "right"), help="Send one 300 ms effect after confirmation")
    mode.add_argument("--simulate", choices=("left", "right"),
                      help="Stream changing Constant Force for 800 ms after confirmation")
    mode.add_argument("--watch", action="store_true", help="Observe game FFB and PWM for 20 seconds")
    parser.add_argument("--strength", type=int, choices=range(10, 101), default=30, metavar="10..100",
                        help="Percent of nominal DirectInput force (default 30)")
    args = parser.parse_args()
    try:
        if args.watch:
            watch_pid()
            return 0
        with direct_input_device() as (device, instance):
            if args.pulse:
                play(device, instance, args.pulse, args.strength)
            elif args.simulate:
                play(device, instance, args.simulate, args.strength, simulate=True)
    except KeyboardInterrupt:
        print("\nCanceled.")
        return 130
    except (OSError, RuntimeError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

