/*
  bridge_echo - Bridge RPC echo for the UNO Q (Linux arduino-router <-> STM32).

  Provides two methods through the router:
    fish_cmd(String line)  each line is answered with "ACK <line>" on the Monitor
                           (router TCP port 127.0.0.1:7500 on the Linux side)
    fish_ping() -> 1       health check; a call fails with router error 2 when this
                           sketch is not running or not registered

  This is the MCU half of `tools/uart_check.py --transport bridge` and of fish_brain's
  bridge transport (FISH_SERIAL_TRANSPORT=bridge).

  Build with the default FQBN `arduino:zephyr:unoq` ("Wait for Linux"), never with
  `wait_linux_boot=no`. `Bridge.begin()` sends `$/reset` to the router and waits for the
  answer with no timeout. In the default mode the loader holds the sketch until the
  router is up (it raises GPIO line 70), and every router stop resets the MCU, so
  `begin()` only ever runs against a listening router. An "Immediate" build calls it a
  few milliseconds after power-up, into a UART nobody reads yet, and blocks forever.
  For the same reason: if the router has released the port (`$/serial/close`), re-attach
  it (`$/serial/open`) and then reset the MCU.

  Rules for this sketch:
  - No second hardware UART: do not call `Serial1.begin()` / `Serial2.begin()`. The
    Bridge already owns the link UART.
  - Thread helpers: only `k_sched_current_thread_query()` and `k_thread_name_copy()`.
    The default dynamic link mode resolves only the symbols listed in the core's
    `syms-dynamic.ld`; `k_current_get()` and `k_thread_name_get()` are not in it.

  See tools/sketches/README.md for compile, upload and verify steps.
*/
#include <Arduino_RouterBridge.h>
#include <zephyr/kernel.h>

// Mailbox between the RPC handler and loop(). The handler may run on the Bridge
// library's own thread, which has a 500-byte stack, so it only copies the line here;
// loop() does the work. One writer, one reader, so two indices are enough (no lock).
static const uint8_t SLOTS = 8;       // power of two
static const size_t SLOT_LEN = 64;    // the app's lines are 15-30 bytes
static char g_slots[SLOTS][SLOT_LEN];
static volatile uint8_t g_head = 0;   // next slot to write (handler)
static volatile uint8_t g_tail = 0;   // next slot to read (loop)
static volatile uint32_t g_dropped = 0;

static volatile k_tid_t g_handler_tid = NULL;
static bool g_threads_printed = false;
static uint32_t g_dropped_reported = 0;

void onCmd(String line) {
  if (g_handler_tid == NULL) {
    g_handler_tid = k_sched_current_thread_query();
  }
  uint8_t head = g_head;
  if ((uint8_t)(head - g_tail) >= SLOTS) {
    g_dropped = g_dropped + 1;        // loop() is behind; say so instead of blocking
    return;
  }
  strncpy(g_slots[head % SLOTS], line.c_str(), SLOT_LEN - 1);
  g_slots[head % SLOTS][SLOT_LEN - 1] = '\0';
  g_head = head + 1;
}

int fishPing() {
  return 1;
}

static String threadName(k_tid_t tid) {
  char buf[32] = "?";
  if (tid == NULL || k_thread_name_copy(tid, buf, sizeof(buf)) != 0 || buf[0] == '\0') {
    return String("?");
  }
  return String(buf);
}

void setup() {
  Bridge.begin();
  Bridge.provide_safe("fish_cmd", onCmd);
  Bridge.provide_safe("fish_ping", fishPing);
  Monitor.begin(115200);
}

void loop() {
  while (g_tail != g_head) {
    // One print per reply: every Monitor write is its own RPC message.
    String out = String("ACK ") + g_slots[g_tail % SLOTS] + "\n";
    g_tail = g_tail + 1;
    Monitor.print(out);
  }

  // Once, after the first command: which thread ran the handler. "bridge" means the
  // library's 500-byte thread, so handlers must stay as small as onCmd().
  if (!g_threads_printed && g_handler_tid != NULL) {
    g_threads_printed = true;
    Monitor.print(String("THREADS handler=") + threadName(g_handler_tid) + " loop=" +
                  threadName(k_sched_current_thread_query()) + "\n");
  }

  uint32_t dropped = g_dropped;
  if (dropped != g_dropped_reported) {
    g_dropped_reported = dropped;
    Monitor.print(String("DROPPED ") + String((unsigned long)dropped) + "\n");
  }
}
