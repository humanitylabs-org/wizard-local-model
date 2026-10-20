---
wizard: 0.2
id: wizard-local-model
name: Local model
type: external
category: system
version: 0.1.0
summary: Run a private model on this box or on your own machine.
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
system: true
uses: []
needs: []
health: /healthz
---

# Local model
Choose On this box for an offline model container, or Another machine for a model server on your tailnet. That machine is now inside your private boundary. There is no cloud inference fallback. Conversation bytes are forwarded but never stored or logged by this provider.
