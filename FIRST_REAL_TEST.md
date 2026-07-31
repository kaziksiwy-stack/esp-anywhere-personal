# First real LAN test

Ta procedura testuje wyłącznie przepływ ESP32-C3 ↔ lokalny Worker ↔ Home
Assistant OS. Worker działa po jawnym `http://` i `ws://` w zaufanej sieci LAN.
OTA nie jest częścią testu.

Wartości używane w procedurze:

- Lenovo/Worker: `192.168.1.59:8788`
- instalacja: `first-real-test`
- urządzenie: `esp32_c3_001`
- HAOS: zastąp `IP_HA` adresem Della
- ESP32: zastąp `/dev/ttyUSB0` właściwym portem

## A. Lenovo — Worker i provisioning

1. Potwierdź adres LAN Lenovo:

   ```bash
   hostname -I
   ```

   Dell z HAOS i ESP32 muszą mieć dostęp do `192.168.1.59:8788`. Jeśli Lenovo
   ma firewall, dopuść TCP 8788 wyłącznie z lokalnej sieci.

2. Ustaw lokalny sekret administratora:

   ```bash
   cd /home/piotr/esp-anywhere-personal/worker
   cp .dev.vars.example .dev.vars
   chmod 600 .dev.vars
   editor .dev.vars
   ```

   Zastąp przykładową wartość `ADMIN_TOKEN` długim losowym sekretem. Plik
   `.dev.vars` jest ignorowany przez Git.

3. Uruchom Workera w pierwszym terminalu i pozostaw go uruchomionego:

   ```bash
   cd /home/piotr/esp-anywhere-personal/worker
   npx wrangler dev --ip 0.0.0.0
   ```

   `worker/wrangler.toml` ustawia lokalny port `8788` i protokół HTTP. Nie
   uruchamiaj tunelu ani `wrangler deploy`.

4. W drugim terminalu wczytaj ten sam sekret bez zapisywania go w historii
   poleceń i wygeneruj kod HA:

   ```bash
   cd /home/piotr/esp-anywhere-personal
   read -rsp 'ADMIN_TOKEN: ' ADMIN_TOKEN; echo
   ./scripts/create_activation_code.sh \
     http://192.168.1.59:8788 "$ADMIN_TOKEN" first-real-test ha
   ```

   Skopiuj wartość `activation_code`. Nie zapisuj jej w repozytorium.

5. Wygeneruj osobny kod urządzenia:

   ```bash
   ./scripts/create_activation_code.sh \
     http://192.168.1.59:8788 "$ADMIN_TOKEN" first-real-test device esp32_c3_001
   unset ADMIN_TOKEN
   ```

   Skopiuj wartość `activation_code` do przygotowywanego lokalnie `config.h`.
   Helper nie wypisuje tokenów permanentnych.

## B. Dell — Home Assistant OS

1. Z Lenovo zainstaluj integrację. Dla standardowego portu SSH:

   ```bash
   cd /home/piotr/esp-anywhere-personal
   ./scripts/install_to_haos.sh root@IP_HA:/config
   ```

   Dla niestandardowego portu, np. 2222:

   ```bash
   ./scripts/install_to_haos.sh root@IP_HA:/config 2222
   ```

   Skrypt tworzy backup istniejącej integracji, kopiuje pliki, weryfikuje
   `websocket_client.py`, `relay_url.py`, `config_flow.py` i `manifest.json`.
   Nie restartuje Home Assistanta.

2. Zrestartuj Home Assistant ręcznie w **Settings → System → Restart**.

3. Otwórz **Settings → Devices & services → Add integration**, wybierz
   **ESP Anywhere Personal**, a następnie transport Cloudflare WebSocket.

4. Wpisz:

   - relay URL: `http://192.168.1.59:8788`
   - activation code: kod HA z kroku A.4

   Config Flow wykona `POST /claim`, zapisze permanentny token w ConfigEntry i
   nie zapisze activation code. Klient HA połączy się pod
   `ws://192.168.1.59:8788/ws`.

5. Oczekiwany wynik: integracja zostaje dodana bez `cannot_connect`,
   `invalid_code` ani timeoutu. W razie błędu sprawdź **Settings → System →
   Logs** oraz terminal `wrangler dev`. Kod jest jednorazowy — po udanym claim
   nie używaj go ponownie.

## C. ESP32-C3

1. Utwórz ignorowany przez Git plik konfiguracji:

   ```bash
   cd /home/piotr/esp-anywhere-personal/esp32_client
   cp include/config.example.h include/config.h
   editor include/config.h
   ```

2. Ustaw dokładnie:

   ```cpp
   #define WIFI_SSID "TWOJA_SIEC"
   #define WIFI_PASSWORD "TWOJE_HASLO"
   #define RELAY_URL "http://192.168.1.59:8788"
   #define INSTALLATION_ID "first-real-test"
   #define ACTIVATION_CODE "KOD_Z_KROKU_A_5"
   #define DEVICE_ID "esp32_c3_001"
   #define LED_PIN 8
   #define LED_ACTIVE_LOW true
   ```


3. Wykonaj czysty build, upload i monitor:

   ```bash
   /home/piotr/.platformio/penv/bin/platformio run --target clean
   /home/piotr/.platformio/penv/bin/platformio run
   /home/piotr/.platformio/penv/bin/platformio run \
     --target upload --upload-port /dev/ttyUSB0
   /home/piotr/.platformio/penv/bin/platformio device monitor \
     --port /dev/ttyUSB0 --baud 115200
   ```

4. Przy pierwszym starcie oczekuj komunikatów:

   ```text
   Performing claim...
   Claim successful; credentials stored.
   [WS] Connected
   ```

   Log nie może zawierać activation code ani tokenu. Po claim token,
   `installation_id` i `device_id` są zapisane w NVS.

## D. Test funkcjonalny i reconnect

1. W HA poczekaj na urządzenie **ESP32 C3 Test Device** oraz dokładnie dwie
   encje: sensor uptime i switch LED.
2. Przełącz switch w HA. Stan GPIO `LED_PIN` i encji powinien się zmienić.
3. Zrestartuj ESP32 przyciskiem reset. Nie zmieniaj `config.h` i nie generuj
   nowego kodu. Oczekuj `[WS] Connected` bez `Performing claim...`; uptime
   zacznie ponownie od małej wartości.
4. Zrestartuj Home Assistant. Po uruchomieniu integracja użyje tokenu z
   ConfigEntry, połączy się ponownie, a Worker odtworzy discovery/state.
5. Ponownie przełącz LED i potwierdź aktualizację uptime.

## E. Rollback

1. Usuń lub odsuń bieżący katalog integracji na HAOS i przywróć ścieżkę backupu
   wypisaną przez instalator, następnie ręcznie zrestartuj HA.
2. Zatrzymaj lokalnego Workera przez `Ctrl+C` w terminalu Lenovo.
3. Credentials ESP kasuj tylko serwisowo: tymczasowo wywołaj
   `resetDeviceCredentials()` bezpośrednio po `preferences.begin(...)`, wgraj
   firmware jeden raz, następnie usuń wywołanie i ponownie wgraj normalny
   firmware. Funkcja nie uruchamia się automatycznie.
