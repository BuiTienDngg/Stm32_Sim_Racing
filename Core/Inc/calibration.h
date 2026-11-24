#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int32_t left_offset;
    int32_t right_offset;
    uint32_t degrees;
} Calibration;

enum { PEDAL_COUNT = 3, PEDAL_ADC_MAX = 4095, PEDAL_MIN_SPAN = 32 };
enum { JOY_POINTS = 4, BUTTON_SOURCES = 21, BUTTON_MAP_GROUP = 10,
       BUTTON_MAP_GROUPS = (BUTTON_SOURCES + BUTTON_MAP_GROUP - 1) / BUTTON_MAP_GROUP };

typedef struct {
    uint16_t point[JOY_POINTS][2]; // center, turn up, turn down, headlight pull
} JoystickCalibration;

bool joystick_calibration_valid(const JoystickCalibration *value);
bool joystick_calibration_load(JoystickCalibration *value);
bool joystick_calibration_save(const JoystickCalibration *value);
bool button_map_load(unsigned group, uint8_t value[BUTTON_MAP_GROUP]);
bool button_map_save(unsigned group, const uint8_t value[BUTTON_MAP_GROUP]);

typedef struct {
    uint16_t released;
    uint16_t pressed;
} PedalCalibration;

bool pedal_calibration_valid(PedalCalibration value);
bool pedal_calibration_load(unsigned channel, PedalCalibration *value);
bool pedal_calibration_save(unsigned channel, PedalCalibration value);
bool pedal_deadzone_load(unsigned channel, uint8_t *percent);
bool pedal_deadzone_save(unsigned channel, uint8_t percent);
bool ffb_limit_load(uint8_t *percent);
bool ffb_limit_save(uint8_t percent);

typedef struct {
    int32_t hall_span;
    int16_t left_offset;
    int16_t right_offset;
    uint32_t degrees;
} EncoderCalibration;

bool encoder_calibration_valid(const EncoderCalibration *value);
bool encoder_calibration_load(EncoderCalibration *value);
bool encoder_calibration_save(const EncoderCalibration *value);

bool calibration_load(Calibration *calibration);
bool calibration_save(const Calibration *calibration);
