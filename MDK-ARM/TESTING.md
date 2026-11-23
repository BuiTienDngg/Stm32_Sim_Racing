# Test vô lăng trên Windows

Mở PowerShell trong thư mục `MDK-ARM`. Trong Keil, các file này nằm ở nhóm **Tests/Windows**.

## Chế độ ghép Hall và AS5600 cùng chặn góc

Firmware dùng Hall A/B trên PA6/PA7 để nội suy chuyển động và AS5600 trên I2C PB8/PB9 để hiệu chỉnh góc. AS5600 gắn trực tiếp trên trục vô lăng, tỷ lệ 1:1. Lệnh encoders hiển thị cả hai góc và góc ghép, kèm trạng thái I2C/nam châm.

```powershell
python wheel_test.py calibrate --degrees 270
python wheel_test.py monitor
```

Ghi tâm, mốc trái và mốc phải theo hướng dẫn. Firmware lưu hai mốc góc và tỷ lệ có dấu của Hall vào flash, dùng vị trí khởi động làm tâm cho lần sau. Thay 270 bằng tổng góc thực tế. Khi chuyển từ bản Hall-only, hiệu chuẩn vô lăng lại một lần. Tổng góc đo trên AS5600 phải khớp góc khai báo trong khoảng 10%.

Lực chặn tăng dần từ 90% hành trình mỗi phía, đạt trần PWM tại mốc đã hiệu chuẩn và tiếp tục kéo vào trong nếu vượt mốc. Chặn hoạt động khi bo có USB, đã calib, hai encoder hoạt động hợp lệ và mô-tơ được cấp nguồn, kể cả khi game chưa phát FFB. Đây là giới hạn bằng lực mô-tơ. Muốn khóa góc tuyệt đối cần chặn cơ khí.


Các lệnh bench/spin dành cho thử mô-tơ tháo tải. Lệnh spin chủ động bỏ hiệu chuẩn trong RAM cho phiên thử đó.

## Bố trí BTS7960 và AS5600

| Chức năng | Chân STM32 | Module |
|---|---|---|
| PWM phải, 20 kHz | PB6 / TIM4_CH1 | RPWM |
| PWM trái, 20 kHz | PB7 / TIM4_CH2 | LPWM |
| Enable chung | PB5 | R_EN và L_EN |
| I2C1 SCL, 400 kHz | PB8 | AS5600 SCL |
| I2C1 SDA | PB9 | AS5600 SDA |
| Encoder Hall A | PA6 / TIM3_CH1 | Hall A |
| Encoder Hall B | PA7 / TIM3_CH2 | Hall B |

Nối B+ của BTS7960 với +12 V, B- với âm nguồn, M+/M- với động cơ. VCC logic cấp theo module (thường 5 V). GND nguồn, module và STM32 nối chung. Các đầu vào điều khiển module phải nhận được logic 3,3 V của STM32. Kéo PB5 xuống GND bằng 10 kΩ để EN giữ thấp khi bo reset.

AS5600 dùng PB8/PB9, cấp nguồn và điện trở kéo lên theo mức 3,3 V với module hỗ trợ mức này. Địa chỉ I2C là 0x36. Chạy lệnh encoders --once để kiểm tra. Firmware ngắt lực khi mất góc hợp lệ quá 20 ms, từ trường ngoài ngưỡng hoặc hai encoder lệch quá 22,5 độ. Lỗi sai lệch cần reset hoặc hiệu chuẩn lại sau khi kiểm tra cơ khí.

FFB hiện giữ ngưỡng PWM tối thiểu 60%, tối đa 100% theo cấu hình trước. Xác nhận chiều và mức lực trên BTS7960 bằng xung nhỏ trước khi chạy FFB trong game.

## Nút nhấn

| Nút | Chân STM32 | Nút | Chân STM32 |
|---|---|---|---|
| Shift+ | Chưa gán | Shift- | PA9 |
| Fn1 | PB13 | Fn2 | PA10 |
| Fn3 | PB14 | Fn4 | PA15 |
| Fn5 | PB15 | Fn6 | PB3 |
| Fn7 | PA8 | Fn8 | PB4 |

Bảy công tắc số được cấu hình input pull-up, tác động mức thấp. PA3/PA4 dành cho joystick ADC; PA5 còn trống. PC14/PC15 dùng khi LSE không hoạt động. Nếu bo có thạch anh hoặc mạch LSE gắn trên hai chân này, kiểm tra và tháo mạch liên quan nếu ảnh hưởng tín hiệu công tắc. PC13 có thể nối LED trên bo, LED có thể sáng khi chọn số 1.

| Số | Chân STM32 | Nút USB |
|---|---|---|
| 1 | PC13 | 11 |
| 2 | PC14 | 12 |
| 3 | PC15 | 13 |
| 4 | PB0 | 14 |
| 5 | PB1 | 15 |
| 6 | PB10 | 16 |
| R | PB12 | 17 |

Mỗi công tắc NO nối giữa chân tín hiệu và GND. Giữ công tắc đóng khi cần số ở vị trí tương ứng. Không công tắc số nào đóng là vị trí N. Trong game, gán Gear 1–6 và Reverse cho nút USB 11–17, chọn hộp số H-pattern nếu game có tùy chọn này. PB12 hiện dành cho số R, nút USB 1 (Shift+) chưa gán chân. Chuyển dây công tắc R từ PB2 sang PB12 và tháo dây tăng số cũ khỏi PB12.

Các nút dùng pull-up nội và đóng xuống GND khi nhấn. Thử từng nút trong `monitor`; Shift- là nút USB 2, Fn1–Fn8 là nút USB 3–10. Nút USB 1 để trống.

Tắt nguồn mô-tơ 12 V và đóng game trước khi hiệu chuẩn. Cấp nguồn encoder đúng mức và cắm STM32 qua USB.

```powershell
python -m pip install hidapi
python wheel_test.py monitor
python wheel_test.py calibrate --degrees 270
```

Thoát monitor bằng Ctrl+C trước khi chạy hiệu chuẩn. Dùng góc hành trình thực tế thay cho 270°. Ghi đủ tâm, trái, phải và chờ thông báo đã lưu vào flash. Những lần sau, đưa vô lăng về tâm **trước khi cắm USB hoặc reset STM32**. Bo dùng vị trí lúc khởi động làm tâm và tự nạp lại hành trình đã lưu. Sau khi kiểm tra góc gần 0° trong monitor, mới bật 12 V khi cần FFB. Bật/tắt riêng 12 V không reset STM32.

Sector 7 dành riêng cho hiệu chuẩn. Khi cập nhật firmware, chọn xóa các sector cần thiết và tránh Full Chip Erase nếu muốn giữ dữ liệu. Flash ghi lần lượt từng bản và giữ bản trước nếu mất nguồn khi ghi.

Để thử cầu H, cố định thân mô-tơ và giữ tay tránh xa trục. Kiểm tra đấu dây, bật 12 V với giới hạn dòng. Lệnh dưới phát một xung 400 ms từ firmware, tối đa 15% PWM ở bản hiện tại.

```powershell
python wheel_test.py pulse right
```

### Xung bàn thử 90%

Nạp bản HEX mới và đóng game. Dùng xung 400 ms để xác nhận chiều encoder trước. Chỉ thử mức 90% khi mô-tơ được cố định, trục tháo tải, có công tắc ngắt 12 V và nguồn giới hạn dòng phù hợp với mô-tơ và BTS7960. Firmware theo dõi encoder để cắt khi kẹt, dòng điện cần được giới hạn ở phần cứng.

Hiệu chuẩn khi 12 V đang tắt, đưa trục về gần tâm rồi cấp nguồn mô-tơ. Chạy:

```powershell
python wheel_test.py pulse right --bench-90
```

Gõ `RUN 90` để phát một xung. Duty PWM tăng dần lên tối đa 90% trong cửa sổ tối đa 1 giây. Xung có thể kết thúc sớm nếu encoder đứng yên 200 ms trong lúc có lệnh PWM, trục đi ngược chiều, tới giới hạn hành trình, mất USB hoặc game gửi lực. Dùng công tắc nguồn 12 V để dừng ngay.

### Đo ngưỡng quay của mô-tơ đã tháo tải

Nạp firmware có hỗ trợ `spin`. Tắt 12 V, tháo vô lăng khỏi trục và cố định thân mô-tơ. Giữ encoder kết nối và cấp nguồn cho nó. Đóng game rồi cấp 12 V qua nguồn giới hạn dòng. Script chuyển sang chế độ bàn thử trong RAM khi bạn xác nhận SPIN và giữ dữ liệu hiệu chuẩn đã lưu.

```powershell
python wheel_test.py spin right --duty 25
```

Gõ `SPIN` để chạy một lần, tối đa 1 giây. Xem `raw span` để biết trục có quay không. Có thể chọn `left` và điều chỉnh duty từ 15 đến 60. Chờ trục dừng hẳn giữa các lần thử. Nếu báo encoder đứng yên, tắt 12 V và reset bo để xóa lỗi. Firmware dừng nếu encoder đứng yên 300 ms hoặc mất USB. Khi lắp lại vô lăng, đặt đúng tâm rồi reset bo để nạp lại hành trình đã lưu.

## Pedal analog ga, phanh và côn

| Pedal | Chân tín hiệu | Trục USB |
|---|---|---|
| Ga | PA0 / ADC1_IN0 | Z |
| Phanh | PA1 / ADC1_IN1 | Rz |
| Côn | PA2 / ADC1_IN2 | Rx |

Với pedal dùng biến trở, nối hai đầu biến trở vào 3V3 và GND, chân giữa vào ADC tương ứng. Giữ tín hiệu trong 0–3,3 V. Nếu còn bỏ trống một đầu vào ADC, dùng điện trở kéo xuống GND để trục đó đứng ở mức nhả.

```powershell
python wheel_test.py pedals
```

Ga dùng mốc mặc định 10–1200 và phanh dùng 0–700 cho đến khi có mốc đã lưu. Côn hoạt động sau lần hiệu chuẩn đầu tiên. Tắt nguồn mô-tơ và đóng game trước khi hiệu chuẩn.

```powershell
python wheel_test.py calibrate-pedal throttle
python wheel_test.py calibrate-pedal brake
python wheel_test.py calibrate-pedal clutch
```

Mỗi lệnh yêu cầu giữ pedal ở vị trí nhả hết rồi đạp hết. Firmware lưu hai mốc riêng cho từng kênh trong flash và tự tải lại khi khởi động. Tín hiệu ADC tăng hoặc giảm khi đạp đều được quy đổi thành 0–4095. Dùng chế độ xóa theo sector khi nạp firmware để giữ dữ liệu hiệu chuẩn.

Chạy lệnh `pedals` để kiểm tra hành trình đã quy đổi trên từng trục. Trong LFS, đặt **Throttle / brake axes = separate** rồi gán **Throttle → Z** và **Brake → Rz**. Nếu có trục bị ngược, dùng **Invert** trên riêng trục đó.

## Giao diện Windows: test, hiệu chuẩn và gán nút

Nạp firmware HEX mới, giữ dữ liệu sector 7 bằng chế độ **Erase Sectors**. Cài HIDAPI một lần, rồi mở giao diện bằng `wheel_gui.bat` hoặc:

```powershell
python -m pip install hidapi
python wheel_gui.py
```

- **Theo dõi / Test**: góc vô lăng, PWM, lỗi, giá trị ga/phanh/côn, ADC joystick, công tắc vật lý và số nút USB game nhận.
- **Hiệu chuẩn**: ghi tâm/trái/phải cho vô lăng; ghi mốc nhả/đạp hết cho từng pedal; ghi joystick lần lượt **giữa → gạt lên → gạt xuống → kéo đèn**. Giữ vị trí khi bấm. Giao diện báo đã lưu flash sau bước cuối. Tắt nguồn mô-tơ 12 V và đóng game lúc hiệu chuẩn.
- **Gán nút USB**: chọn 0 để tắt hoặc số 1–32 cho mỗi công tắc / cử chỉ joystick; bấm **Lưu bảng gán vào flash**. Số mặc định của ba cử chỉ joystick là 18/19/20. Có thể gán trùng để hai công tắc tạo cùng một nút USB. Phần gán **chức năng trong game** thực hiện tại menu điều khiển của game.

Joystick hai biến trở nối **3V3**, **GND** chung và chân tín hiệu trục thứ nhất vào **PA3 / ADC1_IN3**, trục thứ hai vào **PA4 / ADC1_IN4**. Không đưa điện áp quá 3,3 V vào các chân ADC. Quá trình hiệu chuẩn học hướng từ cả hai kênh, nên không cần đoán trước trục nào ứng với gạt hay kéo. Gạt lên/xuống tạo nút USB khi ra khỏi tâm; kéo về tạo nút đá đèn. Lẫy giữ sẽ giữ nút USB đang nhấn, còn động tác tự hồi sẽ nhả nút khi về giữa. Từng cử chỉ cần lệch tâm ít nhất khoảng 128 mức ADC; hai hướng xi nhan phải đối nhau và hướng kéo đèn phải khác hướng xi nhan.

Cấu hình pedal, vô lăng, joystick và gán nút đều nằm trong sector 7 của flash. Sau khi nạp firmware, đưa vô lăng về giữa trước khi cắm USB/reset; không cần hiệu chuẩn lại nếu sector 7 được giữ nguyên.

## Test FFB qua DirectInput

Để xem LFS có phát hiệu ứng hay không, chạy `python ffb_test.py --watch`, chuyển ngay sang LFS và lái qua một khúc cua trong 20 giây. Script chỉ đọc trạng thái bộ chấp hành, hiệu ứng, PWM và lỗi từ firmware. Có thể giữ 12 V tắt cho phép thử này.

Đóng LFS và các chương trình đang giữ độc quyền vô lăng. Lệnh đầu chỉ kiểm tra Windows có nhận đúng thiết bị và Constant Force hay không. Lệnh sau yêu cầu hiệu chuẩn, trục gần tâm và nhấn Enter để phát một lực 300 ms. Giữ nguồn 12 V tắt khi kiểm tra đường tín hiệu lần đầu.

```powershell
python ffb_test.py
python ffb_test.py --pulse right
python ffb_test.py --pulse left
```

Để giả lập game cập nhật lực liên tục, dùng `python ffb_test.py --simulate right --strength 30`. Chế độ này gửi Constant Force biến thiên qua DirectInput trong 800 ms rồi dừng. Thử tín hiệu với nguồn 12 V tắt trước. Khi thử có nguồn, cố định cơ cấu, giữ tay tránh xa vô lăng và ngắt 12 V nếu lực kéo sai chiều. Có thể chạy `--simulate left` sau khi đưa trục về gần tâm.

- `DirectInput reports Constant Force support` cho biết Windows nhận khả năng FFB.
- `Firmware PWM peak` khác 0 cho biết firmware đã xử lý lệnh lực từ DirectInput. Có thể kiểm tra điều này khi 12 V đang tắt. FFB bỏ qua lệnh trong vùng ±5%, sau đó ánh xạ biên độ lực thành duty từ 60% đến 100%. Firmware tăng duty dần và giảm lực hướng ra ngoài ở gần cuối hành trình. Nếu quay vượt mốc hiệu chuẩn thêm 10% khi game đang phát FFB, bo kéo về mép hành trình với duty tối đa 60% trong 1 giây. Bo ngắt lực hồi nếu vượt thêm 25% tính từ mốc hiệu chuẩn, đi sai chiều hoặc sau 300 ms vẫn chưa dịch về. Quay tay vào vùng hiệu chuẩn để tiếp tục. Các lệnh thử cầu H và `spin` vẫn có kiểm tra encoder đứng yên.
- Khi cấp 12 V cho bản FFB 60–100%, cố định cơ cấu và dùng nguồn có giới hạn dòng phù hợp với mô-tơ và L298N. Ngắt 12 V để dừng lực. Giới hạn duty và bộ đếm encoder chỉ bảo vệ theo lệnh và chuyển động, còn giới hạn dòng cần có ở phần cứng. [Datasheet L298](https://www.st.com/resource/en/datasheet/l298.pdf)
- `raw span` cho biết độ dịch chuyển encoder theo số xung trong phép thử. Sau khi xung thử cầu H đã chạy đúng chiều, có thể thử lại DirectInput với 12 V để quan sát chuyển động. Nếu chiều lực trong game có vấn đề, ngắt 12 V ngay.
- Nếu `Acquire` lỗi, đóng chương trình khác đang sử dụng vô lăng và thử lại. Nếu `GetEffectInfo(Constant Force)` lỗi, Windows đã thấy tay lái nhưng chưa báo hỗ trợ Constant Force.

Hai script chạy trên PC. Tùy chọn `--bench-90` cần firmware có hỗ trợ xung bàn thử.

