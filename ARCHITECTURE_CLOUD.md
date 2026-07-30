# Architektura ESP Anywhere Cloud

ESP Anywhere Cloud tworzy wydzielony, skalowalny tunel komunikacyjny między instalacją Home Assistanta a zbiorem kompatybilnych sprzętowo urządzeń, operując bez scentralizowanego brokera typu PubSub/MQTT.

## Główne założenia (Top 15 punktów)

1. **Jeden Durable Object per Instalacja HA**: Stan dla jednego gospodarstwa i powiązanych z nim urządzeń rezyduje wyłącznie w dedykowanej klasie `InstallationDO`.
2. **WebSockets + TLS**: Transport od urządzenia, poprzez Worker, aż do instancji Home Assistanta realizowany jest za pomocą bezpiecznych stałych kanałów WebSocket (wss://).
3. **Provisioning - Kody aktywacyjne**: Uwierzytelnianie startowe opiera się na krótkotrwałych "Activation Codes" generowanych przez uprzywilejowany endpoint `/admin/activation-code`.
4. **Provisioning - Claim HTTP API**: Code zostaje jednorazowo skonsumowany przez proces POST na `/claim`, który rzuca stałe tokeny przypisane konkretnej roli (HA lub Device).
5. **Autoryzacja w Transporcie**: Token wprowadzany jest w postaci nagłówka HTTP `Authorization: Bearer <token>` lub opcjonalnie query przy nawiązywaniu WebSocketa. Urządzenie bez ważnego tokena nie zbuduje połączenia.
6. **Izolacja Routingowa**: DO nasłuchuje komunikatów. Urządzenie wysyła `discovery`, `state` i odpowiedzi do DO, a DO przerzuca to bezpośrednio na zapięty kanał rurki `home_assistant`.
7. **Brak Cross-Contamination**: Rolą urządzenia "Device" jest brak dostępu do nasłuchu dla obcych urządzeń w tej samej Instalacji. Role nie mogą się podszywać.
8. **Asynchroniczny Reconnect HA**: W przypadku restartu Core Home Assistanta, po powrocie połączenia WebSocket, Durable Object natychmiast zrzuca zarejestrowane wcześniej w pamięci (`this.state.storage`) definicje "discovery" i "states" dołączając flagi obecności (Presence), budując natychmiast w locie encje z zachowaniem parametrów.
9. **Kolejkowanie Komend**: Jeśli HA wysyła `command` do `deviceId`, worker targetuje tylko dedykowany dla tego ID socket.
10. **Walidacja Payloadu JSON**: Zbyt duże, puste, i nieskategoryzowane wiadomości (powyżej 32KB lub z błędnym drzewem JSON) są wyciszane po stronie Workera bez ubijania sesji.
11. **Minimalizm Zależności**: Rozwiązanie działa na natywnym `aiohttp` z Home Assistanta i `WebSocketsClient` dla ESP, redukując wagę flash firmware'u.
12. **Konfiguracja "Config Flow"**: Cloudflare Transport dodano jako natywną opcję instalatora UI (Home Assistant), zrywając całkowicie z plikami YAML na rzecz konfiguracji sieciowej i podawania jednorazowego kodu.
13. **Kompatybilność z MQTT (Hybryda)**: Klasa `websocket_client.py` abstrakcyjnie podszywa się pod natywną komunikację ustandaryzowaną przez pierwotny `mqtt_client.py`, bez żadnej ingerencji w parser `runtime.py`.
14. **Ed25519 OTA**: Firmware strumieniowany jest przez HTTPS. Aktualizacja uruchamiana jest z HA paczką WebSocket zawierającą Manifest podpisany z wykorzystaniem mechaniki rfc8785 Ed25519 (bezpieczeństwo łańcucha uaktualnień).
15. **Stateless Edge**: Rozmiar zasobów utrzymywany w edge node jest minimalny, oparty w stu procentach na v8 isolates od Cloudflare Workers.
