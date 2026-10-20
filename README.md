# Local model for Wizard OS

Private model provider for Wizard OS: run a model on your box or your own machine.
GPL-3.0-only. **Candidate app: review branch only, not a published Store release.**

## Two modes

- **On this box** (default): app downloads a curated, SHA256- and revision-pinned GGUF into its models volume. Default: Qwen2.5 1.5B Instruct Q4_K_M (~1.12 GB); 3B (~2.10 GB) and a 0.5B (~491 MB, useful for tests) are alternatives. Progress is shown in Settings. Bad/partial downloads are discarded, not loaded. Startup verifies saved weights before serving. llama.cpp runs on an **internal-only network**, with the models volume read-only, non-root, read-only rootfs and no capabilities. It has no internet. Changing model restarts the model process without Docker socket access. First download/loading may take minutes; readiness lists actual server models, not an invented successful response.
- **Another machine**: enter your own OpenAI-compatible `/v1` base URL in Settings. Its DNS must resolve only to Tailscale IPv4 `100.64.0.0/10` or IPv6 `fd7a:115c:a1e0::/48`. IPs are validated and pinned for each connection, TLS validates the original name, redirects are never followed, URL credentials/queries/fragments are rejected. Hostnames, IPs and ports are owner **settings**, not source. **That machine is now inside your private boundary.** It and its administrator can see prompts. It must not itself route to a cloud model. This app cannot audit another machine's retention or egress.

The local provider sees plaintext by design (unlike an attested relay). The app never logs or persists request/response bodies or plaintext client tokens. It forwards tools and SSE without modifying chat JSON. No upstream availability/auth/network failure uses a cloud fallback.

### Provisioning and tailnet networking exception

The model server is permanently offline; the **app container** needs internet to fetch curated weights on first start/selection and reach an owner tailnet endpoint in remote mode. `owner-provisioning` is an ordinary Compose network, attached only to the app. `model-private` is `internal: true`, shared only by app + model. No model or relay port is published in the production recipe. Runtipi publishes the owner view port 18805 through its main-service handling.

`private_inference.egress: []` declares **no cloud inference provider**, not a claim that the downloader network is physically offline. This requested first-start-download design is a provisioning exception to the spec's blanket "local has no egress network" sentence. It is explicit rather than silently divergent: a deployment enforcing zero app egress must preseed verified weights and remove downloader egress after provisioning, and supply a private owner-tailnet route for remote mode. No broad firewall allowlist is implemented by this app. Its downloader contacts Hugging Face and its signed blob CDN; no conversation bytes are sent there. The acceptance runner proves the model container itself cannot reach DNS-named or numeric public destinations.

## Install / image recipe

1. Build the reviewed commit using `Dockerfile` (stdlib Python; pinned multi-arch Python base). Production publishing follows `RELEASE.md` and the Store's `images/CONNECTION_RELEASE.md` convention: no separate public Store entry until reviewed; runtime bytes copied unchanged into an image build context; test on PR, publish a new immutable version after merge approval.
2. Set `LOCAL_MODEL_IMAGE=ghcr.io/humanitylabs-org/wizard-local-model:<new-version>@sha256:<real-index-digest>` to the **real published digest**. Compose deliberately fails without a value rather than claiming an image exists. The llama.cpp image is pinned to a real multi-architecture digest. No provider image is published by this PR.
3. Configure `WIZARD_OWNER_PEERS` (comma-separated exact trusted proxy/controller source IPs, no CIDRs), `WIZARD_TRUSTED_HOSTS` (exact host:port values) and `WIZARD_TRUSTED_ORIGINS` (exact shell/control origins) for your owner route. Blank peer configuration admits **only loopback**; the externally published settings view/control API fail closed until the installer pins the trusted source. Never trust a whole Runtipi bridge or infer owners from the default route. The trusted proxy/controller must itself enforce owner/box-only access; Origin headers are CSRF controls, **not authentication of arbitrary clients passing through an open proxy**. Forwarded/tailnet identity headers are rejected. Trusted shell origins also drive CSP `frame-ancestors`.
4. Install via the app manager, or exercise the recipe using Compose. Named volumes use Compose project scoping so isolated tests cannot touch a live install. Model selection and remote address live in `settings.json` inside private app data; token hashes live in `clients.json` (0600).

Manual build (not inference):

```sh
docker build -t pp-test-local-model:review .
LOCAL_MODEL_IMAGE=pp-test-local-model:review docker compose -p pp-test-local-model -f runtipi/docker-compose.yml up -d
# Owner UI publication is supplied by Runtipi; for manual testing use an explicit loopback port override.
```

Local tags are **test-only**, never a production substitute for a digest. Docker/Compose downloads the pinned llama image even in remote mode; that container waits idle if no local model has been selected/downloaded. Settings switch relay routing immediately and do not require a Docker restart. Stopping a provider/model fails visibly; no external failover.

## Runtime contract

`wizard.md` advertises `provides: [ai-connection, private-inference]`, kind `local`, relay 8090, `egress: []`. Main port 18805:

| Route | Behavior |
|---|---|
| `GET /api/connection` | `wizard.ai-connection/1`, actual chat models as `{id,label}`, mode/boundary/readiness/download |
| `GET /api/status` | Same snapshot for Settings |
| `POST /api/settings` | Exact `{mode,model,base_url}`; trusted Origin + `X-Wizard-Request: 1` |
| `POST /api/private-clients` | `{agent}` → 200 `{token,relay_url}`; 48 random bytes urlsafe; rotates per-agent token |
| `DELETE /api/private-clients/<agent>` | 204, idempotent revocation |
| `GET /healthz` | App-process health (not proof weights are ready) |

Owner writes use the **same trusted Host + exact Origin + non-simple request-header gate** as the Tinfoil connection's key-save route, not a relay bearer. In addition, the control port admits only loopback or explicitly pinned `WIZARD_OWNER_PEERS`, never the subnet of a default/shared Docker route. Peers in `10.252.0.0/16` are denied even if mistakenly configured as trusted. Model/other-app clients cannot gain owner authority by spoofing browser headers. Every control response closes the connection, so rejected bodies cannot smuggle a second trusted request. Agent Service must connect from a pinned controller address and send configured owner Host/Origin and `X-Wizard-Request: 1`. It stores the returned client token outside the agent's home and uses the passthrough in-seal client. No token belongs in chat, Compose or an agent `.env`.

The runtime creates `wizard-relay-wizard-local-model` (`internal`, one `/24` in `10.252.0.0/16`) and attaches the provider app with alias `wizard-local-model-relay`. It owns creation/cleanup; this app does not mount the Docker socket. Port 8090 derives allowed subnets from **actual container interfaces**, not caller headers or an environment override. Peers must be in the specific attached pool subnet; being elsewhere in `10.252/16` is insufficient. Then `GET /v1/models` / `POST /v1/chat/completions` require the bearer. `GET /healthz` needs the correct subnet but no bearer. Client auth and metadata are stripped before upstream. Unsupported paths return 404; no arbitrary URL proxy. Invalid/revoked auth → 401; disallowed peer → 403; unavailable upstream → sanitized 502. Mid-stream failure closes the stream, never retries.

## Verification

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/appearance.js
git diff --check
```

Fixtures prove HTTP/control/auth/stream/no-logging behavior, **not real model quality, egress or inference**. `tests/integration_thales.py` is the isolated actual-model acceptance runner: stage this exact pushed revision under an external-volume workdir and have the coordinator submit it to the durable Thales worker. It builds the app, downloads the tiny GGUF in the app, proves bearer-authenticated stream and non-stream inference on the runtime-style internal relay network, denies a non-relay peer, checks the model's sole network is internal and two real internet connects fail, tests owner-machine mode against existing Ollama (if populated) or the same llama through a disposable tailnet listener, stops the model to prove fail-closed behavior and scans app logs/data for a randomized probe/token. All names use `pp-test-`; cleanup removes its own containers/networks/volumes/image. No live install is edited. No tokens or completion bodies appear in the receipt.

`tests/appearance_qa.mjs` is a same-origin hosted test harness with explicit status fixtures, not a live installation. Install Playwright outside the production app (or point `PLAYWRIGHT_MODULE` at an existing package) and set `CHROME_PATH` if using an installed Chrome. It stores browser profiles/screenshots under the checkout's ignored `evidence/` on the external volume. Physical-device and real installed-shell checks must be reported separately. The page consumes Appearance v1 and retains drafts across skin updates; standalone stays dark.
