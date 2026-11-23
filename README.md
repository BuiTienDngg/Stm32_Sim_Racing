# Stm32_Sim_Racing

STM32F411 DIY FFB wheel with BTS7960, Hall + AS5600 steering, pedals, H shifter and USB HID. `MDK-ARM/Stimulation_steering_wheel.uvprojx` is the Keil project; `MDK-ARM/wheel_gui.py` is the Windows calibration interface.

## LFS dashboard on ESP32-2432S028

The CYD connects to the PC through its USB-UART port. LFS sends OutGauge UDP to a Python bridge, which sends speed, RPM, gear and pedal positions to the CYD. No wire between the STM32 and ESP32 is required.

**Preview without hardware:** double-click `lfs_dashboard/preview.bat`, or run `python lfs_dashboard/preview.py`. A 2× window simulates the 320×240 CYD layout and cycles through acceleration, shifting, braking and neutral. It uses only Python's built-in Tkinter. The preview copies the dashboard layout; font rendering can differ from the ESP32.

1. Flash `lfs_dashboard/` using PlatformIO and an ESP32-2432S028 with ILI9341 display (`pio run -d lfs_dashboard -t upload`). The display pin configuration is in `platformio.ini`; different CYD revisions may need changes.
2. In the LFS installation folder, close LFS and edit `cfg.txt`:

   ```text
   OutGauge Mode 1
   OutGauge Delay 10
   OutGauge IP 127.0.0.1
   OutGauge Port 30000
   OutGauge ID 0
   ```

3. Install the bridge dependency with `python -m pip install -r lfs_dashboard/requirements.txt`.
4. Find the CYD COM port in Windows Device Manager, then run `python lfs_dashboard/bridge.py --port COM5` (replace COM5). Close serial monitors first. Start driving in cockpit view in LFS.

The bridge accepts 92-byte OutGauge packets, or 96 bytes when `OutGauge ID` is enabled. It sends `LFS,<km/h>,<rpm>,<gear>,<gas%>,<brake%>,<clutch%>` lines at 115200 baud. After two seconds without packets the dashboard shows waiting. The LFS OutGauge format and cockpit-view requirement are documented in the [LFS manual](https://en.lfsmanual.net/wiki/OutGauge).

The CYD code has not yet been flashed or visually checked on the user's board. The STM32 project and dashboard are independent.
