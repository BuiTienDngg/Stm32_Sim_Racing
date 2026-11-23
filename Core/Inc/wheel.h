#pragma once
#include <stdbool.h>
#include <stdint.h>

#define MAX_EFFECTS 8
#define DIAG_ID 0x30
#define DIAG_SIZE 20
#define MAP_DIAG_SIZE 21
#define PEDAL_DIAG_ID 0x31
#define JOY_DIAG_ID 0x33
#define MAP_DIAG_ID 0x34
#define EXTRA_DIAG_ID 0x35
#define DEADZONE_DIAG_ID 0x36
#define WHEEL_INPUT_WORDS 7

int16_t wheel_axis(void);
uint32_t wheel_buttons(void);
void wheel_input_report(uint16_t report[WHEEL_INPUT_WORDS]);
bool wheel_can_drive(void);
void wheel_usb_stop(void);
void wheel_command(const uint8_t *data);
void wheel_status(uint8_t *out);
void wheel_pedal_status(uint8_t *out);
void wheel_joystick_status(uint8_t *out);
void wheel_map_status(uint8_t *out);
void wheel_extra_status(uint8_t *out);
void wheel_deadzone_status(uint8_t *out);

void pid_reset(void);
uint8_t pid_status(void);
int32_t pid_force(uint32_t now);
void pid_set(uint8_t id, bool feature, const uint8_t *data, uint16_t size);
uint16_t pid_get(uint8_t id, uint8_t *out, uint16_t size);

void wheel_init(void);
void wheel_task(void);
