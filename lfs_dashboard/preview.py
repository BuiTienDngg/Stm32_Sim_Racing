"""Preview the CYD dashboard on a PC. No ESP32, LFS or extra packages needed."""
import argparse
import math
import tkinter as tk
import time


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
        self.start = None
        self.playing = True
        self.speed = 0
        self.rpm = 0
        self.gear = "N"
        self.throttle = self.brake = self.clutch = 0
        self.draw()
        self.tick()

    def text(self, x, y, value, size, color, anchor="nw", bold=False):
        self.canvas.create_text(x * SCALE, y * SCALE, text=str(value), anchor=anchor,
                                font=("Arial", size * SCALE, "bold" if bold else "normal"),
                                fill=color)

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.text(12, 8, "LIVE FOR SPEED", 9, CYAN, bold=True)
        self.text(308, 8, "LIVE" if self.playing else "WAITING", 9,
                  GREEN if self.playing else ORANGE, anchor="ne", bold=True)
        self.text(14, 39, "SPEED", 10, WHITE)
        self.text(12, 56, self.speed, 40, CYAN, bold=True)
        self.text(205, 100, "km/h", 9, WHITE)
        c.create_line(12*SCALE, 127*SCALE, 308*SCALE, 127*SCALE, fill=GREY)
        self.text(15, 141, "RPM", 10, WHITE)
        self.text(14, 160, self.rpm, 23, YELLOW, bold=True)
        self.text(232, 142, "GEAR", 10, WHITE)
        self.text(238, 163, self.gear, 24, GREEN, bold=True)
        for i, (name, value, color) in enumerate((
                ("GAS", self.throttle, GREEN), ("BRK", self.brake, RED),
                ("CLT", self.clutch, BLUE))):
            x = 14 + i * 102
            self.text(x, 205, name, 10, WHITE)
            c.create_rectangle(x*SCALE, 225*SCALE, (x+88)*SCALE, 235*SCALE,
                               outline=GREY)
            c.create_rectangle((x+1)*SCALE, 226*SCALE,
                               (x+1+86*max(0, min(100, value))/100)*SCALE,
                               234*SCALE, fill=color, outline="")

    def tick(self):
        if self.start is None:
            self.start = time.monotonic()
        elapsed = time.monotonic() - self.start
        self.speed, self.rpm, self.gear, self.throttle, self.brake, self.clutch = demo_values(elapsed)
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
