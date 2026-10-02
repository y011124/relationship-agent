"""Command line interface; shares the web app's persistent harness."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .engine import RelationshipAgent
from .storage import Store
from .providers import build_model_client
from .schemas import validate_stage, SCHEMAS


def main():
    parser = argparse.ArgumentParser(description="Relationship Agent: bounded relationship reasoning workflow")
    parser.add_argument("--mode", choices=("mock", "api"), default="mock")
    parser.add_argument("--stage", choices=("extract", "full", "feedback", "interactive"), default="full")
    parser.add_argument("--case", default="cases/case_001.json")
    parser.add_argument("--message")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--protocol", choices=("anthropic", "chat-completions"))
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument("--memory-dir", default="memory/v2")
    parser.add_argument("--session-id", help="Continue a saved session")
    parser.add_argument("--resume", help="Resume a failed run ID with the same configuration")
    parser.add_argument("--feedback")
    parser.add_argument("--report", help="A v2 report JSON providing the session ID")
    parser.add_argument("--output")
    args = parser.parse_args()

    def emit(value):
        text = json.dumps(value, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")

    try:
        client = build_model_client(args.mode, model=args.model, base_url=args.base_url,
                                   protocol=args.protocol, api_key_env=args.api_key_env)
        store = Store(args.memory_dir)
        agent = RelationshipAgent(client, store)
        if args.resume:
            emit(agent.execute(args.resume))
            return
        session_id = args.session_id
        if args.stage == "feedback" and args.report:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            session_id = report.get("session_id")
            if not session_id:
                parser.error("旧报告不可作为 v2 记忆，请先运行一次新版分析 / Please generate a v2 report")
        if args.stage == "interactive":
            session_id = session_id or store.create_session("Interactive", client.mode, args.language)["id"]
            print(f"Session: {session_id} · {client.mode}\n/feedback <text> · /quit")
            while True:
                try:
                    message = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if message == "/quit":
                    return
                if not message:
                    continue
                kind = "feedback" if message.startswith("/feedback ") else "analysis"
                message = message[len("/feedback "):] if kind == "feedback" else message
                run_id = agent.start(session_id, message, kind)
                emit(agent.execute(run_id))
        elif args.stage == "feedback":
            if not session_id or not args.feedback:
                parser.error("--stage feedback needs --feedback and --session-id or --report")
            run_id = agent.start(session_id, args.feedback, "feedback")
            emit(agent.execute(run_id))
        else:
            message = args.message
            if not message:
                path = Path(args.case)
                if not path.exists():
                    path = Path(__file__).resolve().parents[2] / args.case
                message = json.loads(path.read_text(encoding="utf-8"))["user_message"]
            if args.stage == "extract":
                payload = {"user_message": message, "language": args.language}
                emit({"is_demo": client.mode == "mock", "evidence": validate_stage("extract", client.complete_json("extract", payload, SCHEMAS["extract"]), payload)})
            else:
                session_id = session_id or store.create_session(message[:60], client.mode, args.language)["id"]
                run_id = agent.start(session_id, message)
                emit(agent.execute(run_id))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
