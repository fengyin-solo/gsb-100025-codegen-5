"""发电监测接口：采集核对队列（进队、补录、校验、入库）与正式记录维护。

路由顺序有意把 /queue、/export、/files 这些字面路径放在 /{entry_id} 之前：
否则 /export 会被当成 entry_id 解析，直接 422。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.power_data import PowerDataService

router = APIRouter(prefix="/api/power_data", tags=["发电监测"])

service = PowerDataService()

LIST_FIELDS = ["记录编号", "电站编号", "发电量", "辐照度", "组件温度", "环境温度", "记录时间", "数据状态"]
STATUSES = ["正常", "偏低", "异常", "补录"]
QUEUE_STATUSES = ["待补录", "待核对", "已通过", "已入库"]


def _csv_response(content: str, file_name: str) -> Response:
    """表格文件统一下载响应：带 BOM 让 Excel 直接认出中文，另存时拿到正确文件名。"""
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"},
    )


# ---- 采集核对队列 ----


@router.get("/queue")
def list_queue(
    status: str | None = Query(default=None, description="待补录、待核对、已通过、已入库"),
    station: str | None = Query(default=None, description="按电站编号过滤"),
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    """查看采集核对队列：每行带温度口径，人工零值与未采集空白分开，另附各状态汇总。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total, summary = service.list_queue(status=status, station=station, page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size, "summary": summary}


@router.post("/queue/intake", response_model=ActionResult)
def intake_entry(payload: EntryPayload) -> ActionResult:
    """采集进入核对队列：电站和小时形成一行；缺组件温度或环境温度的行停在校验区。"""
    entry, message = service.intake(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/queue/{row_id}/supplement", response_model=ActionResult)
def supplement_entry(row_id: int, payload: EntryPayload) -> ActionResult:
    """值班员逐条补录组件温度、环境温度；人工零值需显式确认，与未采集空白区分。"""
    entry, message = service.supplement(row_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/queue/{row_id}/validate", response_model=ActionResult)
def validate_entry(row_id: int) -> ActionResult:
    """校验通过：温度齐全（含已确认人工零值）才放行，否则打回校验区并说明缺什么。"""
    entry, message = service.validate_row(row_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/queue/commit", response_model=ActionResult)
def commit_queue() -> ActionResult:
    """把已通过校验的核对行写入正式记录，并生成可另存的表格文件。"""
    result, message = service.commit()
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("/queue/export")
def export_queue(
    status: str | None = Query(default=None, description="待补录、待核对、已通过、已入库"),
    station: str | None = Query(default=None, description="按电站编号过滤"),
) -> Response:
    """导出队列表格：空范围仍保留模板表头，可直接另存。"""
    content = service.export_queue_csv(status=status, station=station)
    return _csv_response(content, "发电采集核对队列.csv")


# ---- 入库生成的表格文件 ----


@router.get("/files/{file_name}")
def download_file(file_name: str) -> Response:
    """下载入库时生成的表格文件；进程重启后旧文件失效，会明确提示而不是给空文件。"""
    content = service.get_file(file_name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"表格文件 {file_name} 不存在或已过期，请重新入库生成")
    return _csv_response(content, file_name)


# ---- 正式发电记录 ----


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="正常、偏低、异常、补录"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤发电监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出发电监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "power_data", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条发电记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"发电记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条发电记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="发电记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条发电记录执行标记偏低、确认异常、数据补录；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
