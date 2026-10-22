"""Actual MCP SDK/stdio planner verification, isolated from production records."""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with tempfile.TemporaryDirectory(prefix='planner-mcp-smoke-') as directory:
        env = dict(os.environ, PERSONAL_ARCHIVE_HOME=directory,
                   MNEMOSYNE_NO_EMBEDDINGS='1')
        params = StdioServerParameters(command=sys.executable,
                                       args=['/app/mcp_server.py'], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                expected = {'planner_' + name for name in
                            ('get_context', 'create', 'list', 'get', 'delivery',
                             'update', 'complete', 'cancel', 'snooze')}
                assert expected <= names and len(names) == 18, names

                async def call(name, args):
                    result = await client.call_tool(name, args)
                    assert not result.is_error, (name, result.content)
                    value = result.structured_content
                    return value['result'] if isinstance(value, dict) and 'result' in value else value

                context = await call('planner_get_context', {})
                assert context['timezone'] == 'Asia/Shanghai'
                request = {'title': '临时协议验证', 'request_id': 'smoke-' + uuid4().hex}
                first = await call('planner_create', request)
                retry = await call('planner_create', request)
                assert first['saved'] and not first['device_scheduled']
                assert first['task']['id'] == retry['task']['id']
                await call('planner_complete', {'task_id': first['task']['id'],
                           'expected_revision': 1, 'request_id': 'smoke-' + uuid4().hex})
                task = (await call('planner_get', {'task_id': first['task']['id']}))['task']
                assert task['status'] == 'completed'
                due = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(timespec='seconds')
                repeated = await call('planner_create', {'title': '临时每日实例验证',
                    'request_id': 'smoke-' + uuid4().hex, 'due_at': due,
                    'repeat': 'daily', 'remind': True})
                occurrence = repeated['current_occurrence_id']
                assert occurrence
                await call('planner_complete', {'task_id': repeated['task']['id'],
                    'expected_revision': 1, 'request_id': 'smoke-' + uuid4().hex,
                    'occurrence_id': occurrence})
                current = (await call('planner_get', {'task_id': repeated['task']['id']}))['task']
                assert current['status'] == 'pending' and current['revision'] == 1
                archive = await call('archive_status', {})
                assert archive['records'] == 0
                print('PASS: actual MCP stdio, 18 tools, time context, idempotency, '
                      'single completion, recurring instance completion, archive preserved')


if __name__ == '__main__':
    asyncio.run(main())
