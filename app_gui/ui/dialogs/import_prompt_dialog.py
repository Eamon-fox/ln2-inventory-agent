"""Import prompt dialog extracted from main window module."""

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app_gui.i18n import tr
from app_gui.ui.theme import FONT_SIZE_MONO, build_mono_font


_IMPORT_PROMPT_TEMPLATE_EN = """You are a data-cleaning and structuring assistant.
Convert my pasted Excel/CSV/table data into LN2 inventory YAML.

Rules:
1) Output YAML only. Do not add explanations.
2) Top-level keys must be exactly: meta, inventory.
3) Always include:
meta:
  box_layout:
    rows: 9
    cols: 9
  custom_fields: []
inventory: []
4) Data model is tube-level: each inventory item is one physical tube.
5) Required fields for each inventory item: id, box, frozen_at.
6) Optional fields: position, cell_line, short_name, plasmid_name, plasmid_id, note, thaw_events.
7) If a value is missing/unknown, use null.
8) Dates must use YYYY-MM-DD.
9) id must be unique positive integers.
10) If source uses positions like A1/B3, convert to numeric position:
    position = (row_index-1)*cols + col_index, where A=1, B=2...
11) thaw_events format:
    thaw_events:
      - date: "YYYY-MM-DD"
        action: "takeout"   # takeout/move
        positions: [1]
12) Do not invent fields not present in source.

Input data:
<<<DATA
[paste Excel/CSV/table data here]
DATA"""



def _get_import_prompt():
    return tr("main.importPromptTemplate", default=_IMPORT_PROMPT_TEMPLATE_EN)



def _get_yaml_example():
    return """meta:
  box_layout:
    rows: 9
    cols: 9
  custom_fields:
    - key: short_name
      label: Short Name
      type: str
      required: true
    - key: plasmid_name
      label: Plasmid Name
      type: str
      default: unknown
    - key: plasmid_id
      label: Plasmid ID
      type: str
  display_key: cell_line
  color_key: cell_line
  cell_line_required: true

inventory:
  - id: 1
    cell_line: NCCIT
    short_name: NCCIT_ctrl_A
    plasmid_name: pLenti-empty
    plasmid_id: p0001
    box: 1
    position: 1
    frozen_at: "2026-02-01"
    note: baseline control clone
    thaw_events: null

  - id: 2
    cell_line: HeLa
    short_name: HeLa_test_B
    plasmid_name: null
    plasmid_id: null
    box: 1
    position: null
    frozen_at: "2026-01-15"
    note: already taken out
    thaw_events:
      - date: "2026-02-10"
        action: takeout
        positions: [2]"""


class ImportPromptDialog(QDialog):
    """Dialog showing import prompt for converting Excel/CSV to YAML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.importPromptTitle"))
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        desc = QLabel(tr("main.importPromptDesc"))
        desc.setWordWrap(True)
        desc.setProperty("role", "dialogHint")
        layout.addWidget(desc)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(_get_import_prompt())
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setFont(build_mono_font(FONT_SIZE_MONO))
        layout.addWidget(self.prompt_edit, 1)

        buttons = QDialogButtonBox()
        copy_btn = QPushButton(tr("main.importPromptCopy"))
        copy_btn.clicked.connect(self._copy_prompt)
        buttons.addButton(copy_btn, QDialogButtonBox.ActionRole)

        view_yaml_btn = QPushButton(tr("main.importPromptViewYaml"))
        view_yaml_btn.clicked.connect(self._view_yaml_example)
        buttons.addButton(view_yaml_btn, QDialogButtonBox.ActionRole)

        close_btn = QPushButton(tr("common.close"))
        close_btn.clicked.connect(self.reject)
        buttons.addButton(close_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)

    def _copy_prompt(self):
        try:
            QApplication.clipboard().setText(_get_import_prompt())
            self.status_message = tr("main.importPromptCopied")
            QMessageBox.information(self, tr("common.info"), tr("main.importPromptCopied"))
        except Exception as exc:
            print(f"[ImportPrompt] Copy failed: {exc}")

    def _view_yaml_example(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("main.importPromptViewYamlTitle"))
        dlg.setMinimumWidth(500)
        dlg.setMinimumHeight(400)
        layout = QVBoxLayout(dlg)
        text_edit = QTextEdit()
        text_edit.setPlainText(_get_yaml_example())
        text_edit.setReadOnly(True)
        text_edit.setFont(build_mono_font(FONT_SIZE_MONO))
        layout.addWidget(text_edit)
        close_btn = QDialogButtonBox()
        close_button = QPushButton(tr("common.close"))
        close_button.clicked.connect(dlg.reject)
        close_btn.addButton(close_button, QDialogButtonBox.RejectRole)
        layout.addWidget(close_btn)
        dlg.exec()


__all__ = ["ImportPromptDialog"]
