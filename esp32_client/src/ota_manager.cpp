#include "ota_manager.h"

#include <Ed25519.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <esp_ota_ops.h>
#include <mbedtls/base64.h>
#include <mbedtls/sha256.h>

namespace {
constexpr uint32_t HEALTH_TIMEOUT_MS = 60000;
constexpr uint32_t DOWNLOAD_STALL_TIMEOUT_MS = 15000;
constexpr size_t MAX_MANIFEST_BYTES = 16384;
constexpr int OTA_BOOTSTRAP_VERSION = 1;
struct TrustedKey { const char *id; uint8_t publicKey[32]; };
constexpr TrustedKey TRUSTED_KEYS[] = {{"staging-2026-01", {
  0xf6, 0x49, 0x58, 0xcc, 0x03, 0x5b, 0x5a, 0xd8, 0x54, 0x41, 0x95, 0xeb, 0x7d, 0xbb, 0x7a, 0xb0,
  0xdd, 0xe8, 0xe6, 0xc9, 0xec, 0x20, 0x22, 0x4b, 0x0f, 0x85, 0xb5, 0x20, 0x7c, 0xe8, 0x9f, 0xa2
}}};
const char *ALLOWED_FIRMWARE_HOSTS[] = {"raw.githubusercontent.com"};

OtaManagerConfig cfg{};
bool initialized = false;
bool pendingVerification = false;
bool rollbackDetected = false;
uint32_t healthDeadline = 0;
String pendingCommand;
String pendingTarget;

struct Manifest {
  String version, channel, firmwareUrl, firmwareSha256, keyId;
  size_t firmwareSize{};
  int minBootstrap{};
  bool recovery{};
};

void sendJson(JsonDocument &doc) {
  if (!cfg.web_socket || !cfg.web_socket->isConnected()) return;
  String out; serializeJson(doc, out); cfg.web_socket->sendTXT(out);
}

void sendEvent(const char *type, const String &commandId, const char *state, float progress,
               const char *errorCode = nullptr) {
  StaticJsonDocument<384> doc; doc["type"] = type; doc["command_id"] = commandId;
  doc["state"] = state; doc["progress"] = progress;
  if (errorCode) doc["error_code"] = errorCode;
  sendJson(doc);
}

void sendCommandResult(const String &commandId, const char *state, const char *code = nullptr,
                       const char *message = nullptr) {
  StaticJsonDocument<384> doc; doc["type"] = "command_result"; doc["command_id"] = commandId; doc["state"] = state;
  if (code) { JsonObject error = doc.createNestedObject("error"); error["code"] = code; error["message"] = message ?: code; }
  sendJson(doc);
}

void fail(const String &commandId, const char *code, const char *message) {
  sendEvent("ota_failed", commandId, "failed", 0, code);
  sendCommandResult(commandId, "failed", code, message);
}

bool decodeBase64(const String &input, uint8_t *output, size_t capacity, size_t &length) {
  length = 0;
  return mbedtls_base64_decode(output, capacity, &length,
      reinterpret_cast<const unsigned char *>(input.c_str()), input.length()) == 0;
}

bool parseVersion(const String &value, int parts[3]) {
  int first = value.indexOf('.'), second = value.indexOf('.', first + 1);
  if (first <= 0 || second <= first + 1) return false;
  String a=value.substring(0,first), b=value.substring(first+1,second), c=value.substring(second+1);
  if (c.indexOf('-') >= 0) c = c.substring(0,c.indexOf('-'));
  for (const String *s : {&a,&b,&c}) { if (s->isEmpty()) return false; for (char ch:*s) if (ch<'0'||ch>'9') return false; }
  parts[0]=a.toInt(); parts[1]=b.toInt(); parts[2]=c.toInt(); return true;
}

int compareVersions(const String &left, const String &right) {
  int a[3], b[3]; if (!parseVersion(left,a) || !parseVersion(right,b)) return -99;
  for (int i=0;i<3;i++) if (a[i]!=b[i]) return a[i]<b[i]?-1:1;
  return 0;
}

bool safeHttpsUrl(const String &url, const char *const *hosts, size_t hostCount) {
  if (!url.startsWith("https://") || url.indexOf('?') >= 0 || url.indexOf('#') >= 0 || url.indexOf('@') >= 0) return false;
  int start=8, slash=url.indexOf('/',start); if (slash<0) return false;
  String host=url.substring(start,slash); if (host.indexOf(':')>=0 || host.isEmpty()) return false;
  for (size_t i=0;i<hostCount;i++) if (host.equalsIgnoreCase(hosts[i])) return true;
  return false;
}

bool fetchManifest(const String &channel, String &document) {
  if (!cfg.relay_tls || cfg.relay_host.isEmpty()) return false;
  String path = "/ota/" + channel + "/manifest.json";
  String url = "https://" + cfg.relay_host + (cfg.relay_port == 443 ? "" : ":" + String(cfg.relay_port)) + path;
  WiFiClientSecure client; client.setCACertBundle(cfg.ca_bundle, cfg.ca_bundle_size);
  HTTPClient http; if (!http.begin(client, url)) return false;
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS); http.setTimeout(15000);
  int code=http.GET(); int length=http.getSize();
  if (code!=200 || length<=0 || static_cast<size_t>(length)>MAX_MANIFEST_BYTES) { http.end(); return false; }
  document=http.getString(); http.end(); return document.length()==static_cast<size_t>(length);
}

bool verifyManifest(const String &document, Manifest &result, String &error) {
  StaticJsonDocument<2048> outer; if (deserializeJson(outer,document)) { error="manifest_json"; return false; }
  if (outer["schema_version"] != 2 || String(outer["security"]["algorithm"] | "") != "Ed25519") { error="manifest_schema"; return false; }
  String keyId=outer["security"]["key_id"]|"", signatureText=outer["security"]["signature"]|"", payloadText=outer["signed_payload"]|"";
  const uint8_t *publicKey=nullptr; for (const auto &key:TRUSTED_KEYS) if (keyId==key.id) { publicKey=key.publicKey; break; }
  if (!publicKey || signatureText.length()!=88 || payloadText.isEmpty()) { error="untrusted_key"; return false; }
  uint8_t signature[64]; size_t signatureLength; if (!decodeBase64(signatureText,signature,sizeof(signature),signatureLength)||signatureLength!=64) { error="bad_signature"; return false; }
  size_t payloadCapacity=(payloadText.length()*3)/4+4; if (payloadCapacity>MAX_MANIFEST_BYTES) { error="manifest_too_large"; return false; }
  std::unique_ptr<uint8_t[]> payload(new (std::nothrow) uint8_t[payloadCapacity+1]); if (!payload) { error="no_memory"; return false; }
  size_t payloadLength; if (!decodeBase64(payloadText,payload.get(),payloadCapacity,payloadLength)) { error="payload_base64"; return false; }
  if (!Ed25519::verify(signature,publicKey,payload.get(),payloadLength)) { error="bad_signature"; return false; }
  payload[payloadLength]=0;
  StaticJsonDocument<1536> signedDoc; if (deserializeJson(signedDoc,payload.get(),payloadLength)) { error="signed_payload_json"; return false; }
  if (signedDoc["manifest_version"]!=1 || String(signedDoc["project"]|"")!="esp-anywhere" || String(signedDoc["chip_family"]|"")!="ESP32-C3") { error="signed_metadata"; return false; }
  if (String(signedDoc["hardware_profile"]|"") != cfg.hardware_profile || String(signedDoc["min_protocol_version"]|"") != "1.0") { error="incompatible_target"; return false; }
  result.version=String(signedDoc["version"]|""); result.channel=String(signedDoc["channel"]|""); result.recovery=signedDoc["recovery"]|false;
  result.minBootstrap=signedDoc["min_ota_bootstrap"]|0; result.firmwareUrl=String(signedDoc["firmware"]["url"]|"");
  result.firmwareSha256=String(signedDoc["firmware"]["sha256"]|""); result.firmwareSize=signedDoc["firmware"]["size"]|0; result.keyId=keyId;
  if (result.minBootstrap>OTA_BOOTSTRAP_VERSION || result.firmwareSha256.length()!=64 || !safeHttpsUrl(result.firmwareUrl,ALLOWED_FIRMWARE_HOSTS,1)) { error="manifest_policy"; return false; }
  return true;
}

bool downloadAndStage(const Manifest &manifest, const String &commandId) {
  const esp_partition_t *target=esp_ota_get_next_update_partition(nullptr);
  if (!target || manifest.firmwareSize==0 || manifest.firmwareSize>target->size) { fail(commandId,"no_space","Firmware does not fit the inactive OTA partition"); return false; }
  WiFiClientSecure client; client.setCACertBundle(cfg.ca_bundle,cfg.ca_bundle_size);
  HTTPClient http; if (!http.begin(client,manifest.firmwareUrl)) { fail(commandId,"download_start","Cannot open firmware URL"); return false; }
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS); http.setTimeout(DOWNLOAD_STALL_TIMEOUT_MS);
  int code=http.GET(); int length=http.getSize();
  if (code!=200 || length!=static_cast<int>(manifest.firmwareSize)) { http.end(); fail(commandId,"download_response","Firmware HTTPS response is invalid"); return false; }
  esp_ota_handle_t handle; if (esp_ota_begin(target,manifest.firmwareSize,&handle)!=ESP_OK) { http.end(); fail(commandId,"ota_begin","Cannot prepare inactive OTA partition"); return false; }
  mbedtls_sha256_context sha; mbedtls_sha256_init(&sha); mbedtls_sha256_starts(&sha,0);
  NetworkClient *stream=http.getStreamPtr(); uint8_t buffer[4096]; size_t written=0; uint32_t lastData=millis(); bool ok=true;
  while (written<manifest.firmwareSize) {
    size_t available=stream->available();
    if (available) {
      size_t wanted=min(sizeof(buffer),min(available,manifest.firmwareSize-written)); int count=stream->readBytes(buffer,wanted);
      if (count<=0 || esp_ota_write(handle,buffer,count)!=ESP_OK) { ok=false; break; }
      mbedtls_sha256_update(&sha,buffer,count); written+=count; lastData=millis();
      sendEvent("ota_progress",commandId,"downloading",100.0f*written/manifest.firmwareSize);
    } else if (!http.connected() || millis()-lastData>DOWNLOAD_STALL_TIMEOUT_MS) { ok=false; break; }
    else delay(10);
  }
  uint8_t digest[32]; mbedtls_sha256_finish(&sha,digest); mbedtls_sha256_free(&sha); http.end();
  String actual; for (uint8_t byte:digest) { char hex[3]; snprintf(hex,sizeof(hex),"%02x",byte); actual+=hex; }
  if (!ok || written!=manifest.firmwareSize) { esp_ota_abort(handle); fail(commandId,"download_interrupted","Firmware download was interrupted"); return false; }
  sendEvent("ota_verify",commandId,"verifying",100);
  if (!actual.equalsIgnoreCase(manifest.firmwareSha256)) { esp_ota_abort(handle); fail(commandId,"sha256_mismatch","Firmware SHA-256 does not match signed manifest"); return false; }
  if (esp_ota_end(handle)!=ESP_OK || esp_ota_set_boot_partition(target)!=ESP_OK) { fail(commandId,"image_invalid","Firmware image validation failed"); return false; }
  return true;
}
} // namespace

void otaInitialize(const OtaManagerConfig &config) {
  cfg=config; initialized=true; pendingCommand=cfg.preferences->getString("ota_cmd",""); pendingTarget=cfg.preferences->getString("ota_target","");
  if (!cfg.preferences->getBool("ota_pending",false) || pendingCommand.isEmpty() || pendingTarget.isEmpty()) return;
  const esp_partition_t *running=esp_ota_get_running_partition(); esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
  if (running && esp_ota_get_state_partition(running,&state)==ESP_OK && state==ESP_OTA_IMG_PENDING_VERIFY && cfg.current_version==pendingTarget) {
    pendingVerification=true; healthDeadline=millis()+HEALTH_TIMEOUT_MS;
    uint32_t attempts=cfg.preferences->getUInt("ota_attempts",0)+1; cfg.preferences->putUInt("ota_attempts",attempts);
    if (attempts>2) esp_ota_mark_app_invalid_rollback_and_reboot();
  } else if (cfg.current_version!=pendingTarget) rollbackDetected=true;
}

void otaHandleStart(JsonObjectConst message) {
  String commandId=message["command_id"]|"", channel=message["channel"]|"stable", requested=message["target_version"]|""; bool recovery=message["recovery"]|false;
  if (!initialized || commandId.isEmpty() || (channel!="stable"&&channel!="beta"&&channel!="recovery")) return;
  sendEvent("ota_start",commandId,"fetching_manifest",0);
  String document; if (!fetchManifest(channel,document)) { fail(commandId,"manifest_unavailable","Signed manifest is unavailable"); return; }
  Manifest manifest; String error; if (!verifyManifest(document,manifest,error)) { fail(commandId,error.c_str(),"Signed manifest verification failed"); return; }
  if (manifest.channel!=channel || (!requested.isEmpty()&&manifest.version!=requested)) { fail(commandId,"target_mismatch","Manifest target does not match approved update"); return; }
  int comparison=compareVersions(manifest.version,cfg.current_version);
  if (comparison==-99 || comparison==0 || (comparison<0 && !(recovery&&channel=="recovery"&&manifest.recovery))) { fail(commandId,"downgrade_blocked","Firmware downgrade is not authorized"); return; }
  if (!downloadAndStage(manifest,commandId)) return;
  cfg.preferences->putString("ota_cmd",commandId); cfg.preferences->putString("ota_target",manifest.version); cfg.preferences->putString("ota_previous",cfg.current_version);
  cfg.preferences->putBool("ota_pending",true); cfg.preferences->putUInt("ota_attempts",0);
  sendEvent("ota_progress",commandId,"rebooting",100); delay(500); ESP.restart();
}

void otaOnWssHealthy() {
  if (!initialized) return;
  if (pendingVerification) {
    if (esp_ota_mark_app_valid_cancel_rollback()!=ESP_OK) return;
    sendEvent("ota_success",pendingCommand,"confirmed",100); sendCommandResult(pendingCommand,"succeeded");
    cfg.preferences->remove("ota_pending"); cfg.preferences->remove("ota_cmd"); cfg.preferences->remove("ota_target"); cfg.preferences->remove("ota_previous"); cfg.preferences->remove("ota_attempts"); pendingVerification=false;
  } else if (rollbackDetected) {
    sendEvent("ota_rollback",pendingCommand,"rollback",100,"health_check_failed"); sendCommandResult(pendingCommand,"failed","rollback","New firmware failed health verification and was rolled back");
    cfg.preferences->remove("ota_pending"); cfg.preferences->remove("ota_cmd"); cfg.preferences->remove("ota_target"); cfg.preferences->remove("ota_previous"); cfg.preferences->remove("ota_attempts"); rollbackDetected=false;
  }
}

void otaLoop() {
  if (pendingVerification && static_cast<int32_t>(millis()-healthDeadline)>=0) esp_ota_mark_app_invalid_rollback_and_reboot();
}

bool otaIsPendingVerification() { return pendingVerification; }
