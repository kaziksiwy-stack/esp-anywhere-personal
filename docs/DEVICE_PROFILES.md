# Device profiles

Official profiles live in custom_components/esp_anywhere/device_profiles.json; HA UI and firmware build read this single catalog.

Every entry defines ID, name, platform, board, flash layout, LED pin/polarity, USB mode and compatible artifact. v0.3.0 supports esp32-c3-devkitm-1: native USB CDC, huge_app.csv, GPIO 8 active-low.

New boards require a reviewed entry, matching factory build, Web Serial test, LED validation and release-gate coverage.
