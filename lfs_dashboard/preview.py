"""CYD dashboard preview: demo or LFS OutGauge, optionally forwarded to CYD."""
import argparse
import math
import socket
import tkinter as tk
import time
from tkinter import ttk

from bridge import decode


SCALE = 2
WIDTH, HEIGHT = 320, 240
BLACK, WHITE = "#000000", "#ffffff"
CYAN, GREEN, YELLOW = "#00ffff", "#00e060", "#ffe000"
RED, BLUE, ORANGE, GREY = "#f04040", "#407fff", "#ff9800", "#606060"


def demo_values(seconds):
    """Repeatable driving sequence so every display value can be inspected."""
    phase = seconds % 35.0
    if phase < 2:
        return 0, 800, "N", 0, 0, 0
    if phase < 24:
        speed = min(155, int((phase - 2) * 7.2))
        gear = min(6, 1 + speed // 27)
        rpm = 1700 + (speed % 27) * 175
        clutch = 90 if (speed % 27) < 3 else 0
        return speed, rpm, str(gear), 72 + int(18 * math.sin(seconds)), 0, clutch
    if phase < 30:
        speed = max(0, int(155 * (30 - phase) / 6))
        return speed, max(850, int(speed * 33)), str(max(1, 1 + speed // 27)), 0, 78, 0
    return 0, 850, "N", 0, 0, 65 if phase < 31 else 0


class Preview:
    def __init__(self, root):
        self.root = root
        root.title("LFS dashboard · CYD 320×240 preview")
        root.resizable(False, False)
        self.canvas = tk.Canvas(root, width=WIDTH * SCALE, height=HEIGHT * SCALE,
                                bg=BLACK, highlightthickness=0)
        self.canvas.pack()
        controls = ttk.Frame(root, padding=8)
        controls.pack(fill="x")
        self.ports = ttk.Combobox(controls, width=12, state="readonly")
        self.ports.pack(side="left")
        ttk.Button(controls, text="Refresh COM", command=self.refresh_ports).pack(side="left", padx=4)
        self.connect_button = ttk.Button(controls, text="Connect CYD", command=self.toggle_serial)
        self.connect_button.pack(side="left", padx=4)
        self.mode_button = ttk.Button(controls, text="Use LFS", command=self.toggle_mode)
        self.mode_button.pack(side="left", padx=4)
        self.status = tk.StringVar(value="Demo · CYD disconnected")
        ttk.Label(root, textvariable=self.status, padding=(8, 0, 8, 8)).pack(anchor="w")
        self.serial_port = None
        self.udp = None
        self.lfs_mode = False
        self.last_packet = 0.0
        self.last_sent = 0.0
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.start = None
        self.playing = True
        self.speed = 0
        self.rpm = 0
        self.gear = "N"
        self.throttle = self.brake = self.clutch = 0
        self.draw()
        self.tick()

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except ImportError:
            self.status.set("Install pyserial: python -m pip install pyserial")
            ports = []
        current = self.ports.get()
        self.ports["values"] = ports
        if current in ports:
            self.ports.set(current)
        elif ports:
            self.ports.current(0)
        else:
            self.ports.set("")

    def toggle_serial(self):
        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None
            self.connect_button.config(text="Connect CYD")
            return
        if not self.ports.get():
            self.status.set("Select a COM port first")
            return
        try:
            import serial
            self.serial_port = serial.Serial(self.ports.get(), 115200, timeout=0, write_timeout=0.2)
        except Exception as exc:
            self.status.set(f"COM error: {exc}")
            return
        self.connect_button.config(text="Disconnect")
        self.status.set(f"Connected to {self.ports.get()}; ESP32 may reset once")

    def toggle_mode(self):
        if self.lfs_mode:
            self.udp.close()
            self.udp = None
            self.lfs_mode = False
            self.mode_button.config(text="Use LFS")
            self.start = time.monotonic()
            return
        try:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.bind(("127.0.0.1", 30000))
            self.udp.setblocking(False)
        except OSError as exc:
            if self.udp:
                self.udp.close()
                self.udp = None
            self.status.set(f"UDP 30000 unavailable: {exc}; close bridge.py")
            return
        self.lfs_mode = True
        self.last_packet = 0.0
        self.mode_button.config(text="Use demo")

    def send(self, payload):
        if self.serial_port:
            try:
                self.serial_port.write(payload.encode("ascii"))
            except Exception as exc:
                self.status.set(f"COM disconnected: {exc}")
                self.serial_port.close()
                self.serial_port = None
                self.connect_button.config(text="Connect CYD")

    def close(self):
        if self.udp:
            self.udp.close()
        if self.serial_port:
            self.serial_port.close()
        self.root.destroy()

    def text(self, x, y, value, size, color, anchor="nw", bold=False):
        self.canvas.create_text(x * SCALE, y * SCALE, text=str(value), anchor=anchor,
                                font=("Arial", size * SCALE, "bold" if bold else "normal"),
                                fill=color)

    def draw(self):
        c = self.canvas
        c.delete("all")
        panel = "#123454"
        lit = min(24, max(0, self.rpm) * 24 // 8000)
        for i in range(24):
            color = GREEN if i < 13 else YELLOW if i < 19 else RED
            c.create_rectangle((2+i*13)*SCALE, 1*SCALE,
                               (13+i*13)*SCALE, 15*SCALE,
                               fill=color if i < lit else panel, outline="")
        self.text(12, 23, "RACE DASH", 9, WHITE, bold=True)
        self.text(308, 23, "LIVE" if self.playing else "WAIT", 9,
                  GREEN if self.playing else ORANGE, anchor="ne", bold=True)
        c.create_line(12*SCALE, 49*SCALE, 308*SCALE, 49*SCALE, fill=panel)
        self.text(14, 61, "SPEED", 10, WHITE)
        self.text(160, 61, "GEAR", 10, WHITE)
        self.text(12, 82, self.speed, 40, CYAN, bold=True)
        self.text(234, 81, self.gear, 48, GREEN, anchor="n", bold=True)
        self.text(99, 137, "km/h", 9, WHITE)
        c.create_line(12*SCALE, 166*SCALE, 308*SCALE, 166*SCALE, fill=panel)
        self.text(14, 174, "RPM", 10, WHITE)
        self.text(60, 171, self.rpm, 23, YELLOW, bold=True)
        for i, (name, value, color) in enumerate((
                ("THR", self.throttle, GREEN), ("BRK", self.brake, RED),
                ("CLT", self.clutch, CYAN))):
            x = 14 + i * 102
            self.text(x, 207, name, 10, WHITE)
            c.create_rectangle((x+37)*SCALE, 211*SCALE, (x+89)*SCALE, 220*SCALE,
                               outline=panel)
            c.create_rectangle((x+38)*SCALE, 212*SCALE,
                               (x+38+50*max(0, min(100, value))/100)*SCALE,
                               219*SCALE, fill=color, outline="")

    def tick(self):
        if self.start is None:
            self.start = time.monotonic()
        elapsed = time.monotonic() - self.start
        now = time.monotonic()
        if self.lfs_mode:
            try:
                while True:
                    packet, _ = self.udp.recvfrom(256)
                    try:
                        values = decode(packet)
                    except ValueError:
                        continue
                    self.speed, self.rpm, self.gear, self.throttle, self.brake, self.clutch = values
                    self.last_packet = now
                    self.send("LFS," + ",".join(map(str, values)) + "\n")
            except BlockingIOError:
                pass
            self.playing = self.last_packet > 0 and now - self.last_packet <= 2
            if not self.playing and self.last_sent != -1:
                self.speed = self.rpm = self.throttle = self.brake = self.clutch = 0
                self.gear = "N"
                self.send("STOP\n")
                self.last_sent = -1
            elif self.playing:
                self.last_sent = now
            self.status.set(f"LFS {'live' if self.playing else 'waiting'} · " +
                            (f"CYD {self.ports.get()}" if self.serial_port else "CYD disconnected"))
        else:
            self.playing = True
            self.speed, self.rpm, self.gear, self.throttle, self.brake, self.clutch = demo_values(elapsed)
            if now - self.last_sent >= 0.1:
                values = self.speed, self.rpm, self.gear, self.throttle, self.brake, self.clutch
                self.send("LFS," + ",".join(map(str, values)) + "\n")
                self.last_sent = now
            self.status.set("Demo · " + (f"CYD {self.ports.get()}" if self.serial_port else "CYD disconnected"))
        self.draw()
        self.root.after(100, self.tick)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="close automatically after a short render")
    args = parser.parse_args()
    root = tk.Tk()
    Preview(root)
    if args.smoke_test:
        root.after(300, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
