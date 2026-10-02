# ylune · Relationship Agent

A local, bilingual app for ongoing emotional conversation and thinking through relationship uncertainty. Users can chat first, request a structured analysis when useful, practise a conversation, and return with real feedback. The workflow separates user accounts, model judgments and imagined dialogue.

## Run

Python 3.10+; the core application has no third-party runtime dependencies.

```sh
python3 web_app.py
```

Open http://127.0.0.1:8765. Choose English before creating a new conversation. The chat panel supports ongoing conversation; the situation panel runs the structured analysis. Demo mode uses deterministic fixtures; it does not understand arbitrary situations. Configure an authorized API key in Model settings for real conversation and analysis.

The provider presets are GLM (`glm-5.3`) and OpenAI GPT (`gpt-4.1-mini`, `https://api.openai.com/v1`). GPT requires a separate OpenAI API key. Supported protocols: Anthropic Messages and Chat Completions. For GLM-5.3, Chat Completions is the recommended default because the official documentation says some Coding Plan users can only access the model API through it. Model ID, endpoint and key can change at runtime. Keys remain in server memory and are never returned in API responses, persisted in the database, or placed in browser storage. Restarting requires reconfiguration or an environment variable. A local cap allows 20 model request attempts per server start by default; the badge shows remaining local attempts, not account balance.

When a user asks for papers or evidence, the unified chat route selects the `evidence` workflow. It prepares a short topic query, searches Semantic Scholar and OpenAlex directly, and searches Google Scholar through SerpAPI (set `SERPAPI_API_KEY`). `SEMANTIC_SCHOLAR_API_KEY` and `OPENALEX_API_KEY` are optional. Results are deduplicated and only clearly labelled abstract or search-snippet text is passed to the knowledge answer stage; provider status, citations and links are shown in the UI. The adapter does not scrape Google Scholar pages, and provider keys stay in server memory.

Every submitted message and successful reply is stored in the local SQLite database, alongside analysis, feedback and traces. There is no automatic expiry, account sync or in-app deletion yet. Only the latest 12 completed chat pairs within a 10,000-character budget are sent as conversation context; storage is broader than what the model sees on each turn.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python run_experiment.py --mode mock --language en \
  --message "We broke up and he hasn't contacted me. I wonder if he has someone else." \
  --output outputs/demo.json
```

Use --mode api with --model, --base-url, --protocol and --api-key-env to configure a real provider. A normal analysis makes four stage calls, and feedback makes one; bounded retries may add calls.

## Engineering features

- Literal evidence-quote validation and typed JSON contracts.
- Session-scoped, bounded observation retrieval; simulation never becomes evidence.
- SQLite transactions, checkpoints, stable run IDs and resume without repeating successful stages.
- Feedback changes identified hypotheses with provenance and preserved version history.
- Bilingual chat UI, restored sessions, readable result cards and execution records.
- Bounded academic evidence search across Semantic Scholar, OpenAlex and a SerpAPI Google Scholar adapter, with provider status and citation provenance.
- Optional real MCP stdio server, scoped to an explicit session, exposing two read-only tools.

This is a bounded workflow, not an autonomous planner or multi-agent system. Reported observations are not independently verified facts. Substring validation cannot establish semantic truth. The local server is for a single user and is not a public deployment architecture.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -p test_harness.py -v
.venv/bin/pip install -e '.[mcp]'
.venv/bin/python tests/test_mcp_integration.py
.venv/bin/python evals/run_eval.py --output outputs/evaluation.json
```

The eight evaluation cases include bilingual uncertainty, gender swaps, no-contact boundaries, injection attempts and threats. Mock checks establish engineering invariants only. Reports mark response quality NOT_EVALUATED until reviewed against each case's human rubric. Live GLM evaluation requires an authorized key and consumes quota.

The database is local plaintext at memory/v2/sessions.sqlite3. Personal data, outputs, environment files and virtual environments are ignored by Git. Older v0.1 JSONL data is preserved and not imported, because earlier demo outputs were mixed with observations.

See [architecture](architecture.md), [verification](verification.md), and the [Chinese guide](../README.md) for the CLI feedback/resume commands and MCP setup.
