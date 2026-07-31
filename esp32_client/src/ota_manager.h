#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WebSocketsClient.h>

struct OtaManagerConfig {
  Preferences *preferences;
  WebSocketsClient *web_socket;
  String relay_host;
  uint16_t relay_port;
  bool relay_tls;
  const uint8_t *ca_bundle;
  size_t ca_bundle_size;
  String current_version;
  String hardware_profile;
};

void otaInitialize(const OtaManagerConfig &config);
void otaHandleStart(JsonObjectConst message);
void otaOnWssHealthy();
void otaLoop();
bool otaIsPendingVerification();
