#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WiFiClientSecure.h>
#include "config.h"

#ifndef LED_ACTIVE_LOW
#define LED_ACTIVE_LOW false
#endif

extern const uint8_t x509_crt_bundle[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t x509_crt_bundle_end[] asm("_binary_x509_crt_bundle_end");

size_t caBundleSize() {
    return static_cast<size_t>(x509_crt_bundle_end - x509_crt_bundle);
}

#define FIRMWARE_VERSION "1.0.0"
#define HARDWARE_PROFILE "esp32-c3"

WebSocketsClient webSocket;
Preferences preferences;
String deviceToken;
String installationId;
bool isClaimed = false;

struct RelayEndpoint {
    String host;
    uint16_t port;
    bool tls;
};

RelayEndpoint relay;

bool ledState = false;

void writeLedOutput() {
    const bool pinHigh = LED_ACTIVE_LOW ? !ledState : ledState;
    digitalWrite(LED_PIN, pinHigh ? HIGH : LOW);
}

void pushState();
void pushDiscovery();

bool parseRelayBase(const String &value, RelayEndpoint &endpoint) {
    String remainder = value;
    if (remainder.startsWith("https://")) {
        endpoint.tls = true;
        endpoint.port = 443;
        remainder.remove(0, 8);
    } else if (remainder.startsWith("http://")) {
        endpoint.tls = false;
        endpoint.port = 80;
        remainder.remove(0, 7);
    } else if (remainder.startsWith("wss://")) {
        endpoint.tls = true;
        endpoint.port = 443;
        remainder.remove(0, 6);
    } else if (remainder.startsWith("ws://")) {
        endpoint.tls = false;
        endpoint.port = 80;
        remainder.remove(0, 5);
    } else {
        return false;
    }

    if (remainder.endsWith("/")) remainder.remove(remainder.length() - 1);
    if (remainder.isEmpty() || remainder.indexOf('/') >= 0) return false;

    int colon = remainder.lastIndexOf(':');
    if (colon > 0) {
        String portText = remainder.substring(colon + 1);
        int parsedPort = portText.toInt();
        if (parsedPort < 1 || parsedPort > 65535 || String(parsedPort) != portText) return false;
        endpoint.port = static_cast<uint16_t>(parsedPort);
        remainder = remainder.substring(0, colon);
    }
    if (remainder.isEmpty()) return false;
    endpoint.host = remainder;
    return true;
}

void resetDeviceCredentials() {
    preferences.remove("token");
    preferences.remove("install_id");
    preferences.remove("device_id");
    preferences.remove("act_used");
    deviceToken = "";
    installationId = "";
    isClaimed = false;
}

void loadDeviceCredentials() {
    deviceToken = preferences.getString("token", "");
    installationId = preferences.getString("install_id", "");
    String storedDeviceId = preferences.getString("device_id", "");
    if (!deviceToken.isEmpty() && installationId == INSTALLATION_ID && storedDeviceId == DEVICE_ID) {
        isClaimed = true;
        Serial.println("[TOKEN] loaded from NVS");
    } else {
        deviceToken = "";
        installationId = "";
        isClaimed = false;
    }
}

void performClaim() {
    Serial.println("Performing claim...");
    if (preferences.getBool("act_used", false)) {
        Serial.println("Activation code was already consumed; service reset required.");
        return;
    }

    HTTPClient http;
    String claimUrl = String(relay.tls ? "https://" : "http://")
        + relay.host + ":" + relay.port + "/claim";
    WiFiClient plainClient;
    WiFiClientSecure secureClient;
    if (relay.tls) {
        secureClient.setCACertBundle(x509_crt_bundle, caBundleSize());
        http.begin(secureClient, claimUrl);
    } else {
        http.begin(plainClient, claimUrl);
    }
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<200> doc;
    doc["code"] = ACTIVATION_CODE;
    doc["device_id"] = DEVICE_ID;
    String requestBody;
    serializeJson(doc, requestBody);

    int httpResponseCode = http.POST(requestBody);
    if (httpResponseCode == 200) {
        String response = http.getString();
        StaticJsonDocument<256> respDoc;
        DeserializationError error = deserializeJson(respDoc, response);
        String claimedRole = respDoc["role"] | "";
        String claimedDeviceToken = respDoc["token"] | "";
        String claimedInstallationId = respDoc["installation_id"] | "";
        if (!error && claimedRole == "device" && !claimedDeviceToken.isEmpty()
            && claimedInstallationId == INSTALLATION_ID) {
            deviceToken = claimedDeviceToken;
            installationId = claimedInstallationId;
            preferences.putString("token", deviceToken);
            preferences.putString("install_id", installationId);
            preferences.putString("device_id", DEVICE_ID);
            preferences.putBool("act_used", true);
            isClaimed = true;
            Serial.println("Claim successful; credentials stored.");
        } else {
            Serial.println("Claim response was invalid.");
        }
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
                            writeLedOutput();

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
                        StaticJsonDocument<256> ack;
                        ack["type"] = "command_result";
                        ack["command_id"] = cmdId;
                        ack["state"] = "rejected";
                        JsonObject error = ack.createNestedObject("error");
                        error["code"] = "ota_unavailable";
                        error["message"] = "OTA is unavailable in this firmware";
                        String ackStr;
                        serializeJson(ack, ackStr);
                        webSocket.sendTXT(ackStr);
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
    Serial.println("[DISCOVERY] sent");
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
    Serial.println("[STATE] sent");
}

void setup() {
    Serial.begin(115200);
    delay(750);
    Serial.println("[BOOT] ESP Anywhere starting");
    pinMode(LED_PIN, OUTPUT);
    writeLedOutput();

    preferences.begin("esp-anywhere", false);
    loadDeviceCredentials();

    if (!parseRelayBase(RELAY_URL, relay)) {
        Serial.println("Invalid RELAY_URL base address.");
        while (true) delay(1000);
    }

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
    }

    while (!isClaimed) {
        performClaim();
        if (!isClaimed) delay(5000);
    }

    String wsPath = "/ws?role=device&installation_id=" + installationId
        + "&device_id=" + String(DEVICE_ID);
    if (relay.tls) {
        webSocket.beginSslWithBundle(
            relay.host.c_str(), relay.port, wsPath.c_str(),
            x509_crt_bundle, caBundleSize()
        );
    } else {
        webSocket.begin(relay.host, relay.port, wsPath);
    }
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
