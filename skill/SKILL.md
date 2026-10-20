---
name: wizard-local-model
description: Read local-model provider status and configure a private model in the owner settings view.
---

# Local model connection

Read `GET /api/connection` on the app's main port 18805. This returns `wizard.ai-connection/1`, including `{id,label}` model choices, mode and download progress. No credentials are needed for the model itself. The app is not a public inference API.

Direct the owner to the settings view to choose **On this box** or **Another machine**; never invent an upstream address. Another machine must resolve to Tailscale IPv4/IPv6 addresses. That machine is now inside your private boundary and can see prompts. Saved connection settings are private app data.

Agent Service integration: call `POST /api/private-clients {"agent":"<id>"}` on port 18805 with trusted Host, configured trusted Origin and `X-Wizard-Request: 1` (same gate as settings writes). Store the returned bearer outside the agent home; only its hash persists here. Re-POST rotates; `DELETE /api/private-clients/<id>` revokes. Attach provider to runtime-managed `wizard-relay-wizard-local-model`, internal subnet in `10.252.0.0/16`, alias `wizard-local-model-relay`. Relay 8090 admits only peers in the subnet of its actual pool interface and requires the bearer for model/chat endpoints. Health needs the subnet but not the bearer. Use the `passthrough` in-seal client; never connect Hermes directly or give it internet.

Do not expose 8090 to the host or public network. Never request or repeat a relay token in chat. No cloud fallback: provider stop, invalid token or offline model must fail visibly.
