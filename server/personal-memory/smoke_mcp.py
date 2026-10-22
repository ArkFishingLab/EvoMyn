"""Exercise actual stdio tools and local semantic recall in a disposable database."""
import asyncio
import os
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with tempfile.TemporaryDirectory(prefix="memory-mcp-smoke-") as directory:
        env = dict(os.environ, PERSONAL_ARCHIVE_HOME=directory)
        env.pop("MNEMOSYNE_NO_EMBEDDINGS", None)
        params = StdioServerParameters(
            command=sys.executable, args=["/app/mcp_server.py"], env=env
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"archive_record", "archive_update", "archive_search"} <= names

                async def call(name, arguments):
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error, name
                    value = result.structured_content
                    return value["result"] if isinstance(value, dict) and "result" in value else value

                before = await call("archive_status", {})
                assert before["records"] == 0
                record = await call("archive_record", {
                    "category": "event", "title": "临时部署验证记录",
                    "body": "毕业前需要提交学位论文，完成评审并参加答辩。这是临时测试数据。",
                    "occurrence_date": "2040-01-01", "fields": {"状态": "进行中"}
                })
                assert record["index_status"] == "indexed", record.get("index_error")
                updated = await call("archive_update", {
                    "record_id": record["id"], "changes": {"fields": {"状态": "已完成"}},
                    "expected_revision": record["revision"]
                })
                assert updated["id"] == record["id"] and updated["revision"] == 2
                listed = await call("archive_list", {"category": "event", "status": "已完成"})
                assert any(item["id"] == record["id"] for item in listed)
                history = await call("archive_history", {"record_id": record["id"]})
                assert len(history) == 2
                hits = await call("archive_search", {"query": "完成博士学位需要哪些步骤"})
                assert any(item["id"] == record["id"] and item["retrieval"] == "mnemosyne" for item in hits)
                print("PASS: tool discovery, empty database, record, update, list, history, local semantic recall", flush=True)
                print("Tool count:", len(names), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
