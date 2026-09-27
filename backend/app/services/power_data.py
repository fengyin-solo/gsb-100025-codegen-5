"""发电监测业务规则：状态流转、字段校验与筛选口径都收在这里。

采集核对队列：采集到的发电记录先进入队列，电站和小时形成一行；
缺组件温度或环境温度的行停在校验区，由值班员逐条补录；
通过校验的行才允许写入正式记录，并生成可另存的表格文件。
已确认的人工零值与未采集空白在队列里分开标注，空范围导出仍保留模板表头。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "power_data"
QUEUE_MODULE = "power_data_queue"
REQUIRED_FIELDS = ["记录编号", "电站编号", "发电量"]
STATUS_ORDER = ["正常", "偏低", "异常", "补录"]
ACTION_RULES = {"标记偏低": "偏低", "确认异常": "异常", "数据补录": "正常"}
NEGATIVE_ACTIONS = []

QUEUE_STATUSES = ["待补录", "待核对", "已通过", "已入库"]
HOLD_STATUS, READY_STATUS, PASSED_STATUS, COMMITTED_STATUS = QUEUE_STATUSES
TEMP_FIELDS = ["组件温度", "环境温度"]
INTAKE_REQUIRED = ["电站编号", "小时"]
QUEUE_CSV_HEADERS = ["电站编号", "小时", "发电量", "辐照度", "组件温度", "组件温度口径", "环境温度", "环境温度口径", "核对状态"]
RECORD_CSV_HEADERS = ["记录编号", "电站编号", "记录时间", "发电量", "辐照度", "组件温度", "环境温度", "数据状态"]


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_zero(value: Any) -> bool:
    try:
        return float(str(value).strip()) == 0.0
    except (TypeError, ValueError):
        return False


def _temp_state(row: dict[str, Any], field: str) -> str:
    """温度口径：未采集（空白）、零值待确认、人工零值（已确认）、正常值。"""
    raw = row.get(field)
    if _is_blank(raw):
        return "未采集"
    if _is_zero(raw):
        return "人工零值" if row.get(f"{field}零值确认") else "零值待确认"
    return "正常值"


def _missing_temps(row: dict[str, Any]) -> list[str]:
    """还差哪些温度才能过校验：空白未采集，或零值未经人工确认。"""
    return [field for field in TEMP_FIELDS if _temp_state(row, field) in ("未采集", "零值待确认")]


def _records_to_csv(records: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(RECORD_CSV_HEADERS)
    for record in records:
        writer.writerow([record.get(header) for header in RECORD_CSV_HEADERS])
    return buffer.getvalue()


class PowerDataService:
    def __init__(self) -> None:
        # 入库时生成的表格文件：文件名 -> CSV 内容，随进程存续，重启即失效
        self._files: dict[str, str] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"发电记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于发电监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"发电记录已{action}"

    # ---- 采集核对队列 ----

    def list_queue(
        self,
        *,
        status: str | None = None,
        station: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = store.rows(QUEUE_MODULE)
        summary = {name: 0 for name in QUEUE_STATUSES}
        for row in rows:
            key = str(row.get("status", HOLD_STATUS))
            summary[key] = summary.get(key, 0) + 1
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if station:
            rows = [row for row in rows if station in str(row.get("电站编号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._describe(row) for row in rows[start:start + size]], total, summary

    def intake(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """采集进入核对队列：电站和小时形成一行，缺温度的行停在校验区。"""
        missing = [field for field in INTAKE_REQUIRED if _is_blank(values.get(field))]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        station = str(values["电站编号"]).strip()
        hour = str(values["小时"]).strip()
        rows = store.rows(QUEUE_MODULE)
        for row in rows:
            if row.get("电站编号") == station and row.get("小时") == hour:
                return None, f"电站 {station} 在 {hour} 已有核对行（行号 {row.get('id')}），电站和小时只形成一行"
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "电站编号": station,
            "小时": hour,
            "发电量": values.get("发电量"),
            "辐照度": values.get("辐照度"),
            "组件温度": values.get("组件温度"),
            "环境温度": values.get("环境温度"),
            "组件温度零值确认": bool(values.get("组件温度零值确认")),
            "环境温度零值确认": bool(values.get("环境温度零值确认")),
            "补录人": None,
            "abnormal": False,
        }
        entry["status"] = READY_STATUS if not _missing_temps(entry) else HOLD_STATUS
        entry["pending"] = True
        rows.append(entry)
        if entry["status"] == HOLD_STATUS:
            return self._describe(entry), "缺少组件温度或环境温度，已停在校验区，待值班员补录"
        return self._describe(entry), "采集行已进入核对队列，可执行校验通过"

    def supplement(self, row_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """值班员逐条补录：只在校验区或待核对的行上补温度；人工零值要显式确认。"""
        row = store.find(QUEUE_MODULE, row_id)
        if row is None:
            return None, f"核对行 {row_id} 不存在或已清理"
        if row.get("status") not in (HOLD_STATUS, READY_STATUS):
            return None, f"核对行 {row_id} 当前状态为「{row.get('status')}」，不允许再补录"
        for field in TEMP_FIELDS:
            if field in values and not _is_blank(values.get(field)):
                row[field] = str(values.get(field)).strip()
            flag = f"{field}零值确认"
            if flag in values:
                row[flag] = bool(values.get(flag))
        operator = str(values.get("补录人") or "").strip()
        row["补录人"] = operator or row.get("补录人") or "值班员"
        row["补录时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        missing = _missing_temps(row)
        row["status"] = READY_STATUS if not missing else HOLD_STATUS
        row["pending"] = True
        if missing:
            return self._describe(row), f"已登记补录，仍缺：{'、'.join(missing)}（人工零值需勾选确认）"
        return self._describe(row), "补录完成，温度齐全，可执行校验通过"

    def validate_row(self, row_id: int) -> tuple[dict[str, Any] | None, str]:
        """校验通过：只有温度齐全（含已确认人工零值）的行才放行。"""
        row = store.find(QUEUE_MODULE, row_id)
        if row is None:
            return None, f"核对行 {row_id} 不存在或已清理"
        status = row.get("status")
        if status == COMMITTED_STATUS:
            return None, f"核对行 {row_id} 已写入正式记录，无需重复校验"
        if status == PASSED_STATUS:
            return self._describe(row), "该核对行已通过校验，等待入库"
        missing = _missing_temps(row)
        if missing:
            row["status"] = HOLD_STATUS
            row["pending"] = True
            return None, f"仍缺：{'、'.join(missing)}，请在校验区补录后再校验"
        row["status"] = PASSED_STATUS
        row["pending"] = False
        return self._describe(row), "校验通过，可写入正式记录"

    def commit(self) -> tuple[dict[str, Any] | None, str]:
        """把已通过校验的核对行写入正式记录，并生成可另存的表格文件。"""
        rows = store.rows(QUEUE_MODULE)
        passed = [row for row in rows if row.get("status") == PASSED_STATUS]
        if not passed:
            return None, "没有已通过校验的核对行；空范围可先用「导出队列模板」留存表头"
        records = store.rows(MODULE)
        seq = self._next_record_seq(records)
        created: list[dict[str, Any]] = []
        for row in passed:
            supplemented = bool(row.get("补录人"))
            record = {
                "id": max((int(item.get("id", 0)) for item in records), default=0) + 1,
                "记录编号": f"POWE-{seq:04d}",
                "电站编号": row.get("电站编号"),
                "发电量": row.get("发电量"),
                "辐照度": row.get("辐照度"),
                "组件温度": row.get("组件温度"),
                "环境温度": row.get("环境温度"),
                "记录时间": row.get("小时"),
                "数据状态": "补录" if supplemented else "正常",
                "status": "补录" if supplemented else "正常",
                "pending": False,
                "abnormal": False,
            }
            seq += 1
            records.append(record)
            row["status"] = COMMITTED_STATUS
            row["pending"] = False
            row["入库记录编号"] = record["记录编号"]
            created.append(record)
        file_name = self._save_file(created)
        result = {"file": file_name, "rows": len(created), "url": f"/api/power_data/files/{file_name}"}
        return result, f"已写入 {len(created)} 条正式记录，并生成表格文件 {file_name}"

    def export_queue_csv(self, *, status: str | None = None, station: str | None = None) -> str:
        """导出队列表格：空范围也保留模板表头，人工零值与未采集分开标注。"""
        rows = store.rows(QUEUE_MODULE)
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if station:
            rows = [row for row in rows if station in str(row.get("电站编号", ""))]
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(QUEUE_CSV_HEADERS)
        for row in rows:
            writer.writerow([
                row.get("电站编号"),
                row.get("小时"),
                row.get("发电量"),
                row.get("辐照度"),
                row.get("组件温度"),
                _temp_state(row, "组件温度"),
                row.get("环境温度"),
                _temp_state(row, "环境温度"),
                row.get("status"),
            ])
        return buffer.getvalue()

    def get_file(self, file_name: str) -> str | None:
        return self._files.get(file_name)

    def _describe(self, row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["温度口径"] = {field: _temp_state(row, field) for field in TEMP_FIELDS}
        data["缺失字段"] = _missing_temps(row)
        return data

    @staticmethod
    def _next_record_seq(records: list[dict[str, Any]]) -> int:
        seq = 0
        for record in records:
            no = str(record.get("记录编号", ""))
            if no.startswith("POWE-"):
                try:
                    seq = max(seq, int(no.split("-", 1)[1]))
                except ValueError:
                    continue
        return seq + 1

    def _save_file(self, records: list[dict[str, Any]]) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"发电记录_{stamp}.csv"
        suffix = 1
        while name in self._files:
            suffix += 1
            name = f"发电记录_{stamp}_{suffix}.csv"
        self._files[name] = _records_to_csv(records)
        return name
