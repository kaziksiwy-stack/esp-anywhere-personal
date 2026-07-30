# Activation Flow

1. Operator wywołuje `POST /admin/activation-code` z `Authorization: Bearer <AdminToken>`. Określa docelową instalację (`installation_id`) i rolę (`home_assistant` / `device`).
2. API wypluwa kod w strukturze `ID_INSTALACJI:SEKRET_LOSOWY` o czasie życia np. 10 minut.
3. Kody przepisujemy (np. do pliku konfiguracyjnego Config Flow dla HA lub config.h z firmware ESP).
4. Home Assistant w config_flow robi po cichu `POST /claim` z użyciem przepisanego kodu.
5. Jeżeli kod się zgadza i wygasa: baza usuwa go z użycia, HA otrzymuje docelowy permanentny `token`.
6. Proces zapisuje się w Config Entries i transport loguje się na `/ws` autoryzując się nowym tokenem.
7. To samo zachowanie implementuje `performClaim()` w kodzie C++ ESP32.
