#pragma once
#include "calibration.h"
#include <stdbool.h>
#include <stdint.h>

#define ENCODER_DIAG_ID 0x32
#define ENCODER_DIAG_SIZE 20

void encoder_init(void);
void encoder_task(uint32_t now);
bool encoder_begin_calibration(void);
void encoder_set_scale(const EncoderCalibration *value);
int32_t encoder_position(void);
int32_t encoder_absolute_position(void);
int32_t encoder_hall_count(void);
bool encoder_healthy(uint32_t now);
uint8_t encoder_fault(uint32_t now);
void encoder_status(uint8_t *out);
