#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WiFiClientSecure.h>
#if __has_include("config.h")
#include "config.h"
#define ESP_ANYWHERE_HAS_LEGACY_CONFIG 1
#else
#define ESP_ANYWHERE_HAS_LEGACY_CONFIG 0
#define WIFI_SSID ""
#define WIFI_PASSWORD ""
#define RELAY_URL ""
#define INSTALLATION_ID ""
#define ACTIVATION_CODE ""
#define DEVICE_ID ""
#endif
#ifndef LED_PIN
#define LED_PIN ESP_ANYWHERE_LED_PIN
#endif
#ifndef LED_ACTIVE_LOW
#define LED_ACTIVE_LOW ESP_ANYWHERE_LED_ACTIVE_LOW
#endif

extern const uint8_t x509_crt_bundle[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t x509_crt_bundle_end[] asm("_binary_x509_crt_bundle_end");

size_t caBundleSize() {
    return static_cast<size_t>(x509_crt_bundle_end - x509_crt_bundle);
}

#define FIRMWARE_VERSION "0.3.0"
#define HARDWARE_PROFILE ESP_ANYWHERE_PROFILE_ID

WebSocketsClient webSocket;
Preferences preferences;
String deviceToken;
String installationId;
String wifiSsid, wifiPassword, relayUrl, activationCode, configuredDeviceId, configuredDeviceName, configuredProfile;
bool provisioned = false;
bool isClaimed = false;

struct RelayEndpoint {
    String host;
    uint16_t port;
    bool tls;
};

RelayEndpoint relay;

bool ledState = false;

void emitStage(const char *stage, const char *status, const char *error = nullptr, const char *message = nullptr) {
    StaticJsonDocument<256> doc; doc["stage"] = stage; doc["status"] = status;
    if (error) doc["error"] = error; if (message) doc["message"] = message;
    serializeJson(doc, Serial); Serial.println();
}

bool validIdentifier(const String &value) {
    if (value.length() < 3 || value.length() > 64 || value[0] < 'a' || value[0] > 'z') return false;
    for (char ch : value) if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '-')) return false;
    return true;
}

void loadProvisioningConfig() {
    wifiSsid = preferences.getString("wifi_ssid", ""); wifiPassword = preferences.getString("wifi_pass", "");
    relayUrl = preferences.getString("relay_url", ""); installationId = preferences.getString("provision_iid", "");
    activationCode = preferences.getString("activation", ""); configuredDeviceId = preferences.getString("provision_did", "");
    configuredDeviceName = preferences.getString("device_name", ""); configuredProfile = preferences.getString("profile", "");
    provisioned = !wifiSsid.isEmpty() && !relayUrl.isEmpty() && validIdentifier(installationId) && validIdentifier(configuredDeviceId) && configuredProfile == HARDWARE_PROFILE;
#if ESP_ANYWHERE_HAS_LEGACY_CONFIG
    if (!provisioned && String(WIFI_SSID).length() && !String(WIFI_SSID).startsWith("<")) {
        wifiSsid = WIFI_SSID; wifiPassword = WIFI_PASSWORD; relayUrl = RELAY_URL; installationId = INSTALLATION_ID;
        activationCode = ACTIVATION_CODE; configuredDeviceId = DEVICE_ID; configuredDeviceName = String("ESP Anywhere ") + DEVICE_ID;
        configuredProfile = HARDWARE_PROFILE; provisioned = true; Serial.println("[PROVISION] legacy config.h mode");
    }
#endif
}

bool applyProvisionPacket(const String &line) {
    StaticJsonDocument<1024> doc; if (deserializeJson(doc, line)) return false;
    String type = doc["type"] | "";
    if (type == "factory_reset" && String(doc["confirm"] | "") == "ERASE") { preferences.clear(); emitStage("factory_reset", "ok"); delay(250); ESP.restart(); }
    if (type != "provision") return false;
    String ssid = doc["wifi_ssid"] | "", password = doc["wifi_password"] | "", newRelay = doc["relay_url"] | "";
    String newInstallation = doc["installation_id"] | "", newActivation = doc["activation_code"] | "";
    String newDeviceId = doc["device_id"] | "", newName = doc["device_name"] | "", profile = doc["profile_id"] | "";
    if (ssid.isEmpty() || ssid.length() > 32 || password.length() > 64 || !newRelay.startsWith("https://") || !validIdentifier(newInstallation) || !validIdentifier(newDeviceId) || profile != HARDWARE_PROFILE || !newActivation.startsWith(newInstallation + ":") || newName.isEmpty() || newName.length() > 64) {
        emitStage("config_saved", "error", "invalid_configuration", "Konfiguracja urzadzenia jest nieprawidlowa."); return false;
    }
    preferences.remove("token"); preferences.remove("install_id"); preferences.remove("device_id"); preferences.remove("act_used");
    preferences.putString("wifi_ssid", ssid); preferences.putString("wifi_pass", password); preferences.putString("relay_url", newRelay);
    preferences.putString("provision_iid", newInstallation); preferences.putString("activation", newActivation); preferences.putString("provision_did", newDeviceId);
    preferences.putString("device_name", newName); preferences.putString("profile", profile);
    wifiSsid = ssid; wifiPassword = password; relayUrl = newRelay; installationId = newInstallation; activationCode = newActivation;
    configuredDeviceId = newDeviceId; configuredDeviceName = newName; configuredProfile = profile; provisioned = true; emitStage("config_saved", "ok"); return true;
}

void waitForProvisioning() {
    emitStage("detected", "ok"); Serial.setTimeout(1000);
    while (!provisioned) { if (Serial.available()) applyProvisionPacket(Serial.readStringUntil('\n')); delay(20); }
}

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
    String storedInstallationId = preferences.getString("install_id", "");
    String storedDeviceId = preferences.getString("device_id", "");
    if (!deviceToken.isEmpty() && storedInstallationId == installationId && storedDeviceId == configuredDeviceId) {
        isClaimed = true;
        Serial.println("[TOKEN] loaded from NVS");
    } else {
        deviceToken = "";
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
    doc["code"] = activationCode;
    doc["device_id"] = configuredDeviceId;
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
            && claimedInstallationId == installationId) {
            deviceToken = claimedDeviceToken;
            installationId = claimedInstallationId;
            preferences.putString("token", deviceToken);
            preferences.putString("install_id", installationId);
            preferences.putString("device_id", configuredDeviceId);
            preferences.putBool("act_used", true);
            preferences.remove("activation"); activationCode = "";
            isClaimed = true;
            Serial.println("Claim successful; credentials stored.");
            emitStage("claim_success", "ok");
        } else {
            Serial.println("Claim response was invalid.");
        }
    } else {
        Serial.printf("Claim failed. Code: %d\n", httpResponseCode);
        if (httpResponseCode == 400) emitStage("claim_success", "error", "activation_expired", "Kod aktywacyjny wygasl lub zostal juz uzyty.");
        else emitStage("claim_success", "error", "worker_unavailable", "Worker jest chwilowo niedostepny.");
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
            emitStage("worker_connected", "ok");
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
    payload["name"] = configuredDeviceName;
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
    emitStage("discovery_sent", "ok");
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
    Serial.setRxBufferSize(1024);
    Serial.begin(115200);
    delay(750);
    Serial.println("[BOOT] ESP Anywhere starting");
    pinMode(LED_PIN, OUTPUT);
    writeLedOutput();

    preferences.begin("esp-anywhere", false);
    loadProvisioningConfig();
    waitForProvisioning();
    loadDeviceCredentials();

    if (!parseRelayBase(relayUrl, relay)) {
        Serial.println("Invalid RELAY_URL base address.");
        while (true) delay(1000);
    }

    emitStage("wifi_connected", "active");
    WiFi.begin(wifiSsid, wifiPassword);
    unsigned long wifiDeadline = millis() + 30000;
    while (WiFi.status() != WL_CONNECTED && millis() < wifiDeadline) delay(500);
    if (WiFi.status() != WL_CONNECTED) {
        emitStage("wifi_connected", "error", "wifi_auth_failed", "Nie udalo sie polaczyc z Wi-Fi. Sprawdz haslo.");
        provisioned = false; waitForProvisioning(); ESP.restart();
    }
    emitStage("wifi_connected", "ok");

    while (!isClaimed) {
        performClaim();
        if (!isClaimed) delay(5000);
    }

    String wsPath = "/ws?role=device&installation_id=" + installationId
        + "&device_id=" + configuredDeviceId;
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
    if (Serial.available()) applyProvisionPacket(Serial.readStringUntil('\n'));

    if (millis() - lastUpdate > 10000) {
        lastUpdate = millis();
        if (webSocket.isConnected()) {
            pushState();
        }
    }
}
