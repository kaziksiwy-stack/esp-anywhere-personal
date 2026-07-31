# Security policy

Report vulnerabilities privately through GitHub Security Advisories. Never include live tokens, codes, Wi-Fi credentials or unredacted logs in issues.

After exposure rotate ADMIN_TOKEN; clear NVS and re-provision affected devices; recreate an HA entry if its token leaked. Administrator bootstrap codes expire in 10 minutes; HA-issued device codes and opaque provisioning sessions expire in at most 5 minutes. The HA endpoint returns device configuration once and then clears its in-memory activation code. Treat a provisioning link as a short-lived bearer secret.
