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
        from app_gui.i18n import get_language, set_language
        from app_gui.tool_bridge import GuiToolBridge

        previous_language = get_language()
        set_language("en")
        try:
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            panel._show_detail(box, position, panel.overview_pos_map.get((box, position)))
            return panel.ov_hover_hint.text()
        finally:
            set_language(previous_language)

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

    def _table_row_item(self, panel, row):
        for column in range(panel.ov_table.columnCount()):
            item = panel.ov_table.item(row, column)
            if item is not None:
                return item
        return None

    def _table_row_kind(self, panel, row):
        from app_gui.ui.overview_panel import TABLE_ROW_KIND_ROLE

        item = self._table_row_item(panel, row)
        return str(item.data(TABLE_ROW_KIND_ROLE) or "") if item is not None else ""

    def _table_row_confirmed(self, panel, row):
        from app_gui.ui.overview_panel import TABLE_ROW_CONFIRMED_ROLE

        item = self._table_row_item(panel, row)
        return bool(item.data(TABLE_ROW_CONFIRMED_ROLE)) if item is not None else False

    def _table_row_locked(self, panel, row):
        from app_gui.ui.overview_panel import TABLE_ROW_LOCKED_ROLE

        item = self._table_row_item(panel, row)
        return bool(item.data(TABLE_ROW_LOCKED_ROLE)) if item is not None else False

    def _table_row_count(self, panel, *, row_kind=None):
        if row_kind is None:
            return panel.ov_table.rowCount()
        expected_kind = str(row_kind)
        return sum(
            1
            for row in range(panel.ov_table.rowCount())
            if self._table_row_kind(panel, row) == expected_kind
        )

    def _table_find_row(self, panel, *, row_kind=None, record_id=None, box=None, position=None):
        from app_gui.ui.overview_panel import TABLE_ROW_BOX_ROLE, TABLE_ROW_POSITION_ROLE

        id_column = None
        if record_id is not None:
            id_column = self._table_column_index(panel, "id")

        for row in range(panel.ov_table.rowCount()):
            item = self._table_row_item(panel, row)
            if item is None:
                continue
            if row_kind is not None and self._table_row_kind(panel, row) != str(row_kind):
                continue
            if box is not None and item.data(TABLE_ROW_BOX_ROLE) != box:
                continue
            if position is not None and item.data(TABLE_ROW_POSITION_ROLE) != position:
                continue
            if id_column is not None:
                id_item = panel.ov_table.item(row, id_column)
                if str(id_item.text() if id_item is not None else "") != str(record_id):
                    continue
            return row

        raise AssertionError(
            f"table row not found: row_kind={row_kind!r}, record_id={record_id!r}, box={box!r}, position={position!r}"
        )

    def _table_column_texts(self, panel, column_name, *, row_kind=None, non_empty_only=False):
        column_index = self._table_column_index(panel, column_name)
        texts = []
        for row in range(panel.ov_table.rowCount()):
            if row_kind is not None and self._table_row_kind(panel, row) != str(row_kind):
                continue
            item = panel.ov_table.item(row, column_index)
            text = item.text() if item is not None else ""
            if non_empty_only and not str(text).strip():
                continue
            texts.append(text)
        return texts

    def _click_table_header(self, panel, column_name):
        column_index = self._table_column_index(panel, column_name)
        header = panel.ov_table.horizontalHeader()
        section_left = header.sectionViewportPosition(column_index)
        click_point = QPointF(section_left + 20, max(6, header.height() / 2)).toPoint()
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, click_point)
        QTest.qWait(20)

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
            expected_total = 81 * len({int(record["box"]) for record in records})
            self.assertEqual(expected_total, panel.ov_table.rowCount())
            self.assertEqual(len(records), self._table_row_count(panel, row_kind="active"))
            self.assertEqual(
                expected_total - len(records),
                self._table_row_count(panel, row_kind="empty_slot"),
            )
            confirm_col = self._table_column_index(panel, "__confirm__")
            self.assertEqual(
                "__confirm__",
                panel.ov_table.horizontalHeaderItem(confirm_col).data(Qt.UserRole),
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_view_limits_large_layout_render_rows(self):
        layout = {
            "rows": 10,
            "cols": 10,
            "box_count": 8,
            "box_numbers": list(range(1, 9)),
        }
        yaml_path, tmpdir = self._seed_yaml([], meta_extra={"box_layout": layout})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            self.assertEqual(500, len(panel._table_rows))
            self.assertEqual(500, panel.ov_table.rowCount())
            self.assertEqual(500, self._table_row_count(panel, row_kind="empty_slot"))

            response = panel._query_table_rows(keyword="", selected_box=None, selected_cell=None)
            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(800, result["total_count"])
            self.assertEqual(500, result["display_count"])
            self.assertEqual(500, result["limit"])
            self.assertEqual(0, result["offset"])
            self.assertTrue(result["has_more"])
        finally:
            if panel is not None:
                panel.hide()
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
            self.assertEqual(2, self._table_row_count(panel, row_kind="active"))
            self.assertEqual(162, panel.ov_table.rowCount())

            panel.ov_filter_keyword.setText("hela")
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("2", panel.ov_table.item(0, 0).text())

            panel.ov_filter_keyword.clear()
            box_idx = panel.ov_filter_box.findData(1)
            self.assertGreaterEqual(box_idx, 0)
            panel.ov_filter_box.setCurrentIndex(box_idx)
            self.assertEqual(81, panel.ov_table.rowCount())
            self.assertEqual(1, self._table_row_count(panel, row_kind="active"))
            self.assertEqual(["1"], self._table_column_texts(panel, "id", row_kind="active"))

            panel.ov_filter_box.setCurrentIndex(0)
            cell_idx = panel.ov_filter_cell.findData("K562")
            self.assertGreaterEqual(cell_idx, 0)
            panel.ov_filter_cell.setCurrentIndex(cell_idx)
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("1", panel.ov_table.item(0, 0).text())
        finally:
            self._cleanup(tmpdir)

    def test_view_toggle_button_click_switches_to_table_without_crashing(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-02"},
            {"id": 3, "cell_line": "NCCIT", "short_name": "clone-C", "box": 1, "position": 3, "frozen_at": "2025-01-03"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.resize(900, 600)
            panel.show()
            QTest.qWait(20)
            panel.refresh()

            self.assertEqual("grid", panel._overview_view_mode)
            self.assertEqual(0, panel.ov_view_stack.currentIndex())

            with patch.object(bridge, "filter_records", wraps=bridge.filter_records) as mock_filter:
                QTest.mouseClick(panel.ov_view_table_btn, Qt.LeftButton)
                QTest.qWait(20)
                self.assertEqual(0, mock_filter.call_count)

            self.assertEqual("table", panel._overview_view_mode)
            self.assertEqual(1, panel.ov_view_stack.currentIndex())
            self.assertTrue(panel.ov_view_table_btn.isChecked())
            self.assertFalse(panel.ov_view_grid_btn.isChecked())
            self.assertEqual(len(records), self._table_row_count(panel, row_kind="active"))
            self.assertGreater(panel.ov_table.rowCount(), len(records))
            self.assertEqual(
                "__confirm__",
                panel.ov_table.horizontalHeaderItem(self._table_column_index(panel, "__confirm__")).data(Qt.UserRole),
            )
        finally:
            if panel is not None:
                panel.hide()
            self._cleanup(tmpdir)

    def test_view_toggle_button_repeated_switches_remain_stable(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-02"},
            {"id": 3, "cell_line": "NCCIT", "short_name": "clone-C", "box": 1, "position": 3, "frozen_at": "2025-01-03"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.resize(900, 600)
            panel.show()
            QTest.qWait(20)
            panel.refresh()

            for _ in range(15):
                QTest.mouseClick(panel.ov_view_table_btn, Qt.LeftButton)
                QTest.qWait(10)
                self.assertEqual("table", panel._overview_view_mode)
                self.assertEqual(len(records), self._table_row_count(panel, row_kind="active"))
                self.assertGreater(panel.ov_table.rowCount(), len(records))

                QTest.mouseClick(panel.ov_view_grid_btn, Qt.LeftButton)
                QTest.qWait(10)
                self.assertEqual("grid", panel._overview_view_mode)
                self.assertEqual(0, panel.ov_view_stack.currentIndex())

            self.assertEqual(len(records), self._table_row_count(panel, row_kind="active"))
            self.assertGreater(panel.ov_table.rowCount(), len(records))
        finally:
            if panel is not None:
                panel.hide()
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
                ["Box 1 Position 10", "Box 1 Position 2", "Box 1 Position 1"],
                self._table_column_texts(panel, "location", row_kind="active"),
            )

            panel.ov_table.sortItems(location_col, Qt.AscendingOrder)
            self.assertEqual(
                ["Box 1 Position 1", "Box 1 Position 2", "Box 1 Position 10"],
                self._table_column_texts(panel, "location", row_kind="active"),
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_location_display_includes_box_tag_when_available(self):
        records = [
            {"id": 201, "cell_line": "K562", "short_name": "p10", "box": 1, "position": 10, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(
            records,
            meta_extra={
                "color_key": "cell_line",
                "box_layout": {"rows": 9, "cols": 9, "box_tags": {"1": "virus stock"}},
            },
        )
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            self.assertEqual(
                ["Box 1 (virus stock) Position 10"],
                self._table_column_texts(panel, "location", row_kind="active"),
            )
        finally:
            if panel is not None:
                panel.hide()
            self._cleanup(tmpdir)

    def test_table_location_display_uses_alphanumeric_positions_when_layout_requires_it(self):
        records = [
            {"id": 201, "cell_line": "K562", "short_name": "p2", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 202, "cell_line": "K562", "short_name": "p4", "box": 1, "position": 4, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(
            records,
            meta_extra={
                "color_key": "cell_line",
                "box_layout": {"rows": 3, "cols": 3, "indexing": "alphanumeric"},
            },
        )
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            self.assertEqual(
                ["Box 1 Position A2", "Box 1 Position B1"],
                self._table_column_texts(panel, "location", row_kind="active"),
            )
        finally:
            if panel is not None:
                panel.hide()
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
            self.assertEqual(["1", "2", "10"], self._table_column_texts(panel, "id", row_kind="active"))
        finally:
            self._cleanup(tmpdir)

    def test_table_header_click_sorts_in_place_without_requery(self):
        records = [
            {"id": 1, "cell_line": "beta", "short_name": "row-1", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "Alpha", "short_name": "row-2", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 3, "cell_line": "aardvark", "short_name": "row-3", "box": 1, "position": 3, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.resize(900, 600)
            panel.show()
            QTest.qWait(20)
            panel.refresh()
            self._switch_to_table(panel)

            with patch.object(bridge, "filter_records", wraps=bridge.filter_records) as mock_filter:
                self._click_table_header(panel, "cell_line")
                self.assertEqual(0, mock_filter.call_count)

            self.assertEqual("cell_line", panel._table_sort_by)
            self.assertEqual("asc", panel._table_sort_order)
            self.assertEqual(
                ["aardvark", "Alpha", "beta"],
                self._table_column_texts(panel, "cell_line", row_kind="active"),
            )
        finally:
            if panel is not None:
                panel.hide()
            self._cleanup(tmpdir)

    def test_table_header_click_toggles_current_location_sort_without_requery(self):
        records = [
            {"id": 201, "cell_line": "K562", "short_name": "p10", "box": 1, "position": 10, "frozen_at": "2025-01-01"},
            {"id": 202, "cell_line": "K562", "short_name": "p2", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 203, "cell_line": "K562", "short_name": "p1", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.resize(900, 600)
            panel.show()
            QTest.qWait(20)
            panel.refresh()
            self._switch_to_table(panel)

            with patch.object(bridge, "filter_records", wraps=bridge.filter_records) as mock_filter:
                self._click_table_header(panel, "location")
                self.assertEqual(0, mock_filter.call_count)
                self.assertEqual("location", panel._table_sort_by)
                self.assertEqual("desc", panel._table_sort_order)
                self.assertEqual(
                    ["Box 1 Position 10", "Box 1 Position 2", "Box 1 Position 1"],
                    self._table_column_texts(panel, "location", row_kind="active"),
                )

                self._click_table_header(panel, "location")
                self.assertEqual(0, mock_filter.call_count)

            self.assertEqual("location", panel._table_sort_by)
            self.assertEqual("asc", panel._table_sort_order)
            self.assertEqual(
                ["Box 1 Position 1", "Box 1 Position 2", "Box 1 Position 10"],
                self._table_column_texts(panel, "location", row_kind="active"),
            )
        finally:
            if panel is not None:
                panel.hide()
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
                self._table_column_texts(panel, "passage_number", row_kind="active"),
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_header_click_numeric_custom_field_sorts_without_requery(self):
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
        panel = None
        try:
            from app_gui.tool_bridge import GuiToolBridge

            bridge = GuiToolBridge()
            panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)
            panel.resize(900, 600)
            panel.show()
            QTest.qWait(20)
            panel.refresh()
            self._switch_to_table(panel)

            with patch.object(bridge, "filter_records", wraps=bridge.filter_records) as mock_filter:
                self._click_table_header(panel, "passage_number")
                self.assertEqual(0, mock_filter.call_count)

            self.assertEqual("passage_number", panel._table_sort_by)
            self.assertEqual("asc", panel._table_sort_order)
            self.assertEqual(
                ["1", "2", "10"],
                self._table_column_texts(panel, "passage_number", row_kind="active"),
            )
        finally:
            if panel is not None:
                panel.hide()
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

    def test_table_filter_requery_bumps_version_and_clears_unique_cache(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            panel._table_version = 3
            panel._column_unique_cache = {("cell_line", 3): [("K562", 1)]}
            panel.ov_filter_keyword.setText("k562")

            self.assertEqual(4, panel._table_version)
            self.assertEqual({}, panel._column_unique_cache)
        finally:
            self._cleanup(tmpdir)

    def test_render_table_rows_uses_set_row_count_batch_path(self):
        """Lock the incremental-render contract:

        - `_render_table_rows` never uses per-row `insertRow`.
        - First render (shape change) calls `setRowCount(len(rows))` exactly once.
        - Subsequent render with identical rows+shape skips `setRowCount` so the
          table is not torn down and rebuilt on each refresh.
        """
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

            panel._table_row_signatures = []
            panel._table_render_shape_key = None

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
                first_call_count = list(set_row_count_calls)
                panel._render_table_rows(rows)
                second_call_count = list(set_row_count_calls)

            self.assertEqual([len(rows)], first_call_count)
            self.assertEqual(first_call_count, second_call_count)
            self.assertEqual(len(rows), panel.ov_table.rowCount())
        finally:
            self._cleanup(tmpdir)

    def test_render_table_rows_only_rewrites_changed_rows(self):
        """Incremental render contract: when one row's payload changes, only
        that row's cells are re-emitted via `setItem`; untouched rows keep
        their existing QTableWidgetItem instances.
        """
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 3, "cell_line": "HEK", "short_name": "C", "box": 1, "position": 3, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            baseline_rows = list(panel._table_rows)
            panel._render_table_rows(baseline_rows)

            row_to_change = None
            for idx, row in enumerate(baseline_rows):
                if row.get("row_kind") != "empty_slot":
                    row_to_change = idx
                    break
            self.assertIsNotNone(row_to_change)

            items_before = [
                panel.ov_table.item(r, 0) for r in range(panel.ov_table.rowCount())
            ]

            displayed_columns = [
                c for c in list(panel._table_columns or [])
                if c and c not in ("location", "id", "__confirm__")
            ]
            self.assertTrue(displayed_columns)
            target_col = displayed_columns[0]

            mutated_rows = [dict(r) for r in baseline_rows]
            mutated_values = dict(mutated_rows[row_to_change].get("values") or {})
            mutated_values[target_col] = "changed_value_xyz"
            mutated_rows[row_to_change]["values"] = mutated_values

            panel._render_table_rows(mutated_rows)

            items_after = [
                panel.ov_table.item(r, 0) for r in range(panel.ov_table.rowCount())
            ]
            for r in range(len(items_before)):
                if r == row_to_change:
                    self.assertIsNot(items_before[r], items_after[r])
                else:
                    self.assertIs(items_before[r], items_after[r])
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
            self.assertEqual(162, panel.ov_table.rowCount())
            self.assertEqual(2, self._table_row_count(panel, row_kind="active"))

            panel.ov_filter_keyword.setText("hela")
            # Visible mode uses debounced filter application.
            self.assertEqual(162, panel.ov_table.rowCount())
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

            self.assertEqual(1, self._table_row_count(panel, row_kind="active"))
            active_row = self._table_find_row(panel, row_kind="active", record_id=1)
            first_cell = panel.ov_table.item(active_row, 0)
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
            self.assertEqual(tr("overview.showTakenOutTooltip"), panel.ov_filter_secondary_toggle.toolTip())
            self.assertFalse(panel.ov_filter_secondary_toggle.isChecked())

            self._switch_to_grid(panel)
            self.assertTrue(panel.ov_filter_secondary_toggle.isEnabled())
            self.assertEqual(tr("overview.showEmpty"), panel.ov_filter_secondary_toggle.text())
            self.assertEqual("", panel.ov_filter_secondary_toggle.toolTip())
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

            self.assertEqual(81, panel.ov_table.rowCount())
            self.assertEqual(1, self._table_row_count(panel, row_kind="active"))
            self.assertEqual(80, self._table_row_count(panel, row_kind="empty_slot"))
            self.assertFalse(panel.ov_filter_secondary_toggle.isChecked())
            self.assertEqual(
                "__confirm__",
                panel.ov_table.horizontalHeaderItem(self._table_column_index(panel, "__confirm__")).data(Qt.UserRole),
            )

            panel.ov_filter_secondary_toggle.setChecked(True)
            self.assertEqual(2, panel.ov_table.rowCount())
            self.assertEqual(1, self._table_row_count(panel, row_kind="active"))
            self.assertEqual(1, self._table_row_count(panel, row_kind="taken_out"))
            with self.assertRaises(ValueError):
                self._table_column_index(panel, "__confirm__")

            panel.ov_filter_secondary_toggle.setChecked(False)
            self.assertEqual(81, panel.ov_table.rowCount())
            self.assertEqual(1, self._table_row_count(panel, row_kind="active"))
            self.assertEqual(80, self._table_row_count(panel, row_kind="empty_slot"))
        finally:
            self._cleanup(tmpdir)

    def test_table_history_view_delegates_queries_to_filter_records_bridge(self):
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
                self.assertEqual(0, mock_filter.call_count)
                panel.ov_filter_secondary_toggle.setChecked(True)
                self.assertEqual(1, mock_filter.call_count)
                panel.ov_filter_secondary_toggle.setChecked(False)
                self.assertEqual(1, mock_filter.call_count)

            kwargs = mock_filter.call_args.kwargs
            self.assertEqual(str(yaml_path), kwargs.get("yaml_path"))
            self.assertEqual("location", kwargs.get("sort_by"))
            self.assertEqual("asc", kwargs.get("sort_order"))
            self.assertEqual(True, kwargs.get("include_inactive"))
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
            row = self._table_find_row(panel, row_kind="active", record_id=1)
            panel.on_table_row_double_clicked(row, 0)

            self.assertEqual(
                [{"box": 1, "position": 5, "record_id": 1}],
                emitted,
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_inline_entry_confirm_emits_add_plan_item(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                {"key": "short_name", "label": "Short Name", "type": "str"},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            empty_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            date_item = panel.ov_table.item(empty_row, self._table_column_index(panel, "frozen_at"))
            cell_line_item = panel.ov_table.item(empty_row, self._table_column_index(panel, "cell_line"))
            confirm_col = self._table_column_index(panel, "__confirm__")

            self.assertTrue(bool(date_item.flags() & Qt.ItemIsEditable))
            self.assertTrue(bool(cell_line_item.flags() & Qt.ItemIsEditable))

            staged_items = []
            panel.plan_items_requested.connect(lambda payload: staged_items.extend(payload))

            date_item.setText("2026-02-10")
            self._app.processEvents()
            empty_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            cell_line_item = panel.ov_table.item(empty_row, self._table_column_index(panel, "cell_line"))
            cell_line_item.setText("HeLa")
            self._app.processEvents()
            panel.on_table_cell_clicked(empty_row, confirm_col)

            self.assertEqual(1, len(staged_items))
            item = staged_items[0]
            self.assertEqual("add", item.get("action"))
            self.assertEqual("overview_table", item.get("source"))
            self.assertEqual(1, item.get("box"))
            payload = item.get("payload") or {}
            self.assertEqual([2], payload.get("positions"))
            self.assertEqual("2026-02-10", payload.get("stored_at"))
            self.assertEqual("2026-02-10", payload.get("frozen_at"))
            self.assertEqual("HeLa", (payload.get("fields") or {}).get("cell_line"))
        finally:
            self._cleanup(tmpdir)

    def test_table_single_slot_staged_entry_loses_confirm_mark_when_draft_diverges(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge
            from lib.plan_item_factory import build_add_plan_item
            from lib.plan_store import PlanStore

            store = PlanStore()
            store.add(
                [
                    build_add_plan_item(
                        box=1,
                        positions=[2],
                        stored_at="2026-02-10",
                        fields={"cell_line": "K562"},
                        source="tests",
                    )
                ]
            )

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.bind_plan_store(store)
            panel.refresh()
            self._switch_to_table(panel)

            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            confirm_col = self._table_column_index(panel, "__confirm__")
            cell_line_col = self._table_column_index(panel, "cell_line")

            self.assertTrue(self._table_row_confirmed(panel, row))
            self.assertFalse(self._table_row_locked(panel, row))
            self.assertEqual("√", panel.ov_table.item(row, confirm_col).text())

            panel.ov_table.item(row, cell_line_col).setText("HeLa")
            self._app.processEvents()
            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertFalse(self._table_row_confirmed(panel, row))
            self.assertEqual("+", panel.ov_table.item(row, confirm_col).text())

            panel.ov_table.item(row, cell_line_col).setText("K562")
            self._app.processEvents()
            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertTrue(self._table_row_confirmed(panel, row))
            self.assertEqual("√", panel.ov_table.item(row, confirm_col).text())
        finally:
            self._cleanup(tmpdir)

    def test_table_multi_slot_staged_entry_row_is_locked_and_prefills_positions(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge
            from lib.plan_item_factory import build_add_plan_item
            from lib.plan_store import PlanStore

            store = PlanStore()
            store.add(
                [
                    build_add_plan_item(
                        box=1,
                        positions=[2, 3],
                        stored_at="2026-02-10",
                        fields={"cell_line": "K562"},
                        source="tests",
                    )
                ]
            )

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.bind_plan_store(store)
            panel.refresh()
            self._switch_to_table(panel)

            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            date_item = panel.ov_table.item(row, self._table_column_index(panel, "frozen_at"))
            cell_line_item = panel.ov_table.item(row, self._table_column_index(panel, "cell_line"))

            self.assertTrue(self._table_row_confirmed(panel, row))
            self.assertTrue(self._table_row_locked(panel, row))
            self.assertFalse(bool(date_item.flags() & Qt.ItemIsEditable))
            self.assertFalse(bool(cell_line_item.flags() & Qt.ItemIsEditable))

            emitted = []
            panel.request_add_prefill_background.connect(lambda payload: emitted.append(payload))
            panel.on_table_cell_clicked(row, self._table_column_index(panel, "__confirm__"))

            self.assertEqual(
                [{"box": 1, "position": 2, "positions": [2, 3]}],
                emitted,
            )
        finally:
            self._cleanup(tmpdir)

    def test_table_unconfirm_staged_single_slot_emits_removal_signal(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge
            from lib.plan_item_factory import build_add_plan_item
            from lib.plan_store import PlanStore

            store = PlanStore()
            store.add(
                [
                    build_add_plan_item(
                        box=1,
                        positions=[2],
                        stored_at="2026-02-10",
                        fields={"cell_line": "K562"},
                        source="tests",
                    )
                ]
            )

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.bind_plan_store(store)
            panel.refresh()
            self._switch_to_table(panel)

            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            confirm_col = self._table_column_index(panel, "__confirm__")

            # Verify initial staged state
            self.assertTrue(self._table_row_confirmed(panel, row))
            self.assertFalse(self._table_row_locked(panel, row))
            self.assertEqual("\u221a", panel.ov_table.item(row, confirm_col).text())

            # Click confirm column to unconfirm
            removal_emitted = []
            panel.plan_item_removal_requested.connect(lambda payloads: removal_emitted.extend(payloads))
            panel.on_table_cell_clicked(row, confirm_col)

            # Should emit removal signal
            self.assertEqual(1, len(removal_emitted))
            self.assertEqual("add", removal_emitted[0]["action"])
            self.assertEqual(1, removal_emitted[0]["box"])
            self.assertEqual(2, removal_emitted[0]["position"])
        finally:
            self._cleanup(tmpdir)

    def test_table_confirm_column_visual_states(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge
            from lib.plan_item_factory import build_add_plan_item
            from lib.plan_store import PlanStore

            store = PlanStore()
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.bind_plan_store(store)
            panel.refresh()
            self._switch_to_table(panel)

            confirm_col = self._table_column_index(panel, "__confirm__")

            # Empty slot with no draft or staged: confirm cell is empty
            empty_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertEqual("", panel.ov_table.item(empty_row, confirm_col).text())

            # Edit the slot to create a draft: confirm cell shows "+"
            cell_line_col = self._table_column_index(panel, "cell_line")
            frozen_col = self._table_column_index(panel, "frozen_at")
            panel.ov_table.item(empty_row, frozen_col).setText("2026-02-10")
            self._app.processEvents()
            empty_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            panel.ov_table.item(empty_row, cell_line_col).setText("HeLa")
            self._app.processEvents()
            empty_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertEqual("+", panel.ov_table.item(empty_row, confirm_col).text())

            # Stage the item with matching values: confirm cell shows checkmark
            store.add(
                [
                    build_add_plan_item(
                        box=1,
                        positions=[2],
                        stored_at="2026-02-10",
                        fields={"cell_line": "HeLa"},
                        source="tests",
                    )
                ]
            )
            panel.refresh_plan_store_view()
            self._app.processEvents()
            staged_row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertEqual("\u221a", panel.ov_table.item(staged_row, confirm_col).text())
        finally:
            self._cleanup(tmpdir)

    def test_table_escape_key_discards_draft(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {
            "color_key": "cell_line",
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QKeyEvent
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            confirm_col = self._table_column_index(panel, "__confirm__")
            cell_line_col = self._table_column_index(panel, "cell_line")
            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)

            # Create a draft
            panel.ov_table.item(row, cell_line_col).setText("HeLa")
            self._app.processEvents()
            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertEqual("+", panel.ov_table.item(row, confirm_col).text())
            self.assertTrue(panel._draft_store.has_draft((1, 2)))

            # Simulate Escape key on the table
            panel.ov_table.setCurrentItem(panel.ov_table.item(row, cell_line_col))
            escape_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
            panel.eventFilter(panel.ov_table, escape_event)
            self._app.processEvents()

            # Draft should be cleared
            self.assertFalse(panel._draft_store.has_draft((1, 2)))
            row = self._table_find_row(panel, row_kind="empty_slot", box=1, position=2)
            self.assertEqual("", panel.ov_table.item(row, confirm_col).text())
        finally:
            self._cleanup(tmpdir)
