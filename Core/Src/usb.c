#include "tusb.h"
#include "wheel.h"
#include "encoder.h"
#include <string.h>
#include "pid_descriptor.h"

static uint8_t const diag_report[] = {
    0x06,0x31,0xff, 0x09,0x01, 0xa1,0x01, // Vendor page FF31
    0x85,DIAG_ID, 0x09,0x02, 0x15,0x00, 0x26,0xff,0x00,
    0x75,0x08, 0x95,DIAG_SIZE, 0xb1,0x02,
    0x85,PEDAL_DIAG_ID, 0x09,0x03, 0x95,DIAG_SIZE, 0xb1,0x02,
    0x85,ENCODER_DIAG_ID, 0x09,0x04, 0x95,ENCODER_DIAG_SIZE, 0xb1,0x02,
    0x85,JOY_DIAG_ID, 0x09,0x05, 0x95,DIAG_SIZE, 0xb1,0x02,
    0x85,MAP_DIAG_ID, 0x09,0x06, 0x95,MAP_DIAG_SIZE, 0xb1,0x02,
    0x85,EXTRA_DIAG_ID, 0x09,0x07, 0x95,DIAG_SIZE, 0xb1,0x02,
    0x85,DEADZONE_DIAG_ID, 0x09,0x08, 0x95,DIAG_SIZE, 0xb1,0x02, 0xc0
};

// Local prototype VID/PID. Obtain a proper allocation for distribution.
static tusb_desc_device_t const device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = 0xcafe,
    .idProduct = 0x4111,
    .bcdDevice = 0x0107,
    .iManufacturer = 1, .iProduct = 2, .iSerialNumber = 3,
    .bNumConfigurations = 1
};

#define CONFIG_SIZE (TUD_CONFIG_DESC_LEN + TUD_HID_INOUT_DESC_LEN + TUD_HID_DESC_LEN)
static uint8_t const config[] = {
    TUD_CONFIG_DESCRIPTOR(1, 2, 0, CONFIG_SIZE, 0, 100),
    TUD_HID_INOUT_DESCRIPTOR(0, 0, HID_ITF_PROTOCOL_NONE, sizeof wheel_report, 0x01, 0x81, 32, 2),
    TUD_HID_DESCRIPTOR(1, 0, HID_ITF_PROTOCOL_NONE, sizeof diag_report, 0x82, 32, 4)
};

uint8_t const *tud_descriptor_device_cb(void) { return (uint8_t const *)&device; }
uint8_t const *tud_descriptor_configuration_cb(uint8_t index) { (void)index; return config; }
uint8_t const *tud_hid_descriptor_report_cb(uint8_t itf) { return itf ? diag_report : wheel_report; }

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t lang) {
    (void)lang;
    static uint16_t buffer[32];
    static const char *const strings[] = { "", "DIY Sim", "F411 DIY FFB Wheel", "" };
    if (index >= TU_ARRAY_SIZE(strings)) return NULL;
    unsigned len = 0;
    if (index == 0) {
        buffer[++len] = 0x0409;
    } else if (index == 3) {
        const uint32_t *uid = (const uint32_t *)0x1fff7a10u;
        static const char hex[] = "0123456789ABCDEF";
        for (unsigned word = 0; word < 3; ++word)
            for (unsigned digit = 0; digit < 8; ++digit)
                buffer[++len] = hex[(uid[word] >> (28 - 4 * digit)) & 15];
    } else {
        const char *s = strings[index];
        while (*s) buffer[++len] = (uint8_t)*s++;
    }
    buffer[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 + 2 * len));
    return buffer;
}

uint16_t tud_hid_get_report_cb(uint8_t itf, uint8_t id, hid_report_type_t type,
                               uint8_t *buffer, uint16_t size) {
    if (type == HID_REPORT_TYPE_FEATURE) {
        if (itf == 0) return pid_get(id, buffer, size);
        if (id == DIAG_ID && size >= DIAG_SIZE) {
            wheel_status(buffer);
            return DIAG_SIZE;
        }
        if (id == PEDAL_DIAG_ID && size >= DIAG_SIZE) {
            wheel_pedal_status(buffer);
            return DIAG_SIZE;
        }
        if (id == ENCODER_DIAG_ID && size >= ENCODER_DIAG_SIZE) {
            encoder_status(buffer);
            return ENCODER_DIAG_SIZE;
        }
        if (id == JOY_DIAG_ID && size >= DIAG_SIZE) {
            wheel_joystick_status(buffer);
            return DIAG_SIZE;
        }
        if (id == MAP_DIAG_ID && size >= MAP_DIAG_SIZE) {
            wheel_map_status(buffer);
            return MAP_DIAG_SIZE;
        }
        if (id == EXTRA_DIAG_ID && size >= DIAG_SIZE) {
            wheel_extra_status(buffer);
            return DIAG_SIZE;
        }
        if (id == DEADZONE_DIAG_ID && size >= DIAG_SIZE) {
            wheel_deadzone_status(buffer);
            return DIAG_SIZE;
        }
    }
    if (itf == 0 && type == HID_REPORT_TYPE_INPUT) {
        uint16_t input[WHEEL_INPUT_WORDS];
        if (id == 1 && size >= sizeof input) {
            wheel_input_report(input);
            memcpy(buffer, input, sizeof input);
            return sizeof input;
        }
        if (id == 2 && size >= 1) {
            buffer[0] = pid_status();
            return 1;
        }
    }
    return 0;
}

void tud_hid_set_report_cb(uint8_t itf, uint8_t id, hid_report_type_t type,
                           const uint8_t *data, uint16_t size) {
    if (type == HID_REPORT_TYPE_OUTPUT && !id && size) {
        id = *data++;
        --size;
    }
    if (!itf && (type == HID_REPORT_TYPE_OUTPUT || type == HID_REPORT_TYPE_FEATURE))
        pid_set(id, type == HID_REPORT_TYPE_FEATURE, data, size);
    if (itf == 1 && type == HID_REPORT_TYPE_FEATURE && id == DIAG_ID && size >= DIAG_SIZE)
        wheel_command(data);
}

void tud_umount_cb(void) { wheel_usb_stop(); }
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; wheel_usb_stop(); }

