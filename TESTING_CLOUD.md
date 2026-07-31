# Instrukcja testowa

Dla testów E2E użyj skryptu umieszczonego w `tests/e2e_test.py`.
Pamiętaj by uprzednio sklonować plik `.dev.vars` w workerze.
```bash
cd worker
cp .dev.vars.example .dev.vars
npx wrangler dev
```

Następnie na wybranym środowisku terminala odpal pełen cykl z flagą `--mode e2e` i podaj `testadmin` jako kod master:
```bash
python tests/e2e_test.py --mode e2e --ws-url ws://localhost:8787 --http-url http://localhost:8787 --admin-token testadmin --install-id instalacja-test-1 --device-id urzadzenie-test-1
```
