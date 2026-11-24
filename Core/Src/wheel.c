#include "main.h"
#include "calibration.h"
#include "encoder.h"
#include "tusb.h"
#include "wheel.h"
#include <string.h>

#ifndef MOTOR_POLARITY
#define MOTOR_POLARITY 1
#endif
_Static_assert(MOTOR_POLARITY == 1 || MOTOR_POLARITY == -1, "Motor polarity must be +1 or -1");

enum { PWM_PERIOD = 4200, DEFAULT_FFB_LIMIT_PERCENT = 35 };
enum {
    FFB_DEADBAND = 32767 * 5 / 100
};
enum { TEST_PULSE_MS = 400, BENCH_PULSE_MS = 1000, BENCH_STALL_MS = 200 };
enum { BENCH_PWM_MAX = PWM_PERIOD * 90 / 100 };
enum { SPIN_MIN_PERCENT = 15, SPIN_MAX_PERCENT = 60, SPIN_STALL_MS = 300 };
enum {
    TRAVEL_LIMIT = 32767,
    SOFT_STOP_START = TRAVEL_LIMIT * 90 / 100,
    PID_STATE_PLAYING = 0x10
};
enum { MOTOR_ENABLE = GPIO_PIN_5 };

typedef struct { GPIO_TypeDef *port; uint16_t mask; } Pin;
static const Pin buttons[] = {
    {GPIOB, 0},          {GPIOA, GPIO_PIN_9},  // Shift up unassigned, Shift down
    {GPIOB, GPIO_PIN_13}, {GPIOA, GPIO_PIN_10}, // Fn1, Fn2
    {GPIOB, GPIO_PIN_14}, {GPIOA, GPIO_PIN_15}, // Fn3, Fn4
    {GPIOB, GPIO_PIN_15}, {GPIOB, GPIO_PIN_3},  // Fn5, Fn6
    {GPIOA, GPIO_PIN_8},  {GPIOB, GPIO_PIN_4},  // Fn7, Fn8
    {GPIOC, GPIO_PIN_13}, {GPIOC, GPIO_PIN_14}, // Gear 1, Gear 2
    {GPIOC, GPIO_PIN_15}, {GPIOB, GPIO_PIN_0},  // Gear 3, Gear 4
    {GPIOB, GPIO_PIN_1},  {GPIOB, GPIO_PIN_10}, // Gear 5, Gear 6
    {GPIOB, GPIO_PIN_12}                      // Reverse
};

static int32_t count, center, left, right;
static uint32_t keys;
static uint16_t degrees;
static int32_t hall_left;
static uint8_t debounce[TU_ARRAY_SIZE(buttons)], stage, fault, result;
static bool calibration_saved, bench_used;
static int8_t raw_sign = 1, drive_direction;
static int16_t applied_duty;
static int16_t spin_duty;
static uint8_t ffb_limit_percent = DEFAULT_FFB_LIMIT_PERCENT;
static uint32_t pulse_start, movement_time;
static int32_t last_movement;
static int8_t pulse_direction;
extern ADC_HandleTypeDef hadc1;
enum { ADC_COUNT = PEDAL_COUNT + 2, ADC_OVERSAMPLES = 4, JOY_FIRST_SOURCE = 17,
       GEAR_FIRST_SOURCE = 10, GEAR_COUNT = 7, NEUTRAL_SOURCE = 20 };
static int32_t adc_filtered[ADC_COUNT];
static PedalCalibration pedal_ranges[PEDAL_COUNT] = {
    {10, 1200}, {0, 700}, {0, 0} // Leave the clutch inactive until calibrated.
};
static bool pedal_samples_valid;
static uint8_t pedal_saved_mask;
static uint8_t pedal_deadzone[PEDAL_COUNT];
static JoystickCalibration joy_calibration, joy_pending;
static bool joy_calibration_saved;
static uint8_t joy_next;
static uint8_t button_map[BUTTON_SOURCES];

static void sample_pedals(void) {
    uint32_t sums[ADC_COUNT] = {0};
    uint16_t minimum[ADC_COUNT], maximum[ADC_COUNT] = {0};
    for (unsigned i = 0; i < ADC_COUNT; ++i) minimum[i] = UINT16_MAX;

    bool valid = true;
    for (unsigned sample = 0; sample < ADC_OVERSAMPLES && valid; ++sample) {
        valid = HAL_ADC_Start(&hadc1) == HAL_OK;
        for (unsigned i = 0; valid && i < ADC_COUNT; ++i) {
            valid = HAL_ADC_PollForConversion(&hadc1, 1) == HAL_OK;
            if (valid) {
                uint16_t value = HAL_ADC_GetValue(&hadc1);
                sums[i] += value;
                if (value < minimum[i]) minimum[i] = value;
                if (value > maximum[i]) maximum[i] = value;
            }
        }
        valid = valid && !__HAL_ADC_GET_FLAG(&hadc1, ADC_FLAG_OVR);
        HAL_ADC_Stop(&hadc1);
    }
    if (valid) {
        for (unsigned i = 0; i < ADC_COUNT; ++i) {
            // Average the middle two readings to reject a single ADC spike.
            int32_t sample = (int32_t)((sums[i] - minimum[i] - maximum[i] + 1) / 2);
            if (pedal_samples_valid)
                adc_filtered[i] += sample - adc_filtered[i] / 4;
            else
                adc_filtered[i] = 4 * sample;
        }
    }
    pedal_samples_valid = valid;
}

static int32_t clamp(int32_t x, int32_t low, int32_t high) {
    return x < low ? low : (x > high ? high : x);
}

static int32_t ffb_target(int32_t force) {
    int32_t magnitude = clamp(force < 0 ? -force : force, 0, 32767);
    if (magnitude <= FFB_DEADBAND) return 0;
    int32_t duty = (magnitude - FFB_DEADBAND) * (PWM_PERIOD * ffb_limit_percent / 100)
                   / (32767 - FFB_DEADBAND);
    return force < 0 ? -duty : duty;
}

static void motor_off(void) {
    GPIOB->BSRR = MOTOR_ENABLE << 16;
    TIM4->CCR1 = 0;
    TIM4->CCR2 = 0;
    applied_duty = 0;
    drive_direction = 0;
}

static void motor_drive(int32_t target) {
    int32_t limit = PWM_PERIOD * ffb_limit_percent / 100;
    target = clamp(target, -limit, limit);
    if (!target) { motor_off(); return; }
    int8_t direction = target > 0 ? 1 : -1;
    if (drive_direction && direction != drive_direction) {
        motor_off(); // One 1 ms tick at zero before reversing.
        return;
    }
    drive_direction = direction;
    applied_duty = clamp(target, applied_duty - 24, applied_duty + 24);
    uint32_t duty = applied_duty * direction;
    bool forward = direction * MOTOR_POLARITY > 0;
    // Clear the inactive side before enabling the active side.
    if (forward) {
        TIM4->CCR2 = 0;
        TIM4->CCR1 = duty;
    } else {
        TIM4->CCR1 = 0;
        TIM4->CCR2 = duty;
    }
    GPIOB->BSRR = MOTOR_ENABLE;
}

uint32_t wheel_buttons(void) {
    uint32_t mapped = 0;
    for (unsigned i = 0; i < BUTTON_SOURCES; ++i)
        if ((keys & (1u << i)) && button_map[i]) mapped |= 1u << (button_map[i] - 1);
    return mapped;
}

static int32_t normalized(void) {
    if (stage != 3) return 0;
    int32_t offset = (count - center) * raw_sign;
    int32_t span = (offset < 0 ? center - left : right - center) * raw_sign;
    return (int32_t)((int64_t)offset * 32767 / span);
}

int16_t wheel_axis(void) { return clamp(normalized(), -32767, 32767); }

static uint16_t pedal_axis(unsigned channel) {
    PedalCalibration range = pedal_ranges[channel];
    if (!pedal_samples_valid || range.released == range.pressed) return 0;
    int32_t sample = adc_filtered[channel] / 4;
    int32_t scaled = (sample - range.released) * PEDAL_ADC_MAX / (range.pressed - range.released);
    scaled = clamp(scaled, 0, PEDAL_ADC_MAX);
    int32_t dead = PEDAL_ADC_MAX * pedal_deadzone[channel] / 100;
    return scaled <= dead ? 0 : (uint16_t)((scaled - dead) * PEDAL_ADC_MAX / (PEDAL_ADC_MAX - dead));
}

void wheel_input_report(uint16_t report[WHEEL_INPUT_WORDS]) {
    uint32_t pressed = wheel_buttons();
    report[0] = (uint16_t)pressed;
    report[1] = (uint16_t)(pressed >> 16);
    report[2] = (uint16_t)wheel_axis();
    report[3] = 0; // Compatibility Y axis in the PID descriptor.
    for (unsigned i = 0; i < PEDAL_COUNT; ++i)
        report[4 + i] = pedal_axis(i);
}

static bool motor_interlock(void) {
    return !fault && encoder_healthy(HAL_GetTick()) && tud_mounted() && !tud_suspended();
}

bool wheel_can_drive(void) {
    return stage == 3 && motor_interlock();
}

static bool can_start_spin(void) {
    return stage == 0 && motor_interlock() && !bench_used && !applied_duty;
}

void wheel_usb_stop(void) {
    motor_off();
    pulse_direction = 0;
    spin_duty = 0;
    bench_used = false;
    pid_reset();
}

void wheel_status(uint8_t *out) {
    int16_t axis = wheel_axis();
    int32_t millidegrees = (int32_t)((int64_t)(count - center) * raw_sign * 360000 / 4096);
    memcpy(out, &count, 4);
    memcpy(out + 4, &millidegrees, 4);
    memcpy(out + 8, &axis, 2);
    uint32_t mapped = wheel_buttons();
    memcpy(out + 10, &mapped, 2);
    memcpy(out + 12, &applied_duty, 2);
    out[14] = stage;
    out[15] = (wheel_can_drive() ? 2 : 0) | (can_start_spin() ? 4 : 0) |
              (calibration_saved ? 8 : 0) | ((mapped >> 16) & 1u);
    // Flag bit 0 carries button 17 while preserving the diagnostic report size.
    out[16] = fault ? fault : encoder_fault(HAL_GetTick());
    out[17] = result;
    memcpy(out + 18, &degrees, 2);
}

void wheel_pedal_status(uint8_t *out) {
    uint16_t values[3 * PEDAL_COUNT];
    for (unsigned i = 0; i < PEDAL_COUNT; ++i) {
        values[i] = pedal_samples_valid ? adc_filtered[i] / 4 : 0;
        values[PEDAL_COUNT + 2 * i] = pedal_ranges[i].released;
        values[PEDAL_COUNT + 2 * i + 1] = pedal_ranges[i].pressed;
    }
    memcpy(out, values, sizeof values);
    out[18] = pedal_saved_mask;
    out[19] = pedal_samples_valid;
}

void wheel_joystick_status(uint8_t *out) {
    uint16_t values[10] = {0};
    for (unsigned axis = 0; axis < 2; ++axis)
        values[axis] = pedal_samples_valid ? adc_filtered[PEDAL_COUNT + axis] / 4 : 0;
    for (unsigned i = 0; i < JOY_POINTS; ++i)
        for (unsigned axis = 0; axis < 2; ++axis)
            values[2 + 2 * i + axis] = joy_calibration.point[i][axis];
    memcpy(out, values, sizeof values);
}

void wheel_map_status(uint8_t *out) { memcpy(out, button_map, BUTTON_SOURCES); }

void wheel_extra_status(uint8_t *out) {
    uint32_t mapped = wheel_buttons();
    memset(out, 0, DIAG_SIZE);
    memcpy(out, &keys, 4);
    memcpy(out + 4, &mapped, 4);
    out[8] = joy_calibration_saved ? 1 : 0;
    out[9] = pedal_samples_valid ? 1 : 0;
    out[10] = joy_next;
    out[11] = ffb_limit_percent;
    out[12] = 0xA5; // Identifies firmware with an adjustable PWM limit.
}

void wheel_deadzone_status(uint8_t *out) {
    memset(out, 0, DIAG_SIZE);
    memcpy(out, pedal_deadzone, PEDAL_COUNT);
}

void wheel_command(const uint8_t *data) {
    result = 1;
    if (data[0] == 16) {
        unsigned percent = data[1] | data[2] << 8;
        if (percent < 10 || percent > 80 || applied_duty || pulse_direction || spin_duty ||
            (pid_status() & PID_STATE_PLAYING)) return;
        if (ffb_limit_percent == percent) { result = 0; return; }
        if (!ffb_limit_save(percent)) { result = 2; return; }
        ffb_limit_percent = percent;
        result = 0;
        return;
    }
    if (data[0] == 15) {
        unsigned channel = data[1] | data[2] << 8;
        unsigned percent = data[3] | data[4] << 8;
        if (channel >= PEDAL_COUNT || percent > 30 || applied_duty ||
            pulse_direction || spin_duty || (pid_status() & PID_STATE_PLAYING)) return;
        if (pedal_deadzone[channel] == percent) { result = 0; return; }
        if (!pedal_deadzone_save(channel, percent)) { result = 2; return; }
        pedal_deadzone[channel] = percent;
        result = 0;
        return;
    }
    if (data[0] == 13) {
        unsigned point = data[1] | data[2] << 8;
        if (point >= JOY_POINTS || !pedal_samples_valid || applied_duty ||
            pulse_direction || spin_duty || (pid_status() & PID_STATE_PLAYING) ||
            (point && joy_next != point)) return;
        if (!point) joy_next = 0;
        for (unsigned axis = 0; axis < 2; ++axis)
            joy_pending.point[point][axis] = adc_filtered[PEDAL_COUNT + axis] / 4;
        if (point == JOY_POINTS - 1) {
            if (!joystick_calibration_valid(&joy_pending)) { result = 8; return; }
            if (!joystick_calibration_save(&joy_pending)) { result = 2; return; }
            joy_calibration = joy_pending;
            joy_calibration_saved = true;
            joy_next = 0;
        } else joy_next = point + 1;
        result = 0;
        return;
    }
    if (data[0] == 14) {
        unsigned source = data[1] | data[2] << 8;
        unsigned target = data[3] | data[4] << 8;
        if (source >= BUTTON_SOURCES || target > 32 || applied_duty ||
            pulse_direction || spin_duty || (pid_status() & PID_STATE_PLAYING)) return;
        if (button_map[source] == target) { result = 0; return; }
        unsigned group = source / BUTTON_MAP_GROUP;
        uint8_t updated[BUTTON_MAP_GROUP];
        for (unsigned i = 0; i < BUTTON_MAP_GROUP; ++i) {
            unsigned index = group * BUTTON_MAP_GROUP + i;
            updated[i] = index < BUTTON_SOURCES ? button_map[index] : 0;
        }
        updated[source % BUTTON_MAP_GROUP] = target;
        if (!button_map_save(group, updated)) { result = 2; return; }
        button_map[source] = target;
        result = 0;
        return;
    }
    if (data[0] == 12) {
        unsigned channel = data[1] | data[2] << 8;
        PedalCalibration range = {data[3] | data[4] << 8, data[5] | data[6] << 8};
        if (channel >= PEDAL_COUNT || !pedal_calibration_valid(range) ||
            !pedal_samples_valid || applied_duty || pulse_direction || spin_duty ||
            (pid_status() & PID_STATE_PLAYING)) return;
        if ((pedal_saved_mask & (1u << channel)) &&
            range.released == pedal_ranges[channel].released &&
            range.pressed == pedal_ranges[channel].pressed) {
            result = 0;
            return;
        }
        if (!pedal_calibration_save(channel, range)) {
            result = 2;
            return;
        }
        pedal_ranges[channel] = range;
        pedal_saved_mask |= 1u << channel;
        result = 0;
        return;
    }
    if (data[0] == 8 && bench_used) {
        pulse_direction = 0;
        spin_duty = 0;
        bench_used = false;
        motor_off();
        pid_reset();
        result = 0;
        return;
    }
    if (data[0] == 9 || data[0] == 10) {
        uint16_t duty_percent = data[1] | data[2] << 8;
        if (!can_start_spin() || duty_percent < SPIN_MIN_PERCENT || duty_percent > SPIN_MAX_PERCENT) return;
        int16_t duty = PWM_PERIOD * duty_percent / 100;
        spin_duty = data[0] == 9 ? -duty : duty;
        bench_used = true;
        pulse_start = movement_time = HAL_GetTick();
        last_movement = count;
        result = 0;
        return;
    }
    if (data[0] >= 4 && data[0] <= 7) {
        bool bench = data[0] >= 6;
        int16_t axis = wheel_axis();
        if (!wheel_can_drive() || bench_used || pulse_direction || axis > 8192 || axis < -8192) return;
        if (bench && applied_duty) return;
        pulse_start = HAL_GetTick();
        pulse_direction = (data[0] & 1) ? 1 : -1;
        if (bench) {
            bench_used = true;
            last_movement = count;
            movement_time = pulse_start;
        }
        result = 0;
        return;
    }
    if (data[0] == 11) { // Unloaded bench mode for this boot.
        if (!motor_interlock() || applied_duty || pulse_direction || spin_duty || bench_used) return;
        stage = 0;
        pid_reset();
        result = 0;
        return;
    }
    if (data[0] == 1) {
        uint16_t travel = data[1] | data[2] << 8;
        if (travel < 90 || travel > 1080) return;
        if (!encoder_begin_calibration()) { result = 3; return; }
        count = encoder_absolute_position();
        stage = 1;
        calibration_saved = false;
        pulse_direction = 0;
        spin_duty = 0;
        bench_used = false;
        motor_off();
        pid_reset();
        center = count;
        degrees = travel;
    } else if (data[0] == 2 && stage == 1) {
        if (count - center > -16 && count - center < 16) { result = 4; return; }
        if (!encoder_healthy(HAL_GetTick())) { result = 3; return; }
        left = encoder_absolute_position();
        hall_left = encoder_hall_count();
        stage = 2;
    } else if (data[0] == 3 && stage == 2) {
        if (!encoder_healthy(HAL_GetTick())) { result = 3; return; }
        int32_t left_offset = left - center;
        int32_t right_offset = encoder_absolute_position() - center;
        if (left_offset < -32768 || left_offset > 32767 ||
            right_offset < -32768 || right_offset > 32767) { result = 7; return; }
        EncoderCalibration value = {
            encoder_hall_count() - hall_left, (int16_t)left_offset, (int16_t)right_offset, degrees
        };
        if (value.hall_span > -16 && value.hall_span < 16) { result = 5; return; }
        if ((left_offset < 0 && right_offset < 128) ||
            (left_offset > 0 && right_offset > -128)) { result = 6; return; }
        if (!encoder_calibration_valid(&value)) { result = 7; return; }
        if (!encoder_calibration_save(&value)) {
            result = 2;
            return;
        }
        calibration_saved = true;
        encoder_set_scale(&value);
        count = encoder_position();
        raw_sign = left < center ? 1 : -1;
        right = center + value.right_offset;
        stage = 3;
        fault = 0;
        pid_reset();
    } else {
        return;
    }
    result = 0;
}

static void sample_inputs(void) {
    count = encoder_position();
    for (unsigned i = 0; i < TU_ARRAY_SIZE(buttons); ++i) {
        bool pressed = buttons[i].mask && !(buttons[i].port->IDR & buttons[i].mask);
        uint32_t bit = 1u << i;
        if (pressed == !!(keys & bit)) {
            debounce[i] = 0;
        } else if (++debounce[i] == 8) {
            keys ^= bit;
            debounce[i] = 0;
        }
    }
    unsigned joy_winner = 3;
    int64_t best_projection = 0, best_length = 1;
    if (pedal_samples_valid && joy_calibration_saved) {
        for (unsigned i = 0; i < 3; ++i) {
            uint32_t bit = 1u << (JOY_FIRST_SOURCE + i);
            int32_t dx = adc_filtered[PEDAL_COUNT] / 4 - joy_calibration.point[0][0];
            int32_t dy = adc_filtered[PEDAL_COUNT + 1] / 4 - joy_calibration.point[0][1];
            int32_t vx = (int32_t)joy_calibration.point[i + 1][0] - joy_calibration.point[0][0];
            int32_t vy = (int32_t)joy_calibration.point[i + 1][1] - joy_calibration.point[0][1];
            int64_t projection = (int64_t)dx * vx + (int64_t)dy * vy;
            int64_t length = (int64_t)vx * vx + (int64_t)vy * vy;
            if (100 * projection >= (keys & bit ? 35 : 55) * length &&
                (joy_winner == 3 || projection * best_length > best_projection * length)) {
                joy_winner = i;
                best_projection = projection;
                best_length = length;
            }
        }
    }
    keys &= ~(7u << JOY_FIRST_SOURCE);
    if (joy_winner < 3) keys |= 1u << (JOY_FIRST_SOURCE + joy_winner);
    // Neutral is a virtual switch: none of gears 1-6 or reverse is engaged.
    const uint32_t gear_mask = ((1u << GEAR_COUNT) - 1u) << GEAR_FIRST_SOURCE;
    if (keys & gear_mask) keys &= ~(1u << NEUTRAL_SOURCE);
    else keys |= 1u << NEUTRAL_SOURCE;
}

static void update_motor(uint32_t now, int32_t force) {
    if (spin_duty) {
        // The unloaded motor can turn past a wheel's calibrated range.
        if (!motor_interlock() || force || now - pulse_start >= BENCH_PULSE_MS) {
            spin_duty = 0;
            motor_off();
            return;
        }
        int32_t delta = count - last_movement;
        if (delta >= 3 || delta <= -3) {
            last_movement = count;
            movement_time = now;
        } else if (now - movement_time >= SPIN_STALL_MS) {
            fault = 2;
            spin_duty = 0;
            motor_off();
            return;
        }
        motor_drive(spin_duty);
        return;
    }
    int32_t position = normalized();
    if (!wheel_can_drive()) {
        pulse_direction = 0;
        motor_off();
        movement_time = now;
        last_movement = count;
        return;
    }

    int32_t distance = position < 0 ? -position : position;
    if (distance > SOFT_STOP_START) {
        // Active steering stop, including when the game has no effect playing.
        pulse_direction = 0;
        int32_t penetration = clamp(distance - SOFT_STOP_START, 0, TRAVEL_LIMIT - SOFT_STOP_START);
        int32_t duty = penetration * (PWM_PERIOD * ffb_limit_percent / 100)
                       / (TRAVEL_LIMIT - SOFT_STOP_START);
        motor_drive(position > 0 ? -duty : duty);
        return;
    }

    // Hold game force off until the bench tool acknowledges the stop.
    if (bench_used && (!pulse_direction || force || position * pulse_direction >= 32767)) {
        pulse_direction = 0;
        motor_off();
        return;
    }

    bool test_pulse = pulse_direction != 0;
    if (test_pulse) {
        uint32_t duration = bench_used ? BENCH_PULSE_MS : TEST_PULSE_MS;
        if (now - pulse_start < duration) force = pulse_direction * 32767;
        else { pulse_direction = 0; force = 0; }
    }

    int32_t pwm_limit = bench_used ? BENCH_PWM_MAX : PWM_PERIOD * ffb_limit_percent / 100;
    int32_t target = test_pulse ? force * pwm_limit / 32767 : ffb_target(force);

    int32_t delta = count - last_movement;
    if (bench_used && target && delta * raw_sign * pulse_direction <= -3) fault = 3;
    // A driver can hold the wheel still against game torque.
    if (!test_pulse || !target || delta >= 3 || delta <= -3) {
        last_movement = count;
        movement_time = now;
    } else if (now - movement_time >= (bench_used ? BENCH_STALL_MS : 1000)) {
        fault = 2;
    }
    if (fault) motor_off();
    else motor_drive(target);
}

static void send_inputs(uint32_t now) {
    static uint8_t last_pid = 0xff;
    static uint32_t last_input;
    if (!tud_hid_n_ready(0)) return;
    if (now - last_input >= 4) {
        uint16_t input[WHEEL_INPUT_WORDS];
        wheel_input_report(input);
        if (tud_hid_n_report(0, 1, input, sizeof input)) last_input = now;
        return;
    }
    uint8_t status = pid_status();
    if (status != last_pid && tud_hid_n_report(0, 2, &status, 1)) last_pid = status;
}

void wheel_init(void) {
    encoder_init();
    motor_off();
    ffb_limit_load(&ffb_limit_percent);
    EncoderCalibration value;
    for (unsigned i = 0; i < PEDAL_COUNT; ++i)
        if (pedal_calibration_load(i, &pedal_ranges[i])) pedal_saved_mask |= 1u << i;
    for (unsigned i = 0; i < PEDAL_COUNT; ++i)
        pedal_deadzone_load(i, &pedal_deadzone[i]);
    for (unsigned i = 0; i < BUTTON_SOURCES; ++i) button_map[i] = i + 1;
    button_map[NEUTRAL_SOURCE] = 0; // ETS2 treats no H-shifter position as neutral.
    for (unsigned group = 0; group < BUTTON_MAP_GROUPS; ++group) {
        uint8_t saved[BUTTON_MAP_GROUP] = {0};
        if (button_map_load(group, saved))
            for (unsigned i = 0; i < BUTTON_MAP_GROUP; ++i) {
                unsigned index = group * BUTTON_MAP_GROUP + i;
                if (index < BUTTON_SOURCES) button_map[index] = saved[i];
            }
    }
    joy_calibration_saved = joystick_calibration_load(&joy_calibration);
    calibration_saved = encoder_calibration_load(&value);
    if (calibration_saved) {
        encoder_set_scale(&value);
        left = value.left_offset;
        right = value.right_offset;
        degrees = value.degrees;
        raw_sign = left < 0 ? 1 : -1;
        stage = 3; // The initial counter position is the center for this boot.
    }

    GPIO_InitTypeDef pins = {
        .Pin = GPIO_PIN_11 | GPIO_PIN_12, .Mode = GPIO_MODE_AF_PP,
        .Pull = GPIO_NOPULL, .Speed = GPIO_SPEED_FREQ_VERY_HIGH,
        .Alternate = GPIO_AF10_OTG_FS
    };
    HAL_GPIO_Init(GPIOA, &pins);
    __HAL_RCC_USB_OTG_FS_CLK_ENABLE();
    USB_OTG_FS->GCCFG |= USB_OTG_GCCFG_NOVBUSSENS;
    USB_OTG_FS->GCCFG &= ~(USB_OTG_GCCFG_VBUSASEN | USB_OTG_GCCFG_VBUSBSEN);
    HAL_NVIC_SetPriority(OTG_FS_IRQn, 5, 0);
    const tusb_rhport_init_t init = {.role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_FULL};
    if (!tusb_init(0, &init)) Error_Handler();

    IWDG->KR = 0xcccc;
    IWDG->KR = 0x5555;
    IWDG->PR = 4; // LSI / 64
    IWDG->RLR = 124; // Nominally 250 ms
    while (IWDG->SR) {}
    IWDG->KR = 0xaaaa;
}

void wheel_task(void) {
    static uint32_t last_tick;
    tud_task();
    uint32_t now = HAL_GetTick();
    if (now == last_tick) return;
    last_tick = now;
    encoder_task(now);
    sample_pedals();
    sample_inputs();
    now = HAL_GetTick();
    update_motor(now, pid_force(now));
    send_inputs(now);
    IWDG->KR = 0xaaaa;
}

uint32_t tusb_time_millis_api(void) { return HAL_GetTick(); }

void OTG_FS_IRQHandler(void) { tusb_int_handler(0, true); }

