# Activation Flow

1. Operator wywołuje `POST /admin/activation-code` z `Authorization: Bearer <AdminToken>`. Określa docelową instalację (`installation_id`) i rolę (`home_assistant` / `device`).
2. API wypluwa kod w strukturze `ID_INSTALACJI:SEKRET_LOSOWY` o czasie życia np. 10 minut.
3. Kody przepisujemy (np. do pliku konfiguracyjnego Config Flow dla HA lub config.h z firmware ESP).
4. Home Assistant w config_flow robi po cichu `POST /claim` z użyciem przepisanego kodu.
5. Jeżeli kod jest poprawny i nie wygasł: baza usuwa go z użycia, a klient otrzymuje docelowy permanentny `token`. Claim urządzenia przekazuje także `device_id`, z którym token zostaje trwale związany.
6. Proces zapisuje się w Config Entries i transport loguje się na `/ws` autoryzując się nowym tokenem.
7. `performClaim()` w kodzie ESP32 zapisuje token, `installation_id` i `device_id` w NVS; jednorazowy kod nie jest ponownie używany po restarcie.
