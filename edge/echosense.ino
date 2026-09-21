/*
 * ============================================================================
 *  EchoSense — ESP32 Wildlife Acoustic Detection Firmware
 * ============================================================================
 *
 *  Board  : ESP32 WROOM-32 (DevKit v1 or equivalent)
 *  Mic    : INMP441 I2S MEMS Microphone
 *  Storage: MicroSD card module (SPI)
 *
 *  ── WIRING ─────────────────────────────────────────────────────────────────
 *
 *  INMP441 Microphone
 *  ┌──────────┬────────────┐
 *  │  INMP441 │   ESP32    │
 *  ├──────────┼────────────┤
 *  │  VCC     │  3.3 V     │
 *  │  GND     │  GND       │
 *  │  SCK     │  GPIO 26   │
 *  │  WS      │  GPIO 25   │
 *  │  SD      │  GPIO 34   │
 *  │  L/R     │  GND       │  (select left channel)
 *  └──────────┴────────────┘
 *
 *  MicroSD Card Module (SPI)
 *  ┌──────────┬────────────┐
 *  │  SD Card │   ESP32    │
 *  ├──────────┼────────────┤
 *  │  CS      │  GPIO 5    │
 *  │  MOSI    │  GPIO 23   │
 *  │  MISO    │  GPIO 19   │
 *  │  SCK     │  GPIO 18   │
 *  │  VCC     │  3.3 V     │
 *  │  GND     │  GND       │
 *  └──────────┴────────────┘
 *
 *  ── DUTY CYCLE ─────────────────────────────────────────────────────────────
 *
 *  1. Wake from deep sleep (or cold boot)
 *  2. Record 3 s of 16 kHz / 16-bit mono audio via I2S
 *  3. Compute RMS energy → simple Voice Activity Detection (VAD)
 *     • If RMS < VAD_THRESHOLD → skip network, go back to sleep
 *  4. Connect to WiFi, sync NTP time
 *  5. POST a JSON detection payload to the ingestion server
 *  6. Append the detection as a CSV line on the SD card
 *  7. Disconnect WiFi, enter deep sleep for 57 s  (total ≈ 60 s cycle)
 *
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include <SD.h>
#include <SPI.h>
#include <time.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  CONFIGURATION — edit these constants to match your deployment
 * ═══════════════════════════════════════════════════════════════════════════ */

// ── WiFi ────────────────────────────────────────────────────────────────────
static const char* WIFI_SSID     = "YOUR_SSID";
static const char* WIFI_PASSWORD = "YOUR_PASSWORD";

// ── Server ──────────────────────────────────────────────────────────────────
static const char* SERVER_URL = "http://YOUR_SERVER_IP:8000/api/detections";

// ── Device identity & location ──────────────────────────────────────────────
static const char* DEVICE_ID  = "echosense-001";
static const float DEVICE_LAT = 28.6139;   // latitude  (decimal degrees)
static const float DEVICE_LNG = 77.2090;   // longitude (decimal degrees)

// ── NTP ─────────────────────────────────────────────────────────────────────
static const char* NTP_SERVER     = "pool.ntp.org";
static const long  GMT_OFFSET_SEC = 19800;  // IST = UTC+5:30 = 19800 s
static const int   DST_OFFSET_SEC = 0;

// ── I2S / INMP441 pins ─────────────────────────────────────────────────────
static const int I2S_SCK_PIN = 26;  // Serial Clock (BCLK)
static const int I2S_WS_PIN  = 25;  // Word Select  (LRCLK)
static const int I2S_SD_PIN  = 34;  // Serial Data  (DOUT on mic)

// ── Audio parameters ────────────────────────────────────────────────────────
static const int      SAMPLE_RATE      = 16000;  // 16 kHz
static const int      BITS_PER_SAMPLE  = 16;
static const int      RECORD_SECONDS   = 3;
static const uint32_t TOTAL_SAMPLES    = SAMPLE_RATE * RECORD_SECONDS;  // 48 000
static const uint32_t BUFFER_SIZE_BYTES = TOTAL_SAMPLES * sizeof(int16_t);

// ── VAD ─────────────────────────────────────────────────────────────────────
static const int VAD_THRESHOLD = 500;  // RMS energy below this → silence

// ── SD card ─────────────────────────────────────────────────────────────────
static const int    SD_CS_PIN     = 5;
static const char*  CSV_FILE_PATH = "/detections.csv";

// ── Sleep ───────────────────────────────────────────────────────────────────
static const uint64_t DEEP_SLEEP_US = 57ULL * 1000000ULL;  // 57 seconds

/* ═══════════════════════════════════════════════════════════════════════════
 *  GLOBAL AUDIO BUFFER
 *  Allocated on the heap because 96 KB exceeds the default stack.
 * ═══════════════════════════════════════════════════════════════════════════ */
static int16_t* audioBuffer = nullptr;

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 1 — I2S INITIALISATION
 *  Configure I2S peripheral #0 to receive PDM/I2S data from INMP441.
 * ═══════════════════════════════════════════════════════════════════════════ */
bool initI2S() {
  const i2s_config_t i2sConfig = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,  // L/R tied to GND → left
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 1024,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };

  const i2s_pin_config_t pinConfig = {
    .bck_io_num   = I2S_SCK_PIN,
    .ws_io_num    = I2S_WS_PIN,
    .data_out_num = I2S_PIN_NO_CHANGE,   // not transmitting
    .data_in_num  = I2S_SD_PIN
  };

  esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2sConfig, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("[I2S] Driver install failed: %s\n", esp_err_to_name(err));
    return false;
  }

  err = i2s_set_pin(I2S_NUM_0, &pinConfig);
  if (err != ESP_OK) {
    Serial.printf("[I2S] Pin config failed: %s\n", esp_err_to_name(err));
    return false;
  }

  Serial.println("[I2S] Initialised — 16 kHz, 16-bit mono");
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 2 — RECORD AUDIO
 *  Fill audioBuffer with RECORD_SECONDS of samples via DMA reads.
 * ═══════════════════════════════════════════════════════════════════════════ */
bool recordAudio() {
  Serial.printf("[REC] Recording %d seconds of audio…\n", RECORD_SECONDS);

  uint32_t samplesRead   = 0;
  size_t   bytesRead     = 0;

  while (samplesRead < TOTAL_SAMPLES) {
    size_t toRead = (TOTAL_SAMPLES - samplesRead) * sizeof(int16_t);
    esp_err_t err = i2s_read(I2S_NUM_0,
                             (void*)(audioBuffer + samplesRead),
                             toRead,
                             &bytesRead,
                             portMAX_DELAY);
    if (err != ESP_OK) {
      Serial.printf("[REC] I2S read error: %s\n", esp_err_to_name(err));
      return false;
    }
    samplesRead += bytesRead / sizeof(int16_t);
  }

  Serial.printf("[REC] Captured %u samples (%u bytes)\n",
                samplesRead, samplesRead * sizeof(int16_t));
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 3 — VOICE ACTIVITY DETECTION (energy-based)
 *  Compute the Root-Mean-Square of the entire buffer and compare against
 *  VAD_THRESHOLD. Returns true if the audio contains meaningful energy.
 * ═══════════════════════════════════════════════════════════════════════════ */
bool vadCheck() {
  double sumSquares = 0.0;

  for (uint32_t i = 0; i < TOTAL_SAMPLES; i++) {
    double sample = (double)audioBuffer[i];
    sumSquares += sample * sample;
  }

  double rms = sqrt(sumSquares / TOTAL_SAMPLES);
  Serial.printf("[VAD] RMS energy = %.2f  (threshold = %d)\n", rms, VAD_THRESHOLD);

  if (rms < VAD_THRESHOLD) {
    Serial.println("[VAD] Below threshold — silence detected, skipping transmission");
    return false;
  }

  Serial.println("[VAD] Above threshold — sound detected!");
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 4a — WiFi CONNECTION
 *  Connect to the configured access point with a timeout.
 * ═══════════════════════════════════════════════════════════════════════════ */
bool connectWiFi() {
  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 40) {  // ~20 s timeout
    delay(500);
    Serial.print(".");
    retries++;
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Connection FAILED");
    return false;
  }

  Serial.printf("[WiFi] Connected — IP: %s\n", WiFi.localIP().toString().c_str());
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 4b — NTP TIME SYNC
 *  Obtain a valid ISO-8601 timestamp from an NTP server.
 * ═══════════════════════════════════════════════════════════════════════════ */
String getISO8601Timestamp() {
  configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER);

  struct tm timeInfo;
  int retries = 0;
  while (!getLocalTime(&timeInfo) && retries < 10) {
    delay(500);
    retries++;
  }

  if (retries >= 10) {
    Serial.println("[NTP] Failed to obtain time — using fallback");
    return String("1970-01-01T00:00:00Z");
  }

  char buf[30];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeInfo);
  Serial.printf("[NTP] Timestamp: %s\n", buf);
  return String(buf);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 5 — POST DETECTION TO SERVER
 *  Send a JSON array matching the ingestion API schema.
 *  Payload format:
 *    [{"device_id":"…","species":"Unknown","confidence":0.75,
 *      "timestamp":"…","latitude":…,"longitude":…,
 *      "battery_pct":85,"temp_c":25}]
 * ═══════════════════════════════════════════════════════════════════════════ */
bool postDetection(const String& timestamp) {
  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Build the JSON payload
  String json = "[{";
  json += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  json += "\"species\":\"Unknown\",";
  json += "\"confidence\":0.75,";
  json += "\"timestamp\":\"" + timestamp + "\",";
  json += "\"latitude\":" + String(DEVICE_LAT, 6) + ",";
  json += "\"longitude\":" + String(DEVICE_LNG, 6) + ",";
  json += "\"battery_pct\":85,";
  json += "\"temp_c\":25";
  json += "}]";

  Serial.printf("[HTTP] POSTing to %s\n", SERVER_URL);
  Serial.printf("[HTTP] Payload: %s\n", json.c_str());

  int httpCode = http.POST(json);

  if (httpCode > 0) {
    Serial.printf("[HTTP] Response code: %d\n", httpCode);
    String response = http.getString();
    Serial.printf("[HTTP] Response body: %s\n", response.c_str());
  } else {
    Serial.printf("[HTTP] POST failed: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
  return (httpCode >= 200 && httpCode < 300);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 6 — WRITE DETECTION TO SD CARD
 *  Append a CSV line:  timestamp, species, confidence
 *  Creates the file (with a header) if it does not yet exist.
 * ═══════════════════════════════════════════════════════════════════════════ */
bool writeToSD(const String& timestamp) {
  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("[SD] Card mount failed");
    return false;
  }

  bool fileExists = SD.exists(CSV_FILE_PATH);
  File file = SD.open(CSV_FILE_PATH, FILE_APPEND);

  if (!file) {
    Serial.println("[SD] Failed to open file for appending");
    return false;
  }

  // Write CSV header on first use
  if (!fileExists) {
    file.println("timestamp,species,confidence");
    Serial.println("[SD] Created new CSV with header");
  }

  // Append the detection row
  String line = timestamp + ",Unknown,0.75";
  file.println(line);
  Serial.printf("[SD] Wrote: %s\n", line.c_str());

  file.close();
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  STAGE 7 — ENTER DEEP SLEEP
 *  Disconnect radios, free resources, and sleep for DEEP_SLEEP_US µs.
 * ═══════════════════════════════════════════════════════════════════════════ */
void enterDeepSleep() {
  Serial.printf("[SLEEP] Entering deep sleep for %llu seconds…\n",
                DEEP_SLEEP_US / 1000000ULL);

  // Cleanly shut down peripherals
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  i2s_driver_uninstall(I2S_NUM_0);

  // Free the audio buffer before sleeping
  if (audioBuffer != nullptr) {
    free(audioBuffer);
    audioBuffer = nullptr;
  }

  esp_sleep_enable_timer_wakeup(DEEP_SLEEP_US);
  Serial.println("[SLEEP] Good night.\n");
  Serial.flush();
  esp_deep_sleep_start();
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SETUP — runs once on every wake-up (deep sleep resets the CPU)
 * ═══════════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println();
  Serial.println("╔══════════════════════════════════════════╗");
  Serial.println("║        EchoSense — Acoustic Sensor       ║");
  Serial.println("╚══════════════════════════════════════════╝");

  // Determine wake-up reason
  esp_sleep_wakeup_cause_t wakeReason = esp_sleep_get_wakeup_cause();
  switch (wakeReason) {
    case ESP_SLEEP_WAKEUP_TIMER:
      Serial.println("[BOOT] Woke from deep sleep (timer)");
      break;
    default:
      Serial.println("[BOOT] Cold boot / reset");
      break;
  }

  // ── Stage 1: Initialise I2S ───────────────────────────────────────────
  if (!initI2S()) {
    Serial.println("[ERR] I2S init failed — sleeping");
    enterDeepSleep();
  }

  // ── Allocate audio buffer on heap ─────────────────────────────────────
  audioBuffer = (int16_t*)malloc(BUFFER_SIZE_BYTES);
  if (audioBuffer == nullptr) {
    Serial.println("[ERR] Failed to allocate audio buffer — sleeping");
    enterDeepSleep();
  }
  Serial.printf("[MEM] Allocated %u bytes for audio buffer\n", BUFFER_SIZE_BYTES);

  // ── Stage 2: Record audio ─────────────────────────────────────────────
  if (!recordAudio()) {
    Serial.println("[ERR] Recording failed — sleeping");
    enterDeepSleep();
  }

  // Uninstall I2S immediately after recording to free DMA memory
  i2s_driver_uninstall(I2S_NUM_0);

  // ── Stage 3: VAD check ────────────────────────────────────────────────
  if (!vadCheck()) {
    // Silence — no point transmitting or logging
    enterDeepSleep();
  }

  // ── Stage 4: Connect WiFi & sync NTP ──────────────────────────────────
  if (!connectWiFi()) {
    Serial.println("[ERR] WiFi failed — writing local-only and sleeping");
    writeToSD("no-ntp-time");
    enterDeepSleep();
  }

  String timestamp = getISO8601Timestamp();

  // ── Stage 5: POST detection to server ─────────────────────────────────
  bool posted = postDetection(timestamp);
  if (!posted) {
    Serial.println("[WARN] Server POST failed — detection saved locally only");
  }

  // ── Stage 6: Write to SD card ─────────────────────────────────────────
  writeToSD(timestamp);

  // ── Stage 7: Deep sleep ───────────────────────────────────────────────
  enterDeepSleep();
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  LOOP — never reached because setup() always ends with deep sleep.
 *  Included for safety / Arduino framework compliance.
 * ═══════════════════════════════════════════════════════════════════════════ */
void loop() {
  // Not reached — deep sleep restarts from setup()
}
