#include "main.h"
#include "encoder.h"
#include <string.h>

extern I2C_HandleTypeDef hi2c1;

enum {
    AS5600_ADDRESS = 0x36 << 1,
    AS5600_STATUS = 0x0b,
    COUNTS_PER_TURN = 4096,
    FRACTION = 65536,
    READ_INTERVAL_MS = 4,
    STALE_MS = 20,
    MAX_DISAGREEMENT = 256 // 22.5 degrees on the steering shaft.
};

static uint16_t previous_hall, raw_angle, zero_angle;
static int32_t hall_count, hall_origin, absolute_position, disagreement;
static int32_t hall_span, angle_span;
static int64_t fused_q;
static uint32_t last_attempt, last_good;
static uint8_t magnet_status, io_status;
static bool initialized, scaled, mismatch;

static int32_t wrap_difference(int32_t value) {
    value %= COUNTS_PER_TURN;
    if (value >= COUNTS_PER_TURN / 2) value -= COUNTS_PER_TURN;
    if (value < -COUNTS_PER_TURN / 2) value += COUNTS_PER_TURN;
    return value;
}

void encoder_init(void) {
    previous_hall = TIM3->CNT;
    last_attempt = HAL_GetTick() - READ_INTERVAL_MS;
}

bool encoder_begin_calibration(void) {
    if (!initialized || (magnet_status & 0x38) != 0x20 ||
        HAL_GetTick() - last_good > STALE_MS) return false;
    mismatch = false;
    scaled = false;
    fused_q = (int64_t)absolute_position * FRACTION;
    return true;
}

void encoder_set_scale(const EncoderCalibration *value) {
    hall_span = value->hall_span;
    angle_span = (int32_t)value->right_offset - value->left_offset;
    scaled = true;
    // Calibration is captured from the absolute sensor, so align interpolation.
    fused_q = (int64_t)absolute_position * FRACTION;
    disagreement = 0;
}

int32_t encoder_position(void) { return (int32_t)(fused_q / FRACTION); }
int32_t encoder_absolute_position(void) { return absolute_position; }
int32_t encoder_hall_count(void) { return hall_count - hall_origin; }

bool encoder_healthy(uint32_t now) {
    return initialized && !mismatch && (magnet_status & 0x38) == 0x20 &&
           now - last_good <= STALE_MS;
}

uint8_t encoder_fault(uint32_t now) {
    if (mismatch) return 5;
    return encoder_healthy(now) ? 0 : 4;
}

void encoder_task(uint32_t now) {
    uint16_t current = TIM3->CNT;
    int16_t delta = (int16_t)(current - previous_hall);
    previous_hall = current;
    hall_count += delta;
    if (initialized && scaled)
        fused_q += (int64_t)delta * angle_span * FRACTION / hall_span;

    if (now - last_attempt < READ_INTERVAL_MS) return;
    last_attempt = now;
    // Avoid HAL's separate 25 ms BUSY wait when a disconnected bus is stuck.
    if (__HAL_I2C_GET_FLAG(&hi2c1, I2C_FLAG_BUSY)) {
        io_status = 2;
        return;
    }
    uint8_t data[3];
    HAL_StatusTypeDef status = HAL_I2C_Mem_Read(&hi2c1, AS5600_ADDRESS, AS5600_STATUS,
                                              I2C_MEMADD_SIZE_8BIT, data, sizeof data, 2);
    if (status != HAL_OK) {
        io_status = 5;
        if (hi2c1.ErrorCode & HAL_I2C_ERROR_AF) io_status = 3;
        if (status == HAL_TIMEOUT || (hi2c1.ErrorCode & HAL_I2C_ERROR_TIMEOUT)) io_status = 4;
        return;
    }
    io_status = 1;
    magnet_status = data[0];
    if ((magnet_status & 0x38) != 0x20) return;
    raw_angle = ((data[1] & 0x0f) << 8) | data[2];
    if (!initialized) {
        zero_angle = raw_angle;
        hall_origin = hall_count;
        initialized = true;
        fused_q = 0;
    } else if (!scaled && now - last_good > STALE_MS) {
        // An uncalibrated Hall sensor cannot resolve turns lost during an outage.
        mismatch = true;
    }
    last_good = now;
    int32_t predicted = encoder_position();
    int32_t relative = (int32_t)raw_angle - zero_angle;
    disagreement = wrap_difference(relative - predicted);
    absolute_position = predicted + disagreement;
    if (!scaled) {
        fused_q = (int64_t)absolute_position * FRACTION;
        return;
    }
    if (disagreement > MAX_DISAGREEMENT || disagreement < -MAX_DISAGREEMENT) {
        mismatch = true;
        return;
    }
    if (!mismatch)
        fused_q += ((int64_t)absolute_position * FRACTION - fused_q) / 4;
}

void encoder_status(uint8_t *out) {
    int32_t values[4] = {
        encoder_hall_count(), absolute_position, encoder_position(),
        scaled ? (int32_t)((int64_t)angle_span * FRACTION / hall_span) : 0
    };
    memcpy(out, values, sizeof values);
    memcpy(out + 16, &raw_angle, 2);
    out[18] = (initialized ? 1 : 0) | (encoder_healthy(HAL_GetTick()) ? 2 : 0) |
              (scaled ? 4 : 0) | (mismatch ? 8 : 0) | (io_status << 4);
    out[19] = magnet_status;
}
