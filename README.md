# Local model for Wizard OS

Private on-box inference. GPL-3.0-only. Review candidate, not a published Store image.

## Provision, then seal

1. WAM `private.prepare` compiles the recipe and an internal-bootstrap network override. Runtipi must **not** add the main service to its implicit public shared network. WAM refuses unsafe bootstrap networks or conflicting owner overrides.
2. `provision` runs once on its ordinary provisioning network, before provider startup (`service_completed_successfully`). It has only the named weights volume: no relay, tokens, private data or prompt listener. Exact immutable Hugging Face URLs/SHA256 pins are in `wizard.md` and `app/artifacts.py`. Selected model comes from install-time `DEFAULT_MODEL` (default Qwen2.5 1.5B, alternatives 3B or tiny 0.5B for tests). It verifies size and SHA256, atomically writes `ready.json`, and exits. Failure removes stale readiness and partial files. Restarts verify/reuse good weights without downloading again.
3. A single sealed runtime container runs the Python provider and pinned llama.cpp server. llama listens only on loopback. Weights are mounted read-only; both processes are non-root with read-only rootfs, no capabilities, no-new-privileges. The provider initially has only an internal bootstrap network; runtime later replaces it with its owned relay and provider-ingress networks, both internal. `egress: []` means **no proxy and no internet**; DNS is `127.0.0.1` resolver sink. No downloader network is attached to the provider, ever.
4. Startup independently verifies weights SHA256. Discovery and token mint fail closed until the marker matches and the model actually responds. Missing marker => mint HTTP 503 `private_provider_unavailable`; runtime admission exposes that failure, never falls back. Hermes enforces at least 64K served context: llama runs one 65,536-token slot with fit disabled and YaRN 2x scaling from Qwen's native 32K. This is a configured extended context, not a claim that long-context answer quality was benchmarked. A 6 GiB container memory ceiling accommodates the larger catalogue models; the tiny acceptance model uses less.

The local provider sees plaintext by design. Neither provider nor llama logs prompts/completions or stores conversation bodies. The downloader never sees them. Remote owner-machine/tailnet mode is **disabled** (API refuses, UI unavailable); separate private routing/trust design is follow-up, not this package's capability. Changing/retrying weights is a WAM install/upgrade provisioning operation, not an online settings download.

## Image / installation

Build the exact reviewed pushed source (`Dockerfile`), based on the pinned multiarch llama.cpp OCI image. Production release follows `RELEASE.md`; no fabricated/published digest is claimed. Supply `LOCAL_MODEL_IMAGE=ghcr.io/humanitylabs-org/wizard-local-model:<new-version>@sha256:<real-index-digest>`. Runtime and provisioner use that same image. Named volumes are project-scoped. For isolated testing only, a locally built tag is accepted; production must pin a real digest. Set `DEFAULT_MODEL=qwen2.5-0.5b` in WAM's persistent app.env for the tiny test artifact.

The runtime's dedicated provider-ingress edge (exact subnet address +3 in an actually attached `10.253.0.0/16` /24) is the granted controller peer. No other bridge peer is implicitly trusted. External owner-only proxies may be pinned with `WIZARD_OWNER_PEERS` exact IPs; never a whole subnet. That proxy must enforce owner access. Host/Origin + `X-Wizard-Request: 1` are additional CSRF/rebinding gates, not user authentication. Relay peers in `10.252/16` are never owners even if mistakenly pinned. Forwarded identity headers are rejected. Runtime validates the owned ingress topology; this app never mounts Docker's socket. Configure `WIZARD_TRUSTED_HOSTS`/`WIZARD_TRUSTED_ORIGINS` for the shell owner route.

## HTTP contract

Owner port 18805: `GET /api/connection` (`wizard.ai-connection/1`, actual models, `weights_ready`); `/api/status`; `/healthz` (process only, not model readiness). `POST /api/private-clients {agent}` mints/rotates a 48-byte opaque urlsafe token; hashes only in `clients.json` (0600). `DELETE /api/private-clients/<agent>` revokes. Exact `{mode,model,base_url}` settings POST accepts only the current on-box settings; changes return 409 with a reprovision message. No online download or remote URL dialing.

Relay port 8090: peers must belong to the specific actual attached interface subnet in `10.252/16`; no spoofed forwarding headers. `GET /healthz` without bearer; `GET /v1/models` and `POST /v1/chat/completions` require client bearer. Requests stream byte-for-byte, with client auth/identity stripped. Invalid/revoked tokens => 401; non-relay peers => 403; unavailable model => sanitized 502. No retry/fallback, arbitrary URL proxy, prompt logging or body persistence. Runtime holds relay tokens outside Hermes home, never in agent .env/compose.

## Verification

```
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/appearance.js
git diff --check
```

Unit HTTP fixtures are not inference proof. The milestone end-to-end run is WAM prepare/install → Agent Service private-agent create → completed Hermes run → all six disposable rig checks, plus provider egress/weights/readiness/options evidence. The previous `tests/integration_thales.py` is a **legacy two-container harness**, not valid for this recipe; use the real pp-rig lane until a standalone sealed harness is ported. No live host modifications.

`tests/appearance_qa.mjs` is a same-origin hosted proxy with explicit status fixtures (not installed-shell/device proof). Run directly on Thales with browser scratch/screenshots on ThalesMedia. It verifies desktop/mobile UA, two skins, draft preservation, disabled remote mode and root Back. The page retains the existing Appearance v1 transport/CSP and dark standalone fallback.
