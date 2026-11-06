#ifndef SETTINGS_H
#define SETTINGS_H
// ****************************************************************************
// Voice Crow (Arduino Nano) User Configuration
// ****************************************************************************

// ============================================================================
// PIN DEFINITIONS
// ============================================================================
#define PIN_SERVO                     9     // beak servo signal (orange wire)
#define PIN_STEPPER_IN1               4     // ULN2003 board IN1
#define PIN_STEPPER_IN2               5     // ULN2003 board IN2
#define PIN_STEPPER_IN3               6     // ULN2003 board IN3
#define PIN_STEPPER_IN4               7     // ULN2003 board IN4
#define PIN_LED_EYES                  3     // must be a PWM pin: 3 or 11 (9/10 lose PWM to the servo)

// ============================================================================
// BEAK SERVO
// ============================================================================
// Calibrated for this crow with the U command (see voiceCrow/README.md, "Calibrate").
// Re-check them if the servo arm is ever removed or re-seated.
#define SERVO_PWM_OPEN                915   // fully open pulse (microseconds)
#define SERVO_PWM_CLOSED              1170  // fully closed pulse (microseconds)
#define BEAK_SMOOTHING                0.35  // 0.1 = soft and slow, 1.0 = snaps instantly
#define BEAK_TIMEOUT_MS               500   // close the beak if the laptop stops sending

// ============================================================================
// NECK STEPPER (28BYJ-48 + ULN2003)
// ============================================================================
#define NECK_RANGE                    1400  // total range of motion in half-steps
#define NECK_SPEED_SLOW_MAX           3250  // slow movement max speed
#define NECK_SPEED_SLOW_ACCEL         500   // slow movement acceleration
#define NECK_SPEED_FAST_MAX           4000  // fast movement max speed (a Nano tops out near 4000)
#define NECK_SPEED_FAST_ACCEL         4000  // fast movement acceleration
#define NECK_RELEASE_WHEN_IDLE        true  // cut stepper power between moves so it stays cool

// ============================================================================
// EYES
// ============================================================================
#define EYE_BRIGHTNESS                255   // max brightness 0-255
#define EYE_PULSE_PERIOD_MS           1800  // "listening" breathing speed
#define BLINK_DURATION_MS             90    // how long eyes stay closed
#define BLINK_MIN_INTERVAL_MS         3000  // min time between blinks
#define BLINK_MAX_INTERVAL_MS         8000  // max time between blinks

#endif
