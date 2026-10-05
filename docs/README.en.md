# Persona AI

A relationship conversation assistant that remembers the people and experiences you choose to save.

**Status:** local invite-beta implementation. Public hosting, live-model quality review and real-user studies remain pending. Mock evaluation is not evidence of advice quality.

## Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[beta,mcp,test]'
.venv/bin/python persona_app.py
```

Open http://127.0.0.1:8770/, switch to English, create an account and add a person. Only the nickname is required. Accounts and confirmed person memories are independent; legacy local data is never auto-assigned.

To configure a model, run `.venv/bin/python scripts/configure_model.py`, enter an authorized key locally, then restart. The script writes an ignored, mode-0600 `.env`; users do not see provider settings.

## What is implemented

One checkpointed agent workflow with person profiles, confirmed event memory, bounded retrieval, source-aware answers, optional academic search and rehearsal. User accounts use opaque HttpOnly sessions, scrypt password hashing, CSRF and origin checks. Each resource is authorized on the server. Durable jobs support leases, idempotency and resume; budgets count every actual model attempt, including retries.

Retrieval uses registered names/aliases and scoped lexical ranking, not vectors. Character creation means profiles of people, not independent autonomous agents or accurate digital replicas. Astrology is metadata, not behavioral evidence. Simulations are not real events.

Correction invalidates old conversational context. Deletion conservatively removes related chats to prevent deleted information from being reused. This trades continuity for clear memory control; the UI explains the consequence before deletion.

## Evidence and remaining work

Run `python -m unittest discover -s tests -p 'test_*.py' -v` and `python evals/persona_eval.py`. Forty synthetic bilingual multi-turn cases compare chat-only and person-memory variants. Human ratings remain blank until reviewed. Local QA users and UI feedback are synthetic.

Production requires PostgreSQL, HTTPS, an invitation code, server-side model credentials, configured model prices, a privacy contact, validated backups and completed launch checks. Deployment manifests and CI are supplied; no paid cloud account has been created or charged.

See [deployment](deployment.md), [architecture](persona-architecture.md), [evaluation](evaluation.md), and [release status](release-status.md).

## Verification

90 independent local tests passed. [GitHub CI](https://github.com/y011124/relationship-agent/actions/runs/37314361389) passed on Python 3.10/3.12, PostgreSQL 17, Docker and Chromium browser flows. All fixtures are synthetic; no live-model quality or real-user outcome is claimed.
