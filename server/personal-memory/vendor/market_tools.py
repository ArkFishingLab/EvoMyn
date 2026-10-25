"""Small typed adapters to installed providers, without passing archive secrets."""
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_packages import Packages


async def call_time_server(python, name, arguments):
    # A virtualenv can share the signed app's standard library. Do not write
    # bytecode beside those resources when launching an optional provider.
    params = StdioServerParameters(command=str(python), args=['-B', '-X', 'utf8', '-m', 'mcp_server_time',
        '--local-timezone=Asia/Shanghai'], env={'PYTHONUTF8': '1'}, cwd=str(Path(python).resolve().parents[2]))
    async with asyncio.timeout(20):
        with open(os.devnull, 'w', encoding='utf-8') as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    result = await client.call_tool(name, arguments)
                    if result.is_error: raise ValueError('时间查询失败，请检查时区和时间。')
                    data = result.structured_content
                    if isinstance(data, dict): return data
                    text = next((part.text for part in result.content if hasattr(part, 'text')), '')
                    data = json.loads(text)
                    if not isinstance(data, dict): raise ValueError('Invalid time response')
                    return data


def register_market_tools(mcp, packages=None):
    packages = packages or Packages(Path(__file__).resolve().parent.parent / 'mcp-packages.json')
    if not any(item['id'] == 'worldtime' and item['enabled'] for item in packages.list()): return

    async def invoke(name, arguments):
        if not any(item['id'] == 'worldtime' and item['enabled'] for item in packages.list()):
            raise ValueError('世界时间未开启。')
        return await call_time_server(packages.python('worldtime'), name, arguments)

    @mcp.tool(structured_output=True)
    async def worldtime_now(timezone: str = 'Asia/Shanghai') -> dict[str, Any]:
        """查询某地真实当前时间。timezone 使用 IANA 时区，如 Asia/Shanghai、Asia/Tokyo、Europe/London。"""
        return await invoke('get_current_time', {'timezone': timezone})

    @mcp.tool(structured_output=True)
    async def worldtime_convert(source_timezone: str, time: str, target_timezone: str) -> dict[str, Any]:
        """换算两个地区的时间。时区用 IANA 名称，time 使用24小时 HH:MM 格式。"""
        return await invoke('convert_time', {'source_timezone': source_timezone, 'time': time,
                                           'target_timezone': target_timezone})
