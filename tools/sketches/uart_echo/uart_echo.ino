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

  See tools/sketches/README.md for compile, upload and verify steps.
*/

// LINK = the MCU UART wired to Linux /dev/ttyHS1 (LPUART1).
//   core arduino:zephyr 0.55.0 .. 1.0.0 (0.55.2 is on the board): Serial2
//   core 0.51 .. 0.54:                                             Serial1
// Serial1 on current cores is USART1 on D0/D1 (Zephyr console and boot banner).
#ifndef LINK
#define LINK Serial2
#endif

static const size_t MAX_LINE = 128;   // longer lines are cut here, the rest is dropped
static char g_line[MAX_LINE + 1];
static size_t g_len = 0;

void setup() {
  LINK.begin(115200);
}

void loop() {
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
      }
    } else if (g_len < MAX_LINE) {
      g_line[g_len++] = (char)c;
    }
  }
}
