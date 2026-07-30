# Protokół Websocket (Cloud)
Dokument opisuje zarys pakietów transportowanych po rurze WebSocket. Odpowiednik modelu opartego na starych topicach MQTT.

## Wiadomości z urządzenia
* `discovery` -> Tworzy model w HA. W payload znajduje się klasyczna architektura, zgodna z oryginalnym formatem ESP.
* `state` -> Regularny update lub update po command.
* `command_result` -> Informacja zwrotna wysyłana z powrotem.

## Wiadomości z Home Assistant
* `command` -> Posiada "device_id" i "command". Wysłanie `set_entity` załączy żądanie dla uC.

*Ograniczenie: Limit wiadomości 32KB. Format UTF-8 JSON.*
