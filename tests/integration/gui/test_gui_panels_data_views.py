"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class CellLineDropdownTests(ManagedPathTestCase):
    """Tests for cell_line QComboBox in operations panel."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _hint_lines():
        return [
            tr("operations.cellLineOptionsHintLine1"),
            tr("operations.cellLineOptionsHintLine2"),
        ]

    def test_cell_line_combo_is_absent_without_active_policy(self):
        """Operations panel hides cell_line when schema/policy does not expose it."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        self.assertTrue(hasattr(panel, "a_cell_line"))
        self.assertIsNone(panel.a_cell_line)

    def test_cell_line_combo_starts_with_empty_when_legacy_meta_exposes_it(self):
        """Legacy meta should materialize the combo with an empty first option."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        panel.apply_meta_update(
            {
                "cell_line_required": False,
                "cell_line_options": ["K562", "HeLa"],
            }
        )
        self.assertEqual("", panel.a_cell_line.itemText(0))

    def test_apply_meta_update_populates_cell_line_combo(self):
        """apply_meta_update should populate legacy-backed cell_line options."""
        from lib.custom_fields import get_field_options, is_field_required

        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        meta = {"cell_line_options": ["K562", "HeLa", "NCCIT"]}
        panel.apply_meta_update(meta)
        hints = self._hint_lines()
        required = is_field_required(meta, "cell_line")
        options = get_field_options(meta, "cell_line")
        option_start = 0 if required else 1
        expected_count = len(options) + (0 if required else 1) + len(hints)
        self.assertEqual(expected_count, panel.a_cell_line.count())
        self.assertEqual("K562", panel.a_cell_line.itemText(option_start))
        self.assertEqual("HeLa", panel.a_cell_line.itemText(option_start + 1))
        self.assertEqual("NCCIT", panel.a_cell_line.itemText(option_start + 2))

        model = panel.a_cell_line.model()
        for i, hint in enumerate(hints):
            row = panel.a_cell_line.count() - len(hints) + i
            self.assertEqual(hint, panel.a_cell_line.itemText(row))
            flags = model.flags(model.index(row, 0))
            self.assertFalse(bool(flags & Qt.ItemIsSelectable))

    def test_apply_meta_update_rebuilds_cell_line_combo_deterministically(self):
        """Refreshing from canonical meta rebuilds the combo deterministically."""
        from lib.custom_fields import is_field_required

        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        meta = {"cell_line_options": ["K562", "HeLa"]}
        panel.apply_meta_update(meta)
        hella_index = 1 if is_field_required(meta, "cell_line") else 2
        panel.a_cell_line.setCurrentIndex(hella_index)  # HeLa
        self.assertEqual("HeLa", panel.a_cell_line.currentText())

        # Refresh again with same options
        panel.apply_meta_update(meta)
        self.assertEqual("K562", panel.a_cell_line.currentText())

    def test_apply_meta_update_keeps_cell_line_combo_absent_without_policy(self):
        """Without legacy policy or schema, the combo stays empty."""

        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        panel.apply_meta_update({})
        self.assertIsNone(panel.a_cell_line)

    def test_apply_meta_update_switches_required_mode_immediately(self):
        """Changing cell_line_required should update add-form combo immediately."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

        panel.apply_meta_update({
            "cell_line_required": True,
            "cell_line_options": ["K562", "HeLa"],
            "custom_fields": [],
        })
        self.assertEqual(2 + len(self._hint_lines()), panel.a_cell_line.count())
        self.assertEqual("K562", panel.a_cell_line.itemText(0))

        panel.apply_meta_update({
            "cell_line_required": False,
            "cell_line_options": ["K562", "HeLa"],
            "custom_fields": [],
        })
        self.assertEqual(3 + len(self._hint_lines()), panel.a_cell_line.count())
        self.assertEqual("", panel.a_cell_line.itemText(0))
        self.assertEqual("K562", panel.a_cell_line.itemText(1))

    def test_context_cell_line_uses_lockable_edit_fields(self):
        """Thaw/move cell_line context should support lock-based inline editing."""
        from PySide6.QtWidgets import QLineEdit

        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        self.assertIsInstance(panel.t_ctx_cell_line, QLineEdit)
        self.assertIsInstance(panel.m_ctx_cell_line, QLineEdit)
        self.assertTrue(panel.t_ctx_cell_line.isReadOnly())
        self.assertTrue(panel.m_ctx_cell_line.isReadOnly())

    def test_context_cell_line_prefix_validator_and_completer(self):
        """Cell line edit should allow only option prefixes and exact option values."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        panel.apply_meta_update({
            "cell_line_required": True,
            "cell_line_options": ["K562", "HeLa", "NCCIT"],
            "custom_fields": [],
        })

        validator = panel.t_ctx_cell_line.validator()
        self.assertIsInstance(validator, QValidator)

        state, _, _ = validator.validate("K", 1)
        self.assertIn(state, (QValidator.Intermediate, QValidator.Acceptable))

        state, _, _ = validator.validate("X", 1)
        self.assertEqual(QValidator.Invalid, state)

        state, _, _ = validator.validate("hela", 4)
        self.assertEqual(QValidator.Acceptable, state)

        panel.t_ctx_cell_line.setText("")
        completer = panel.t_ctx_cell_line.completer()
        self.assertIsNotNone(completer)
        self.assertEqual(QCompleter.UnfilteredPopupCompletion, completer.completionMode())
        model = completer.model()
        self.assertIsNotNone(model)
        hints = self._hint_lines()
        self.assertEqual(3 + len(hints), model.rowCount())
        self.assertEqual(model.rowCount(), completer.maxVisibleItems())
        popup = completer.popup()
        self.assertIsNotNone(popup)
        self.assertEqual(Qt.ScrollBarAlwaysOff, popup.verticalScrollBarPolicy())
        self.assertEqual(Qt.ScrollBarAlwaysOff, popup.horizontalScrollBarPolicy())
        self.assertEqual(popup.minimumHeight(), popup.maximumHeight())
        self.assertGreater(popup.maximumHeight(), 0)

        move_completer = panel.m_ctx_cell_line.completer()
        self.assertIsNotNone(move_completer)
        self.assertEqual(model.rowCount(), move_completer.maxVisibleItems())

        for i, hint in enumerate(hints):
            row = model.rowCount() - len(hints) + i
            idx = model.index(row, 0)
            self.assertEqual(hint, model.data(idx))
            flags = model.flags(idx)
            self.assertFalse(bool(flags & Qt.ItemIsSelectable))

    def test_add_cell_line_combo_expands_without_scrollbar(self):
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        opts = [f"Cell-{i:02d}" for i in range(30)]
        panel.apply_meta_update({
            "cell_line_required": True,
            "cell_line_options": opts,
            "custom_fields": [],
        })

        hints = self._hint_lines()
        expected_rows = len(opts) + len(hints)
        self.assertEqual(expected_rows, panel.a_cell_line.maxVisibleItems())
        view = panel.a_cell_line.view()
        self.assertIsNotNone(view)
        self.assertEqual(Qt.ScrollBarAlwaysOff, view.verticalScrollBarPolicy())
        self.assertEqual(view.minimumHeight(), view.maximumHeight())
        self.assertGreater(view.maximumHeight(), 0)

        model = panel.a_cell_line.model()
        self.assertEqual(expected_rows, panel.a_cell_line.count())
        for i, hint in enumerate(hints):
            row = panel.a_cell_line.count() - len(hints) + i
            self.assertEqual(hint, panel.a_cell_line.itemText(row))
            self.assertFalse(bool(model.flags(model.index(row, 0)) & Qt.ItemIsSelectable))

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class OverviewColorKeyFilterTests(ManagedPathTestCase):
    """Tests for overview panel filtering by color_key."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records, meta_extra=None):
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="ln2_ov_ck_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        meta = {"box_layout": {"rows": 9, "cols": 9}}
        if meta_extra:
            meta.update(meta_extra)
        from lib.yaml_ops import write_yaml
        write_yaml(
            {"meta": meta, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def _hover_preview_text(self, yaml_path, box=1, position=1):
        from app_gui.i18n import set_language
        from app_gui.tool_bridge import GuiToolBridge

        set_language("en")
        panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
        panel.refresh()
        panel._show_detail(box, position, panel.overview_pos_map.get((box, position)))
        return panel.ov_hover_hint.text()

    def test_filter_dropdown_uses_color_key_values(self):
        """Filter dropdown should show unique values of the color_key field."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 3, "cell_line": "K562", "short_name": "C", "box": 1, "position": 3, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            items = [panel.ov_filter_cell.itemText(i) for i in range(panel.ov_filter_cell.count())]
            self.assertIn(tr("overview.allCells"), items)
            self.assertIn("K562", items)
            self.assertIn("HeLa", items)
        finally:
            self._cleanup(tmpdir)

    def test_filter_by_color_key_hides_non_matching(self):
        """Selecting a color_key value should filter the dropdown correctly."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            # Verify pos_map is populated
            self.assertIn((1, 1), panel.overview_pos_map)
            self.assertIn((1, 2), panel.overview_pos_map)

            # Verify color_key_value property is set on buttons
            btn_1 = panel.overview_cells.get((1, 1))
            btn_2 = panel.overview_cells.get((1, 2))
            self.assertIsNotNone(btn_1)
            self.assertIsNotNone(btn_2)
            self.assertEqual("K562", btn_1.property("color_key_value"))
            self.assertEqual("HeLa", btn_2.property("color_key_value"))
        finally:
            self._cleanup(tmpdir)

    def test_refresh_maps_alphanumeric_stats_positions_to_internal_indices(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 2,
                "frozen_at": "2025-01-01",
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(
            records,
            meta_extra={"box_layout": {"rows": 9, "cols": 9, "indexing": "alphanumeric"}},
        )
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self.assertIn((1, 2), panel.overview_pos_map)
        finally:
            self._cleanup(tmpdir)

    def test_color_key_custom_field(self):
        """color_key can be set to a user field like short_name."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "Alpha", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "K562", "short_name": "Beta", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "short_name"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            items = [panel.ov_filter_cell.itemText(i) for i in range(panel.ov_filter_cell.count())]
            self.assertIn("Alpha", items)
            self.assertIn("Beta", items)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_uses_display_and_color_keys(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "custom_tag": "Tag-A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "cell_line", "color_key": "custom_tag"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("K562 / Tag-A", text)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_deduplicates_when_display_and_color_key_same(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "cell_line", "color_key": "cell_line"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("K562", text)
            self.assertNotIn(" / ", text)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_deduplicates_when_values_equal(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "custom_tag": "K562",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "cell_line", "color_key": "custom_tag"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("K562", text)
            self.assertNotIn(" / ", text)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_skips_empty_values(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "custom_tag": " ",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "custom_tag", "color_key": "cell_line"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("K562", text)
            self.assertNotIn(" / ", text)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_uses_dash_when_display_and_color_empty(self):
        records = [
            {
                "id": 1,
                "cell_line": "",
                "custom_tag": " ",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "custom_tag", "color_key": "cell_line"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("| -", text)
            self.assertNotIn(" / ", text)
        finally:
            self._cleanup(tmpdir)

    def test_hover_preview_does_not_require_short_name(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        meta_extra = {"display_key": "cell_line", "color_key": "short_name"}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            text = self._hover_preview_text(yaml_path)
            self.assertIn("K562", text)
            self.assertNotIn(" / ", text)
        finally:
            self._cleanup(tmpdir)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class OverviewTableViewTests(ManagedPathTestCase):
    """Tests for Overview table view and shared live filters."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records, meta_extra=None):
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="ln2_ov_table_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        meta = {"box_layout": {"rows": 9, "cols": 9}}
        if meta_extra:
            meta.update(meta_extra)
        from lib.yaml_ops import write_yaml

        write_yaml(
            {"meta": meta, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup(self, tmpdir):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def _switch_to_table(self, panel):
        if hasattr(panel, "ov_view_mode"):
            idx = panel.ov_view_mode.findData("table")
            self.assertGreaterEqual(idx, 0)
            panel.ov_view_mode.setCurrentIndex(idx)
        else:
            panel._on_view_mode_changed("table")

    def _switch_to_grid(self, panel):
        if hasattr(panel, "ov_view_mode"):
            idx = panel.ov_view_mode.findData("grid")
            self.assertGreaterEqual(idx, 0)
            panel.ov_view_mode.setCurrentIndex(idx)
        else:
            panel._on_view_mode_changed("grid")

    def _table_header_texts(self, panel):
        return [
            panel.ov_table.horizontalHeaderItem(i).text()
            for i in range(panel.ov_table.columnCount())
        ]

    def _table_headers(self, panel):
        return self._table_header_texts(panel)

    def _table_column_index(self, panel, column_name):
        for idx in range(panel.ov_table.columnCount()):
            header_item = panel.ov_table.horizontalHeaderItem(idx)
            if header_item is None:
                continue
            raw_column = header_item.data(Qt.UserRole)
            if raw_column in (None, ""):
                raw_column = header_item.text()
            if str(raw_column) == str(column_name):
                return idx
        raise ValueError(f"column not found: {column_name}")

    def _table_column_texts(self, panel, column_name):
        column_index = self._table_column_index(panel, column_name)
        return [
            panel.ov_table.item(row, column_index).text()
            for row in range(panel.ov_table.rowCount())
        ]

    def test_table_view_uses_export_columns(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "passage_number": 3,
            },
            {
                "id": 2,
                "cell_line": "HeLa",
                "short_name": "B",
                "box": 2,
                "position": 2,
                "frozen_at": "2025-01-01",
                "passage_number": 7,
            },
        ]
        meta_extra = {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "passage_number", "label": "Passage #", "type": "int"},
            ],
            "color_key": "cell_line",
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = self._table_header_texts(panel)
            self.assertIn("id", headers)
            self.assertIn("Cell Line", headers)
            self.assertIn("location", headers)  # Changed from "position" to "location"
            self.assertIn("Passage #", headers)
            self.assertEqual(
                "cell_line",
                panel.ov_table.horizontalHeaderItem(self._table_column_index(panel, "cell_line")).data(Qt.UserRole),
            )
            self.assertEqual(
                "passage_number",
                panel.ov_table.horizontalHeaderItem(self._table_column_index(panel, "passage_number")).data(Qt.UserRole),
            )
            self.assertEqual(2, panel.ov_table.rowCount())
        finally:
            self._cleanup(tmpdir)

    def test_table_view_refresh_updates_custom_field_header_label_without_column_key_change(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "sample_tag": "tag-A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(
            records,
            meta_extra={
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "sample_tag", "label": "Old Label", "type": "str"},
                ],
                "display_key": "sample_tag",
                "color_key": "cell_line",
            },
        )
        try:
            from app_gui.tool_bridge import GuiToolBridge
            from lib.yaml_ops import write_yaml

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            sample_tag_col = self._table_column_index(panel, "sample_tag")
            self.assertEqual("Old Label", panel.ov_table.horizontalHeaderItem(sample_tag_col).text())

            write_yaml(
                {
                    "meta": {
                        "box_layout": {"rows": 9, "cols": 9},
                        "custom_fields": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                            {"key": "sample_tag", "label": "New Label", "type": "str"},
                        ],
                        "display_key": "sample_tag",
                        "color_key": "cell_line",
                    },
                    "inventory": records,
                },
                path=yaml_path,
                audit_meta={"action": "tests", "source": "tests"},
            )
            panel._stats_response_cache = {}
            panel.refresh()

            sample_tag_col = self._table_column_index(panel, "sample_tag")
            header_item = panel.ov_table.horizontalHeaderItem(sample_tag_col)
            self.assertEqual("New Label", header_item.text())
            self.assertEqual("sample_tag", header_item.data(Qt.UserRole))
        finally:
            self._cleanup(tmpdir)

    def test_table_view_displays_updated_structural_labels_in_english(self):
        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "thaw_events": [{"date": "2025-01-03", "action": "takeout", "positions": [1]}],
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from PySide6.QtWidgets import QDialog
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = self._table_header_texts(panel)
            self.assertIn("Deposited Date", headers)
            self.assertIn("Storage Events", headers)
            self.assertNotIn("frozen_at", headers)
            self.assertNotIn("thaw_events", headers)
        finally:
            self._cleanup(tmpdir)

    def test_table_view_displays_updated_structural_labels_in_chinese(self):
        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("zh-CN"))

        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "thaw_events": [{"date": "2025-01-03", "action": "takeout", "positions": [1]}],
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = self._table_header_texts(panel)
            self.assertIn("存入日期", headers)
            self.assertIn("存储事件", headers)
            self.assertNotIn("frozen_at", headers)
            self.assertNotIn("thaw_events", headers)
        finally:
            self._cleanup(tmpdir)

    def test_table_column_filter_dialog_uses_display_label_but_keeps_logical_key(self):
        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "thaw_events": [{"date": "2025-01-03", "action": "takeout", "positions": [1]}],
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from PySide6.QtWidgets import QDialog
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = self._table_header_texts(panel)
            storage_events_col = headers.index("Storage Events")
            captured = {}

            class _FakeDialog:
                def __init__(self, _parent, column_name, filter_type, unique_values, current_filter):
                    captured["column_name"] = column_name
                    captured["filter_type"] = filter_type
                    captured["unique_values"] = unique_values
                    captured["current_filter"] = current_filter
                    self.filter_config = {"type": "text", "text": "takeout"}

                def exec(self):
                    return QDialog.Accepted

                def get_filter_config(self):
                    return dict(self.filter_config)

            with patch("app_gui.ui.overview_panel._ColumnFilterDialog", _FakeDialog), patch.object(
                panel,
                "_apply_filters",
            ) as apply_mock:
                panel._on_column_filter_clicked(storage_events_col, headers[storage_events_col])

            self.assertEqual("Storage Events", captured.get("column_name"))
            self.assertEqual("text", captured.get("filter_type"))
            self.assertIsNone(captured.get("unique_values"))
            self.assertEqual({"type": "text", "text": "takeout"}, panel._column_filters.get("thaw_events"))
            self.assertNotIn("Storage Events", panel._column_filters)
            apply_mock.assert_called_once()
        finally:
            self._cleanup(tmpdir)

    def test_table_column_filter_dialog_uses_custom_display_label_but_keeps_raw_key(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "sample_tag": "Alpha",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
            {
                "id": 2,
                "cell_line": "HeLa",
                "sample_tag": "Beta",
                "box": 1,
                "position": 2,
                "frozen_at": "2025-01-01",
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(
            records,
            meta_extra={
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "sample_tag", "label": "Sample Tag", "type": "str"},
                ],
                "display_key": "sample_tag",
                "color_key": "cell_line",
            },
        )
        try:
            from PySide6.QtWidgets import QDialog
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            sample_tag_col = self._table_column_index(panel, "sample_tag")
            captured = {}

            class _FakeDialog:
                def __init__(self, _parent, column_name, filter_type, unique_values, current_filter):
                    captured["column_name"] = column_name
                    captured["filter_type"] = filter_type
                    captured["unique_values"] = list(unique_values or [])
                    captured["current_filter"] = current_filter
                    self.filter_config = {"type": "list", "values": ["Alpha"]}

                def exec(self):
                    return QDialog.Accepted

                def get_filter_config(self):
                    return dict(self.filter_config)

            with patch("app_gui.ui.overview_panel._ColumnFilterDialog", _FakeDialog), patch.object(
                panel,
                "_apply_filters",
            ) as apply_mock:
                panel._on_column_filter_clicked(sample_tag_col, "sample_tag")

            self.assertEqual("Sample Tag", captured.get("column_name"))
            self.assertEqual("list", captured.get("filter_type"))
            self.assertIn(("Alpha", 1), captured.get("unique_values"))
            self.assertEqual({"type": "list", "values": ["Alpha"]}, panel._column_filters.get("sample_tag"))
            self.assertNotIn("Sample Tag", panel._column_filters)
            apply_mock.assert_called_once()
        finally:
            self._cleanup(tmpdir)

    def test_table_view_shares_live_filters(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)
            self.assertEqual(2, panel.ov_table.rowCount())

            panel.ov_filter_keyword.setText("hela")
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("2", panel.ov_table.item(0, 0).text())

            panel.ov_filter_keyword.clear()
            box_idx = panel.ov_filter_box.findData(1)
            self.assertGreaterEqual(box_idx, 0)
            panel.ov_filter_box.setCurrentIndex(box_idx)
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("1", panel.ov_table.item(0, 0).text())

            panel.ov_filter_box.setCurrentIndex(0)
            cell_idx = panel.ov_filter_cell.findData("K562")
            self.assertGreaterEqual(cell_idx, 0)
            panel.ov_filter_cell.setCurrentIndex(cell_idx)
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("1", panel.ov_table.item(0, 0).text())
        finally:
            self._cleanup(tmpdir)

    def test_table_location_sort_uses_natural_box_position_order(self):
        records = [
            {"id": 201, "cell_line": "K562", "short_name": "p10", "box": 1, "position": 10, "frozen_at": "2025-01-01"},
            {"id": 202, "cell_line": "K562", "short_name": "p2", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 203, "cell_line": "K562", "short_name": "p1", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            location_col = self._table_column_index(panel, "location")

            panel.ov_table.sortItems(location_col, Qt.DescendingOrder)
            self.assertEqual(
                ["1:10", "1:2", "1:1"],
                self._table_column_texts(panel, "location"),
            )

            panel.ov_table.sortItems(location_col, Qt.AscendingOrder)
            self.assertEqual(
                ["1:1", "1:2", "1:10"],
                self._table_column_texts(panel, "location"),
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_id_sort_uses_numeric_order(self):
        records = [
            {"id": 10, "cell_line": "K562", "short_name": "ten", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "K562", "short_name": "two", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 1, "cell_line": "K562", "short_name": "one", "box": 1, "position": 3, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            id_col = self._table_column_index(panel, "id")

            panel.ov_table.sortItems(id_col, Qt.AscendingOrder)
            self.assertEqual(["1", "2", "10"], self._table_column_texts(panel, "id"))
        finally:
            self._cleanup(tmpdir)

    def test_table_numeric_custom_field_sort_uses_numeric_order(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "ten",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "passage_number": 10,
            },
            {
                "id": 2,
                "cell_line": "K562",
                "short_name": "two",
                "box": 1,
                "position": 2,
                "frozen_at": "2025-01-01",
                "passage_number": 2,
            },
            {
                "id": 3,
                "cell_line": "K562",
                "short_name": "one",
                "box": 1,
                "position": 3,
                "frozen_at": "2025-01-01",
                "passage_number": 1,
            },
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [{"key": "passage_number", "label": "Passage #", "type": "int"}],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            passage_col = self._table_column_index(panel, "passage_number")

            panel.ov_table.sortItems(passage_col, Qt.AscendingOrder)
            self.assertEqual(
                ["1", "2", "10"],
                self._table_column_texts(panel, "passage_number"),
            )
        finally:
            self._cleanup(tmpdir)

    def test_detect_column_type_uses_current_meta_without_yaml_load(self):
        records = []
        for idx in range(1, 31):
            records.append(
                {
                    "id": idx,
                    "cell_line": f"Line-{idx}",
                    "short_name": f"S-{idx}",
                    "box": 1,
                    "position": idx,
                    "frozen_at": "2025-01-01",
                    "passage_number": idx,
                }
            )
        meta_extra = {
            "custom_fields": [{"key": "passage_number", "label": "Passage #", "type": "int"}],
            "color_key": "cell_line",
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            with patch(
                "lib.yaml_ops.load_yaml",
                side_effect=AssertionError("column type detection should not reload YAML"),
            ):
                detected = panel._detect_column_type("passage_number")

            self.assertEqual("number", detected)
        finally:
            self._cleanup(tmpdir)

    def test_get_unique_column_values_uses_table_version_cache(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            class _CountingRows(list):
                def __init__(self, rows):
                    super().__init__(rows)
                    self.iter_calls = 0

                def __iter__(self):
                    self.iter_calls += 1
                    return super().__iter__()

            panel._table_rows = _CountingRows(list(panel._table_rows))
            panel._table_version = 7
            panel._column_unique_cache = {}

            first = panel._get_unique_column_values("cell_line")
            second = panel._get_unique_column_values("cell_line")
            self.assertEqual(first, second)
            self.assertEqual(1, panel._table_rows.iter_calls)

            panel._table_version = 8
            panel._get_unique_column_values("cell_line")
            self.assertEqual(2, panel._table_rows.iter_calls)
        finally:
            self._cleanup(tmpdir)

    def test_rebuild_table_rows_bumps_version_and_clears_unique_cache(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            panel._table_version = 3
            panel._column_unique_cache = {("cell_line", 3): [("K562", 1)]}
            panel._rebuild_table_rows(panel._current_records)

            self.assertEqual(4, panel._table_version)
            self.assertEqual({}, panel._column_unique_cache)
        finally:
            self._cleanup(tmpdir)

    def test_render_table_rows_uses_set_row_count_batch_path(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            rows = list(panel._table_rows)
            table_cls = type(panel.ov_table)
            set_row_count_calls = []
            original_set_row_count = table_cls.setRowCount

            def _tracked_set_row_count(count):
                set_row_count_calls.append(count)
                return original_set_row_count(panel.ov_table, count)

            with patch.object(
                table_cls,
                "insertRow",
                autospec=True,
                side_effect=AssertionError("_render_table_rows should not use insertRow per row"),
            ), patch.object(
                table_cls,
                "setRowCount",
                autospec=True,
                side_effect=_tracked_set_row_count,
            ):
                panel._render_table_rows(rows)

            self.assertEqual([len(rows)], set_row_count_calls)
            self.assertEqual(len(rows), panel.ov_table.rowCount())
        finally:
            self._cleanup(tmpdir)

    def test_match_column_filter_list_compiles_value_set(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            row_data = {"values": {"cell_line": "HeLa"}}
            filter_config = {"type": "list", "values": ["K562", "HeLa"]}

            self.assertTrue(panel._match_column_filter(row_data, "cell_line", filter_config))
            self.assertEqual({"K562", "HeLa"}, filter_config.get("_values_set"))

            filter_config["values"] = ["A549"]
            self.assertFalse(panel._match_column_filter(row_data, "cell_line", filter_config))
            self.assertEqual({"A549"}, filter_config.get("_values_set"))
        finally:
            self._cleanup(tmpdir)

    def test_table_keyword_filter_debounces_when_panel_visible(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)
            panel.show()
            self._app.processEvents()
            self.assertTrue(panel.isVisible())
            self.assertEqual(2, panel.ov_table.rowCount())

            panel.ov_filter_keyword.setText("hela")
            # Visible mode uses debounced filter application.
            self.assertEqual(2, panel.ov_table.rowCount())
            QTest.qWait(int(panel._filter_debounce_ms) + 40)
            self.assertEqual(1, panel.ov_table.rowCount())
        finally:
            if panel is not None:
                panel.hide()
            self._cleanup(tmpdir)

    def test_refresh_reuses_cached_stats_when_yaml_unchanged(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            call_count = {"n": 0}
            original_generate_stats = bridge.generate_stats

            def _counted_generate_stats(*args, **kwargs):
                call_count["n"] += 1
                return original_generate_stats(*args, **kwargs)

            bridge.generate_stats = _counted_generate_stats

            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            panel.refresh()
            self.assertEqual(1, call_count["n"])
        finally:
            self._cleanup(tmpdir)

    def test_refresh_blocks_legacy_box_fields_dataset(self):
        import shutil
        import tempfile
        import yaml
        from pathlib import Path
        from app_gui.tool_bridge import GuiToolBridge

        tmpdir = tempfile.mkdtemp(prefix="ln2_ov_box_fields_")
        yaml_path = Path(tmpdir) / "inventory.yaml"
        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 1,
                    "box_numbers": [1],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
                "box_fields": {
                    "1": [
                        {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                    ]
                },
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "virus_titer": "MOI50",
                }
            ],
        }
        yaml_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        try:
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: str(yaml_path))
            panel.refresh()

            self.assertTrue(panel.ov_status.text())
            self.assertTrue(
                ("meta.box_fields" in panel.ov_status.text())
                or ("overview.loadFailed" in panel.ov_status.text())
            )
            self.assertEqual([], panel._current_records)
            self.assertEqual(0, panel.ov_table.rowCount())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_refresh_skips_repainting_when_cell_signatures_unchanged(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            with patch.object(panel, "_paint_cell", wraps=panel._paint_cell) as paint_mock:
                panel.refresh()
            self.assertEqual(0, paint_mock.call_count)
        finally:
            self._cleanup(tmpdir)

    def test_table_view_row_color_matches_grid_palette(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {"color_key": "cell_line", "cell_line_options": ["K562", "HeLa"]}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            id_col = self._table_column_index(panel, "id")

            row_bg_by_id = {}
            tint_role = int(TABLE_ROW_TINT_ROLE)
            for row in range(panel.ov_table.rowCount()):
                rid = panel.ov_table.item(row, id_col).text()
                first_color = str(panel.ov_table.item(row, 0).data(tint_role) or "").lower()
                for col in range(panel.ov_table.columnCount()):
                    item_color = str(panel.ov_table.item(row, col).data(tint_role) or "").lower()
                    self.assertEqual(first_color, item_color)
                row_bg_by_id[rid] = first_color

            self.assertEqual(cell_color("K562").lower(), row_bg_by_id.get("1"))
            self.assertEqual(cell_color("HeLa").lower(), row_bg_by_id.get("2"))
        finally:
            self._cleanup(tmpdir)

    def test_table_view_row_text_uses_contrasting_color_for_dark_tint(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            with patch("app_gui.ui.overview_panel_table.cell_color", return_value="#000000"):
                panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
                panel.refresh()
                self._switch_to_table(panel)

            self.assertEqual(1, panel.ov_table.rowCount())
            first_cell = panel.ov_table.item(0, 0)
            self.assertIsNotNone(first_cell)
            self.assertEqual("#000000", str(first_cell.data(int(TABLE_ROW_TINT_ROLE)) or "").lower())
            self.assertEqual("#ffffff", first_cell.foreground().color().name())
        finally:
            self._cleanup(tmpdir)

    def test_table_mode_switches_show_empty_toggle_to_show_taken_out(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            self.assertTrue(panel.ov_filter_secondary_toggle.isEnabled())
            self.assertEqual(tr("overview.showEmpty"), panel.ov_filter_secondary_toggle.text())
            self.assertTrue(panel.ov_filter_secondary_toggle.isChecked())

            self._switch_to_table(panel)
            self.assertTrue(panel.ov_filter_secondary_toggle.isEnabled())
            self.assertEqual(tr("overview.showTakenOut"), panel.ov_filter_secondary_toggle.text())
            self.assertFalse(panel.ov_filter_secondary_toggle.isChecked())

            self._switch_to_grid(panel)
            self.assertTrue(panel.ov_filter_secondary_toggle.isEnabled())
            self.assertEqual(tr("overview.showEmpty"), panel.ov_filter_secondary_toggle.text())
            self.assertTrue(panel.ov_filter_secondary_toggle.isChecked())
        finally:
            self._cleanup(tmpdir)

    def test_table_mode_show_taken_out_toggle_controls_inactive_rows(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {
                "id": 2,
                "cell_line": "K562",
                "short_name": "taken-out",
                "box": 1,
                "position": None,
                "frozen_at": "2025-01-02",
                "thaw_events": [{"date": "2025-01-03", "action": "takeout", "positions": [1]}],
            },
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertFalse(panel.ov_filter_secondary_toggle.isChecked())

            panel.ov_filter_secondary_toggle.setChecked(True)
            self.assertEqual(2, panel.ov_table.rowCount())

            panel.ov_filter_secondary_toggle.setChecked(False)
            self.assertEqual(1, panel.ov_table.rowCount())
        finally:
            self._cleanup(tmpdir)

    def test_table_mode_delegates_queries_to_filter_records_bridge(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 2, "position": 2, "frozen_at": "2025-01-02"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            with patch.object(bridge, "filter_records", wraps=bridge.filter_records) as mock_filter:
                self._switch_to_table(panel)

            mock_filter.assert_called()
            kwargs = mock_filter.call_args.kwargs
            self.assertEqual(str(yaml_path), kwargs.get("yaml_path"))
            self.assertEqual("location", kwargs.get("sort_by"))
            self.assertEqual("asc", kwargs.get("sort_order"))
            self.assertEqual(False, kwargs.get("include_inactive"))
            self.assertEqual({}, kwargs.get("column_filters"))
        finally:
            self._cleanup(tmpdir)

    def test_table_click_prefills_takeout_context(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            emitted = []
            panel.request_prefill_background.connect(lambda payload: emitted.append(payload))
            panel.on_table_row_double_clicked(0, 0)

            self.assertEqual(
                [{"box": 1, "position": 5, "record_id": 1}],
                emitted,
            )
        finally:
            self._cleanup(tmpdir)
