"""Typed personal archive tools for Codex, backed by the actual Mnemosyne SDK."""
from typing import Any
from pathlib import Path
from mcp.server.mcpserver import MCPServer
from archive_store import ArchiveStore
from mcp_packages import Packages, planner_owner
from market_tools import register_market_tools

PLANNER_OWNER = planner_owner()
store = ArchiveStore()
mcp = MCPServer('EvoMyn')

@mcp.tool(structured_output=True)
def archive_status() -> dict[str, Any]:
    """查看个人库状态和当前分类列表（categories 的 id/label）。写入前据此选择默认或自定义分类。"""
    return store.status()

@mcp.tool(structured_output=True, description=(
    '记录用户明确提供的个人事实。category 使用 archive_status 返回的 categories.id，支持用户自定义分类。'
    '发生时间未知留空，支持 YYYY、YYYY-MM、YYYY-MM-DD 与 occurrence_end 时间段，持续至今可用 ongoing；不补造具体日。'
    'fields 保存用户事实，links 仅关联已有档案 ID，本地附件使用 file_path。'
    '未来计划、待办、日程和提醒使用圆盘设备自己的 self.planner.* 工具；不能当成已发生的档案事实。'
    '只有用户明确确认完成后，设备才将真实完成日志归档。index_status=pending 表示原文已保存但语义索引待重试。'
    if PLANNER_OWNER == 'device' else None))
def archive_record(category: str, title: str, body: str, occurrence_date: str | None = None,
                   fields: dict | None = None, tags: list[str] | None = None,
                   links: list[str] | None = None, steps: list[dict] | None = None,
                   file_path: str | None = None, href: str | None = None,
                   occurrence_end: str | None = None) -> dict[str, Any]:
    """记录用户明确提供的个人信息。默认 category: background个人/people人脉/journal日志/resource资料。
    自定义分类先调用 archive_status，使用 categories 中的稳定 id；不要将显示名称当作 id。
    occurrence_date 是事情发生日期，不能用录入日期代替已知历史日期。只记录用户事实，未知信息留空。
    日期支持YYYY、YYYY-MM、YYYY-MM-DD；时间段使用occurrence_end，端点各自保留精度，可不同，持续至今可用ongoing。不要补造具体日。
    人脉信息用fields，事件状态用fields.状态，关联使用已有记录id。本地附件用file_path。
    未来计划、待办、便笺、日程或提醒请用 planner_create，不要当成已发生的事实。
    索引失败时index_status为pending，原始记录仍已保存，应明确告诉用户。"""
    record = {'category': category, 'title': title, 'body': body, 'fields': fields or {}, 'tags': tags or [], 'links': links or []}
    for key, value in [('date', occurrence_date), ('date_end', occurrence_end), ('steps', steps), ('file_path', file_path), ('href', href)]:
        if value is not None: record[key] = value
    return store.save(record)

@mcp.tool(structured_output=True)
def archive_update(record_id: str, changes: dict, expected_revision: int | None = None) -> dict[str, Any]:
    """根据用户新信息修改已有记录，保留历史。先读取记录。fields是整对象替换，请合并已有字段。
    changes 可包含title/body/date/date_end/fields/tags/links/steps/file_path/href，不能修改id或category。"""
    return store.update(record_id, changes, expected_revision)

@mcp.tool(structured_output=True, description=(
    '完整列出个人档案，按 category、from_date/to_date、query、status 筛选；不截断为语义搜索 top-k。'
    '时间段按交集匹配，保持原始年/月精度。用于回顾已发生的日志、人物、事件；'
    '未来计划和待办请使用圆盘设备自己的 self.planner.* 工具查询。'
    if PLANNER_OWNER == 'device' else None))
def archive_list(category: str | None = None, from_date: str | None = None,
                 to_date: str | None = None, query: str | None = None,
                 status: str | None = None) -> list[dict[str, Any]]:
    """完整列出个人记录，按分类、发生日期、关键词、事件状态筛选，不截断为语义搜索top-k。
    时间段按交集筛选；只知年/月的记录按该年/月范围匹配，保持原精度，非具体日已知。
    回顾某段时间的日志、列出全部人物或已有档案事件时使用此工具；未来计划/待办请用planner_list。"""
    return store.list(category, from_date, to_date, query, status)

@mcp.tool(structured_output=True)
def archive_get(record_id: str) -> dict[str, Any]:
    """按稳定id读取个人记录及双向关联，便于回看人物、事件和资料。"""
    record = store.get(record_id)
    record['related'] = [other for other in store.list() if other['id'] != record_id and (other['id'] in record['links'] or record_id in other['links'])]
    return record

@mcp.tool(structured_output=True)
def archive_search(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """通过真实 Mnemosyne 检索相关个人信息。模糊回忆时使用；完整列表使用archive_list。"""
    return store.search(query, top_k)

@mcp.tool(structured_output=True)
def archive_history(record_id: str) -> list[dict[str, Any]]:
    """查看记录的历史版本，例如某事件要求和状态的变化。"""
    return store.history(record_id)

@mcp.tool(structured_output=True)
def archive_backup() -> dict[str, Any]:
    """为个人记录和Mnemosyne记忆做一致的完整SQLite备份。"""
    return {'backup': str(store.backup())}

@mcp.tool(structured_output=True)
def archive_retry_index() -> dict[str, Any]:
    """重试索引尚未成功同步到Mnemosyne的已保存记录。"""
    return store.retry_index()

if PLANNER_OWNER == 'pc':
    from planner_tools import register_planner_tools
    register_planner_tools(mcp)
register_market_tools(mcp)

# Direct stdio clients bypass the Xiaozhi pipe, so apply built-in switches here
# as well. Reconnecting the client picks up any changes made in the dashboard.
for group in Packages(Path(__file__).resolve().parent.parent / 'mcp-packages.json').list():
    if group.get('builtin') and not group.get('external') and not group['enabled']:
        for name in group['tools']:
            mcp.remove_tool(name)

if __name__ == '__main__': mcp.run(transport='stdio')


