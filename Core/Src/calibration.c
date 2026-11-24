#include "calibration.h"
#include "stm32f4xx_hal.h"

// STM32F411CE flash sector 7, reserved by the Keil linker configuration.
#define CAL_FLASH_START 0x08060000u
#define CAL_FLASH_SIZE  0x00020000u
#define CAL_COMMIT      0x43414c31u
#define PEDAL_COMMIT    0x50454431u
#define ENCODER_COMMIT  0x454e4331u
#define JOYSTICK_COMMIT 0x4a4f5931u
#define BUTTON_MAP_COMMIT 0x4d415031u
#define PEDAL_DEADZONE_COMMIT 0x445a4e31u
#define FFB_LIMIT_COMMIT 0x46464231u

enum { CAL_WORDS = 5, CAL_SLOT_SIZE = CAL_WORDS * sizeof(uint32_t) };

static uint32_t checksum(const uint32_t *words) {
    uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < 3; ++i) {
        crc ^= words[i];
        for (unsigned bit = 0; bit < 32; ++bit)
            crc = (crc >> 1) ^ ((crc & 1u) ? 0xedb88320u : 0u);
    }
    return ~crc;
}

static bool valid(const Calibration *value) {
    int32_t left = value->left_offset, right = value->right_offset;
    return value->degrees >= 90 && value->degrees <= 1080 &&
           left >= -1000000 && left <= 1000000 &&
           right >= -1000000 && right <= 1000000 &&
           ((left <= -16 && right >= 16) || (left >= 16 && right <= -16));
}

bool calibration_load(Calibration *calibration) {
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != CAL_COMMIT || words[3] != checksum(words)) continue;
        Calibration value = {(int32_t)words[0], (int32_t)words[1], words[2]};
        if (!valid(&value)) continue;
        *calibration = value;
        return true;
    }
    return false;
}

static bool append_record(uint32_t words[CAL_WORDS]) {
    words[3] = checksum(words);

    // Append only. A partial write occupies a slot, preserving all earlier records.
    uint32_t address = CAL_FLASH_START;
    for (; address <= CAL_FLASH_START + CAL_FLASH_SIZE - CAL_SLOT_SIZE; address += CAL_SLOT_SIZE) {
        const uint32_t *existing = (const uint32_t *)address;
        unsigned i = 0;
        while (i < CAL_WORDS && existing[i] == UINT32_MAX) ++i;
        if (i == CAL_WORDS) break;
    }
    if (address > CAL_FLASH_START + CAL_FLASH_SIZE - CAL_SLOT_SIZE) return false;
    if (HAL_FLASH_Unlock() != HAL_OK) return false;

    bool cache_enabled = (FLASH->ACR & FLASH_ACR_DCEN) != 0;
    __HAL_FLASH_DATA_CACHE_DISABLE();
    __HAL_FLASH_DATA_CACHE_RESET();
    bool written = true;
    for (unsigned i = 0; i < CAL_WORDS; ++i) {
        uint32_t word_address = address + i * sizeof(uint32_t);
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, word_address, words[i]) != HAL_OK ||
            *(const volatile uint32_t *)word_address != words[i]) {
            written = false;
            break;
        }
    }
    if (cache_enabled) __HAL_FLASH_DATA_CACHE_ENABLE();
    HAL_FLASH_Lock();
    return written;
}

bool calibration_save(const Calibration *calibration) {
    if (!valid(calibration)) return false;
    uint32_t words[CAL_WORDS] = {
        (uint32_t)calibration->left_offset, (uint32_t)calibration->right_offset,
        calibration->degrees, 0, CAL_COMMIT
    };
    return append_record(words);
}

bool pedal_calibration_valid(PedalCalibration value) {
    int32_t span = (int32_t)value.pressed - value.released;
    return value.released <= PEDAL_ADC_MAX && value.pressed <= PEDAL_ADC_MAX &&
           (span >= PEDAL_MIN_SPAN || span <= -PEDAL_MIN_SPAN);
}

bool pedal_calibration_load(unsigned channel, PedalCalibration *value) {
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != PEDAL_COMMIT || words[2] != channel ||
            words[0] > PEDAL_ADC_MAX || words[1] > PEDAL_ADC_MAX ||
            words[3] != checksum(words)) continue;
        PedalCalibration saved = {(uint16_t)words[0], (uint16_t)words[1]};
        if (!pedal_calibration_valid(saved)) continue;
        *value = saved;
        return true;
    }
    return false;
}

bool pedal_calibration_save(unsigned channel, PedalCalibration value) {
    if (channel >= PEDAL_COUNT || !pedal_calibration_valid(value)) return false;
    uint32_t words[CAL_WORDS] = {value.released, value.pressed, channel, 0, PEDAL_COMMIT};
    return append_record(words);
}

bool pedal_deadzone_load(unsigned channel, uint8_t *percent) {
    if (channel >= PEDAL_COUNT) return false;
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != PEDAL_DEADZONE_COMMIT || words[1] != channel ||
            words[0] > 30 || words[3] != checksum(words)) continue;
        *percent = (uint8_t)words[0];
        return true;
    }
    return false;
}

bool pedal_deadzone_save(unsigned channel, uint8_t percent) {
    if (channel >= PEDAL_COUNT || percent > 30) return false;
    uint32_t words[CAL_WORDS] = {percent, channel, 0, 0, PEDAL_DEADZONE_COMMIT};
    return append_record(words);
}

bool ffb_limit_load(uint8_t *percent) {
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != FFB_LIMIT_COMMIT || words[0] < 10 || words[0] > 80 ||
            words[3] != checksum(words)) continue;
        *percent = (uint8_t)words[0];
        return true;
    }
    return false;
}

bool ffb_limit_save(uint8_t percent) {
    if (percent < 10 || percent > 80) return false;
    uint32_t words[CAL_WORDS] = {percent, 0, 0, 0, FFB_LIMIT_COMMIT};
    return append_record(words);
}

bool encoder_calibration_valid(const EncoderCalibration *value) {
    int32_t left = value->left_offset, right = value->right_offset;
    int32_t measured = right - left;
    if (measured < 0) measured = -measured;
    int32_t expected = (int32_t)value->degrees * 4096 / 360;
    return value->degrees >= 90 && value->degrees <= 1080 &&
           value->hall_span >= -1000000 && value->hall_span <= 1000000 &&
           (value->hall_span >= 16 || value->hall_span <= -16) &&
           ((left <= -128 && right >= 128) || (left >= 128 && right <= -128)) &&
           measured >= expected * 9 / 10 && measured <= expected * 11 / 10;
}

bool encoder_calibration_load(EncoderCalibration *value) {
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != ENCODER_COMMIT || words[3] != checksum(words)) continue;
        EncoderCalibration saved = {
            (int32_t)words[0], (int16_t)words[1], (int16_t)(words[1] >> 16), words[2]
        };
        if (!encoder_calibration_valid(&saved)) continue;
        *value = saved;
        return true;
    }
    return false;
}

bool encoder_calibration_save(const EncoderCalibration *value) {
    if (!encoder_calibration_valid(value)) return false;
    uint32_t offsets = (uint16_t)value->left_offset | (uint32_t)(uint16_t)value->right_offset << 16;
    uint32_t words[CAL_WORDS] = {(uint32_t)value->hall_span, offsets, value->degrees, 0, ENCODER_COMMIT};
    return append_record(words);
}

static void pack_bits(uint32_t words[3], unsigned offset, uint32_t value, unsigned width) {
    for (unsigned bit = 0; bit < width; ++bit)
        if (value & (1u << bit)) words[(offset + bit) / 32] |= 1u << ((offset + bit) % 32);
}

static uint32_t unpack_bits(const uint32_t words[3], unsigned offset, unsigned width) {
    uint32_t value = 0;
    for (unsigned bit = 0; bit < width; ++bit)
        if (words[(offset + bit) / 32] & (1u << ((offset + bit) % 32))) value |= 1u << bit;
    return value;
}

bool joystick_calibration_valid(const JoystickCalibration *value) {
    int32_t dx[3], dy[3];
    int64_t length[3];
    for (unsigned i = 0; i < JOY_POINTS; ++i)
        for (unsigned axis = 0; axis < 2; ++axis)
            if (value->point[i][axis] > PEDAL_ADC_MAX) return false;
    for (unsigned i = 0; i < 3; ++i) {
        dx[i] = (int32_t)value->point[i + 1][0] - value->point[0][0];
        dy[i] = (int32_t)value->point[i + 1][1] - value->point[0][1];
        length[i] = (int64_t)dx[i] * dx[i] + (int64_t)dy[i] * dy[i];
        if (length[i] < 128 * 128) return false;
    }
    int64_t opposite = (int64_t)dx[0] * dx[1] + (int64_t)dy[0] * dy[1];
    if (opposite >= 0 || opposite * opposite * 4 < length[0] * length[1]) return false;
    for (unsigned i = 0; i < 2; ++i) {
        int64_t dot = (int64_t)dx[i] * dx[2] + (int64_t)dy[i] * dy[2];
        if (dot * dot * 4 >= length[i] * length[2] * 3) return false;
    }
    return true;
}

bool joystick_calibration_load(JoystickCalibration *value) {
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != JOYSTICK_COMMIT || words[3] != checksum(words)) continue;
        JoystickCalibration saved;
        for (unsigned i = 0; i < JOY_POINTS; ++i)
            for (unsigned axis = 0; axis < 2; ++axis)
                saved.point[i][axis] = unpack_bits(words, (2 * i + axis) * 12, 12);
        if (!joystick_calibration_valid(&saved)) continue;
        *value = saved;
        return true;
    }
    return false;
}

bool joystick_calibration_save(const JoystickCalibration *value) {
    if (!joystick_calibration_valid(value)) return false;
    uint32_t words[CAL_WORDS] = {0, 0, 0, 0, JOYSTICK_COMMIT};
    for (unsigned i = 0; i < JOY_POINTS; ++i)
        for (unsigned axis = 0; axis < 2; ++axis)
            pack_bits(words, (2 * i + axis) * 12, value->point[i][axis], 12);
    return append_record(words);
}

bool button_map_load(unsigned group, uint8_t value[BUTTON_MAP_GROUP]) {
    if (group >= BUTTON_MAP_GROUPS) return false;
    for (uint32_t slot = CAL_FLASH_SIZE / CAL_SLOT_SIZE; slot > 0; --slot) {
        const uint32_t *words = (const uint32_t *)(CAL_FLASH_START + (slot - 1) * CAL_SLOT_SIZE);
        if (words[4] != BUTTON_MAP_COMMIT || words[2] != group || words[3] != checksum(words)) continue;
        uint8_t saved[BUTTON_MAP_GROUP];
        bool valid = true;
        for (unsigned i = 0; i < BUTTON_MAP_GROUP; ++i) {
            saved[i] = unpack_bits(words, i * 6, 6);
            valid = valid && saved[i] <= 32;
        }
        if (!valid) continue;
        for (unsigned i = 0; i < BUTTON_MAP_GROUP; ++i) value[i] = saved[i];
        return true;
    }
    return false;
}

bool button_map_save(unsigned group, const uint8_t value[BUTTON_MAP_GROUP]) {
    if (group >= BUTTON_MAP_GROUPS) return false;
    uint32_t words[CAL_WORDS] = {0, 0, group, 0, BUTTON_MAP_COMMIT};
    for (unsigned i = 0; i < BUTTON_MAP_GROUP; ++i) {
        if (value[i] > 32) return false;
        pack_bits(words, i * 6, value[i], 6);
    }
    return append_record(words);
}
