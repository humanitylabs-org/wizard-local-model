---
name: wizard-local-model
description: Read sealed local-model readiness; reprovision weights through WAM.
---

# Local model connection

Read `GET /api/connection` on the app's main port 18805. This returns `wizard.ai-connection/1`, including `{id,label}` model choices, mode and download progress. No credentials are needed for the model itself. The app is not a public inference API.

Only **On this box** is supported. Remote-machine/tailnet mode is disabled. Changing or retrying weights is a WAM install/upgrade provisioning operation: the one-shot provisioner downloads immutable SHA256-pinned artifacts into the weights volume, writes the ready marker, and exits before sealing. Provider and llama.cpp share one offline container with read-only weights. Never attach the provider to the downloader's public network, configure a local egress proxy, or invent a remote endpoint. Startup verifies SHA256; token minting must return visible private_provider_unavailable until marker/model readiness.

Agent Service integration: main-port access grants only the runtime-owned ingress edge (exact +3 address on an attached 10.253/16 subnet), loopback, and optional installer-pinned exact controller/proxy IPs in `WIZARD_OWNER_PEERS`; never trust a whole shared Docker subnet. The trusted proxy must enforce owner access. Call `POST /api/private-clients {"agent":"<id>"}` on port 18805 with trusted Host, configured trusted Origin and `X-Wizard-Request: 1` (same gate as settings writes). Store the returned bearer outside the agent home; only its hash persists here. Re-POST rotates; `DELETE /api/private-clients/<id>` revokes. Attach provider to runtime-managed `wizard-relay-wizard-local-model`, internal subnet in `10.252.0.0/16`, alias `wizard-local-model-relay`. Relay 8090 admits only peers in the subnet of its actual pool interface and requires the bearer for model/chat endpoints. Health needs the subnet but not the bearer. Use the `passthrough` in-seal client; never connect Hermes directly or give it internet.

Do not expose 8090 to the host or public network. Never request or repeat a relay token in chat. No cloud fallback: provider stop, invalid token or offline model must fail visibly.
