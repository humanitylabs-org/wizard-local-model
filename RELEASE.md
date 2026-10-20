# Image release handoff

Source repo: `humanitylabs-org/wizard-local-model`, GPL-3.0-only.
Runtime build context is this repo (`Dockerfile`, `app/`, `web/`, `openapi.json`, LICENSE). Tests are stdlib-only. The pinned Python and llama.cpp digests are OCI indexes supporting amd64/arm64; model GGUF source revisions, byte sizes and SHA256s are in `app/server.py` (queried from Hugging Face's real blob metadata).

Follow `humanitylabs-org/wizard-app-store/images/CONNECTION_RELEASE.md`:

1. Review/merge the **app PR** only with owner/coordinator approval; this lane does not merge or publish.
2. Either copy the runtime context **unchanged** to Store `images/wizard-local-model/` plus an image-specific workflow and provenance row, or dispatch this repo's workflow from approved main. Do not create a competing public app-index entry. Store-copy should preserve runtime/test bytes; name the exact upstream commit in its provenance row.
3. PR CI runs tests without publishing. A manual publish from main requires the explicit `publish` boolean and a fresh semver version equal to wizard.md/config/Dockerfile. It refuses an existing version tag. Build amd64+arm64, push to `ghcr.io/humanitylabs-org/wizard-local-model:<version>` once, record the real multiarch digest, then rerun container and Thales real-model checks against that image. Never repush a version or use `latest` as an install reference.
4. Replace `LOCAL_MODEL_IMAGE` with `ghcr.io/humanitylabs-org/wizard-local-model:<version>@sha256:<real digest>` in the reviewed app recipe/release. There is **no fabricated app digest or claimed published image in this branch**. Current recipe refuses to start unless operator supplies the reviewed image value. Local tags are only for isolated testing.
5. No live install, Agent Service cutover or owner update approval is performed by the image workflow. App Manager updates still require owner's yes. A successful source check is not proof the Store image exists or a test box installed it.

## Remaining release gates

- Durable Thales acceptance receipt at the tested pushed commit and real model download/inference (not fixture responses).
- Installed-shell Appearance QA on two skins and mobile/desktop, or explicitly narrower hosted-proxy evidence.
- Private provider integration with the Agent Service / in-seal passthrough client from the sibling lanes.
- New image published by approved workflow and returned digest pinned in the installation recipe; current source-only candidate is not Store-listable yet.
- Coordinator resolves the spec's local-egress sentence against the explicitly requested first-download/owner-tailnet network exception documented in README.
