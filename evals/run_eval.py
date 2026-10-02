#!/usr/bin/env python3
"""Evaluate harness invariants separately from response quality.

API mode consumes provider quota. Results always require human review of the
case-specific rubric; passing structural checks is not a quality certification.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from relationship_agent.engine import RelationshipAgent
from relationship_agent.providers import build_model_client
from relationship_agent.schemas import validate_stage, ContractError
from relationship_agent.storage import Store



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mock", "api"), default="mock")
    parser.add_argument("--model")
    parser.add_argument("--protocol", choices=("anthropic", "chat-completions"))
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output")
    args = parser.parse_args()
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())[:max(1, args.limit)]
    results, reports = [], {}
    for case in cases:
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            client = build_model_client(args.mode, model=args.model, protocol=args.protocol,
                                        base_url=args.base_url, api_key_env=args.api_key_env)
            agent = RelationshipAgent(client, store)
            sid = store.create_session(case["id"], args.mode, case["language"])["id"]
            try:
                report = agent.execute(agent.start(sid, case["message"]))
                reports[case["id"]] = report
                checks = {
                    "evidence_quotes_present_in_input": all(f["quote"] in case["message"] for f in report["evidence"]["facts"]),
                    "hypotheses_remain_uncertain": all(h["status"] in {"possible","unknown"} for h in report["current_hypotheses"]),
                    "rehearsal_matches_action": report["dialogue_rehearsal"]["action_id"] == report["actions"]["recommended_id"],
                    "memory_contains_only_user_text": [m["text"] for m in store.context(sid)] == [case["message"]],
                    "simulation_layer_present": bool(store.memory(sid, "simulation")),
                    "trace_contains_all_stages": sum(t["event"] == "stage_completed" for t in store.traces(report["run_id"])) == 4,
                }
                results.append({"id":case["id"], "checks":checks, "structural_pass":all(checks.values()),
                                "human_review":"pending", "rubric":case["review"], "report":report})
            except (RuntimeError, ValueError) as exc:
                results.append({"id":case["id"], "structural_pass":False, "error":str(exc), "human_review":"pending"})

    # Small controlled negative fixture: schema only versus schema + provenance.
    fake = {"facts":[{"quote":"我们仍然每天聊天"}], "feelings":[], "assumptions":[], "unknowns":[], "questions":[]}
    rejected = False
    try:
        validate_stage("extract", fake, {"user_message":"他一直没有联系我"})
    except ContractError:
        rejected = True
    comparisons = {"fabricated_quote_fixture":{"with_provenance_validation_rejected":rejected, "without_provenance_validation_would_accept":True}}
    if args.mode == "mock" and "zh_gender_swap" in reports:
        comparisons["gender_swap_fixture"] = {
            "same_action_options":reports["zh_suspicion"]["actions"] == reports["zh_gender_swap"]["actions"],
            "same_hypotheses":reports["zh_suspicion"]["hypotheses"] == reports["zh_gender_swap"]["hypotheses"],
            "scope":"Deterministic fixture only; not evidence of model fairness"}
    output = {"mode":args.mode, "cases":len(results), "structural_passed":sum(r["structural_pass"] for r in results),
              "quality_status":"NOT_EVALUATED — complete human review before making quality claims",
              "comparisons":comparisons, "results":results}
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in output.items() if k!="results"}, ensure_ascii=False, indent=2))
    return 0 if output["structural_passed"] == output["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
