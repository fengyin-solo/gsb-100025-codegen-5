"""发电监测接口：维护发电记录，覆盖标记偏低、确认异常、数据补录等动作。

采集核对队列：采集数据先入队（电站×小时一行），缺组件温度或环境温度的行停在
校验区由值班员逐条补录，通过校验才写入正式记录，并可另存为表格文件。
"""
from __future__ import annotations

import csv
import io
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.power_data import PowerDataService
from app.services.power_data_queue import PowerDataQueueService

router = APIRouter(prefix="/api/power_data", tags=["发电监测"])

service = PowerDataService()
queue_service = PowerDataQueueService()

LIST_FIELDS = ["记录编号", "电站编号", "发电量", "辐照度", "组件温度", "环境温度", "记录时间", "数据状态"]
STATUSES = ["正常", "偏低", "异常", "补录"]
EXPORT_FIELDS = ["记录编号", "电站编号", "记录时间", "发电量", "辐照度", "组件温度", "环境温度", "数据状态"]


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


@router.get("/queue", response_model=PageResult[dict])
def list_queue(
    station: str | None = Query(default=None, description="按电站编号过滤"),
    date: str | None = Query(default=None, description="按日期过滤，格式 YYYY-MM-DD"),
    status: str | None = Query(default=None, description="未采集、待补录、人工零值、待入库、已入库"),
    page: int = 1,
    size: int = 100,
) -> PageResult[dict]:
    """查看采集核对队列；指定日期时空范围也会保留电站×小时的模板行。"""
    if size > 1000:
        raise HTTPException(status_code=400, detail="每页最多 1000 条，请缩小分页范围")
    items, total, error = queue_service.list_rows(station=station, date=date, status=status, page=page, size=size)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/queue/collect", response_model=ActionResult)
def collect_queue(payload: EntryPayload) -> ActionResult:
    """把一批采集数据送入核对队列；已有行只补空缺字段，不覆盖值班员补录结果。"""
    summary, message = queue_service.collect(payload.values)
    if summary is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=summary)


@router.post("/queue/{row_id}/supplement", response_model=ActionResult)
def supplement_queue_row(row_id: int, payload: EntryPayload) -> ActionResult:
    """值班员逐条补录组件温度、环境温度等字段；仍缺温度的行继续留在校验区。"""
    row, message = queue_service.supplement(row_id, payload.values)
    if row is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=row)


@router.post("/queue/{row_id}/confirm_zero", response_model=ActionResult)
def confirm_queue_zero(row_id: int, payload: EntryPayload) -> ActionResult:
    """把空行确认为人工零值，与未采集空白在队列里分开列示。"""
    row, message = queue_service.confirm_zero(row_id, payload.values)
    if row is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=row)


@router.post("/queue/commit", response_model=ActionResult)
def commit_queue(payload: EntryPayload) -> ActionResult:
    """校验通过的行写入正式记录；缺温度的行留在校验区，未采集模板保留。"""
    summary, message = queue_service.commit(payload.values)
    if summary is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/queue/export")
def export_queue(
    station: str | None = Query(default=None, description="按电站编号过滤"),
    date: str | None = Query(default=None, description="按日期过滤，格式 YYYY-MM-DD"),
) -> Response:
    """把已入库的正式记录生成可另存的表格文件（CSV，带表头）。"""
    rows, _total = queue_service.export_rows(station=station, date=date)
    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM，保证 Excel 另存打开时中文不乱码
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_FIELDS)
    for row in rows:
        writer.writerow([row.get(field) if row.get(field) is not None else "" for field in EXPORT_FIELDS])
    filename = quote(f"发电记录_{date or '全部'}.csv")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


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
