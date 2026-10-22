"""Typed MCP registration, kept testable without loading the archive embedding SDK."""
import os
import time
from typing import Any
from planner_store import PlannerStore, client_operation_id

def register_planner_tools(mcp,store=None,device=None):
    store=store or PlannerStore()
    device=device or os.getenv('PLANNER_DEVICE_ID','02:00:00:00:00:01')
    def delivery(task_id,wait_ms=0,occurrence_id=None,chosen_date=None):
        if type(wait_ms) is not int or not 0<=wait_ms<=3000:raise ValueError('wait_ms must be 0–3000')
        deadline=time.monotonic()+wait_ms/1000
        while True:
            result=store.delivery(task_id,device,occurrence_id,chosen_date)
            if result['device_scheduled'] or time.monotonic()>=deadline:return result
            time.sleep(min(.1,max(0,deadline-time.monotonic())))

    @mcp.tool(structured_output=True)
    def planner_get_context() -> dict[str,Any]:
        """解析今天/明天/下周等相对时间之前必用：返回服务器真实当前 UTC、北京时间日期和时区。不要使用提示词中固定日期或猜测今天。模糊“早上/晚点”先问用户明确时刻。"""
        return store.context()

    @mcp.tool(structured_output=True)
    def planner_create(title:str,request_id:str,body:str='',kind:str='task',due_at:str|None=None,repeat:str='none',timezone:str='Asia/Shanghai',remind:bool=False,archive_links:list[str]|None=None,wait_ms:int=0,start_at:str|None=None,end_at:str|None=None,remind_at:str|None=None) -> dict[str,Any]:
        """用户明确要求记下未来计划/待办/便笺/日程/提醒时使用，未来意图不要存成 archive 已发生事实。
        kind: note/task/event；due_at为截止时间，start_at/end_at为日程起止，remind_at为独立提醒时刻；均为准确 ISO datetime，未知留空。例15点会议14点50提醒，start_at填15点、remind_at填14点50，不能混为同一时间。相对时间先planner_get_context；模糊提醒时间先澄清，不补造日期。
        repeat: none/daily/weekly；remind默认false，只有用户明确要求提醒才设true（有截止时间不代表要提醒）。true时优先remind_at，否则使用明确start_at/due_at。archive_links仅已有档案ID。未明确要求不要自动保存。
        request_id 每次用户意图用新的ASCII唯一值，重试沿用同值。saved=true 仅表示持久保存；只有 device_scheduled=true 才可说设备已确认提醒，false 应说已保存等待设备同步。wait_ms 可选0–3000。"""
        task=store.create(title,body,kind,due_at,repeat,timezone,remind,archive_links,request_id,start_at,end_at,remind_at)
        return delivery(task['id'],wait_ms)

    @mcp.tool(structured_output=True)
    def planner_list(status:str|None='pending',kind:str|None=None,from_at:str|None=None,to_at:str|None=None,query:str|None=None) -> list[dict[str,Any]]:
        """查询完整计划/便笺/待办列表，含结构化状态与准确时间。默认pending；status=null包含整项完成和取消。status=completed只列整项已完成，不代表重复任务某次已完成；重复实例完成记录查planner_get.occurrence_history。日期筛选按原始start_at→due_at→remind_at，查某日重复计划需结合规则。不要用archive_list代替未来计划表。"""
        return store.list(status,kind,store.parse_time(from_at,'Asia/Shanghai'),store.parse_time(to_at,'Asia/Shanghai'),query)

    @mcp.tool(structured_output=True)
    def planner_get(task_id:str) -> dict[str,Any]:
        """读取任务最新revision与历史。history为整项版本历史；occurrence_history为该任务最近100条实例记录（按acted_at/at倒序），查询每日/每周哪次已完成用此字段，含id/status/at/task_revision/parent_occurrence_id/acted_at。实例完成不改变整项pending状态，未来pending实例保留。"""
        return {'task':store.get(task_id),'history':store.history(task_id),'occurrence_history':store.occurrence_history(task_id)}

    @mcp.tool(structured_output=True)
    def planner_delivery(task_id:str,wait_ms:int=0,chosen_date:str|None=None) -> dict[str,Any]:
        """查询计划提醒与真实设备ACK。用户说“刚才的提醒稍后再响”时，优先使用recent_fired_occurrence_id或current_occurrence_id作为planner_snooze的occurrence_id；不要使用明天的next_occurrence_id替代刚响过的实例。
        current优先最近7天已响且未关闭/未稍后的实例，否则重复任务选本地今天或最近未完成到期实例；不会因硬件5分钟响铃窗口跳到明天。返回current_occurrence_date供确认操作日期。用户明确指定某天时chosen_date填准确YYYY-MM-DD（相对时间先取真实context），只查该日实例，不会替换成别的日期；已完成/不在重复规则的那天current为空。next是下一pending提醒；旧occurrence_id和device_scheduled仍只表示实际pending提醒ACK。wait_ms最多3000。"""
        return delivery(task_id,wait_ms,chosen_date=chosen_date)

    @mcp.tool(structured_output=True)
    def planner_update(task_id:str,changes:dict,expected_revision:int,request_id:str,wait_ms:int=0) -> dict[str,Any]:
        """用户明确要求修改计划才调用。先 planner_get，用其revision作expected_revision；冲突先重读。
        changes 仅 title/body/kind/status/due_at/start_at/end_at/remind_at/repeat/timezone/remind/archive_links；截止、日程起止、提醒时刻分开；提醒需明确授权和时刻。status仅pending/completed/cancelled。
        用新request_id，重试沿用。返回saved与device_scheduled，未ACK不能承诺设备已设置提醒。"""
        store.update(task_id,changes,expected_revision,request_id)
        return delivery(task_id,wait_ms)

    @mcp.tool(structured_output=True)
    def planner_complete(task_id:str,expected_revision:int,request_id:str,occurrence_id:str|None=None) -> dict[str,Any]:
        """只有用户明确表示已完成才调用。单次/无时间任务标记整体完成；每日/每周任务必须提供真实occurrence_id，仅完成本次，保持未来实例与任务pending不变。
        重复任务先planner_delivery读取current_occurrence_id并核对current_occurrence_date；用户指定日期须先chosen_date精确查该日，不能猜造、省略或使用明天实例代替今天。先读取最新task revision。完成某实例也会关闭该实例的稍后提醒子链，其他日期不变。要结束整个系列，明确要求后用planner_cancel或planner_update(status=completed)。历史保留。"""
        store.action('mcp',client_operation_id('mcp',request_id),'complete',task_id,expected_revision,occurrence_id)
        return delivery(task_id)

    @mcp.tool(structured_output=True)
    def planner_cancel(task_id:str,expected_revision:int,request_id:str) -> dict[str,Any]:
        """用户明确要求取消计划/停止重复提醒时调用。先读取最新revision，取消后保留记录和历史。"""
        store.update(task_id,{'status':'cancelled'},expected_revision,request_id)
        return delivery(task_id)

    @mcp.tool(structured_output=True)
    def planner_snooze(task_id:str,occurrence_id:str,expected_revision:int,request_id:str,seconds:int=600,wait_ms:int=0) -> dict[str,Any]:
        """用户明确要求将当前具体提醒延后才调用，不完成计划。先planner_delivery；刚响过的提醒用recent_fired_occurrence_id或current_occurrence_id，不能误用next_occurrence_id把明天提醒移走；不能猜造ID。seconds 60–604800，默认600。request_id为ASCII唯一值。返回只有device_scheduled=true才能确认设备已缓存此次稍后提醒。"""
        op_id=client_operation_id('mcp',request_id)
        store.action('mcp',op_id,'snooze',task_id,expected_revision,occurrence_id,seconds)
        return delivery(task_id,wait_ms,'snooze-'+op_id)
