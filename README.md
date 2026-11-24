# Stm32_Sim_Racing

STM32F411 DIY FFB wheel with BTS7960, Hall + AS5600 steering, pedals, H shifter and USB HID. `MDK-ARM/Stimulation_steering_wheel.uvprojx` is the Keil project; `MDK-ARM/wheel_gui.py` is the Windows calibration interface.

The wheel GUI's **Hiệu chuẩn → Giới hạn lực FF** slider sets the motor's maximum PWM duty from 10% to 80%. The current firmware defaults to 35% if no limit has been saved. With the game stopped and motor idle, choose a value and click **Lưu vào flash**; the limit persists across resets. This cap applies to game force, steering end stops and motor test commands. Start low if the wheel drive slips, then increase gradually. Flash the updated STM32 firmware before using this control.

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
4. Double-click `lfs_dashboard/bridge.bat`, select the CYD COM port shown in the window, and start driving in cockpit view in LFS. You can also run `python lfs_dashboard/bridge.py --port COM5` (replace COM5). Close serial monitors and the preview's CYD connection first.

The bridge accepts 92-byte OutGauge packets, or 96 bytes when `OutGauge ID` is enabled. It sends `LFS,<km/h>,<rpm>,<gear>,<gas%>,<brake%>,<clutch%>` lines at 115200 baud. After two seconds without packets the dashboard shows waiting. The LFS OutGauge format and cockpit-view requirement are documented in the [LFS manual](https://en.lfsmanual.net/wiki/OutGauge).

The CYD code has not yet been flashed or visually checked on the user's board. The STM32 project and dashboard are independent.

If an earlier CYD build showed a white background, divider and pedal outlines but no text, rebuild and upload the current version. The PlatformIO configuration now enables fonts 2/4/7 and display inversion for the ILI9341_2 panel. If your panel has a different controller, its display settings may need adjustment.

The dashboard has a green-to-yellow-to-red RPM bar at the top (full at 8000 RPM). Run `lfs_dashboard/preview.bat` to open the PC preview. Choose the CYD USB-UART COM port and click **Connect CYD**. The default demo sends sample driving data to both the PC preview and the CYD. Click **Use LFS** to listen for OutGauge on UDP port 30000 and forward live values to the CYD. Close `bridge.py` before using LFS mode in the preview; both programs use the same UDP and serial ports. The preview requires `pyserial` for COM access: `python -m pip install pyserial`.

The latest CYD firmware uses a full-width RPM bar and redraws only changed screen regions, reducing visible flicker. The PC preview follows the same RACE DASH layout. Rebuild and upload the firmware to see the new layout on the physical screen.
