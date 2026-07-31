# Testowanie na Home Assistant OS

Ten dokument opisuje jak zainstalować eksperymentalną gałąź zawierającą połączenie WebSocket dla Cloudflare na rzeczywistej instancji Home Assistant OS i przetestować funkcjonalność przy użyciu symulatora urządzenia.

## 1. Uruchomienie lokalnego Workera
Wejdź do katalogu worker/ w sklonowanym repozytorium na Twoim PC, upewnij się, że masz połączone konto przez `npx wrangler login` (lub pracuj na dev).
```bash
cd worker
npm install
npx wrangler dev
```
Worker domyślnie nasłuchuje pod adresem http://localhost:8787. Zapisz docelowy publiczny adres (jeśli zrobiłeś `wrangler deploy` to użyj przyznanej domeny `.workers.dev`).

## 2. Kopiowanie integracji na HAOS
Skorzystaj z dedykowanego skryptu ułatwiającego kopiowanie plików do serwera. Skrypt automatycznie wykona bezpieczny backup poprzedniej wersji. Użyj SSH lub bezpośredniej ścieżki do plików z HA (np. dla Home Assistant OS to typowo `/config` podmontowane przez sambę lub SSH root login).
```bash
# Jeśli dostęp jest lokalny (np. dev container)
./scripts/install_to_haos.sh /config

# Jeśli używasz SCP/SSH do maszyny z HAOS (zamień IP i użytkownika)
./scripts/install_to_haos.sh root@192.168.1.10:/config
```
Po udanym skopiowaniu przejdź do panelu HA (Settings -> System -> Restart) i zrestartuj serwer Home Assistant, by przeładował nową wersję z custom_components.

## 3. Konfiguracja w Config Flow
W interfejsie przeglądarki Home Assistant:
1. Przejdź do Settings -> Devices & Services.
2. Kliknij Add Integration i znajdź "ESP Anywhere Personal".
3. W kroku transportu pozostaw domyślne `cloudflare_websocket`.
4. Wpisz odpowiednie zmienne:
   * **Relay URL**: `ws://<IP_twojego_komputera>:8787` (lub wss:// z cloudflare/ngrok, jeśli przetestowano w sieci izolowanej od LAN)
   * **Installation ID**: `test-home-1`
   * **Token**: (Dowolny, ustalony do testów, np. `sekret-123`)

## 4. Uruchomienie symulatora urządzenia (device-only)
Na maszynie deweloperskiej wywołaj tryb symulatora. Ten moduł wcieli się w testowe urządzenie "dev_001", wysyłając Discovery i czekając na odpowiedź.
```bash
python tests/e2e_test.py --mode device-only --ws-url ws://localhost:8787 --token sekret-123 --install-id test-home-1 --device-id dev_001
```

## 5. Oczekiwane zachowanie
- W konsoli HA (logach) powinieneś zauważyć poprawne połączenie klienta Websocket.
- Na dashboardzie HA powinna pojawić się nowa encja w sekcji urządzenia dla "ESP Anywhere Personal". Pojawią się: sensor ("Test Sensor") i switch ("Test Switch").
- Sensor będzie cyklicznie inkrementować licznik wartości co ~10 sekund.
- Przełączenie Switcha w interfejsie HA wyśle event (komendę), terminal wykonujący `e2e_test.py` odbierze polecenie z "succeeded", a interfejs w HA zaktualizuje stan suwaka prawidłowo.

## 6. Przywracanie kopii zapasowej
Backupy znajdują się w `/config/esp_anywhere_backups`, poza katalogiem aktywnych integracji. Aby przywrócić wersję, zatrzymaj HA Core, skopiuj wybrany backup do `/config/custom_components/esp_anywhere`, a następnie uruchom Core.
