"""发电监测采集核对队列：采集数据先入队核对，通过校验才允许写入正式记录。

队列行以「电站编号 + 日期 + 小时」为唯一键：
- 未采集：空范围保留的模板行，还没有任何采集数据；
- 待补录：缺组件温度或环境温度，停在校验区，由值班员逐条补录；
- 人工零值：值班员确认的零发电，与未采集空白分开列示；
- 待入库：字段齐全、通过校验，允许写入正式记录；
- 已入库：已写入正式记录，队列里只读留存。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

QUEUE_MODULE = "power_data_queue"
FORMAL_MODULE = "power_data"

TEMP_FIELDS = ["组件温度", "环境温度"]
SUPPLEMENT_FIELDS = ["发电量", "辐照度", "组件温度", "环境温度"]
QUEUE_STATUSES = ["未采集", "待补录", "人工零值", "待入库", "已入库"]

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 起服务即可看到各分类样例：完整采集、缺温度待补录、人工零值、未采集模板。
SEED_QUEUE_ROWS: list[dict[str, Any]] = [
    {"电站编号": "PLAN-0001", "日期": "2026-09-27", "小时": 8, "发电量": 126.5, "辐照度": 412.0, "组件温度": 31.2, "环境温度": 26.8, "零值确认": False, "来源": "采集"},
    {"电站编号": "PLAN-0001", "日期": "2026-09-27", "小时": 9, "发电量": 188.4, "辐照度": 563.0, "组件温度": None, "环境温度": 27.5, "零值确认": False, "来源": "采集"},
    {"电站编号": "PLAN-0001", "日期": "2026-09-27", "小时": 10, "发电量": 235.1, "辐照度": 688.0, "组件温度": 36.4, "环境温度": None, "零值确认": False, "来源": "采集"},
    {"电站编号": "PLAN-0002", "日期": "2026-09-27", "小时": 8, "发电量": 0.0, "辐照度": 405.0, "组件温度": 30.6, "环境温度": 26.4, "零值确认": True, "来源": "人工"},
    {"电站编号": "PLAN-0002", "日期": "2026-09-27", "小时": 9, "发电量": 172.9, "辐照度": 551.0, "组件温度": None, "环境温度": None, "零值确认": False, "来源": "采集"},
    {"电站编号": "PLAN-0003", "日期": "2026-09-27", "小时": 8, "发电量": None, "辐照度": None, "组件温度": None, "环境温度": None, "零值确认": False, "来源": "模板"},
]


def _to_float(value: Any) -> float | None:
    """把输入转成浮点数；空串、None 视为未填写，非数字返回 None 由调用方拦截。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class PowerDataQueueService:
    def __init__(self) -> None:
        rows = store.rows(QUEUE_MODULE)
        if not rows:
            for index, seed in enumerate(SEED_QUEUE_ROWS, start=1):
                row = {"id": index, "已入库": False}
                row.update(seed)
                rows.append(row)

    # ---------- 基础工具 ----------

    def _station_codes(self) -> list[str]:
        codes = [str(row.get("电站编号") or "").strip() for row in store.rows("plant")]
        return [code for code in codes if code]

    def _next_id(self) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(QUEUE_MODULE)), default=0) + 1

    def _find_row(self, station: str, date: str, hour: int) -> dict[str, Any] | None:
        for row in store.rows(QUEUE_MODULE):
            if row.get("电站编号") == station and row.get("日期") == date and int(row.get("小时", -1)) == hour:
                return row
        return None

    def _new_row(self, station: str, date: str, hour: int, source: str) -> dict[str, Any]:
        row = {
            "id": self._next_id(),
            "电站编号": station,
            "日期": date,
            "小时": hour,
            "发电量": None,
            "辐照度": None,
            "组件温度": None,
            "环境温度": None,
            "零值确认": False,
            "来源": source,
            "已入库": False,
        }
        store.rows(QUEUE_MODULE).append(row)
        return row

    def _ensure_template(self, date: str, stations: list[str]) -> None:
        """空范围仍保留模板：指定日期下电站×小时缺一格补一格未采集空行。"""
        for station in stations:
            for hour in range(24):
                if self._find_row(station, date, hour) is None:
                    self._new_row(station, date, hour, "模板")

    @staticmethod
    def _classify(row: dict[str, Any]) -> str:
        if row.get("已入库"):
            return "已入库"
        has_power = row.get("发电量") is not None or row.get("零值确认")
        if not has_power:
            return "未采集"
        if any(row.get(field) is None for field in TEMP_FIELDS):
            return "待补录"
        if row.get("零值确认"):
            return "人工零值"
        return "待入库"

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        view = dict(row)
        view["队列状态"] = self._classify(row)
        return view

    # ---------- 查询 ----------

    def list_rows(
        self,
        *,
        station: str | None = None,
        date: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 100,
    ) -> tuple[list[dict[str, Any]], int, str | None]:
        if date and not DATE_PATTERN.match(date):
            return [], 0, f"日期「{date}」格式应为 YYYY-MM-DD"
        if status and status not in QUEUE_STATUSES:
            return [], 0, f"队列状态「{status}」不在{ '、'.join(QUEUE_STATUSES) }里"
        stations = [station] if station else self._station_codes()
        if date and stations:
            self._ensure_template(date, stations)
        rows = store.rows(QUEUE_MODULE)
        if station:
            rows = [row for row in rows if row.get("电站编号") == station]
        if date:
            rows = [row for row in rows if row.get("日期") == date]
        views = [self._view(row) for row in rows]
        if status:
            views = [view for view in views if view["队列状态"] == status]
        views.sort(key=lambda item: (str(item.get("日期")), str(item.get("电站编号")), int(item.get("小时", 0))))
        total = len(views)
        start = max(page - 1, 0) * size
        return views[start:start + size], total, None

    # ---------- 采集入队 ----------

    def collect(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """模拟一次采集：按电站×小时入队，已有行只补空缺字段，不覆盖补录结果。"""
        date = str(values.get("日期") or "").strip()
        if not DATE_PATTERN.match(date):
            return None, "采集日期缺失或格式应为 YYYY-MM-DD"
        stations = [str(item).strip() for item in values.get("电站列表") or [] if str(item).strip()]
        if not stations:
            stations = self._station_codes()
        if not stations:
            return None, "没有可用的电站编号，请先在电站档案里登记"
        try:
            start_hour = int(values.get("开始小时", 6))
            end_hour = int(values.get("结束小时", 18))
        except (TypeError, ValueError):
            return None, "开始小时、结束小时应为 0-23 的整数"
        if not (0 <= start_hour <= end_hour <= 23):
            return None, "小时范围应满足 0 ≤ 开始小时 ≤ 结束小时 ≤ 23"

        created = merged = 0
        for station in stations:
            for hour in range(start_hour, end_hour + 1):
                sample = self._sample_reading(hour)
                row = self._find_row(station, date, hour)
                if row is None:
                    row = self._new_row(station, date, hour, "采集")
                    created += 1
                    for field in SUPPLEMENT_FIELDS:
                        row[field] = sample[field]
                    if (hour + len(station)) % 3 == 0:
                        row["组件温度"] = None  # 留一档缺组件温度的行停在校验区
                    elif hour % 3 == 0:
                        row["环境温度"] = None  # 留一档缺环境温度的行停在校验区
                else:
                    if row.get("已入库"):
                        continue
                    for field in SUPPLEMENT_FIELDS:
                        if row.get(field) is None and sample[field] is not None:
                            row[field] = sample[field]
                            merged += 1
        return {"新增行数": created, "补全字段数": merged, "电站数": len(stations)}, (
            f"采集已入队：新增 {created} 行、补全 {merged} 个空缺字段；"
            "缺组件温度或环境温度的行已停在校验区"
        )

    @staticmethod
    def _sample_reading(hour: int) -> dict[str, float | None]:
        if 6 <= hour <= 18:
            return {
                "发电量": round(40.0 + (hour - 6) * 12.5, 1),
                "辐照度": round(300.0 + (hour - 6) * 35.0, 1),
                "组件温度": round(28.0 + (hour - 6) * 0.9, 1),
                "环境温度": round(24.0 + (hour - 6) * 0.6, 1),
            }
        return {"发电量": 0.0, "辐照度": 0.0, "组件温度": 22.0, "环境温度": 20.0}

    # ---------- 值班员补录 ----------

    def supplement(self, row_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        row = self._find_by_id(row_id)
        if row is None:
            return None, f"队列行 {row_id} 不存在或已移除"
        if row.get("已入库"):
            return None, "该行已写入正式记录，如需修改请走正式记录的补录动作"
        invalid = [field for field in SUPPLEMENT_FIELDS if field in values and str(values.get(field) or "").strip() and _to_float(values[field]) is None]
        if invalid:
            return None, f"字段{'、'.join(invalid)}应为数字，本次未写入"
        filled = []
        for field in SUPPLEMENT_FIELDS:
            number = _to_float(values.get(field))
            if number is None:
                continue
            row[field] = number
            filled.append(field)
        if not filled:
            return None, "没有可写入的补录内容，请至少填写一个数值字段"
        if row.get("来源") in ("模板", "采集"):
            row["来源"] = "补录"
        operator = str(values.get("操作人") or "").strip()
        if operator:
            row["补录人"] = operator
        status = self._classify(row)
        if status == "待补录":
            missing = "、".join(field for field in TEMP_FIELDS if row.get(field) is None)
            message = f"已补录{'、'.join(filled)}；仍缺{missing}，继续留在校验区"
        else:
            message = f"已补录{'、'.join(filled)}，校验通过，可写入正式记录"
        return self._view(row), message

    def confirm_zero(self, row_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        row = self._find_by_id(row_id)
        if row is None:
            return None, f"队列行 {row_id} 不存在或已移除"
        if row.get("已入库"):
            return None, "该行已写入正式记录，不能再改判零值"
        power = row.get("发电量")
        if power is not None and float(power) != 0.0:
            return None, f"该行已有发电量 {power}，不能标记为人工零值"
        row["发电量"] = 0.0
        row["零值确认"] = True
        row["来源"] = "人工"
        operator = str(values.get("操作人") or "").strip()
        if operator:
            row["补录人"] = operator
        return self._view(row), "已确认为人工零值，与未采集空白分开列示"

    def _find_by_id(self, row_id: int) -> dict[str, Any] | None:
        for row in store.rows(QUEUE_MODULE):
            if int(row.get("id", 0)) == row_id:
                return row
        return None

    # ---------- 校验入库 ----------

    def commit(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """只把通过校验的行写入正式记录；缺温度的留在校验区，未采集模板保留。"""
        station = str(values.get("电站编号") or "").strip() or None
        date = str(values.get("日期") or "").strip() or None
        rows = store.rows(QUEUE_MODULE)
        if station:
            rows = [row for row in rows if row.get("电站编号") == station]
        if date:
            rows = [row for row in rows if row.get("日期") == date]

        committed: list[dict[str, Any]] = []
        blocked = blank = 0
        for row in rows:
            status = self._classify(row)
            if status == "待补录":
                blocked += 1
            elif status == "未采集":
                blank += 1
            elif status in ("待入库", "人工零值"):
                committed.append(self._commit_row(row))
        if not committed:
            return None, f"没有通过校验的行：{blocked} 行缺温度留在校验区，{blank} 行未采集保留模板"
        message = f"已写入正式记录 {len(committed)} 条"
        if blocked:
            message += f"；{blocked} 行仍缺组件温度或环境温度，留在校验区"
        if blank:
            message += f"；{blank} 行未采集，空范围模板保留"
        return {"写入条数": len(committed), "校验区滞留": blocked, "未采集保留": blank, "记录编号": [row["记录编号"] for row in committed]}, message

    def _commit_row(self, row: dict[str, Any]) -> dict[str, Any]:
        formal_rows = store.rows(FORMAL_MODULE)
        record_no = self._next_record_no()
        entry = {
            "id": max((int(item.get("id", 0)) for item in formal_rows), default=0) + 1,
            "记录编号": record_no,
            "电站编号": row.get("电站编号"),
            "发电量": row.get("发电量") if not row.get("零值确认") else 0.0,
            "辐照度": row.get("辐照度"),
            "组件温度": row.get("组件温度"),
            "环境温度": row.get("环境温度"),
            "记录时间": f"{row.get('日期')} {int(row.get('小时', 0)):02d}:00",
            "数据状态": "人工零值" if row.get("零值确认") else str(row.get("来源") or "采集"),
            "status": "补录" if row.get("来源") == "补录" else "正常",
            "pending": False,
            "abnormal": False,
        }
        formal_rows.append(entry)
        row["已入库"] = True
        row["记录编号"] = record_no
        return entry

    @staticmethod
    def _next_record_no() -> str:
        suffix = 0
        for item in store.rows(FORMAL_MODULE):
            text = str(item.get("记录编号") or "")
            if text.startswith("POWE-") and text[5:].isdigit():
                suffix = max(suffix, int(text[5:]))
        return f"POWE-{suffix + 1:04d}"

    # ---------- 另存表格 ----------

    def export_rows(self, *, station: str | None = None, date: str | None = None) -> tuple[list[dict[str, Any]], int]:
        """导出正式记录：只有校验通过写入的记录才进入可另存的表格。"""
        rows = list(store.rows(FORMAL_MODULE))
        if station:
            rows = [row for row in rows if row.get("电站编号") == station]
        if date:
            rows = [row for row in rows if str(row.get("记录时间") or "").startswith(date)]
        return rows, len(rows)
