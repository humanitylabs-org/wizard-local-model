---
wizard: 0.2
id: wizard-local-model
name: Local model
type: external
category: system
version: 0.1.0
summary: Provision verified weights, then run a sealed private model on this box.
tags: [security, ai]
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-local-model
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 18805
  path: /api
  spec: openapi.json
skill: skill/SKILL.md
view:
  path: /
  port: 18805
  source:
    path: web
    dist: web
provides: [ai-connection, private-inference]
private_inference:
  kind: local
  relay_port: 8090
  egress: []
  provisioning_service: provision
  weights_ready: /models/ready.json
  owner_peer_policy: runtime-ingress
  model_artifacts:
    - id: qwen2.5-1.5b
      url: https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf
      sha256: 6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e
    - id: qwen2.5-3b
      url: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/7dabda4d13d513e3e842b20f0d435c732f172cbe/qwen2.5-3b-instruct-q4_k_m.gguf
      sha256: 626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d
    - id: qwen2.5-0.5b
      url: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf
      sha256: 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
system: true
uses: []
needs: []
health: /healthz
---

# Local model
App Manager runs the one-shot provision service before the provider starts. It downloads the selected pinned GGUF into a named weights volume, verifies SHA256, atomically writes /models/ready.json, and exits. The provisioner never joins the relay or mounts provider-private data. The sealed provider runs llama.cpp on loopback in the same container, mounts weights read-only, and has no internet, DNS resolver or egress proxy. Token minting and model discovery fail closed until the marker and verified model are ready. Runtime grants owner access only to its dedicated ingress edge (10.253.x.3 on an actually attached interface); relay/client peers are never owners. Remote owner-machine mode is disabled and is a follow-up, not an advertised capability. No cloud fallback, conversation persistence or body logs.
