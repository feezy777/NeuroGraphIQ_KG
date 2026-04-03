from __future__ import annotations

import json
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scripts.desktop.services import DesktopController
from scripts.desktop.view_models import MAJOR_NAVIGATION


STYLE = """
QMainWindow, QWidget {
  background: #f8fafc;
  color: #111827;
  font-size: 13px;
}
QGroupBox {
  border: 1px solid #d1d9e6;
  border-radius: 8px;
  margin-top: 10px;
  background: #ffffff;
  font-weight: 600;
}
QGroupBox::title {
  left: 10px;
  padding: 0 4px;
  color: #334155;
}
QTabWidget::pane {
  border: 1px solid #d6deeb;
  border-radius: 8px;
  background: #ffffff;
}
QTabBar::tab {
  background: #eef2f7;
  border: 1px solid #d6deeb;
  padding: 6px 10px;
  color: #1f2937;
  min-width: 100px;
}
QTabBar::tab:selected {
  background: #ffffff;
  border-bottom-color: #ffffff;
  color: #0f172a;
}
QTableWidget, QPlainTextEdit, QComboBox {
  background: #ffffff;
  color: #111827;
  border: 1px solid #d6deeb;
}
QHeaderView::section {
  background: #edf2f7;
  color: #0f172a;
  border: 1px solid #d6deeb;
  padding: 4px;
}
QTableWidget::item:selected {
  background: #dbeafe;
  color: #0f172a;
}
QPushButton {
  background: #f8fafc;
  color: #111827;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 8px 12px;
  min-height: 36px;
  text-align: left;
}
QPushButton:checked {
  background: #e2e8f0;
  border: 1px solid #94a3b8;
  color: #0f172a;
}
QProgressBar {
  border: 1px solid #cbd5e1;
  background: #f1f5f9;
  text-align: center;
}
QProgressBar::chunk {
  background: #3b82f6;
}
"""


def _safe_text(value: Any) -> str:
    return str(value) if value is not None else ""


def _list_lines(items: list[Any], prefix: str = "- ") -> list[str]:
    return [f"{prefix}{_safe_text(item)}" for item in items if _safe_text(item).strip()]


class DesktopMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.controller = DesktopController()
        self.setWindowTitle("NeuroKG Desktop V3.2")
        self.resize(1820, 1020)
        self.setStyleSheet(STYLE)

        self.selected_file_id = ""
        self.selected_major_pane = "major_regions"
        self.current_page = "major"
        self.crawler_jobs: list[dict[str, Any]] = []

        self._init_ui()
        self._bind()
        self.refresh_all()
        self._show_help("import_ontology")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_runtime)
        self.timer.start(1500)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.controller.shutdown()
        super().closeEvent(event)

    def _init_ui(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        self.act_import_ontology = QAction("Import Ontology", self)
        self.act_import_files = QAction("Import Files", self)
        self.act_preprocess = QAction("Start Preprocess", self)
        self.act_report = QAction("View Report", self)
        self.act_extract = QAction("Open Extract", self)
        self.act_preview_refresh = QAction("Refresh Preview", self)
        self.act_fine_route = QAction("Fine Route", self)
        self.act_save_settings = QAction("Save Settings", self)
        for action in [
            self.act_import_ontology,
            self.act_import_files,
            self.act_preprocess,
            self.act_report,
            self.act_extract,
            self.act_preview_refresh,
            self.act_fine_route,
            self.act_save_settings,
        ]:
            toolbar.addAction(action)

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        top_splitter = QSplitter(Qt.Horizontal, root)

        nav_box = QGroupBox("Modules", root)
        nav_box.setMinimumWidth(200)
        nav_box.setMaximumWidth(240)
        nav_layout = QVBoxLayout(nav_box)
        self.btn_page_major = QPushButton("主脑区", nav_box)
        self.btn_page_anatomy = QPushButton("解剖层", nav_box)
        self.btn_page_sub = QPushButton("Sub", nav_box)
        self.btn_page_allen = QPushButton("Allen", nav_box)
        self.btn_page_crawler = QPushButton("爬虫", nav_box)
        self.btn_page_settings = QPushButton("设置", nav_box)
        for btn in [
            self.btn_page_major,
            self.btn_page_anatomy,
            self.btn_page_sub,
            self.btn_page_allen,
            self.btn_page_crawler,
            self.btn_page_settings,
        ]:
            btn.setCheckable(True)
            btn.setMinimumHeight(38)
            nav_layout.addWidget(btn)
        nav_layout.addStretch(1)
        top_splitter.addWidget(nav_box)

        workspace_help_splitter = QSplitter(Qt.Horizontal, root)
        self.workspace_stack = QStackedWidget(root)
        self._build_major_page()
        self._build_anatomy_page()
        self._build_sub_page()
        self._build_allen_page()
        self._build_crawler_page()
        self._build_settings_page()
        workspace_help_splitter.addWidget(self.workspace_stack)

        help_box = QGroupBox("DeepSeek Help", root)
        help_box.setMinimumWidth(320)
        help_box.setMaximumWidth(420)
        help_layout = QVBoxLayout(help_box)
        self.help_title = QLabel("Action: -", help_box)
        self.help_source = QLabel("Source: -", help_box)
        self.help_body = QPlainTextEdit(help_box)
        self.help_body.setReadOnly(True)
        help_layout.addWidget(self.help_title)
        help_layout.addWidget(self.help_source)
        help_layout.addWidget(self.help_body, 1)
        workspace_help_splitter.addWidget(help_box)
        workspace_help_splitter.setSizes([1480, 340])

        top_splitter.addWidget(workspace_help_splitter)
        top_splitter.setSizes([220, 1600])
        root_layout.addWidget(top_splitter, 1)

        bottom = QGroupBox("Task Console", root)
        bottom_layout = QVBoxLayout(bottom)
        status_row = QHBoxLayout()
        self.lbl_gate = QLabel("Gate: -", bottom)
        self.lbl_stage = QLabel("Stage: -", bottom)
        self.lbl_queue = QLabel("Queue: -", bottom)
        self.progress = QProgressBar(bottom)
        self.progress.setRange(0, 100)
        status_row.addWidget(self.lbl_gate)
        status_row.addWidget(self.lbl_stage)
        status_row.addWidget(self.lbl_queue)
        status_row.addWidget(self.progress, 1)
        bottom_layout.addLayout(status_row)
        self.log_text = QPlainTextEdit(bottom)
        self.log_text.setReadOnly(True)
        bottom_layout.addWidget(self.log_text, 1)
        root_layout.addWidget(bottom, 0)

        self.setCentralWidget(root)
        self._set_page("major")

    def _build_major_page(self) -> None:
        page = QWidget(self.workspace_stack)
        page_layout = QVBoxLayout(page)
        splitter = QSplitter(Qt.Horizontal, page)

        left_box = QGroupBox("主脑区流程", page)
        left_layout = QVBoxLayout(left_box)
        self.file_filter = QComboBox(left_box)
        for name, key in [("All", "all"), ("PASS", "pass"), ("WARN", "warn"), ("FAIL", "fail"), ("Blocked", "blocked")]:
            self.file_filter.addItem(name, key)
        left_layout.addWidget(self.file_filter)

        self.file_table = QTableWidget(left_box)
        self.file_table.setColumnCount(7)
        self.file_table.setHorizontalHeaderLabels(["Name", "Type", "Label", "Score", "Blocked", "Status", "Last Processed"])
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.file_table.setSelectionMode(QTableWidget.SingleSelection)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.file_table, 1)

        left_layout.addWidget(QLabel("Major Pane", left_box))
        self.major_nav = QComboBox(left_box)
        for pane_id, title in MAJOR_NAVIGATION:
            self.major_nav.addItem(title, pane_id)
        left_layout.addWidget(self.major_nav)

        splitter.addWidget(left_box)

        right_box = QGroupBox("主脑区工作区", page)
        right_layout = QVBoxLayout(right_box)
        self.major_tabs = QTabWidget(right_box)
        self.preview_text = QPlainTextEdit(right_box)
        self.preview_text.setReadOnly(True)
        self.report_text = QPlainTextEdit(right_box)
        self.report_text.setReadOnly(True)
        self.major_text = QPlainTextEdit(right_box)
        self.major_text.setReadOnly(True)
        self.queue_text = QPlainTextEdit(right_box)
        self.queue_text.setReadOnly(True)
        self.major_tabs.addTab(self.preview_text, "文件预览")
        self.major_tabs.addTab(self.report_text, "校验报告")
        self.major_tabs.addTab(self.major_text, "提取结果")
        self.major_tabs.addTab(self.queue_text, "预处理队列")
        right_layout.addWidget(self.major_tabs, 1)
        splitter.addWidget(right_box)

        splitter.setSizes([560, 1180])
        page_layout.addWidget(splitter, 1)
        self.workspace_stack.addWidget(page)
    def _build_anatomy_page(self) -> None:
        page = QWidget(self.workspace_stack)
        layout = QVBoxLayout(page)
        box = QGroupBox("解剖层工作区", page)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(QLabel("用于 Organism/System/Organ/Division 的提取与校验。", box))
        self.anatomy_text = QPlainTextEdit(box)
        self.anatomy_text.setReadOnly(True)
        box_layout.addWidget(self.anatomy_text, 1)
        layout.addWidget(box, 1)
        self.workspace_stack.addWidget(page)

    def _build_sub_page(self) -> None:
        page = QWidget(self.workspace_stack)
        layout = QVBoxLayout(page)
        box = QGroupBox("Sub 粒度工作区", page)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(QLabel("Sub 层流程预留（结构已就绪，后续接业务逻辑）。", box))
        self.sub_text = QPlainTextEdit(box)
        self.sub_text.setReadOnly(True)
        box_layout.addWidget(self.sub_text, 1)
        layout.addWidget(box, 1)
        self.workspace_stack.addWidget(page)

    def _build_allen_page(self) -> None:
        page = QWidget(self.workspace_stack)
        layout = QVBoxLayout(page)
        box = QGroupBox("Allen 粒度工作区", page)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(QLabel("Allen 层流程预留（结构已就绪，后续接业务逻辑）。", box))
        self.allen_text = QPlainTextEdit(box)
        self.allen_text.setReadOnly(True)
        box_layout.addWidget(self.allen_text, 1)
        layout.addWidget(box, 1)
        self.workspace_stack.addWidget(page)

    def _build_crawler_page(self) -> None:
        page = QWidget(self.workspace_stack)
        layout = QVBoxLayout(page)

        box = QGroupBox("爬虫工作区", page)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(
            QLabel(
                "Crawler 是独立模块。当前版本为 deferred：可排队、可查看面板，不执行抓取。",
                box,
            )
        )
        self.crawler_source_text = QPlainTextEdit(box)
        self.crawler_source_text.setPlaceholderText("输入来源（每行一个）：URL / DOI / PMID / keyword")
        box_layout.addWidget(self.crawler_source_text, 1)
        row = QHBoxLayout()
        self.btn_crawler_queue = QPushButton("Queue Crawler Job", box)
        self.btn_crawler_refresh = QPushButton("Refresh Crawler Panel", box)
        row.addWidget(self.btn_crawler_queue)
        row.addWidget(self.btn_crawler_refresh)
        row.addStretch(1)
        box_layout.addLayout(row)
        self.crawler_text = QPlainTextEdit(box)
        self.crawler_text.setReadOnly(True)
        box_layout.addWidget(self.crawler_text, 1)

        layout.addWidget(box, 1)
        self.workspace_stack.addWidget(page)

    def _build_settings_page(self) -> None:
        page = QWidget(self.workspace_stack)
        layout = QVBoxLayout(page)
        box = QGroupBox("Settings (JSON Override)", page)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(
            QLabel(
                "Edit partial JSON override and click Save Settings.\n"
                "Example: {\"deepseek\": {\"api_key\": \"...\"}, \"pipeline\": {\"use_deepseek\": true}}",
                box,
            )
        )
        self.settings_editor = QPlainTextEdit(box)
        box_layout.addWidget(self.settings_editor, 1)
        self.btn_settings_reload = QPushButton("Reload Runtime Settings", box)
        box_layout.addWidget(self.btn_settings_reload)
        layout.addWidget(box, 1)
        self.workspace_stack.addWidget(page)

    def _bind(self) -> None:
        self.act_import_ontology.triggered.connect(self.on_import_ontology)
        self.act_import_files.triggered.connect(self.on_import_files)
        self.act_preprocess.triggered.connect(self.on_preprocess)
        self.act_report.triggered.connect(self.on_show_report)
        self.act_extract.triggered.connect(self.on_enter_extract)
        self.act_preview_refresh.triggered.connect(self.on_preview_refresh)
        self.act_fine_route.triggered.connect(self.on_fine_route)
        self.act_save_settings.triggered.connect(self.on_save_settings)

        self.btn_page_major.clicked.connect(lambda: self._set_page("major"))
        self.btn_page_anatomy.clicked.connect(lambda: self._set_page("anatomy"))
        self.btn_page_sub.clicked.connect(lambda: self._set_page("sub"))
        self.btn_page_allen.clicked.connect(lambda: self._set_page("allen"))
        self.btn_page_crawler.clicked.connect(lambda: self._set_page("crawler"))
        self.btn_page_settings.clicked.connect(lambda: self._set_page("settings"))

        self.file_filter.currentIndexChanged.connect(self.refresh_files)
        self.file_table.itemSelectionChanged.connect(self.on_select_file)
        self.major_nav.currentIndexChanged.connect(self.on_select_major_pane)

        self.btn_crawler_queue.clicked.connect(self.on_crawler_queue)
        self.btn_crawler_refresh.clicked.connect(self.on_crawler_refresh)
        self.btn_settings_reload.clicked.connect(self.on_settings_reload)

    def _set_page(self, page_key: str) -> None:
        mapping = {
            "major": 0,
            "anatomy": 1,
            "sub": 2,
            "allen": 3,
            "crawler": 4,
            "settings": 5,
        }
        idx = mapping.get(page_key, 0)
        self.workspace_stack.setCurrentIndex(idx)
        self.current_page = page_key

        self.btn_page_major.setChecked(page_key == "major")
        self.btn_page_anatomy.setChecked(page_key == "anatomy")
        self.btn_page_sub.setChecked(page_key == "sub")
        self.btn_page_allen.setChecked(page_key == "allen")
        self.btn_page_crawler.setChecked(page_key == "crawler")
        self.btn_page_settings.setChecked(page_key == "settings")

        if page_key == "settings":
            self.on_settings_reload()
        self._rebalance_layout()

    def _rebalance_layout(self) -> None:
        # Keep workspace dominant and avoid text clipping on high-DPI displays.
        if self.current_page == "major":
            self.file_table.resizeColumnsToContents()
            self.major_tabs.setCurrentWidget(self.major_tabs.currentWidget())

    def _show_help(self, action_id: str) -> None:
        vm = self.controller.get_action_help_view_model(action_id)
        self.help_title.setText(f"Action: {vm.get('title', action_id)}")
        self.help_source.setText(f"Source: {vm.get('source', '-')}")
        lines = [
            f"Purpose: {vm.get('purpose', '')}",
            "",
            "Preconditions:",
            *_list_lines(vm.get("preconditions", [])),
            "",
            "Inputs:",
            *_list_lines(vm.get("inputs", [])),
            "",
            "Risks:",
            *_list_lines(vm.get("risks", [])),
            "",
            "Next Steps:",
            *_list_lines(vm.get("next_steps", [])),
        ]
        self.help_body.setPlainText("\n".join(lines))

    def refresh_all(self) -> None:
        self.refresh_files()
        self.refresh_runtime()
        self.refresh_views()

    def refresh_runtime(self) -> None:
        gate = self.controller.gate_decision()
        self.lbl_gate.setText(f"Gate: {'READY' if not gate.block_reason else f'BLOCKED ({gate.block_reason})'}")
        tasks = self.controller.list_preprocess_tasks()
        done = len([x for x in tasks if x.get("status") in {"succeeded", "failed", "blocked"}])
        self.lbl_stage.setText(f"Stage: {tasks[0].get('current_stage', 'idle')}" if tasks else "Stage: idle")
        self.lbl_queue.setText(f"Queue: {done}/{len(tasks)}" if tasks else "Queue: 0/0")
        self.progress.setValue(int((done / len(tasks)) * 100) if tasks else 0)
        self.log_text.setPlainText("\n".join(self.controller.recent_logs()))

    def refresh_files(self) -> None:
        rows = self.controller.list_file_view_models(str(self.file_filter.currentData() or "all")).get("items", [])
        self.file_table.setRowCount(len(rows))
        selected_row = -1
        for r, row in enumerate(rows):
            values = [
                row.get("filename", ""),
                row.get("file_type", ""),
                row.get("label", ""),
                row.get("score", ""),
                "Yes" if row.get("blocked_on_load") else "No",
                row.get("status", ""),
                row.get("last_processed_at", ""),
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(_safe_text(v))
                if c == 0:
                    file_id = _safe_text(row.get("file_id", ""))
                    item.setData(Qt.UserRole, file_id)
                    if file_id and file_id == self.selected_file_id:
                        selected_row = r
                self.file_table.setItem(r, c, item)
        if selected_row >= 0:
            self.file_table.selectRow(selected_row)
        self.file_table.resizeColumnsToContents()
    def _render_preview_text(self, preview: dict[str, Any]) -> str:
        if preview.get("blocked"):
            return f"Preview blocked: {preview.get('message') or preview.get('block_reason') or '-'}"
        meta = preview.get("meta", {})
        payload = preview.get("payload", {}) if isinstance(preview.get("payload"), dict) else {}
        mode = _safe_text(preview.get("mode", ""))
        lines = [
            f"File: {meta.get('filename', '-')}",
            f"Type: {meta.get('file_type', '-')}",
            f"Label: {meta.get('preprocess_label', '-')}",
            f"Score: {meta.get('score', '-')}",
            f"Page: {meta.get('page', '-')}/{meta.get('total_pages', '-')}",
            f"Mode: {mode or '-'}",
            "",
        ]
        if mode == "table":
            headers = payload.get("headers", []) or []
            rows = payload.get("rows", []) or []
            lines.append(f"Total rows: {payload.get('total_rows', 0)}, page rows: {len(rows)}")
            lines.append(f"Columns: {', '.join([_safe_text(x) for x in headers])}")
            lines.append("")
            for idx, row in enumerate(rows[:30], start=1):
                if not isinstance(row, dict):
                    continue
                compact = " | ".join([f"{k}={_safe_text(v)}" for k, v in row.items()])
                lines.append(f"{idx}. {compact}")
        elif mode == "json":
            lines.append("JSON preview (first 40 lines):")
            text = _safe_text(payload.get("value", ""))
            lines.extend(text.splitlines()[:40])
        elif mode == "text":
            text = _safe_text(payload.get("text", ""))
            lines.append(f"Text length: {payload.get('chars', 0)} chars")
            lines.append(f"Total lines: {payload.get('total_lines', 0)}")
            lines.append("")
            lines.extend(text.splitlines()[:120])
        elif mode == "raw_embed":
            lines.append("Raw embed preview is active for this file.")
            lines.append(f"MIME: {payload.get('mime_type', '-')}")
            lines.append(f"Content API: {payload.get('content_url', '-')}")
            fallback_reason = _safe_text(payload.get("fallback_reason", ""))
            if fallback_reason:
                lines.append(f"Fallback reason: {fallback_reason}")
        else:
            lines.append("No preview content.")
        return "\n".join(lines)

    def _render_report_text(self, report: dict[str, Any]) -> str:
        if report.get("blocked"):
            overview = report.get("overview", {})
            return f"Report blocked: {overview.get('message') or report.get('block_reason') or '-'}"
        overview = report.get("overview", {})
        issues = report.get("issues", []) or []
        auto_fix = report.get("auto_fix_plan", []) or []
        manual_fix = report.get("manual_fix_plan", []) or []
        lines = [
            f"File: {overview.get('filename', '-')}",
            f"Label: {overview.get('label', '-')}",
            f"Score: {overview.get('score', '-')}",
            f"Issue count: {overview.get('issue_count', 0)}",
            f"Auto fix count: {overview.get('auto_applied_count', 0)}",
            f"Manual fix count: {overview.get('manual_required_count', 0)}",
            f"Blocked on load: {'Yes' if overview.get('blocked_on_load') else 'No'}",
            f"Summary: {overview.get('summary_cn', '')}",
            "",
            "Issues:",
        ]
        if issues:
            for item in issues[:50]:
                lines.append(
                    f"- [{item.get('severity', '-')}] {item.get('code', '-')}: {item.get('message', '-')}"
                    f" | suggestion: {item.get('suggestion', '-')}"
                )
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Auto Fix Plan:")
        lines.extend([f"- {x.get('action', '-')} ({x.get('risk', '-')}) - {x.get('reason', '-')}" for x in auto_fix[:30]] or ["- none"])
        lines.append("")
        lines.append("Manual Fix Plan:")
        lines.extend(
            [f"- {x.get('action', '-')} ({x.get('priority', '-')}) - {x.get('reason', '-')}" for x in manual_fix[:30]]
            or ["- none"]
        )
        lines.append("")
        lines.append("Artifact Paths:")
        for path_item in report.get("paths", []) or []:
            lines.append(f"- {path_item.get('label', '-')}: {path_item.get('value', '-')}")
        return "\n".join(lines)

    def _render_major_text(self, major: dict[str, Any]) -> str:
        if not major.get("available"):
            run_info = major.get("run_info", {})
            return f"No major result to display. {run_info.get('message', '')}".strip()

        run_info = major.get("run_info", {})
        pane = major.get("panes", {}).get(self.selected_major_pane, {})
        lines = [
            f"run_id: {run_info.get('run_id', '-')}",
            f"status: {run_info.get('status', '-')}",
            f"pane: {self.selected_major_pane}",
            "",
            "Summary Cards:",
        ]
        for card in major.get("summary_cards", []) or []:
            lines.append(f"- {card.get('title', '-')}: {card.get('value', '-')}")
        lines.append("")

        kind = _safe_text(pane.get("kind", ""))
        if kind == "table":
            rows = pane.get("rows", []) or []
            lines.append(f"Row count: {len(rows)}")
            lines.append("First 30 rows:")
            for idx, row in enumerate(rows[:30], start=1):
                if isinstance(row, dict):
                    compact = " | ".join([f"{k}={_safe_text(v)}" for k, v in row.items()])
                else:
                    compact = _safe_text(row)
                lines.append(f"{idx}. {compact}")
        else:
            cards = pane.get("cards", []) or []
            summary = pane.get("summary", []) or []
            lines.append("Pane Cards:")
            for item in cards:
                lines.append(f"- {item.get('title', '-')}: {item.get('value', '-')}")
            lines.append("")
            lines.append("Pane Summary:")
            for item in summary:
                lines.append(f"- {item.get('label', '-')}: {item.get('value', '-')}")
            tables = pane.get("tables", {}) or {}
            if tables:
                lines.append("")
                lines.append("Pane Tables:")
                for table_name, table_rows in tables.items():
                    lines.append(f"- {table_name}: {len(table_rows or [])} rows")
        return "\n".join(lines)

    def _render_crawler_text(self) -> str:
        lines = [f"Crawler job count: {len(self.crawler_jobs)}", ""]
        if not self.crawler_jobs:
            lines.append("No crawler jobs queued yet.")
            lines.append("Note: crawler module is deferred in current version.")
            return "\n".join(lines)
        for idx, job in enumerate(reversed(self.crawler_jobs[-100:]), start=1):
            lines.append(
                f"{idx}. job_id={job.get('job_id')} status={job.get('status')} source_count={job.get('source_count')} at={job.get('created_at')}"
            )
        return "\n".join(lines)

    def refresh_views(self) -> None:
        file_id = self.selected_file_id or self.controller.get_last_selected_file()
        if file_id:
            preview = self.controller.get_file_preview_view_model(file_id=file_id, page=1, page_size=200, mode="auto")
            report = self.controller.get_preprocess_report_view_model(file_id)
            self.preview_text.setPlainText(self._render_preview_text(preview))
            self.report_text.setPlainText(self._render_report_text(report))
        else:
            self.preview_text.setPlainText("No file selected.")
            self.report_text.setPlainText("No file selected.")

        major = self.controller.get_major_results_view_model()
        self.major_text.setPlainText(self._render_major_text(major))

        queue_rows = self.controller.list_preprocess_tasks()
        queue_lines = [f"Task count: {len(queue_rows)}", ""]
        for row in queue_rows[:200]:
            queue_lines.append(
                f"- task={row.get('task_id', '-')}, file={row.get('file_id', '-')}, "
                f"status={row.get('status', '-')}, stage={row.get('current_stage', '-')}"
            )
        self.queue_text.setPlainText("\n".join(queue_lines))

        latest_run = self.controller.latest_successful_run_id() or "-"
        gate = self.controller.gate_decision()
        self.anatomy_text.setPlainText(
            "\n".join(
                [
                    "Anatomy workspace reserved for organism/system/organ/division extraction.",
                    f"Gate allow preprocess: {gate.allow_preprocess}",
                    f"Latest major run: {latest_run}",
                ]
            )
        )
        self.sub_text.setPlainText(
            "\n".join(
                [
                    "Sub workspace is ready as independent module.",
                    "Business logic is pending implementation.",
                    f"Latest major run: {latest_run}",
                ]
            )
        )
        self.allen_text.setPlainText(
            "\n".join(
                [
                    "Allen workspace is ready as independent module.",
                    "Business logic is pending implementation.",
                    f"Latest major run: {latest_run}",
                ]
            )
        )
        self.crawler_text.setPlainText(self._render_crawler_text())
    def on_select_file(self) -> None:
        rows = self.file_table.selectionModel().selectedRows() if self.file_table.selectionModel() else []
        if not rows:
            return
        item = self.file_table.item(rows[0].row(), 0)
        if not item:
            return
        self.selected_file_id = _safe_text(item.data(Qt.UserRole) or "")
        self.controller.set_last_selected_file(self.selected_file_id)
        self.refresh_views()

    def on_select_major_pane(self) -> None:
        self.selected_major_pane = _safe_text(self.major_nav.currentData() or "major_regions")
        self.refresh_views()

    def on_import_ontology(self) -> None:
        self._show_help("import_ontology")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ontology file",
            "",
            "Ontology Files (*.rdf *.owl *.xml);;All Files (*.*)",
        )
        if not path:
            return
        result = self.controller.import_ontology(path)
        self.refresh_all()
        if result.get("success"):
            QMessageBox.information(self, "Ontology", _safe_text(result.get("message", "Ontology imported.")))
        else:
            QMessageBox.critical(self, "Ontology", _safe_text(result.get("message", "Ontology import failed.")))

    def on_import_files(self) -> None:
        self._show_help("import_files")
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select source files",
            "",
            "Supported Files (*.xlsx *.csv *.tsv *.json *.jsonl *.txt *.md *.pdf *.docx *.rdf *.owl *.xml);;All Files (*.*)",
        )
        if not files:
            return
        self.controller.import_files(files)
        self.refresh_all()

    def on_preprocess(self) -> None:
        self._show_help("start_preprocess")
        try:
            if self.selected_file_id:
                self.controller.start_preprocess([self.selected_file_id])
            else:
                self.controller.start_preprocess()
        except Exception as exc:
            QMessageBox.warning(self, "Preprocess", _safe_text(exc))
        self.refresh_all()

    def on_show_report(self) -> None:
        self._show_help("show_report")
        self._set_page("major")
        self.major_tabs.setCurrentWidget(self.report_text)
        self.refresh_views()

    def on_enter_extract(self) -> None:
        self._show_help("enter_extract")
        self._set_page("major")
        self.major_tabs.setCurrentWidget(self.major_text)
        self.refresh_views()

    def on_preview_refresh(self) -> None:
        self._show_help("preview_refresh")
        self._set_page("major")
        self.major_tabs.setCurrentWidget(self.preview_text)
        self.refresh_views()

    def on_fine_route(self) -> None:
        self._show_help("fine_route")
        if not self.selected_file_id:
            QMessageBox.information(self, "Fine Route", "Please select a file first.")
            return
        route = self.controller.route_for_fine_process(self.selected_file_id)
        lines = [
            f"processor_type: {route.get('processor_type', '-')}",
            f"status: {route.get('status', '-')}",
            "",
            "input_contract:",
        ]
        input_contract = route.get("input_contract", {}) if isinstance(route.get("input_contract"), dict) else {}
        output_contract = route.get("output_contract", {}) if isinstance(route.get("output_contract"), dict) else {}
        lines.extend(_list_lines(input_contract.get("required", [])))
        lines.append("")
        lines.append("output_contract:")
        lines.extend(_list_lines(output_contract.get("produces", [])))
        self.report_text.setPlainText("\n".join(lines))
        self._set_page("major")
        self.major_tabs.setCurrentWidget(self.report_text)

    def on_save_settings(self) -> None:
        self._show_help("save_settings")
        raw = self.settings_editor.toPlainText().strip()
        payload: dict[str, Any] = {}
        if raw:
            try:
                loaded = json.loads(raw)
                if not isinstance(loaded, dict):
                    raise ValueError("JSON root must be object")
                payload = loaded
            except Exception as exc:
                QMessageBox.warning(self, "Settings", f"Invalid JSON: {exc}")
                return
        self.controller.save_settings(payload)
        QMessageBox.information(self, "Settings", "Runtime settings saved.")
        self.refresh_runtime()

    def on_settings_reload(self) -> None:
        self._show_help("save_settings")
        settings = self.controller.load_settings()
        self.settings_editor.setPlainText(json.dumps(settings, ensure_ascii=False, indent=2))

    def on_crawler_queue(self) -> None:
        self._show_help("default")
        source_text = self.crawler_source_text.toPlainText().strip()
        source_count = len([x for x in source_text.splitlines() if x.strip()])
        job = {
            "job_id": f"crawler_{int(time.time())}",
            "status": "deferred",
            "source_count": source_count,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.crawler_jobs.append(job)
        self.crawler_text.setPlainText(self._render_crawler_text())
        QMessageBox.information(self, "Crawler", "Crawler job recorded as deferred (execution disabled in V3.2).")

    def on_crawler_refresh(self) -> None:
        self._show_help("default")
        self.crawler_text.setPlainText(self._render_crawler_text())


def run_desktop_app() -> None:
    app = QApplication.instance() or QApplication([])
    win = DesktopMainWindow()
    win.show()
    app.exec()
