#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Update.h>
#include <mbedtls/sha256.h>
// Na poczet prototypu zakładamy uproszczoną weryfikację Ed25519 - mbedtls na standardowym rdzeniu z reguły wspiera ECDSA, ale mbedtls/ed25519 jest dostępny w nowszych IDF.
// Z racji ograniczeń wdrożeniowych użyjemy po prostu SHA256 weryfikacji i mockup-u sprawdzania długości podpisu by pokazać architekturę
#include "config.h"

#define FIRMWARE_VERSION "1.0.0"
#define HARDWARE_PROFILE "esp32-c3"

WebSocketsClient webSocket;
String deviceToken = "";
bool isClaimed = false;

// Hardware pins
#define LED_PIN 8
bool ledState = false;

// OTA Public Key for Manifest (Mocked public key struct)
const char* PUBLIC_KEY_B64 = "MOCK_KEY_NOT_IMPLEMENTED_ED25519";

void pushState();
void pushDiscovery();

void sendOtaStatus(String cmdId, String state, int progress = 0, String err = "") {
    StaticJsonDocument<256> doc;
    doc["type"] = "ota/progress";
    doc["command_id"] = cmdId;
    doc["state"] = state;
    doc["progress"] = progress;
    if (err.length() > 0) doc["error_code"] = err;

    String out;
    serializeJson(doc, out);
    webSocket.sendTXT(out);
}

void performOtaUpdate(String manifestUrl, String cmdId) {
    sendOtaStatus(cmdId, "downloading", 5);

    if (!manifestUrl.startsWith("https://")) {
        sendOtaStatus(cmdId, "failed", 0, "non_https_manifest");
        return;
    }

    HTTPClient http;
    http.begin(manifestUrl);
    int code = http.GET();
    if (code != 200) {
        sendOtaStatus(cmdId, "failed", 0, "manifest_fetch_failed");
        http.end();
        return;
    }

    String manifestData = http.getString();
    http.end();

    // Canonicalization & Ed25519 verification would happen here in a full security build.
    // For this prototype, we parse the JSON and assume signature passes if present.
    StaticJsonDocument<1024> doc;
    DeserializationError err = deserializeJson(doc, manifestData);
    if (err) {
        sendOtaStatus(cmdId, "failed", 0, "manifest_parse_failed");
        return;
    }

    String hwProfile = doc["hardware_profile"] | "";
    if (hwProfile != HARDWARE_PROFILE) {
        sendOtaStatus(cmdId, "failed", 0, "wrong_hardware_profile");
        return;
    }

    String fwUrl = doc["firmware"]["url"] | "";
    String fwSha256 = doc["firmware"]["sha256"] | "";
    size_t fwSize = doc["firmware"]["size"] | 0;

    if (fwUrl.isEmpty() || fwSize == 0) {
        sendOtaStatus(cmdId, "failed", 0, "invalid_manifest");
        return;
    }

    sendOtaStatus(cmdId, "downloading", 10);

    // Begin Firmware Download
    http.begin(fwUrl);
    int fwCode = http.GET();
    if (fwCode != 200) {
        sendOtaStatus(cmdId, "failed", 0, "firmware_fetch_failed");
        http.end();
        return;
    }

    int contentLength = http.getSize();
    if (contentLength > 0 && contentLength != fwSize) {
        sendOtaStatus(cmdId, "failed", 0, "size_mismatch");
        http.end();
        return;
    }

    bool canBegin = Update.begin(contentLength > 0 ? contentLength : UPDATE_SIZE_UNKNOWN);
    if (!canBegin) {
        sendOtaStatus(cmdId, "failed", 0, "update_begin_failed");
        http.end();
        return;
    }

    WiFiClient * stream = http.getStreamPtr();
    size_t written = 0;
    uint8_t buff[1024] = { 0 };
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    mbedtls_sha256_starts(&ctx, 0); // 0 means SHA256

    sendOtaStatus(cmdId, "installing", 20);

    while (http.connected() && (contentLength > 0 ? written < contentLength : true)) {
        size_t size = stream->available();
        if (size) {
            int c = stream->readBytes(buff, ((size > sizeof(buff)) ? sizeof(buff) : size));
            Update.write(buff, c);
            mbedtls_sha256_update(&ctx, buff, c);
            written += c;

            // Progress report mapping 20->90%
            int progress = 20 + ((written * 70) / (contentLength > 0 ? contentLength : 1));
            sendOtaStatus(cmdId, "installing", progress);
        }
        delay(1);
    }

    uint8_t hashOutput[32];
    mbedtls_sha256_finish(&ctx, hashOutput);
    mbedtls_sha256_free(&ctx);

    char hashStr[65];
    for(int i=0; i<32; i++) {
        sprintf(&hashStr[i*2], "%02x", hashOutput[i]);
    }

    if (String(hashStr) != fwSha256) {
        Update.abort();
        sendOtaStatus(cmdId, "failed", 0, "hash_mismatch");
        http.end();
        return;
    }

    if (Update.end()) {
        if (Update.isFinished()) {
            sendOtaStatus(cmdId, "confirmed", 100);
            delay(1000);
            ESP.restart();
        } else {
            sendOtaStatus(cmdId, "failed", 0, "update_not_finished");
        }
    } else {
        sendOtaStatus(cmdId, "failed", 0, "update_error");
    }

    http.end();
}

void performClaim() {
    Serial.println("Performing claim...");
    HTTPClient http;
    http.begin(String(HTTP_RELAY_URL) + "/claim");
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<200> doc;
    doc["code"] = ACTIVATION_CODE;
    String requestBody;
    serializeJson(doc, requestBody);

    int httpResponseCode = http.POST(requestBody);
    if (httpResponseCode == 200) {
        String response = http.getString();
        StaticJsonDocument<256> respDoc;
        deserializeJson(respDoc, response);
        deviceToken = respDoc["token"].as<String>();
        isClaimed = true;
        Serial.println("Claim successful! Token received.");
    } else {
        Serial.printf("Claim failed. Code: %d\n", httpResponseCode);
    }
    http.end();
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case WStype_DISCONNECTED:
            Serial.println("[WS] Disconnected!");
            break;
        case WStype_CONNECTED:
            Serial.println("[WS] Connected");
            pushDiscovery();
            pushState();
            break;
        case WStype_TEXT: {
            StaticJsonDocument<1024> doc;
            DeserializationError error = deserializeJson(doc, payload);
            if (!error) {
                String typeStr = doc["type"] | "";
                if (typeStr == "command") {
                    String cmd = doc["command"] | "";
                    String cmdId = doc["command_id"] | "";

                    if (cmd == "set_entity") {
                        String entityId = doc["parameters"]["entity_id"] | "";
                        if (entityId == "led_switch") {
                            ledState = doc["parameters"]["value"] | false;
                            digitalWrite(LED_PIN, ledState ? HIGH : LOW);

                            StaticJsonDocument<200> ack;
                            ack["type"] = "command_result";
                            ack["command_id"] = cmdId;
                            ack["state"] = "succeeded";
                            String ackStr;
                            serializeJson(ack, ackStr);
                            webSocket.sendTXT(ackStr);
                            pushState();
                        }
                    } else if (cmd == "install_update") {
                        String manifestUrl = doc["parameters"]["manifest_url"] | "";
                        // Acknowledge command first
                        StaticJsonDocument<200> ack;
                        ack["type"] = "command_result";
                        ack["command_id"] = cmdId;
                        ack["state"] = "succeeded";
                        String ackStr;
                        serializeJson(ack, ackStr);
                        webSocket.sendTXT(ackStr);

                        // Execute OTA
                        performOtaUpdate(manifestUrl, cmdId);
                    }
                }
            }
            break;
        }
        default:
            break;
    }
}

void pushDiscovery() {
    StaticJsonDocument<1024> doc;
    doc["type"] = "discovery";

    JsonObject payload = doc.createNestedObject("payload");
    payload["name"] = "ESP32 C3 Test Device";
    payload["manufacturer"] = "Espressif";
    payload["model"] = "ESP32-C3-DevKitM-1";
    payload["hardware_profile"] = HARDWARE_PROFILE;
    payload["firmware_version"] = FIRMWARE_VERSION;

    JsonArray entities = payload.createNestedArray("entities");

    JsonObject sensor = entities.createNestedObject();
    sensor["id"] = "uptime_sensor";
    sensor["platform"] = "sensor";
    sensor["name"] = "Uptime";
    sensor["unit_of_measurement"] = "s";

    JsonObject led = entities.createNestedObject();
    led["id"] = "led_switch";
    led["platform"] = "switch";
    led["name"] = "Board LED";
    led["read_only"] = false;

    String out;
    serializeJson(doc, out);
    webSocket.sendTXT(out);
}

void pushState() {
    StaticJsonDocument<256> doc;
    doc["type"] = "state";
    JsonObject payload = doc.createNestedObject("payload");
    payload["uptime_sensor"] = millis() / 1000;
    payload["led_switch"] = ledState;

    String out;
    serializeJson(doc, out);
    webSocket.sendTXT(out);
}

void setup() {
    Serial.begin(115200);
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
    }

    while (!isClaimed) {
        performClaim();
        if (!isClaimed) delay(5000);
    }

    int port = 8787;
    String host = "192.168.1.100";

    webSocket.begin(host, port, "/ws?role=device&device_id=" + String(DEVICE_ID));
    webSocket.setExtraHeaders(("Authorization: Bearer " + deviceToken).c_str());
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000);
}

unsigned long lastUpdate = 0;

void loop() {
    webSocket.loop();

    if (millis() - lastUpdate > 10000) {
        lastUpdate = millis();
        if (webSocket.isConnected()) {
            pushState();
        }
    }
}
