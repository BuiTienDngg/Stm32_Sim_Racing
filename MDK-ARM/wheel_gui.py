"""Visual Windows dashboard for the STM32F411 wheel. Run: python wheel_gui.py"""
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from wheel_test import (BUTTONS, FAULTS, PEDALS, capture_pedal, open_wheel,
                        read_deadzones, read_extra, read_joystick, read_mapping,
                        read_pedal_status, read_status, send)


BG = "#09111f"
SIDEBAR = "#0d1829"
CARD = "#132239"
CARD_ALT = "#172a44"
EDGE = "#27405a"
TEXT = "#eaf3ff"
MUTED = "#91a5bc"
TEAL = "#34d6c0"
BLUE = "#58a6ff"
AMBER = "#ffca65"
RED = "#ff777e"
OFF = "#263b53"
FONT = "Segoe UI"
PINS = ("—", "PA9", "PB13", "PA10", "PB14", "PA15", "PB15", "PB3",
        "PA8", "PB4", "PC13", "PC14", "PC15", "PB0", "PB1", "PB10",
        "PB12", "PA3/4", "PA3/4", "PA3/4", "Ảo")
GUI_NAMES = ("Shift+ · chưa đấu", "Giảm số", *(f"Fn{i}" for i in range(1, 9)),
             *(f"Số {i}" for i in range(1, 7)), "Số R",
             "Xi nhan ↑ · giữ", "Xi nhan ↓ · giữ", "Đá đèn", "Số N · tự động")


def label(parent, text="", size=11, weight="normal", color=TEXT, bg=None, **kwargs):
    return tk.Label(parent, text=text, font=(FONT, size, weight), fg=color,
                    bg=bg or parent.cget("bg"), **kwargs)


def card(parent, **kwargs):
    return tk.Frame(parent, bg=CARD, highlightbackground=EDGE,
                    highlightthickness=1, **kwargs)


def button(parent, text, command, primary=False, width=None):
    color = TEAL if primary else CARD_ALT
    return tk.Button(parent, text=text, command=command, width=width,
                     font=(FONT, 10, "bold"), bg=color,
                     fg=BG if primary else TEXT, activebackground=BLUE,
                     activeforeground=BG, bd=0, relief="flat", cursor="hand2",
                     padx=14, pady=9, highlightthickness=0)


class WheelWorker(threading.Thread):
    """Own the HID handle so GUI redraws never block on USB control transfers."""

    def __init__(self, events, commands):
        super().__init__(daemon=True)
        self.events = events
        self.commands = commands

    def run(self):
        while True:
            try:
                with open_wheel() as device:
                    self.events.put(("connected", True))
                    while True:
                        try:
                            token, operation, args = self.commands.get_nowait()
                        except queue.Empty:
                            token = None
                        if token is not None:
                            try:
                                if operation == "pedal_capture":
                                    answer = capture_pedal(device, args[0])
                                elif operation == "map_save":
                                    for source, target in args[0]:
                                        send(device, 14, source, target)
                                    answer = read_mapping(device)
                                else:
                                    answer = send(device, *args)
                                self.events.put(("result", token, answer, None))
                            except (OSError, RuntimeError) as exc:
                                self.events.put(("result", token, None, str(exc)))
                        self.events.put(("snapshot", {
                            "status": read_status(device),
                            "pedals": read_pedal_status(device),
                            "joy": read_joystick(device),
                            "mapping": read_mapping(device),
                            "extra": read_extra(device),
                            "deadzones": read_deadzones(device),
                        }))
                        time.sleep(0.10)
            except (OSError, RuntimeError) as exc:
                self.events.put(("connected", False, str(exc)))
                time.sleep(1.5)


class WheelApp:
    def __init__(self, root):
        self.root = root
        root.title("Wheel Control · STM32 F411")
        root.geometry("1280x820")
        root.minsize(1080, 700)
        root.configure(bg=BG)
        self.events, self.commands = queue.Queue(), queue.Queue()
        self.callbacks = {}
        self.next_token = 1
        self.connected = False
        self.map_loaded = False
        self.actual_map = None
        self.pedal_release = {}
        self.deadzone_loaded = False
        self.ffb_limit_loaded = False
        self.deadzone_values = (0, 0, 0)
        self.angle_degrees = 0
        self.travel_degrees = 270
        self.joy_report = (2048, 2048) + (0,) * 8
        self.latest_physical = 0
        self.map_vars = []
        self.map_badges = []
        self.nav_buttons = {}

        top = tk.Frame(root, bg=SIDEBAR, height=82)
        top.pack(fill="x")
        top.pack_propagate(False)
        mark = tk.Frame(top, bg=TEAL, width=42, height=42)
        mark.pack(side="left", padx=(22, 13), pady=18)
        mark.pack_propagate(False)
        label(mark, "W", 20, "bold", BG, TEAL).pack(expand=True)
        heading = tk.Frame(top, bg=SIDEBAR)
        heading.pack(side="left", pady=16)
        label(heading, "WHEEL CONTROL", 17, "bold").pack(anchor="w")
        label(heading, "STM32F411  /  USB FORCE FEEDBACK", 9,
              color=MUTED).pack(anchor="w")
        self.connection = tk.StringVar(value="ĐANG TÌM THIẾT BỊ")
        self.connection_chip = label(top, textvariable=self.connection,
                                     size=10, weight="bold", color=AMBER,
                                     bg=CARD_ALT, padx=16, pady=10)
        self.connection_chip.pack(side="right", padx=24)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, bg=SIDEBAR, width=210)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        label(nav, "KHÔNG GIAN LÀM VIỆC", 9, "bold", MUTED).pack(
            anchor="w", padx=18, pady=(28, 16))
        for key, title, symbol in (("live", "Theo dõi", "◉"),
                                   ("cal", "Hiệu chuẩn", "◎"),
                                   ("map", "Gán nút USB", "▦")):
            item = tk.Button(nav, text=f"  {symbol}   {title}",
                             command=lambda k=key: self.show_page(k),
                             anchor="w", font=(FONT, 11, "bold"),
                             fg=MUTED, bg=SIDEBAR, activeforeground=TEXT,
                             activebackground=CARD_ALT, bd=0, relief="flat",
                             padx=12, pady=15, cursor="hand2")
            item.pack(fill="x", padx=10, pady=3)
            self.nav_buttons[key] = item
        self.nav_note = tk.StringVar(value="Cắm USB để bắt đầu")
        label(nav, textvariable=self.nav_note, size=10, color=MUTED,
              wraplength=166, justify="left").pack(
            side="bottom", anchor="w", padx=20, pady=(0, 14))
        label(nav, "KẾT NỐI", 9, "bold", MUTED).pack(
            side="bottom", anchor="w", padx=20, pady=(0, 12))

        content = tk.Frame(body, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        self.pages = {key: tk.Frame(content, bg=BG) for key in ("live", "cal", "map")}
        for page in self.pages.values():
            page.place(relwidth=1, relheight=1)
        self.make_live()
        self.make_calibration()
        self.make_mapping()
        self.show_page("live")
        WheelWorker(self.events, self.commands).start()
        root.after(70, self.drain_events)

    def show_page(self, key):
        self.pages[key].tkraise()
        for name, item in self.nav_buttons.items():
            item.configure(bg=CARD_ALT if name == key else SIDEBAR,
                           fg=TEAL if name == key else MUTED)

    def page_title(self, parent, title, subtitle):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=22, pady=(19, 15))
        label(head, title, 20, "bold").pack(anchor="w")
        label(head, subtitle, 10, color=MUTED).pack(anchor="w", pady=(3, 0))

    def bind_scroll(self, widget, viewport):
        if widget.winfo_class() not in ("TCombobox", "Entry"):
            widget.bind("<MouseWheel>", lambda event: (
                viewport.yview_scroll(-3 if event.delta > 0 else 3, "units"),
                "break")[1])
        for child in widget.winfo_children():
            self.bind_scroll(child, viewport)

    def make_live(self):
        page = self.pages["live"]
        self.page_title(page, "Bảng điều khiển",
                        "Xem tín hiệu thực từ vô lăng, pedal và joystick.")
        viewport = tk.Canvas(page, bg=BG, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient="vertical", command=viewport.yview)
        viewport.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        viewport.pack(side="left", fill="both", expand=True)
        section = tk.Frame(viewport, bg=BG)
        window = viewport.create_window((0, 0), window=section, anchor="nw")
        section.bind("<Configure>", lambda _: viewport.configure(
            scrollregion=viewport.bbox("all")))
        viewport.bind("<Configure>", lambda event: viewport.itemconfigure(
            window, width=event.width))
        upper = tk.Frame(section, bg=BG, height=310)
        upper.pack(fill="x", padx=22, pady=(0, 12))
        upper.pack_propagate(False)
        lower = tk.Frame(section, bg=BG, height=280)
        lower.pack(fill="x", padx=22, pady=(0, 22))
        lower.pack_propagate(False)

        wheel = card(upper)
        wheel.pack(side="left", fill="both", expand=True, padx=(0, 12))
        wheel_top = tk.Frame(wheel, bg=CARD)
        wheel_top.pack(fill="x", padx=18, pady=(15, 0))
        label(wheel_top, "VÔ LĂNG", 10, "bold", MUTED).pack(side="left")
        self.fault_badge = label(wheel_top, "CHƯA CÓ DỮ LIỆU", 9, "bold",
                                 color=AMBER, bg=CARD_ALT, padx=10, pady=5)
        self.fault_badge.pack(side="right")
        self.wheel_canvas = tk.Canvas(wheel, bg=CARD, bd=0, highlightthickness=0,
                                      height=210)
        self.wheel_canvas.pack(fill="both", expand=True, padx=18)
        self.wheel_canvas.bind("<Configure>", lambda _: self.draw_wheel())
        self.wheel_meta = tk.StringVar(value="HID X  —      PWM  —")
        label(wheel, textvariable=self.wheel_meta, size=10, color=MUTED).pack(
            anchor="w", padx=22, pady=(0, 14))

        stick = card(upper, width=322)
        stick.pack(side="right", fill="y")
        stick.pack_propagate(False)
        label(stick, "JOYSTICK  ·  PA3 / PA4", 10, "bold", MUTED).pack(
            anchor="w", padx=18, pady=(17, 3))
        self.joy_canvas = tk.Canvas(stick, width=250, height=202, bg=CARD,
                                    bd=0, highlightthickness=0)
        self.joy_canvas.pack(pady=(0, 3))
        self.joy_raw = tk.StringVar(value="PA3  —      PA4  —")
        label(stick, textvariable=self.joy_raw, size=10, color=MUTED).pack(
            anchor="w", padx=18, pady=(0, 12))

        pedals = card(lower, width=430)
        pedals.pack(side="left", fill="both", padx=(0, 12))
        pedals.pack_propagate(False)
        label(pedals, "PEDAL", 10, "bold", MUTED).pack(
            anchor="w", padx=18, pady=(17, 15))
        self.pedal_bars = []
        self.pedal_values = []
        for name, pin, color in (("GA", "PA0 / Z", TEAL),
                                  ("PHANH", "PA1 / Rz", RED),
                                  ("CÔN", "PA2 / Rx", BLUE)):
            row = tk.Frame(pedals, bg=CARD)
            row.pack(fill="x", padx=18, pady=10)
            label(row, name, 10, "bold", width=7, anchor="w").pack(side="left")
            meter = tk.Frame(row, bg=OFF, height=16)
            meter.pack(side="left", fill="x", expand=True, padx=(5, 10))
            meter.pack_propagate(False)
            fill = tk.Frame(meter, bg=color, width=1)
            fill.place(x=0, y=0, relheight=1)
            value = tk.StringVar(value="—")
            label(row, textvariable=value, size=11, weight="bold", width=6,
                  anchor="e").pack(side="right")
            detail = tk.StringVar(value=f"{pin}   ·   ADC —")
            label(pedals, textvariable=detail, size=9, color=MUTED).pack(
                anchor="w", padx=105)
            self.pedal_bars.append((meter, fill))
            self.pedal_values.append((value, detail))

        switches = card(lower)
        switches.pack(side="left", fill="both", expand=True)
        title_row = tk.Frame(switches, bg=CARD)
        title_row.pack(fill="x", padx=18, pady=(17, 11))
        label(title_row, "CÔNG TẮC / NÚT USB", 10, "bold", MUTED).pack(side="left")
        self.gear_state = tk.StringVar(value="SỐ —")
        label(title_row, textvariable=self.gear_state, size=12, weight="bold",
              color=AMBER).pack(side="left", padx=14)
        self.hid_buttons = tk.StringVar(value="USB: —")
        label(title_row, textvariable=self.hid_buttons, size=10, weight="bold",
              color=TEAL).pack(side="right")
        grid = tk.Frame(switches, bg=CARD)
        grid.pack(fill="both", expand=True, padx=17, pady=(0, 17))
        self.switch_labels = []
        short_names = ("SHIFT+", "SHIFT−", "FN1", "FN2", "FN3", "FN4",
                       "FN5", "FN6", "FN7", "FN8", "SỐ 1", "SỐ 2",
                       "SỐ 3", "SỐ 4", "SỐ 5", "SỐ 6", "R",
                       "XI NHAN ↑", "XI NHAN ↓", "ĐÁ ĐÈN", "SỐ N")
        for col in range(5):
            grid.grid_columnconfigure(col, weight=1)
        for i, name in enumerate(short_names):
            chip = label(grid, name, 9, "bold", MUTED, OFF,
                         padx=4, pady=9)
            chip.grid(row=i // 5, column=i % 5, sticky="ew", padx=3, pady=4)
            self.switch_labels.append(chip)
        self.draw_wheel()
        self.draw_joystick()
        self.bind_scroll(section, viewport)

    def draw_wheel(self):
        c = self.wheel_canvas
        c.delete("all")
        width = max(c.winfo_width(), 350)
        height = max(c.winfo_height(), 180)
        cx, cy = width / 2, height / 2 - 5
        radius = min(height / 2 - 19, 76)
        c.create_oval(cx-radius-17, cy-radius-17, cx+radius+17, cy+radius+17,
                      outline=EDGE, width=2)
        c.create_oval(cx-radius, cy-radius, cx+radius, cy+radius,
                      outline=TEAL, width=9)
        rotation = math.radians(self.angle_degrees - 90)
        for offset in (0, 2 * math.pi / 3, 4 * math.pi / 3):
            theta = rotation + offset
            c.create_line(cx + 21 * math.cos(theta), cy + 21 * math.sin(theta),
                          cx + (radius - 5) * math.cos(theta),
                          cy + (radius - 5) * math.sin(theta),
                          fill=BLUE, width=8, capstyle="round")
        c.create_oval(cx-24, cy-24, cx+24, cy+24, fill=CARD_ALT,
                      outline=TEAL, width=2)
        c.create_text(18, 20, text=f"−{self.travel_degrees / 2:g}°",
                      anchor="w", fill=MUTED, font=(FONT, 9))
        c.create_text(width-18, 20, text=f"+{self.travel_degrees / 2:g}°",
                      anchor="e", fill=MUTED, font=(FONT, 9))
        c.create_text(cx, height-12, text=f"{self.angle_degrees:+.1f}°",
                      fill=TEXT, font=(FONT, 19, "bold"))

    def draw_joystick(self):
        c = self.joy_canvas
        c.delete("all")
        x0, y0, side = 35, 9, 180
        c.create_rectangle(x0, y0, x0+side, y0+side, outline=EDGE, width=2)
        c.create_line(x0+side/2, y0, x0+side/2, y0+side,
                      fill=EDGE, dash=(4, 5))
        c.create_line(x0, y0+side/2, x0+side, y0+side/2,
                      fill=EDGE, dash=(4, 5))
        cal = self.joy_report
        for i, color in ((1, TEAL), (2, BLUE), (3, AMBER)):
            x, y = cal[2+2*i:4+2*i]
            if x or y:
                px = x0 + side * x / 4095
                py = y0 + side * (4095 - y) / 4095
                c.create_oval(px-5, py-5, px+5, py+5, fill=color, outline="")
        x, y = cal[:2]
        px = x0 + side * x / 4095
        py = y0 + side * (4095 - y) / 4095
        c.create_oval(px-10, py-10, px+10, py+10, fill=TEAL,
                      outline=TEXT, width=2)
        c.create_text(12, 99, text="PA4", angle=90, fill=MUTED,
                      font=(FONT, 9))
        c.create_text(125, 197, text="PA3", fill=MUTED, font=(FONT, 9))

    def make_calibration(self):
        page = self.pages["cal"]
        self.page_title(page, "Hiệu chuẩn",
                        "Làm từng bước. Mốc đã hoàn tất được ghi vào flash.")
        viewport = tk.Canvas(page, bg=BG, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient="vertical", command=viewport.yview)
        viewport.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        viewport.pack(side="left", fill="both", expand=True)
        section = tk.Frame(viewport, bg=BG)
        window = viewport.create_window((0, 0), window=section, anchor="nw")
        section.bind("<Configure>", lambda _: viewport.configure(
            scrollregion=viewport.bbox("all")))
        viewport.bind("<Configure>", lambda event: viewport.itemconfigure(
            window, width=event.width))
        warning = tk.Frame(section, bg="#382d23")
        warning.pack(fill="x", padx=22, pady=(0, 12))
        label(warning, "Tắt nguồn mô-tơ 12 V và đóng game khi hiệu chuẩn. Đặt vô lăng ở giữa trước khi cắm USB hoặc reset.",
              10, "bold", AMBER, warning.cget("bg"), padx=15,
              pady=10, wraplength=860, justify="left").pack(anchor="w")

        steering = card(section)
        steering.pack(fill="x", padx=22, pady=6)
        header = tk.Frame(steering, bg=CARD)
        header.pack(fill="x", padx=17, pady=(13, 9))
        label(header, "01  GÓC VÔ LĂNG", 11, "bold").pack(side="left")
        label(header, "Hall + AS5600", 9, color=MUTED).pack(side="right")
        row = tk.Frame(steering, bg=CARD)
        row.pack(fill="x", padx=17)
        label(row, "Tổng góc", 10, color=MUTED).pack(side="left")
        self.travel = tk.StringVar(value="270")
        tk.Entry(row, textvariable=self.travel, width=6, font=(FONT, 11),
                 bg=CARD_ALT, fg=TEXT, insertbackground=TEXT, bd=0,
                 justify="center").pack(side="left", padx=10)
        label(row, "°", 10, color=MUTED).pack(side="left")
        for i, text in enumerate(("Ghi tâm", "Ghi trái", "Ghi phải + lưu"), 1):
            button(row, f"{i}. {text}", lambda step=i: self.steer_cal(step),
                   primary=i == 1).pack(side="left", padx=(16, 0))
        self.steer_state = tk.StringVar(value="Chưa đọc trạng thái")
        label(steering, textvariable=self.steer_state, size=10,
              color=TEAL).pack(anchor="w", padx=17, pady=(8, 13))

        force = card(section)
        force.pack(fill="x", padx=22, pady=6)
        label(force, "02  GIỚI HẠN LỰC FF", 11, "bold").pack(
            anchor="w", padx=17, pady=(13, 4))
        label(force, "Trần PWM cho mô-tơ, kể cả lực chặn cuối hành trình. Bắt đầu thấp rồi tăng dần.",
              9, color=MUTED).pack(anchor="w", padx=17)
        row = tk.Frame(force, bg=CARD)
        row.pack(fill="x", padx=17, pady=8)
        self.ffb_limit = tk.IntVar(value=35)
        tk.Scale(row, from_=10, to=80, orient="horizontal", variable=self.ffb_limit,
                 resolution=1, length=390, bg=CARD, fg=TEXT, troughcolor=CARD_ALT,
                 highlightthickness=0).pack(side="left")
        label(row, "% PWM", 10, color=MUTED).pack(side="left", padx=8)
        button(row, "Lưu vào flash", self.save_ffb_limit, primary=True).pack(side="left", padx=16)
        self.ffb_limit_state = tk.StringVar(value="Chờ đọc giới hạn từ firmware")
        label(force, textvariable=self.ffb_limit_state, size=10,
              color=TEAL).pack(anchor="w", padx=17, pady=(0, 13))

        pedals = card(section)
        pedals.pack(fill="x", padx=22, pady=6)
        label(pedals, "02  PEDAL", 11, "bold").pack(
            anchor="w", padx=17, pady=(13, 7))
        self.pedal_cal_state = [tk.StringVar(value="Chưa ghi mốc") for _ in PEDALS]
        self.deadzone_vars = []
        for i, name in enumerate(("Ga", "Phanh", "Côn")):
            row = tk.Frame(pedals, bg=CARD)
            row.pack(fill="x", padx=17, pady=5)
            label(row, name, 10, "bold", width=8, anchor="w").pack(side="left")
            button(row, "1. Nhả hết / Ghi",
                   lambda n=i: self.pedal_cal(n, False)).pack(side="left", padx=5)
            button(row, "2. Đạp hết / Lưu",
                   lambda n=i: self.pedal_cal(n, True),
                   primary=True).pack(side="left", padx=5)
            label(row, textvariable=self.pedal_cal_state[i], size=10,
                  color=MUTED).pack(side="left", padx=15)
            dead = tk.StringVar(value="0")
            self.deadzone_vars.append(dead)
            label(row, "Deadzone", 9, color=MUTED).pack(side="left", padx=(8, 4))
            ttk.Combobox(row, textvariable=dead, values=[str(x) for x in range(31)],
                         state="readonly", width=3).pack(side="left")
            label(row, "%", 9, color=MUTED).pack(side="left", padx=(2, 5))
            button(row, "Lưu", lambda n=i: self.save_deadzone(n)).pack(side="left")
        tk.Frame(pedals, bg=CARD, height=6).pack()

        joystick = card(section)
        joystick.pack(fill="x", padx=22, pady=6)
        label(joystick, "03  JOYSTICK  ·  PA3 + PA4", 11, "bold").pack(
            anchor="w", padx=17, pady=(13, 3))
        label(joystick, "Giữ nguyên từng vị trí khi bấm. Hai hướng xi nhan cần đối nhau; kéo đèn phải lệch sang hướng khác.",
              9, color=MUTED, wraplength=850, justify="left").pack(
            anchor="w", padx=17)
        row = tk.Frame(joystick, bg=CARD)
        row.pack(anchor="w", padx=17, pady=10)
        for i, text in enumerate(("Giữa", "Gạt lên", "Gạt xuống", "Kéo đèn + lưu")):
            button(row, f"{i+1}. {text}", lambda point=i: self.joy_cal(point),
                   primary=i == 0).pack(side="left", padx=(0, 9))
        self.joy_state = tk.StringVar(value="Chưa hiệu chuẩn")
        label(joystick, textvariable=self.joy_state, size=10,
              color=TEAL).pack(anchor="w", padx=17, pady=(0, 12))
        self.bind_scroll(section, viewport)

    def make_mapping(self):
        page = self.pages["map"]
        self.page_title(page, "Gán nút USB",
                        "Mỗi công tắc hoặc thao tác joystick có thể phát nút USB 1–32.")
        bar = card(page)
        bar.pack(fill="x", padx=22, pady=(0, 12))
        label(bar, "0 = tắt   ·   Có thể dùng cùng một số USB cho nhiều công tắc.",
              10, color=MUTED).pack(side="left", padx=16, pady=14)
        self.map_state = tk.StringVar(value="Chờ đọc bảng gán…")
        label(bar, textvariable=self.map_state, size=10, color=TEAL).pack(
            side="right", padx=16)
        label(page, "ETS2: để Số N = USB 0. Xi nhan cần gạt giữ: dùng hai nút xi nhan ở chế độ giữ của game (lblinkerh/rblinkerh).",
              10, color=MUTED, wraplength=900, justify="left").pack(
            anchor="w", padx=24, pady=(0, 8))

        viewport = tk.Canvas(page, bg=BG, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient="vertical", command=viewport.yview)
        viewport.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        viewport.pack(fill="both", expand=True)
        self.map_grid = tk.Frame(viewport, bg=BG)
        window = viewport.create_window((0, 0), window=self.map_grid,
                                        anchor="nw")
        self.map_grid.bind("<Configure>", lambda _: viewport.configure(
            scrollregion=viewport.bbox("all")))
        viewport.bind("<Configure>", lambda event: viewport.itemconfigure(
            window, width=event.width))
        for col in range(2):
            self.map_grid.grid_columnconfigure(col, weight=1, uniform="maps")
        split = (len(GUI_NAMES) + 1) // 2
        for i, name in enumerate(GUI_NAMES):
            cell = card(self.map_grid)
            cell.grid(row=i % split, column=i // split, sticky="ew",
                      padx=(22, 10) if i < split else (10, 22), pady=3)
            badge = label(cell, "●", 14, color=OFF)
            badge.pack(side="left", padx=(12, 5))
            self.map_badges.append(badge)
            label(cell, name, 10, "bold", width=20,
                  anchor="w").pack(side="left")
            label(cell, PINS[i], 9, color=MUTED, width=7,
                  anchor="e").pack(side="left", padx=(0, 10))
            label(cell, "USB", 9, color=MUTED).pack(side="left")
            var = tk.StringVar(value=str(i+1))
            var.trace_add("write", lambda *_: self.update_map_dirty())
            ttk.Combobox(cell, textvariable=var, values=[str(x) for x in range(33)],
                         state="readonly", width=4,
                         font=(FONT, 10)).pack(side="right", padx=12, pady=6)
            self.map_vars.append(var)
        footer = tk.Frame(page, bg=BG)
        footer.pack(fill="x", padx=22, pady=(12, 20))
        self.map_dirty = tk.StringVar(value="Chưa có thay đổi")
        label(footer, textvariable=self.map_dirty, size=10, color=MUTED).pack(
            side="left")
        button(footer, "Lưu bảng gán vào flash", self.save_mapping,
               primary=True).pack(side="right")
        self.bind_scroll(self.map_grid, viewport)

    def update_map_dirty(self):
        if not self.map_vars or self.actual_map is None:
            return
        changed = sum(int(var.get()) != actual for var, actual
                      in zip(self.map_vars, self.actual_map))
        self.map_dirty.set(f"{changed} thay đổi chưa lưu" if changed
                           else "Đã đồng bộ với firmware")

    def submit(self, operation, args, callback):
        if not self.connected:
            messagebox.showerror("Chưa kết nối",
                                 "Chưa thấy vô lăng USB. Kiểm tra cáp và firmware.")
            return
        token = self.next_token
        self.next_token += 1
        self.callbacks[token] = callback
        self.commands.put((token, operation, args))

    def steer_cal(self, step):
        try:
            degrees = int(self.travel.get())
            if not 90 <= degrees <= 1080:
                raise ValueError
        except ValueError:
            messagebox.showerror("Tổng góc", "Nhập tổng góc từ 90 đến 1080 độ.")
            return
        self.submit("send", (step, degrees if step == 1 else 0),
                    lambda _: self.steer_state.set(
                        "Đã lưu flash." if step == 3
                        else f"Đã ghi bước {step}; chuyển sang vị trí tiếp theo."))

    def pedal_cal(self, channel, pressed):
        if not pressed:
            self.submit("pedal_capture", (channel,),
                        lambda value: self._pedal_released(channel, value))
            return
        if channel not in self.pedal_release:
            messagebox.showerror("Thứ tự hiệu chuẩn",
                                 "Bấm 'Nhả hết / Ghi' trước.")
            return
        self.submit("pedal_capture", (channel,),
                    lambda value: self._pedal_pressed(channel, value))

    def _pedal_released(self, channel, value):
        self.pedal_release[channel] = value
        self.pedal_cal_state[channel].set(f"Mốc nhả {value}. Hãy đạp hết.")

    def _pedal_pressed(self, channel, value):
        released = self.pedal_release[channel]
        if abs(value - released) < 32:
            messagebox.showerror("Hành trình ADC",
                                 f"Chỉ lệch {abs(value - released)}; cần ít nhất 32.")
            return
        self.submit("send", (12, channel, released, value),
                    lambda _: self.pedal_cal_state[channel].set(
                        f"Đã lưu flash: {released} → {value}"))

    def joy_cal(self, point):
        self.submit("send", (13, point),
                    lambda _: self.joy_state.set(
                        "Đã lưu flash cả 4 vị trí." if point == 3
                        else f"Đã ghi vị trí {point+1}; chuyển sang vị trí tiếp theo."))

    def save_deadzone(self, channel):
        percent = int(self.deadzone_vars[channel].get())
        self.submit("send", (15, channel, percent),
                    lambda _: self.pedal_cal_state[channel].set(
                        f"Deadzone {percent}% đã lưu flash"))

    def save_ffb_limit(self):
        percent = self.ffb_limit.get()
        self.submit("send", (16, percent),
                    lambda _: self.ffb_limit_state.set(
                        f"Đã lưu trần FF {percent}% vào flash"))

    def save_mapping(self):
        if self.actual_map is None:
            messagebox.showerror("Chưa đọc cấu hình", "Chờ kết nối và đọc bảng gán.")
            return
        desired = [int(var.get()) for var in self.map_vars]
        changed = [(i, target) for i, target in enumerate(desired)
                   if self.actual_map[i] != target]
        if not changed:
            self.map_state.set("Không có thay đổi cần lưu.")
            return
        self.map_state.set(f"Đang lưu {len(changed)} thay đổi…")
        self.submit("map_save", (changed,), self._mapping_saved)

    def _mapping_saved(self, actual):
        self.actual_map = actual
        self.update_map_dirty()
        self.map_state.set("Đã lưu bảng gán vào flash.")

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "connected":
                    self.connected = event[1]
                    if self.connected:
                        self.connection.set("●  ĐÃ KẾT NỐI")
                        self.connection_chip.configure(fg=TEAL)
                        self.nav_note.set("USB sẵn sàng. Xem tín hiệu trực tiếp.")
                        self.map_loaded = False
                        self.deadzone_loaded = False
                        self.ffb_limit_loaded = False
                    else:
                        self.connection.set("●  CHƯA KẾT NỐI")
                        self.connection_chip.configure(fg=AMBER)
                        self.nav_note.set(event[2])
                elif event[0] == "result":
                    callback = self.callbacks.pop(event[1], None)
                    if event[3]:
                        messagebox.showerror("Firmware từ chối", event[3])
                        self.map_state.set("Chưa lưu xong; kiểm tra và thử lại.")
                    elif callback:
                        callback(event[2])
                elif event[0] == "snapshot":
                    self.display(event[1])
        except queue.Empty:
            pass
        self.root.after(70, self.drain_events)

    def display(self, data):
        status, pedals, joy, mapping, extra = (
            data[k] for k in ("status", "pedals", "joy", "mapping", "extra"))
        self.deadzone_values = data["deadzones"]
        if not self.deadzone_loaded:
            for var, percent in zip(self.deadzone_vars, self.deadzone_values):
                var.set(str(percent))
            self.deadzone_loaded = True
        physical, mapped = extra[:2]
        # EXTRA_PAYLOAD is <II12B>: out[8] becomes tuple[2].
        if not self.ffb_limit_loaded and extra[6] == 0xA5:
            self.ffb_limit.set(extra[5])
            self.ffb_limit_state.set(f"Trần hiện tại: {extra[5]}% PWM")
            self.ffb_limit_loaded = True
        elif not self.ffb_limit_loaded:
            self.ffb_limit_state.set("Cần nạp firmware mới để chỉnh trần FF")
        gear = next((str(i + 1) for i in range(6) if physical & (1 << (10 + i))),
                    "R" if physical & (1 << 16) else "N")
        self.gear_state.set(f"SỐ {gear}")
        self.angle_degrees = status.millidegrees / 1000
        if status.travel:
            self.travel_degrees = status.travel
        self.draw_wheel()
        self.wheel_meta.set(
            f"HID X  {status.axis:+6d}     PWM  {100 * status.duty / 4200:+5.1f}%"
            f"     CALIB  {'ĐÃ LƯU' if status.calibration_saved else 'CHƯA LƯU'}")
        fault = FAULTS.get(status.fault, str(status.fault))
        self.fault_badge.configure(
            text=(f"LỖI: {fault}" if status.fault else
                  "SẴN SÀNG" if status.ready else "CHƯA SẴN SÀNG"),
            fg=RED if status.fault else TEAL if status.ready else AMBER)
        for i, ((meter, fill), (value_var, detail_var)) in enumerate(
                zip(self.pedal_bars, self.pedal_values)):
            released, pressed = pedals[3+2*i:5+2*i]
            raw = pedals[i]
            scaled = (max(0, min(4095, int((raw-released)*4095/(pressed-released))))
                      if pressed != released and pedals[-1] else 0)
            threshold = 4095 * self.deadzone_values[i] // 100
            scaled = max(0, (scaled - threshold) * 4095 // (4095 - threshold))
            ratio = scaled / 4095
            meter.update_idletasks()
            fill.place_configure(width=max(1, int(meter.winfo_width() * ratio)))
            value_var.set(f"{ratio*100:3.0f}%")
            detail_var.set(
                f"{('PA0 / Z', 'PA1 / Rz', 'PA2 / Rx')[i]}   ·   "
                f"ADC {raw}   ·   {released} → {pressed}")
        self.joy_report = joy
        self.draw_joystick()
        self.joy_raw.set(f"PA3  {joy[0]:4d}       PA4  {joy[1]:4d}"
                         + ("   ·   ĐÃ CALIB" if extra[2] else "   ·   CHƯA CALIB"))
        if physical != self.latest_physical:
            self.latest_physical = physical
            for i, chip in enumerate(self.switch_labels):
                chip.configure(bg=TEAL if physical & (1 << i) else OFF,
                               fg=BG if physical & (1 << i) else MUTED)
            for i, badge in enumerate(self.map_badges):
                badge.configure(fg=TEAL if physical & (1 << i) else OFF)
        numbers = [str(i+1) for i in range(32) if mapped & (1 << i)]
        self.hid_buttons.set("USB: " + (", ".join(numbers) if numbers else "—"))
        self.steer_state.set(
            "Góc vô lăng: đã lưu flash" if status.calibration_saved
            else f"Góc vô lăng: bước {status.stage}/3")
        if extra[4]:
            self.joy_state.set(f"Đang chờ vị trí {extra[4]+1}/4")
        elif extra[2]:
            self.joy_state.set("Joystick đã hiệu chuẩn và lưu flash")
        if not self.map_loaded:
            self.actual_map = mapping
            for var, target in zip(self.map_vars, mapping):
                var.set(str(target))
            self.map_loaded = True
            self.map_state.set("Đã đọc bảng gán từ firmware.")
            self.update_map_dirty()


if __name__ == "__main__":
    root = tk.Tk()
    WheelApp(root)
    root.mainloop()
