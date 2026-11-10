/*
 * Voice Crow Controller (Arduino Nano)
 * ------------------------------------
 *
 * The laptop listens, thinks and talks. This sketch moves the crow when told
 * to, using one-line commands over USB serial at 115200 baud:
 *
 *   B<0-100>   beak position, 0 = closed, 100 = fully open (smoothed)
 *   U<us>      raw beak servo pulse in microseconds (for calibration)
 *   N<pos>     neck position in half-steps, 0 = center, +/- NECK_RANGE/2
 *   S<0|1>     neck speed: 0 = slow, 1 = fast
 *   C          re-center the neck (runs into the end stop, like at startup)
 *   E<0-4>     eye mode: 0 off, 1 awake (blinking), 2 listening (pulse),
 *              3 thinking (flicker), 4 talking (steady)
 *   L<0-255>   eyes at a fixed brightness
 *   P          ping, replies PONG
 *   ?          help and current settings
 *
 * Commands are case-insensitive and may contain a space: "B 40" == "b40".
 *
 * >> "User Configuration" is located in settings.h <<
 */
#include <Arduino.h>
#include <Servo.h>
#include <AccelStepper.h>

#include "settings.h"

// ============================================================================
// GLOBAL OBJECTS
// ============================================================================
AccelStepper stepper(AccelStepper::HALF4WIRE, PIN_STEPPER_IN1, PIN_STEPPER_IN3, PIN_STEPPER_IN2, PIN_STEPPER_IN4);
Servo beakServo;

const int NECK_SIDE = NECK_RANGE / 2;

// ============================================================================
// STATE TRACKING
// ============================================================================
enum EyeMode {
  EYES_OFF,
  EYES_AWAKE,
  EYES_LISTENING,
  EYES_THINKING,
  EYES_TALKING,
  EYES_FIXED
};

// Beak
float beakCurrent = 0;              // percent open, smoothed
int beakTarget = 0;                 // percent open, as requested
bool beakRaw = false;               // true while calibrating with U
int lastBeakUs = -1;
unsigned long lastBeakCommand = 0;
unsigned long lastBeakUpdate = 0;

// Neck
bool neckFast = false;
bool neckPowered = true;

// Eyes
EyeMode eyeMode = EYES_AWAKE;
uint8_t eyeFixedLevel = 0;
uint8_t flickerLevel = 0;
unsigned long lastEyeUpdate = 0;
unsigned long nextBlinkTime = 0;
unsigned long blinkEndTime = 0;
unsigned long nextFlickerTime = 0;
bool secondBlinkDue = false;

// Serial input
char commandBuffer[24];
uint8_t commandLength = 0;

// ============================================================================
// SETUP
// ============================================================================
void setup() {
  Serial.begin(115200);
  randomSeed(analogRead(A0));

  pinMode(PIN_LED_EYES, OUTPUT);
  analogWrite(PIN_LED_EYES, EYE_BRIGHTNESS);  // eyes on while starting up

  // Wide limits so U can reach any pulse during calibration;
  // normal beak moves are kept between SERVO_PWM_OPEN and SERVO_PWM_CLOSED.
  beakServo.writeMicroseconds(SERVO_PWM_CLOSED);
  beakServo.attach(PIN_SERVO, 500, 2500);
  lastBeakUs = SERVO_PWM_CLOSED;

  centerNeck();

  nextBlinkTime = millis() + random(BLINK_MIN_INTERVAL_MS, BLINK_MAX_INTERVAL_MS);
  Serial.println(F("READY"));
}

// ============================================================================
// MAIN LOOP
// ============================================================================
void loop() {
  unsigned long now = millis();
  readSerial();
  stepper.run();
  releaseNeckWhenIdle();
  updateBeak(now);
  updateEyes(now);
}

// ============================================================================
// COMMANDS
// ============================================================================

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (commandLength > 0) {
        commandBuffer[commandLength] = '\0';
        handleCommand(commandBuffer);
        commandLength = 0;
      }
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = c;
    }
  }
}

void handleCommand(char* command) {
  char op = toupper(command[0]);
  long value = atol(command + 1);

  switch (op) {
    case 'B':
      beakRaw = false;
      beakTarget = constrain(value, 0, 100);
      lastBeakCommand = millis();
      break;

    case 'U':
      beakRaw = true;
      value = constrain(value, 500, 2500);
      writeBeakUs(value);
      Serial.print(F("Beak pulse "));
      Serial.println(value);
      break;

    case 'N':
      moveNeck(constrain(value, -NECK_SIDE, NECK_SIDE));
      break;

    case 'S':
      setNeckSpeed(value != 0);
      break;

    case 'C':
      centerNeck();
      Serial.println(F("Neck centered"));
      break;

    case 'E':
      setEyeMode((EyeMode)constrain(value, EYES_OFF, EYES_TALKING));
      break;

    case 'L':
      eyeFixedLevel = constrain(value, 0, 255);
      setEyeMode(EYES_FIXED);
      break;

    case 'P':
      Serial.println(F("PONG"));
      break;

    case '?':
      printHelp();
      break;

    default:
      Serial.print(F("Unknown command: "));
      Serial.println(command);
  }
}

void printHelp() {
  Serial.println(F("\n=== Voice Crow ==="));
  Serial.println(F("B<0-100>  beak percent open"));
  Serial.println(F("U<us>     raw beak pulse (calibration)"));
  Serial.println(F("N<pos>    neck position, 0 = center"));
  Serial.println(F("S<0|1>    neck speed slow/fast"));
  Serial.println(F("C         re-center neck"));
  Serial.println(F("E<0-4>    eyes off/awake/listening/thinking/talking"));
  Serial.println(F("L<0-255>  eyes fixed brightness"));
  Serial.println(F("P         ping"));
  Serial.print(F("Beak open/closed: "));
  Serial.print(SERVO_PWM_OPEN);
  Serial.print(F(" / "));
  Serial.println(SERVO_PWM_CLOSED);
  Serial.print(F("Neck range: +/-"));
  Serial.println(NECK_SIDE);
}

// ============================================================================
// BEAK CONTROL
// ============================================================================

void updateBeak(unsigned long now) {
  if (beakRaw || now - lastBeakUpdate < 10) return;
  lastBeakUpdate = now;

  // Close the beak if the laptop goes quiet mid-sentence
  if (beakTarget > 0 && now - lastBeakCommand > BEAK_TIMEOUT_MS) {
    beakTarget = 0;
  }

  beakCurrent += (beakTarget - beakCurrent) * BEAK_SMOOTHING;
  int us = SERVO_PWM_CLOSED + (int)((SERVO_PWM_OPEN - SERVO_PWM_CLOSED) * beakCurrent / 100.0 + 0.5);
  writeBeakUs(us);
}

void writeBeakUs(int us) {
  if (us != lastBeakUs) {
    beakServo.writeMicroseconds(us);
    lastBeakUs = us;
  }
}

// ============================================================================
// NECK CONTROL
// ============================================================================

void setNeckSpeed(bool fast) {
  neckFast = fast;
  if (fast) {
    stepper.setMaxSpeed(NECK_SPEED_FAST_MAX);
    stepper.setAcceleration(NECK_SPEED_FAST_ACCEL);
  } else {
    stepper.setMaxSpeed(NECK_SPEED_SLOW_MAX);
    stepper.setAcceleration(NECK_SPEED_SLOW_ACCEL);
  }
}

void moveNeck(long position) {
  if (!neckPowered) {
    stepper.enableOutputs();
    neckPowered = true;
  }
  stepper.moveTo(position);
}

void releaseNeckWhenIdle() {
#if NECK_RELEASE_WHEN_IDLE
  static unsigned long stoppedAt = 0;
  if (!neckPowered) return;
  if (stepper.distanceToGo() != 0) {
    stoppedAt = 0;
    return;
  }
  // Hold position briefly so the head settles before the coils let go
  if (stoppedAt == 0) stoppedAt = millis();
  if (millis() - stoppedAt >= NECK_RELEASE_DELAY_MS) {
    stepper.disableOutputs();
    neckPowered = false;
    stoppedAt = 0;
  }
#endif
}

// There is no position sensor, so (like the original crow) drive past the
// full range into the end stop, then come back half the range to the center.
void centerNeck() {
  stepper.enableOutputs();
  neckPowered = true;
  bool wasFast = neckFast;
  setNeckSpeed(false);

  stepper.setCurrentPosition(0);
  stepper.runToNewPosition(NECK_RANGE + 100);
  stepper.setCurrentPosition(0);
  stepper.runToNewPosition(-(NECK_SIDE + 50));
  stepper.setCurrentPosition(0);

  setNeckSpeed(wasFast);
}

// ============================================================================
// EYES
// ============================================================================

void setEyeMode(EyeMode mode) {
  eyeMode = mode;
  blinkEndTime = 0;
}

void updateEyes(unsigned long now) {
  if (now - lastEyeUpdate < 10) return;
  lastEyeUpdate = now;

  uint8_t level = 0;
  switch (eyeMode) {
    case EYES_OFF:
      level = 0;
      break;

    case EYES_AWAKE:  // steady with random blinks
      if (now >= nextBlinkTime) {
        blinkEndTime = now + BLINK_DURATION_MS;
        // Now and then follow a blink straight away with a second one
        if (!secondBlinkDue && random(100) < DOUBLE_BLINK_PERCENT) {
          nextBlinkTime = blinkEndTime + 120;
          secondBlinkDue = true;
        } else {
          nextBlinkTime = now + random(BLINK_MIN_INTERVAL_MS, BLINK_MAX_INTERVAL_MS);
          secondBlinkDue = false;
        }
      }
      level = (now < blinkEndTime) ? 0 : EYE_BRIGHTNESS;
      break;

    case EYES_LISTENING: {  // slow breathing pulse
      float phase = (now % EYE_PULSE_PERIOD_MS) / (float)EYE_PULSE_PERIOD_MS;
      float wave = 0.5 - 0.5 * cos(phase * 2 * PI);
      level = EYE_BRIGHTNESS * (0.15 + 0.85 * wave);
      break;
    }

    case EYES_THINKING:  // nervous flicker
      if (now >= nextFlickerTime) {
        flickerLevel = random(EYE_BRIGHTNESS / 8, EYE_BRIGHTNESS + 1);
        nextFlickerTime = now + random(30, 120);
      }
      level = flickerLevel;
      break;

    case EYES_TALKING:
      level = EYE_BRIGHTNESS;
      break;

    case EYES_FIXED:
      level = eyeFixedLevel;
      break;
  }
  analogWrite(PIN_LED_EYES, level);
}
