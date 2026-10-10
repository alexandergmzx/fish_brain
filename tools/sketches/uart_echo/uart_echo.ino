/*
  uart_echo - raw UART echo for the UNO Q link (Linux /dev/ttyHS1 <-> STM32 LPUART1).

  Every line received on the link is answered with "ACK <line>". This is the MCU half of
  `tools/uart_check.py` (serial transport): it proves the wire, the baud rate and the
  line rate before the real firmware is ported.

  Rules for this sketch:
  - Use only LINK. Never touch `Serial`, `Monitor` or `Bridge` here: on this core
    `Serial` is the router Monitor, a blocking RPC with no timeout, and it hangs the
    sketch when nothing answers on the other side.
  - Build with the default FQBN `arduino:zephyr:unoq` ("Wait for Linux").
  - On the Linux side the arduino-router daemon owns /dev/ttyHS1. Release it first
    (`uart_check.py --release-router`, or `arduino-router-cli '$/serial/close' /dev/ttyHS1`).

  What you see on the board (the MCU's RGB LED, LED3):
  - blue blinks once a second: the sketch is running;
  - green changes state on every line received: the link carries data. At 33 lines per
    second it looks dimly lit; a single `echo PING > /dev/ttyHS1` flips it once.

  See tools/sketches/README.md for compile, upload and verify steps.
*/

// LINK = the MCU UART wired to Linux /dev/ttyHS1 (LPUART1).
//   core arduino:zephyr 0.55.0 .. 1.0.0 (0.55.2 is on the board): Serial2
//   core 0.51 .. 0.54:                                             Serial1
// Serial1 on current cores is USART1 on D0/D1 (Zephyr console and boot banner).
#ifndef LINK
#define LINK Serial2
#endif

// LED3 is wired active-low: LOW lights it.
static const int LED_ON = LOW;
static const int LED_OFF = HIGH;
static bool g_green = false;
static bool g_blue = false;
static unsigned long g_beat_ms = 0;

static const size_t MAX_LINE = 128;   // longer lines are cut here, the rest is dropped
static char g_line[MAX_LINE + 1];
static size_t g_len = 0;

void setup() {
  pinMode(LED3_R, OUTPUT);
  pinMode(LED3_G, OUTPUT);
  pinMode(LED3_B, OUTPUT);
  digitalWrite(LED3_R, LED_OFF);
  digitalWrite(LED3_G, LED_OFF);
  digitalWrite(LED3_B, LED_OFF);
  LINK.begin(115200);
}

void loop() {
  unsigned long now = millis();
  if (now - g_beat_ms >= 500) {       // heartbeat: on 0.5 s, off 0.5 s
    g_beat_ms = now;
    g_blue = !g_blue;
    digitalWrite(LED3_B, g_blue ? LED_ON : LED_OFF);
  }
  while (LINK.available() > 0) {
    int c = LINK.read();
    if (c < 0) {
      break;
    }
    if (c == '\n' || c == '\r') {     // either one ends a line, like the real firmware
      if (g_len > 0) {
        g_line[g_len] = '\0';
        LINK.print("ACK ");
        LINK.println(g_line);
        g_len = 0;
        g_green = !g_green;
        digitalWrite(LED3_G, g_green ? LED_ON : LED_OFF);
      }
    } else if (g_len < MAX_LINE) {
      g_line[g_len++] = (char)c;
    }
  }
}
