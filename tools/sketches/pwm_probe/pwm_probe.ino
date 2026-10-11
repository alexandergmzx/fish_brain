/*
  pwm_probe - what the UNO Q's header pins, timers and LEDs really do (core arduino:zephyr).

  It answers, before the fish firmware is trusted on this board:
  - in which state the nine motor pins are when a sketch starts;
  - whether analogWrite alone gives PWM on D6, D3 and D5, at which duty and frequency;
  - whether PWM and the direction pins disturb each other (TIM1 is shared by D5 with
    D11/D12/D13, TIM3 by D3/D6 with D8);
  - how long analogWrite, digitalRead and a matrix redraw take, and how late a PWM edge is;
  - how the LED matrix is oriented and how LED3 and LED4 are wired.

  The report goes out on the link (Serial2 <-> Linux /dev/ttyHS1, 115200). Every line starts
  with "PP ", the report starts again every 20 s, and its last line is
  "PP END ok=<n> fail=<n>". Read it with the router's hold on the port released.

  Rules for this sketch:
  - Use only LINK. Never touch `Serial`, `Monitor` or `Bridge` (see uart_echo.ino).
  - Arduino calls only. The one exception is reading GPIO registers through
    portInputRegister(); build with -DPP_REGISTERS=0 to leave that out, then pins are
    sampled with digitalRead and section A prints no mode bits.
  - Nothing is wired to D2..D13 while it runs: it drives the motor pins as outputs.

  Sections (the tag after "PP "):
    ENTRY   A  the nine motor pins as the loader left them, read before any pinMode
    DIG     B  each direction pin written and read back; the others must not move
    PWM     C  analogWrite alone on D6, D3, D5 at eight values: duty and frequency
    SIM     E  the three together, then D6 back to 0 (D3 and D6 share a timer)
    ILV        direction pins against running PWM, both ways
    EDGE       time from analogWrite to the pin following, 100 times per pin
    PWM     C  mode=aw_other: the same at one value on D2, D7..D13 (a spare is then known)
    PWM     D  mode=pinmode_aw: pinMode(OUTPUT) before analogWrite, on the spares D9, D10
    COST    F  analogWrite, digitalRead, digitalWrite in microseconds
    MATRIX  G  redraw cost, then a picture that stays: row 0 bright, column 0 half
               bright, a grey ramp 0..7 at the right end of row 7
    LED3    H  duty read back per colour, then red, green, blue fade up one after another
    LED4    I  red, green, blue, each driven LOW in turn
    CLOCK   J K  loop passes per second; millis against micros; micros wrap
    TXROOM  L  Serial2.availableForWrite() with nothing queued

  See tools/sketches/README.md for compile, upload and verify steps.
*/

#include "Arduino_LED_Matrix.h"

// LINK = the MCU UART wired to Linux /dev/ttyHS1 (core 0.55.0 .. 1.0.0: Serial2).
#ifndef LINK
#define LINK Serial2
#endif

#ifndef PP_REGISTERS
#define PP_REGISTERS 1
#endif

static const unsigned long REPORT_PERIOD_MS = 20000;
static const float DUTY_TOLERANCE = 1.5f;   // percentage points

// The fish's pin map (Big_mouth include/Config.h): IN1, IN2, ENA per motor.
static const uint8_t ALL_PINS[9] = {12, 11, 6, 2, 4, 3, 7, 8, 5};
static const uint8_t DIR_PINS[6] = {12, 11, 2, 4, 7, 8};
static const uint8_t ENA_PINS[3] = {6, 3, 5};
static const uint8_t OTHER_PWM_PINS[8] = {2, 7, 8, 9, 10, 11, 12, 13};
static const uint8_t SPARE_PWM_PINS[2] = {9, 10};
static const uint8_t PWM_VALUES[8] = {0, 1, 64, 128, 200, 238, 254, 255};

// The types come before the first function: the sketch preprocessor puts its generated
// prototypes there, and they name these.
struct FastPin {            // one pin, ready for fast sampling
  uint8_t pin;
  volatile uint32_t* idr;
  uint32_t mask;
};

struct Meas {               // one sampling window
  unsigned long n;       // samples
  unsigned long high;    // samples that read high
  unsigned long rises;
  unsigned long us;      // length of the window
};

struct Entry {              // section A: one pin as found at start
  unsigned long reg;     // address of the input register
  unsigned long mask;
  uint8_t mode;          // 0 input, 1 output, 2 alternate function, 3 analog
  uint8_t af;
  uint8_t pull;          // 0 none, 1 up, 2 down
  uint8_t level;
  char cls;              // f float, h held high, l held low, ? neither
};

static Arduino_LED_Matrix matrix;
static uint8_t g_frame[104];
static unsigned long g_matrix_begin_us = 0;

static unsigned long g_report = 0;
static unsigned long g_ok = 0;
static unsigned long g_fail = 0;
static bool g_use_reg = false;   // sample pins through the input register

// micros() with wrap bookkeeping: the wrap period is one of the questions.
static unsigned long g_last_us = 0;
static unsigned long g_wraps = 0;
static unsigned long g_wrap_at_ms = 0;
static unsigned long g_wrap_period_ms = 0;
static unsigned long g_before_wrap_us = 0;

static unsigned long nowUs() {
  unsigned long t = micros();
  if (t < g_last_us) {
    unsigned long ms = millis();
    if (g_wraps > 0) {
      g_wrap_period_ms = ms - g_wrap_at_ms;
    }
    g_wrap_at_ms = ms;
    g_before_wrap_us = g_last_us;
    g_wraps++;
  }
  g_last_us = t;
  return t;
}

// ---- output: "PP <tag> key=value ..." ---------------------------------------------------
static void ppTag(const char* name) {
  LINK.print("PP ");
  LINK.print(name);
}

static void pinTag(const char* name, uint8_t pin) {
  ppTag(name);
  LINK.print(" D");
  LINK.print(pin);
}

static void kv(const char* key, long value) {
  LINK.print(' ');
  LINK.print(key);
  LINK.print('=');
  LINK.print(value);
}

static void kvu(const char* key, unsigned long value) {
  LINK.print(' ');
  LINK.print(key);
  LINK.print('=');
  LINK.print(value);
}

static void kvf(const char* key, float value) {
  LINK.print(' ');
  LINK.print(key);
  LINK.print('=');
  LINK.print(value, 1);
}

static void kvs(const char* key, const char* value) {
  LINK.print(' ');
  LINK.print(key);
  LINK.print('=');
  LINK.print(value);
}

static void kvx(const char* key, unsigned long value) {
  LINK.print(' ');
  LINK.print(key);
  LINK.print("=0x");
  LINK.print(value, HEX);
}

// Counts a pass or a fail and prints " <key>=ok" or " <key>=FAIL".
static bool verdict(const char* key, bool good) {
  if (good) {
    g_ok++;
  } else {
    g_fail++;
  }
  kvs(key, good ? "ok" : "FAIL");
  return good;
}

static void ppEnd() {
  LINK.println();
}

// ---- pin sampling -----------------------------------------------------------------------
static FastPin fastPin(uint8_t pin) {
  FastPin p;
  p.pin = pin;
  p.idr = nullptr;
  p.mask = 0;
#if PP_REGISTERS
  p.idr = (volatile uint32_t*)(uintptr_t)portInputRegister(pin);
  p.mask = (uint32_t)digitalPinToBitMask(pin);
#endif
  return p;
}

static inline bool readFast(const FastPin& p) {
#if PP_REGISTERS
  if (g_use_reg) {
    return (*p.idr & p.mask) != 0;
  }
#endif
  return digitalRead(p.pin) == HIGH;
}

// Sample `pin` as fast as possible for windowMs. With togglePin >= 0 that pin is flipped
// every 256 samples while sampling, and left as it was found.
static Meas measure(uint8_t pin, unsigned long windowMs, int togglePin) {
  FastPin p = fastPin(pin);
  Meas m = {0, 0, 0, 0};
  bool toggleStart = togglePin >= 0 ? (digitalRead(togglePin) == HIGH) : false;
  bool toggle = toggleStart;
  unsigned long windowUs = windowMs * 1000UL;
  unsigned long ms0 = millis();
  unsigned long t0 = nowUs();
  bool last = readFast(p);
  for (;;) {
    bool v = readFast(p);
    m.n++;
    if (v) {
      m.high++;
      if (!last) {
        m.rises++;
      }
    }
    last = v;
    if ((m.n & 0x3F) == 0) {
      // millis() is the second guard, in case micros() wraps inside the window.
      if ((unsigned long)(micros() - t0) >= windowUs || millis() - ms0 > windowMs + 5) {
        break;
      }
      if (togglePin >= 0 && (m.n & 0xFF) == 0) {
        toggle = !toggle;
        digitalWrite(togglePin, toggle ? HIGH : LOW);
      }
    }
  }
  m.us = nowUs() - t0;
  if (togglePin >= 0) {
    digitalWrite(togglePin, toggleStart ? HIGH : LOW);
  }
  return m;
}

static float dutyOf(const Meas& m) {
  return m.n ? (100.0f * (float)m.high) / (float)m.n : 0.0f;
}

static float hzOf(const Meas& m) {
  return m.us ? ((float)m.rises * 1000000.0f) / (float)m.us : 0.0f;
}

static float dutyWanted(int value) {
  return (100.0f * (float)value) / 255.0f;
}

static bool dutyClose(float got, float wanted) {
  float d = got - wanted;
  if (d < 0) {
    d = -d;
  }
  return d <= DUTY_TOLERANCE;
}

static void printMeas(const Meas& m) {
  kvf("duty", dutyOf(m));
  kvf("f", hzOf(m));
  kvu("edges", m.rises);
  kvu("n", m.n);
}

// How many reads of the pin within windowMs differ from `want`.
static unsigned long mismatches(uint8_t pin, bool want, unsigned long windowMs) {
  Meas m = measure(pin, windowMs, -1);
  return want ? (m.n - m.high) : m.high;
}

static void motorPinsToRest() {
  for (uint8_t i = 0; i < 3; i++) {
    analogWrite(ENA_PINS[i], 0);
  }
  for (uint8_t i = 0; i < 6; i++) {
    pinMode(DIR_PINS[i], OUTPUT);
    digitalWrite(DIR_PINS[i], LOW);
  }
}

// ---- A: state at entry ------------------------------------------------------------------
static Entry g_entry[9];
static bool g_reg_agrees = true;

// Called first thing in setup(), before any pinMode.
static void captureEntry() {
  for (uint8_t i = 0; i < 9; i++) {
    uint8_t pin = ALL_PINS[i];
    Entry& e = g_entry[i];
    e.reg = 0;
    e.mask = 0;
    e.mode = 0xFF;
    e.af = 0xFF;
    e.pull = 0xFF;
    e.cls = '?';
#if PP_REGISTERS
    // STM32 GPIO block: MODER +0x00, PUPDR +0x0C, IDR +0x10, AFRL +0x20, AFRH +0x24.
    volatile uint32_t* idr = (volatile uint32_t*)(uintptr_t)portInputRegister(pin);
    uint32_t mask = (uint32_t)digitalPinToBitMask(pin);
    uint8_t bit = 0;
    while (bit < 15 && !(mask & (1UL << bit))) {
      bit++;
    }
    e.reg = (unsigned long)(uintptr_t)idr;
    e.mask = mask;
    e.mode = (uint8_t)((idr[-4] >> (2 * bit)) & 3);
    e.pull = (uint8_t)((idr[-1] >> (2 * bit)) & 3);
    e.af = (uint8_t)(bit < 8 ? (idr[4] >> (4 * bit)) & 15 : (idr[5] >> (4 * (bit - 8))) & 15);
    e.level = (*idr & mask) ? 1 : 0;
#else
    e.level = digitalRead(pin) == HIGH ? 1 : 0;
#endif
  }
  // Driven from outside or floating: a floating pin follows the pull.
  for (uint8_t i = 0; i < 9; i++) {
    uint8_t pin = ALL_PINS[i];
    FastPin p = fastPin(pin);
    pinMode(pin, INPUT_PULLUP);
    delay(2);
    bool up = digitalRead(pin) == HIGH;
#if PP_REGISTERS
    if (((*p.idr & p.mask) != 0) != up) {
      g_reg_agrees = false;
    }
#endif
    pinMode(pin, INPUT_PULLDOWN);
    delay(2);
    bool down = digitalRead(pin) == HIGH;
#if PP_REGISTERS
    if (((*p.idr & p.mask) != 0) != down) {
      g_reg_agrees = false;
    }
#else
    (void)p;
#endif
    g_entry[i].cls = (up && !down) ? 'f' : (up && down) ? 'h' : (!up && !down) ? 'l' : '?';
  }
#if PP_REGISTERS
  g_use_reg = g_reg_agrees;
#endif
}

static void sectionEntry() {
  static const char* const MODES[4] = {"in", "out", "AF", "analog"};
  for (uint8_t i = 0; i < 9; i++) {
    const Entry& e = g_entry[i];
    pinTag("ENTRY", ALL_PINS[i]);
    if (e.mode <= 3) {
      kvx("reg", e.reg);
      kvx("mask", e.mask);
      kvs("mode", MODES[e.mode]);
      kv("af", e.af);
      kv("pull", e.pull);
    }
    kv("idr", e.level);
    kvs("class", e.cls == 'f' ? "float" : e.cls == 'h' ? "high" : e.cls == 'l' ? "low" : "odd");
    // An enable pin that starts high would run a motor before setup().
    bool ena = (i % 3) == 2;
    if (ena) {
      verdict("safe", e.cls != 'h' && !(e.mode == 1 && e.level == 1));
    }
    ppEnd();
  }
  ppTag("ENTRY");
  kvs("sampling", g_use_reg ? "register" : "digitalRead");
#if PP_REGISTERS
  verdict("register_agrees_with_digitalRead", g_reg_agrees);
#endif
  ppEnd();
}

// ---- B: digital write and read back -----------------------------------------------------
static void sectionDigital() {
  for (uint8_t i = 0; i < 3; i++) {
    pinMode(ENA_PINS[i], INPUT_PULLDOWN);   // quiet inputs while the others are checked
  }
  for (uint8_t i = 0; i < 6; i++) {
    pinMode(DIR_PINS[i], OUTPUT);
    digitalWrite(DIR_PINS[i], LOW);
  }
  for (uint8_t i = 0; i < 6; i++) {
    uint8_t pin = DIR_PINS[i];
    uint16_t before = 0, after1 = 0, after0 = 0;
    for (uint8_t k = 0; k < 9; k++) {
      if (ALL_PINS[k] != pin && digitalRead(ALL_PINS[k]) == HIGH) before |= (uint16_t)(1u << k);
    }
    digitalWrite(pin, HIGH);
    delayMicroseconds(200);
    int w1 = digitalRead(pin) == HIGH ? 1 : 0;
    for (uint8_t k = 0; k < 9; k++) {
      if (ALL_PINS[k] != pin && digitalRead(ALL_PINS[k]) == HIGH) after1 |= (uint16_t)(1u << k);
    }
    digitalWrite(pin, LOW);
    delayMicroseconds(200);
    int w0 = digitalRead(pin) == HIGH ? 1 : 0;
    for (uint8_t k = 0; k < 9; k++) {
      if (ALL_PINS[k] != pin && digitalRead(ALL_PINS[k]) == HIGH) after0 |= (uint16_t)(1u << k);
    }
    pinTag("DIG", pin);
    kv("w1", w1);
    kv("w0", w0);
    verdict("readback", w1 == 1 && w0 == 0);
    verdict("others", before == after1 && before == after0);
    ppEnd();
  }
}

// ---- C: PWM from analogWrite alone ------------------------------------------------------
static void sectionPwm() {
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = ENA_PINS[i];
    for (uint8_t k = 0; k < 8; k++) {
      int v = PWM_VALUES[k];
      analogWrite(pin, v);
      delay(5);
      Meas m = measure(pin, 100, -1);
      pinTag("PWM", pin);
      kv("v", v);
      kvs("mode", "aw");
      printMeas(m);
      if (v == 0) {
        verdict("duty_ok", m.high == 0);
      } else if (v == 255) {
        verdict("duty_ok", dutyOf(m) >= 99.5f);
      } else {
        verdict("duty_ok", dutyClose(dutyOf(m), dutyWanted(v)));
      }
      ppEnd();
    }
    analogWrite(pin, 0);
  }
}

// ---- E: the three enables together ------------------------------------------------------
static void sectionTogether() {
  static const int V[3] = {238, 128, 64};   // D6, D3, D5
  for (uint8_t i = 0; i < 3; i++) {
    analogWrite(ENA_PINS[i], V[i]);
  }
  delay(5);
  float d[3];
  bool good = true;
  for (uint8_t i = 0; i < 3; i++) {
    d[i] = dutyOf(measure(ENA_PINS[i], 100, -1));
    good = good && dutyClose(d[i], dutyWanted(V[i]));
  }
  ppTag("SIM");
  kvf("D6", d[0]);
  kvf("D3", d[1]);
  kvf("D5", d[2]);
  verdict("duty_ok", good);
  ppEnd();

  analogWrite(ENA_PINS[0], 0);   // D6 off: D3 is on the same timer
  delay(5);
  float d3 = dutyOf(measure(ENA_PINS[1], 100, -1));
  unsigned long d6high = measure(ENA_PINS[0], 20, -1).high;
  float moved = d3 - d[1];
  if (moved < 0) {
    moved = -moved;
  }
  ppTag("SIM");
  kvs("after", "D6=0");
  kvf("D3", d3);
  kvu("D6_high_samples", d6high);
  verdict("D3_unmoved", moved < 1.0f && d6high == 0);
  ppEnd();
  for (uint8_t i = 0; i < 3; i++) {
    analogWrite(ENA_PINS[i], 0);
  }
}

// ---- direction pins against running PWM -------------------------------------------------
static void sectionInterleaved() {
  static const int V[3] = {200, 128, 64};   // D6, D3, D5
  for (uint8_t pass = 0; pass < 2; pass++) {
    // Pattern 101010 on D12 D11 D2 D4 D7 D8, then its inverse.
    bool want[6];
    for (uint8_t i = 0; i < 3; i++) {
      analogWrite(ENA_PINS[i], 0);
    }
    for (uint8_t i = 0; i < 6; i++) {
      want[i] = ((i % 2) == 0) != (pass == 1);
      pinMode(DIR_PINS[i], OUTPUT);
      digitalWrite(DIR_PINS[i], want[i] ? HIGH : LOW);
    }
    // 1. Starting PWM must leave the direction pins alone.
    for (uint8_t i = 0; i < 3; i++) {
      analogWrite(ENA_PINS[i], V[i]);
    }
    delay(5);
    unsigned long wrong = 0;
    for (uint8_t i = 0; i < 6; i++) {
      wrong += mismatches(DIR_PINS[i], want[i], 10);
    }
    float base[3];
    bool baseGood = true;
    for (uint8_t i = 0; i < 3; i++) {
      base[i] = dutyOf(measure(ENA_PINS[i], 60, -1));
      baseGood = baseGood && dutyClose(base[i], dutyWanted(V[i]));
    }
    ppTag("ILV");
    kv("pass", pass);
    kvs("step", "pwm_start");
    kvu("dir_wrong_samples", wrong);
    verdict("dir_kept", wrong == 0);
    kvf("D6", base[0]);
    kvf("D3", base[1]);
    kvf("D5", base[2]);
    verdict("duty_ok", baseGood);
    ppEnd();

    // 2. Writing a direction pin must leave the PWM alone, and must still work.
    for (uint8_t i = 0; i < 6; i++) {
      uint8_t pin = DIR_PINS[i];
      float worst = 0;
      for (uint8_t k = 0; k < 3; k++) {
        float d = dutyOf(measure(ENA_PINS[k], 40, pin)) - base[k];   // pin flips while sampling
        if (d < 0) {
          d = -d;
        }
        if (d > worst) {
          worst = d;
        }
      }
      digitalWrite(pin, want[i] ? LOW : HIGH);
      delayMicroseconds(200);
      unsigned long flipped = mismatches(pin, !want[i], 5);
      digitalWrite(pin, want[i] ? HIGH : LOW);
      delayMicroseconds(200);
      unsigned long back = mismatches(pin, want[i], 5);
      pinTag("ILV", pin);
      kv("pass", pass);
      kvs("step", "dir_toggle");
      kvf("worst_duty_shift", worst);
      verdict("pwm_kept", worst <= DUTY_TOLERANCE);
      kvu("wrong_samples", flipped + back);
      verdict("dir_follows", flipped == 0 && back == 0);
      ppEnd();
    }
  }
  motorPinsToRest();
}

// ---- time from analogWrite to the pin ---------------------------------------------------
static void sectionEdge() {
  static const int V = 238;                  // the mouth's open PWM
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t pin = ENA_PINS[i];
    FastPin p = fastPin(pin);
    unsigned long riseMin = 0xFFFFFFFFUL, riseMax = 0, riseSum = 0;
    unsigned long fallMin = 0xFFFFFFFFUL, fallMax = 0, fallSum = 0;
    unsigned long timeouts = 0, counted = 0;
    for (uint8_t k = 0; k < 100; k++) {
      analogWrite(pin, 0);
      delayMicroseconds(700 + (unsigned int)((k * 37) % 1900));   // move across the PWM period
      // Rising: 0 -> V, the first high sample.
      unsigned long t0 = micros();
      analogWrite(pin, V);
      unsigned long rise = 0;
      bool seen = false;
      for (;;) {
        bool v = readFast(p);
        unsigned long t = micros() - t0;
        if (v) {
          rise = t;
          seen = true;
          break;
        }
        if (t > 5000) {
          break;
        }
      }
      delayMicroseconds(1000 + (unsigned int)((k * 53) % 1900));
      // Falling: V -> 0, the last high sample within 3 ms of the call.
      t0 = micros();
      analogWrite(pin, 0);
      unsigned long fall = 0;
      for (;;) {
        bool v = readFast(p);
        unsigned long t = micros() - t0;
        if (v) {
          fall = t;
        }
        if (t > 3000) {
          break;
        }
      }
      if (!seen || fall > 2900) {
        timeouts++;
        continue;
      }
      counted++;
      riseSum += rise;
      fallSum += fall;
      if (rise < riseMin) riseMin = rise;
      if (rise > riseMax) riseMax = rise;
      if (fall < fallMin) fallMin = fall;
      if (fall > fallMax) fallMax = fall;
    }
    nowUs();
    pinTag("EDGE", pin);
    kv("v", V);
    kvu("n", counted);
    if (counted > 0) {
      kvu("rise_us_min", riseMin);
      kvu("rise_us_avg", riseSum / counted);
      kvu("rise_us_max", riseMax);
      kvu("fall_us_min", fallMin);
      kvu("fall_us_avg", fallSum / counted);
      kvu("fall_us_max", fallMax);
    }
    kvu("timeouts", timeouts);
    verdict("edges_seen", timeouts == 0);
    ppEnd();
    analogWrite(pin, 0);
  }
}

// ---- C on the other PWM-capable pins, D on the spares -----------------------------------
static void sectionOtherPins() {
  for (uint8_t i = 0; i < 8; i++) {
    uint8_t pin = OTHER_PWM_PINS[i];
    analogWrite(pin, 128);
    delay(5);
    Meas m = measure(pin, 60, -1);
    analogWrite(pin, 0);
    pinTag("PWM", pin);
    kv("v", 128);
    kvs("mode", "aw_other");
    printMeas(m);
    kvs("pwm", dutyClose(dutyOf(m), dutyWanted(128)) ? "yes" : "no");
    // Direction pins must come back as plain outputs.
    bool isDir = false;
    for (uint8_t k = 0; k < 6; k++) {
      isDir = isDir || DIR_PINS[k] == pin;
    }
    if (isDir) {
      pinMode(pin, OUTPUT);
      digitalWrite(pin, HIGH);
      delayMicroseconds(200);
      unsigned long bad = mismatches(pin, true, 5);
      digitalWrite(pin, LOW);
      delayMicroseconds(200);
      bad += mismatches(pin, false, 5);
      verdict("output_again", bad == 0);
    }
    ppEnd();
  }
  // D: the forum report says pinMode(OUTPUT) before analogWrite kills the PWM. Tried on the
  // spare pins so the fish's enables are not left in that state for the next round.
  for (uint8_t i = 0; i < 2; i++) {
    uint8_t pin = SPARE_PWM_PINS[i];
    pinMode(pin, OUTPUT);
    analogWrite(pin, 128);
    delay(5);
    Meas m = measure(pin, 60, -1);
    analogWrite(pin, 0);
    pinTag("PWM", pin);
    kv("v", 128);
    kvs("mode", "pinmode_aw");
    printMeas(m);
    kvs("result", dutyClose(dutyOf(m), dutyWanted(128)) ? "OK" : "BROKEN");
    ppEnd();
  }
}

// ---- F: what the calls cost -------------------------------------------------------------
static void costLine(const char* what, unsigned long lo, unsigned long sum, unsigned long hi,
                     unsigned long n) {
  ppTag("COST");
  kvs("call", what);
  kvu("us_min", lo);
  kvu("us_avg", sum / n);
  kvu("us_max", hi);
  kvu("n", n);
}

static void sectionCost() {
  unsigned long lo, hi, sum;

  lo = 0xFFFFFFFFUL; hi = 0; sum = 0;
  for (uint8_t k = 0; k < 100; k++) {
    unsigned long t0 = micros();
    analogWrite(ENA_PINS[0], 100 + (k & 1));
    unsigned long t = micros() - t0;
    if (t > 1000000UL) { k--; continue; }   // micros() wrapped: take it again
    sum += t;
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  analogWrite(ENA_PINS[0], 0);
  costLine("analogWrite", lo, sum, hi, 100);
  verdict("under_500us", hi <= 500);
  ppEnd();

  lo = 0xFFFFFFFFUL; hi = 0; sum = 0;
  for (uint8_t k = 0; k < 100; k++) {
    unsigned long t0 = micros();
    (void)digitalRead(DIR_PINS[0]);
    unsigned long t = micros() - t0;
    if (t > 1000000UL) { k--; continue; }
    sum += t;
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  costLine("digitalRead", lo, sum, hi, 100);
  ppEnd();

  lo = 0xFFFFFFFFUL; hi = 0; sum = 0;
  for (uint8_t k = 0; k < 100; k++) {
    unsigned long t0 = micros();
    digitalWrite(DIR_PINS[0], (k & 1) ? HIGH : LOW);
    unsigned long t = micros() - t0;
    if (t > 1000000UL) { k--; continue; }
    sum += t;
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  digitalWrite(DIR_PINS[0], LOW);
  costLine("digitalWrite", lo, sum, hi, 100);
  ppEnd();
  nowUs();
}

// ---- G: LED matrix ----------------------------------------------------------------------
static void orientationPicture() {
  for (uint8_t i = 0; i < 104; i++) {
    g_frame[i] = 0;
  }
  for (uint8_t c = 0; c < 13; c++) {
    g_frame[c] = 7;                     // row 0: bright
  }
  for (uint8_t r = 1; r < 8; r++) {
    g_frame[r * 13] = 3;                // column 0: half
  }
  for (uint8_t g = 0; g < 8; g++) {
    g_frame[7 * 13 + 5 + g] = g;        // row 7, columns 5..12: grey 0..7
  }
}

static void sectionMatrix() {
  unsigned long lo = 0xFFFFFFFFUL, hi = 0, sum = 0;
  orientationPicture();
  for (uint8_t k = 0; k < 20; k++) {
    g_frame[4 * 13 + 6] = (k & 1) ? 7 : 0;   // one pixel changes, so every draw is a new picture
    unsigned long t0 = micros();
    matrix.draw(g_frame);
    unsigned long t = micros() - t0;
    if (t > 1000000UL) { k--; continue; }
    sum += t;
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  orientationPicture();
  matrix.draw(g_frame);   // stays until the next round
  ppTag("MATRIX");
  kvu("begin_us", g_matrix_begin_us);
  kvu("draw_us_min", lo);
  kvu("draw_us_avg", sum / 20);
  kvu("draw_us_max", hi);
  verdict("under_1000us", hi <= 1000);
  ppEnd();
  ppTag("MATRIX");
  kvs("picture", "row0=bright col0=half row7_cols5..12=grey0..7");
  kvs("owner", "where_is_the_bright_row_seen_from_the_USB-C_side");
  ppEnd();
  nowUs();
}

// ---- H: LED3 (PWM) ----------------------------------------------------------------------
static void sectionLed3() {
  static const int PINS[3] = {LED3_R, LED3_G, LED3_B};
  static const char* const NAMES[3] = {"R", "G", "B"};
  static const int V[3] = {64, 128, 255};
  for (uint8_t i = 0; i < 3; i++) {
    ppTag("LED3");
    kvs("colour", NAMES[i]);
    for (uint8_t k = 0; k < 3; k++) {
      analogWrite(PINS[i], V[k]);
      delay(3);
      Meas m = measure(PINS[i], 40, -1);
      LINK.print(" high_at_");
      LINK.print(V[k]);
      LINK.print('=');
      LINK.print(dutyOf(m), 1);
      if (k == 1) {
        kvf("f", hzOf(m));
      }
    }
    kvs("owner", "fades_up_now");
    ppEnd();
    LINK.flush();
    for (int v = 0; v <= 255; v += 5) {   // about 0.6 s
      analogWrite(PINS[i], v);
      delay(12);
    }
    analogWrite(PINS[i], 0);
  }
  ppTag("LED3");
  kvs("left_at", "analogWrite_0");
  kvs("owner", "is_LED3_dark_now");
  ppEnd();
  nowUs();
}

// ---- I: LED4 (digital) ------------------------------------------------------------------
static void sectionLed4() {
  static const int PINS[3] = {LED4_R, LED4_G, LED4_B};
  static const char* const NAMES[3] = {"R", "G", "B"};
  for (uint8_t i = 0; i < 3; i++) {
    pinMode(PINS[i], OUTPUT);
    digitalWrite(PINS[i], HIGH);
  }
  for (uint8_t i = 0; i < 3; i++) {
    ppTag("LED4");
    kvs("colour", NAMES[i]);
    kvs("level", "LOW_for_0.7s");
    kvs("owner", "does_it_light");
    ppEnd();
    LINK.flush();
    digitalWrite(PINS[i], LOW);
    delay(700);
    digitalWrite(PINS[i], HIGH);
    nowUs();
  }
}

// ---- J, K: loop rate and clocks; L: transmit room ---------------------------------------
static void sectionClock() {
  unsigned long ms0 = millis();
  while (millis() == ms0) {
  }
  ms0 = millis();
  unsigned long us0 = micros();
  unsigned long passes = 0;
  while (millis() - ms0 < 1000) {
    passes++;
  }
  unsigned long us1 = micros();
  ppTag("CLOCK");
  kvu("empty_loop_passes_per_s", passes);
  if (us1 >= us0) {
    long diff = (long)(us1 - us0) - 1000000L;
    kv("micros_minus_millis_us", diff);
    verdict("agree_1ms", diff > -1000 && diff < 1000);
  } else {
    kvs("micros", "wrapped_in_this_second");
  }
  ppEnd();
  nowUs();
  ppTag("CLOCK");
  kvu("micros_now", micros());
  kvu("millis_now", millis());
  kvu("micros_wraps_seen", g_wraps);
  if (g_wraps > 0) {
    kvu("last_value_before_wrap", g_before_wrap_us);
  }
  if (g_wraps > 1) {
    kvu("wrap_period_ms", g_wrap_period_ms);
  }
  ppEnd();

  LINK.flush();
  delay(20);
  ppTag("TXROOM");
  kv("availableForWrite_idle", LINK.availableForWrite());
  ppEnd();
}

// ---- report -----------------------------------------------------------------------------
static void report() {
  g_report++;
  g_ok = 0;
  g_fail = 0;
  ppTag("BEGIN");
  kvu("report", g_report);
  kvu("ms", millis());
  kv("registers", PP_REGISTERS);
  ppEnd();

  sectionEntry();
  sectionDigital();
  sectionPwm();
  sectionTogether();
  sectionInterleaved();
  sectionEdge();
  sectionOtherPins();
  motorPinsToRest();
  sectionCost();
  sectionMatrix();
  sectionLed3();
  sectionLed4();
  sectionClock();
  motorPinsToRest();

  ppTag("END");
  kvu("ok", g_ok);
  kvu("fail", g_fail);
  ppEnd();
}

void setup() {
  captureEntry();          // before anything else touches a pin
  motorPinsToRest();
  LINK.begin(115200);
  unsigned long t0 = micros();
  matrix.begin();
  matrix.setGrayscaleBits(3);
  g_matrix_begin_us = micros() - t0;
  orientationPicture();
  matrix.draw(g_frame);
}

void loop() {
  unsigned long start = millis();
  report();
  while (millis() - start < REPORT_PERIOD_MS) {
    nowUs();                  // keep watching for a micros() wrap
    delay(1);
  }
}
