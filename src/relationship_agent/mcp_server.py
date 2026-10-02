"""Optional real MCP stdio server, scoped to one explicitly selected session."""
import argparse
from pathlib import Path
from .storage import Store


def build_server(root, session_id):
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError:
        raise SystemExit('Install the optional integration: pip install -e ".[mcp]"')
    if not (Path(root) / "sessions.sqlite3").is_file():
        raise ValueError("A saved database is required")
    store = Store(root)
    store.session(session_id)
    server = FastMCP("Between: one relationship session")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=annotations)
    def get_observations() -> dict:
        """Return bounded user-reported observations only. These are not independently verified facts. Never includes simulated dialogue."""
        return {"session_id": session_id, "source": "user_report_unverified", "observations": store.context(session_id)}

    @server.tool(annotations=annotations)
    def get_hypotheses() -> dict:
        """Return current model judgments, explicitly NOT observations or facts."""
        report = store.latest_report(session_id)
        return {"session_id": session_id, "layer": "inference", "hypotheses": report["current_hypotheses"] if report else []}

    return server


def main():
    parser = argparse.ArgumentParser(description="Read-only MCP stdio access to one session")
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    build_server(args.memory_dir, args.session_id).run(transport="stdio")


if __name__ == "__main__":
    main()
