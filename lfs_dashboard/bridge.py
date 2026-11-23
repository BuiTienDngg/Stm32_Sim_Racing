"""LFS OutGauge UDP -> ESP32 CYD USB serial. Python 3.10+, pyserial."""
import argparse
import socket
import struct
import time

import serial


OUTGAUGE = struct.Struct("<I4sHBB7fII3f16s16s")
assert OUTGAUGE.size == 92


def decode(packet):
    if len(packet) not in (92, 96):
        raise ValueError(f"OutGauge packet length {len(packet)}, expected 92 or 96")
    fields = OUTGAUGE.unpack(packet[:92])
    _, car, flags, gear, _, speed, rpm, turbo, eng_temp, fuel, oil_pressure, oil_temp, dash, shown, throttle, brake, clutch, display1, display2 = fields
    # OutGauge gear: 0=R, 1=N, 2=first forward gear.
    gear_text = "R" if gear == 0 else "N" if gear == 1 else str(gear - 1)
    return (max(0, round(speed * 3.6)), max(0, round(rpm)), gear_text,
            round(max(0, min(1, throttle)) * 100),
            round(max(0, min(1, brake)) * 100),
            round(max(0, min(1, clutch)) * 100))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="ESP32 USB-UART COM port, e.g. COM5")
    parser.add_argument("--udp-port", type=int, default=30000)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, serial.Serial(args.port, args.baud, timeout=1) as esp:
        udp.bind(("127.0.0.1", args.udp_port))
        udp.settimeout(0.5)
        time.sleep(2)  # Opening an ESP32 serial port can reset the board.
        print(f"Listening for LFS OutGauge on 127.0.0.1:{args.udp_port}; sending to {args.port}")
        last = time.monotonic()
        stale = False
        while True:
            try:
                packet, _ = udp.recvfrom(256)
                values = decode(packet)
                esp.write(("LFS," + ",".join(map(str, values)) + "\n").encode("ascii"))
                last = time.monotonic()
                stale = False
                print("\r" + "  ".join(map(str, values)).ljust(65), end="", flush=True)
            except socket.timeout:
                if not stale and time.monotonic() - last > 2:
                    esp.write(b"STOP\n")
                    print("\nWaiting for LFS telemetry...")
                    stale = True
            except ValueError as exc:
                print(f"\nSkipped packet: {exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
