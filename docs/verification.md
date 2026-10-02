# Verification record

Last local verification: 2026-09-22.

## Passed

- `python -m unittest discover -s tests -p test_harness.py -q`: 28 tests passed, including two-turn chat persistence, the local API request cap, and rejection of generated questions as hypothesis support.
- `python tests/test_mcp_integration.py`: 1 MCP stdio integration test passed.
- `python evals/run_eval.py --output outputs/evaluation-final.json`: 8/8 structural cases passed.
- `node --check src/relationship_agent/web/app.js`: passed.
- Editable package installation with the optional MCP extra: passed.
- Browser smoke check on `http://127.0.0.1:8765`: two live GLM-5.3 chat turns displayed; the second turn honored a request to listen without advice; reloading preserved both turns.
- A synthetic live GLM-5.3 case completed extraction, hypotheses, actions, private rehearsal, and feedback revision in the browser. One format repair was needed during the four-stage analysis. A generated clarification question appeared as hypothesis support; the support contract was then tightened to require an exact user-account quote. That final contract change passed local tests but was not followed by another paid live analysis.
- One short direct GLM-5.3 chat request confirmed the official Chat Completions endpoint and JSON reply contract. No batch live evaluation was run. The current local server was restarted with a 12-attempt cap to preserve the remaining test budget.
- Local API fixture checked both Anthropic Messages and Chat Completions envelopes, auth headers, bounded malformed-output repair and no secret echo.

## What these checks mean

They establish code behavior: data layers stay separated, generated rehearsal is excluded from retrieved observations, facts require an input quote, feedback updates an existing hypothesis with a quote, sessions do not leak into one another, model configuration is isolated, failed stages can resume, and the two protocol adapters are wired as expected.

The Mock evaluation does not establish that GLM gives good relationship advice. It is a deterministic fixture. `quality_status` is deliberately `NOT_EVALUATED` until a human reviews real outputs against the rubric in `evals/cases.json`. The limited live browser checks demonstrate that the workflow executes; they do not establish advice quality or safety across diverse situations.

## Further review

For a small live evaluation after entering an authorized key:

```sh
read -rs "GLM_API_KEY?Paste your authorized key: "; export GLM_API_KEY; echo
.venv/bin/python evals/run_eval.py --mode api --model glm-5.3 --protocol chat-completions --limit 2 --output outputs/live-evaluation.json
```

Inspect the two reports before deciding whether model behavior is good enough. The call consumes API quota and sends the case text to the configured provider.
