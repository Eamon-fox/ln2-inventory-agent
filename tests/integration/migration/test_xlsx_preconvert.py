"""
Module: test_xlsx_preconvert
Layer: integration/migration
Covers: lib/migration/xlsx_preconvert.py, app_gui/xlsx_preconvert.py

XLSX 到 YAML 的预转换与资源生成，验证工作簿解析、
Sheet 到 CSV 转换、Schema 摘要生成以及异常处理逻辑。
"""

import csv
from datetime import date
import json
from pathlib import Path
import tempfile

from openpyxl import Workbook

from app_gui.xlsx_preconvert import XlsxPreconvertService


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_convert_staged_xlsx_generates_normalized_assets():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source_path = root / "legacy.xlsx"
        normalized_root = root / "normalized"

        workbook = Workbook()
        ws = workbook.active
        ws.title = "Inventory"
        ws.append(["box", "position", "frozen_at", "cell_line"])
        ws.append([1, 1, date(2025, 1, 2), "A549"])
        sheet2 = workbook.create_sheet("Notes")
        sheet2.append(["note"])
        sheet2.append(["sample"])
        workbook.save(source_path)

        result = XlsxPreconvertService().convert_staged_files(
            [str(source_path)],
            normalized_root=str(normalized_root),
        )

        assert result.status == "ok"
        assert Path(result.report_path).is_file()
        assert result.normalized_assets

        root_report = _read_json(result.report_path)
        assert root_report["status"] == "ok"
        assert root_report["xlsx_detected"] == 1
        assert len(root_report["sources"]) == 1

        source_report = root_report["sources"][0]
        assert source_report["status"] == "ok"
        schema_summary = _read_json(source_report["schema_summary_path"])
        assert schema_summary["sheet_count"] == 2
        inventory_sheet = next(
            sheet for sheet in schema_summary["sheets"] if sheet["sheet_name"] == "Inventory"
        )
        assert inventory_sheet["header_candidate"]["row_index"] == 1

        csv_path = Path(inventory_sheet["csv_path"])
        with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        assert rows[1][2] == "2025-01-02"
        assert rows[1][3] == "A549"


def test_convert_staged_files_skips_when_no_xlsx_present():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        csv_path = root / "source.csv"
        csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

        result = XlsxPreconvertService().convert_staged_files(
            [str(csv_path)],
            normalized_root=str(root / "normalized"),
        )

        assert result.status == "skipped"
        report = _read_json(result.report_path)
        assert report["status"] == "skipped"
        assert report["xlsx_detected"] == 0
        assert report["sources"] == []


def test_convert_staged_files_handles_invalid_xlsx_with_failed_status():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bad_xlsx = root / "bad.xlsx"
        bad_xlsx.write_text("not-an-xlsx", encoding="utf-8")

        result = XlsxPreconvertService().convert_staged_files(
            [str(bad_xlsx)],
            normalized_root=str(root / "normalized"),
        )

        assert result.status == "failed"
        assert "fallback" in result.message.lower()
        report = _read_json(result.report_path)
        assert report["status"] == "failed"
        assert report["xlsx_detected"] == 1
        assert report["sources"][0]["status"] == "failed"
