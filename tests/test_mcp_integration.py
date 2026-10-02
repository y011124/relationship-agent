"""Exercise a real MCP initialization, tool list and call over stdio."""
import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from relationship_agent.storage import Store
from relationship_agent.engine import RelationshipAgent
from relationship_agent.demo import MockModelClient


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP extra not installed")
class MCPIntegrationTests(unittest.TestCase):
    def test_stdio_tool_call(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            sid = store.create_session("MCP fixture", "mock")["id"]
            agent = RelationshipAgent(MockModelClient(), store)
            agent.execute(agent.start(sid, "他一直没有联系我"))

            async def check():
                params = StdioServerParameters(command=sys.executable, args=["-m", "relationship_agent.mcp_server", "--memory-dir", directory, "--session-id", sid], env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual({t.name for t in tools.tools}, {"get_observations", "get_hypotheses"})
                        result = await session.call_tool("get_observations", {})
                        self.assertFalse(result.isError)
                        text = "".join(item.text for item in result.content if hasattr(item, "text"))
                        self.assertIn("他一直没有联系我", text)
                        self.assertNotIn("imagined_reply", text)
                        self.assertNotIn("practice_reply", text)
            asyncio.run(check())

if __name__ == "__main__":
    unittest.main()
