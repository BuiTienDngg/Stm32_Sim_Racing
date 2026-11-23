#include "wheel.h"
#include "stm32f4xx_hal.h"
#include <math.h>
#include <string.h>

typedef struct {
    uint32_t start, updated, attack, fade;
    uint16_t duration, delay, attack_level, fade_level;
    int16_t magnitude;
    uint8_t gain, loops;
    float direction;
    bool allocated, playing;
} Effect;

static Effect effects[MAX_EFFECTS];
static uint8_t load_index, load_status = 3, device_gain = 255;
static bool enabled, paused, playing;

static uint16_t u16(const uint8_t *p) {
    return (uint16_t)(p[0] | p[1] << 8);
}

static uint32_t u32(const uint8_t *p) {
    return u16(p) | (uint32_t)u16(p + 2) << 16;
}

static unsigned free_slots(void) {
    unsigned count = 0;
    for (unsigned i = 0; i < MAX_EFFECTS; ++i)
        count += !effects[i].allocated;
    return count;
}

static void stop_all(void) {
    for (unsigned i = 0; i < MAX_EFFECTS; ++i)
        effects[i].playing = false;
    playing = false;
}

void pid_reset(void) {
    memset(effects, 0, sizeof effects);
    enabled = paused = playing = false;
    device_gain = 255;
    load_index = 0;
    load_status = 3;
}

uint8_t pid_status(void) {
    return (paused ? 1 : 0) | (enabled ? 2 : 0) |
           (wheel_can_drive() ? 8 : 0) | (playing ? 16 : 0);
}

static void allocate(uint8_t type) {
    load_index = 0;
    load_status = type == 1 ? 2 : 3;
    if (type != 1) return;
    for (unsigned i = 0; i < MAX_EFFECTS; ++i) {
        if (effects[i].allocated) continue;
        effects[i] = (Effect){ .allocated = true, .gain = 255, .direction = 1.0f };
        load_index = i + 1;
        load_status = 1;
        break;
    }
}

uint16_t pid_get(uint8_t id, uint8_t *out, uint16_t size) {
    if (size < 4) return 0;
    if (id == 0x12) {
        out[0] = load_index;
        out[1] = load_status;
        out[2] = free_slots();
        out[3] = 0;
    } else if (id == 0x13) {
        out[0] = MAX_EFFECTS;
        out[1] = 0;
        out[2] = MAX_EFFECTS;
        out[3] = 1; // Device-managed pool
    } else {
        return 0;
    }
    return 4;
}

void pid_set(uint8_t id, bool feature, const uint8_t *data, uint16_t size) {
    if (!size) return;
    if (feature) {
        if (id == 0x11 && size >= 3) allocate(data[0]);
        return;
    }
    if (id == 0x0c) {
        uint8_t command = data[0];
        if (command & 8) {
            pid_reset();
            enabled = true; // USB PID DC Reset clears effects and enables actuators.
            return;
        }
        if (command & 1) enabled = true;
        if (command & 2) { enabled = false; stop_all(); }
        if (command & 4) stop_all();
        if (command & 16) { paused = true; stop_all(); }
        if (command & 32) paused = false;
        return;
    }
    if (id == 0x0d) { device_gain = data[0]; return; }

    unsigned index = data[0];
    if (!index || index > MAX_EFFECTS || !effects[index - 1].allocated) return;
    Effect *effect = &effects[index - 1];
    uint32_t now = HAL_GetTick();
    switch (id) {
        case 1: // Set Effect
            if (size < 21 || data[1] != 1) break;
            effect->duration = u16(data + 2);
            effect->delay = u16(data + 8);
            effect->gain = data[10];
            if (data[12] & 4) {
                effect->direction = -sinf(u16(data + 13) * (6.283185307f / 36000.0f));
            } else {
                effect->direction = (data[12] & 1) ? (18000.0f - u16(data + 13)) / 18000.0f : 0.0f;
            }
            break;
        case 2: // Envelope
            if (size < 13) break;
            effect->attack_level = u16(data + 1);
            effect->fade_level = u16(data + 3);
            effect->attack = u32(data + 5);
            effect->fade = u32(data + 9);
            break;
        case 5: // Set Constant Force
            if (size < 3) break;
            effect->magnitude = (int16_t)u16(data + 1);
            effect->updated = now;
            break;
        case 0x0a: // Start, start solo, stop
            if (size < 3) break;
            if (data[1] == 2) stop_all();
            if (data[1] == 1 || data[1] == 2) {
                effect->start = now;
                effect->updated = now;
                effect->loops = data[2];
                effect->playing = true;
            } else if (data[1] == 3) {
                effect->playing = false;
            }
            break;
        case 0x0b:
            *effect = (Effect){0};
            break;
    }
}

int32_t pid_force(uint32_t now) {
    playing = false;
    if (!enabled || paused) return 0;
    float force = 0.0f;
    for (unsigned i = 0; i < MAX_EFFECTS; ++i) {
        Effect *effect = &effects[i];
        if (!effect->playing || now - effect->updated >= 500) continue;
        uint32_t elapsed = now - effect->start;
        if (elapsed < effect->delay) continue;
        elapsed -= effect->delay;
        bool finite = effect->duration && effect->duration < 0x7fff;
        if (finite && effect->loops != 255 &&
            elapsed >= (uint32_t)effect->duration * (effect->loops ? effect->loops : 1)) {
            effect->playing = false;
            continue;
        }
        if (finite) elapsed %= effect->duration;
        int32_t level = effect->magnitude;
        int32_t absolute = level < 0 ? -level : level;
        float shaped = absolute;
        if (effect->attack && elapsed < effect->attack) {
            shaped = effect->attack_level + (absolute - (int32_t)effect->attack_level)
                     * ((float)elapsed / effect->attack);
        } else if (finite && effect->fade && effect->duration - elapsed < effect->fade) {
            shaped = effect->fade_level + (absolute - (int32_t)effect->fade_level)
                     * ((float)(effect->duration - elapsed) / effect->fade);
        }
        if (level == 0) shaped = 0;
        if (level < 0) shaped = -shaped;
        force += shaped * effect->direction * (effect->gain / 255.0f);
        playing = true;
    }
    return (int32_t)(force * (device_gain / 255.0f));
}

