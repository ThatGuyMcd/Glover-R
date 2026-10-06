#ifndef ROCKET_MOD_H
#define ROCKET_MOD_H

/* Glover-R API 1. Guest pointers and integers use the N64 O32 ABI. */
#define ROCKET_CALLBACK(event) __attribute__((used, retain, section(".recomp_callback.*:" #event)))
#define ROCKET_IMPORT __attribute__((noinline, weak, used, section(".recomp_import.*")))
typedef unsigned int RocketU32;

/* Valid only during rocket_on_camera_update. Glover uses Y-up native
 * coordinates; orbit yaw/pitch are radians. Requests enter the authored
 * camera update before its remaining native constraints. Collision, recenter
 * and special-camera compatibility require gameplay validation in this port.
 * Packet pointers are temporary. Set apply and all output fields together. */
typedef struct RocketCamera {
    RocketU32 api, size;
    float delta_time, look_x, look_y;
    RocketU32 recenter, reset;
    float yaw, pitch, distance;
    RocketU32 apply;
    float output_yaw, output_pitch, output_distance;
} RocketCamera;

/* Optional rocket_on_mouse_look event, delivered immediately before the camera
 * update. Deltas are radians since the last update, independent of frame rate.
 * Positive yaw looks right; positive pitch moves the mouse down. */
typedef struct RocketMouseLook {
    RocketU32 api, size;
    float yaw, pitch;
} RocketMouseLook;

/* Reserved compatible first-person ABI. Glover's dedicated first-person
 * analogue adapter is not yet implemented; this event is not emitted. */
typedef struct RocketFirstPersonCamera {
    RocketU32 api, size;
    float delta_time, look_x, look_y;
    RocketU32 recenter, reset;
    float yaw, pitch;
    RocketU32 apply;
    float output_yaw, output_pitch;
} RocketFirstPersonCamera;

ROCKET_IMPORT void rocket_claim_analogue_camera(void) {}
ROCKET_IMPORT void rocket_enable_mouse_look(void) {}
ROCKET_IMPORT void rocket_enable_first_person_look(void) {}
/* Compatible reserved import. The Glover host retains its native follow spring;
 * the test mod implements response/glide in guest code. */
ROCKET_IMPORT void rocket_set_camera_smoothing(RocketU32 percent) { (void)percent; }
ROCKET_IMPORT double recomp_get_config_double(const char* key) { (void)key; return 0; }
ROCKET_IMPORT RocketU32 recomp_get_config_u32(const char* key) { (void)key; return 0; }

#endif
