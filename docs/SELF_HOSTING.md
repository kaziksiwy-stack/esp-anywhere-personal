# Self-hosting

Normal users do not need this. A backend administrator deploys the Worker, configures ESP_ANYWHERE_INSTALLATION, and sets a long random Wrangler ADMIN_TOKEN. It is used only to bootstrap HA and is never exposed to HA users or provisioning pages.

After HA claims its code, its role token prepares device-only codes for its own installation. Tailscale is not required.
