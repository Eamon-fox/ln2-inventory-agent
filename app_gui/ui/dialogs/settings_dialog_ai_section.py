from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from app_gui.application.ai_provider_catalog import (
    AI_PROVIDER_DEFAULTS,
    normalize_ai_provider,
)
from app_gui.gui_config import DEFAULT_MAX_STEPS, MAX_AGENT_STEPS
from app_gui.i18n import tr


def build_ai_group(dialog, *, combo_box_cls, spin_box_cls, text_edit_cls) -> QGroupBox:
    ai_group = QGroupBox(tr("settings.ai"))
    ai_layout = QFormLayout(ai_group)

    api_keys_config = dialog._config.get("api_keys", {})
    dialog._api_key_edits = {}
    dialog._api_key_lock_buttons = {}
    for provider_id, cfg in AI_PROVIDER_DEFAULTS.items():
        key_row, key_edit, lock_btn = build_locked_api_key_row(
            dialog,
            api_keys_config.get(provider_id, ""),
        )
        dialog._api_key_edits[provider_id] = key_edit
        dialog._api_key_lock_buttons[provider_id] = lock_btn
        help_url = str(cfg.get("help_url") or "").strip()
        if help_url:
            label_widget = QLabel(
                f'<a href="{help_url}">{cfg["display_name"]}</a> ({cfg["env_key"]}):'
            )
            label_widget.setOpenExternalLinks(True)
        else:
            label_widget = QLabel(f'{cfg["display_name"]} ({cfg["env_key"]}):')
        ai_layout.addRow(label_widget, key_row)

    api_hint_text = str(tr("settings.apiKeyHint") or "").strip()
    if api_hint_text:
        api_hint = QLabel(api_hint_text)
        api_hint.setProperty("role", "settingsHint")
        api_hint.setWordWrap(True)
        ai_layout.addRow("", api_hint)

    ai_advanced = dialog._config.get("ai", {})
    current_provider = normalize_ai_provider(ai_advanced.get("provider"))
    dialog.ai_provider_combo = combo_box_cls()
    for provider_id, cfg in AI_PROVIDER_DEFAULTS.items():
        dialog.ai_provider_combo.addItem(cfg["display_name"], provider_id)
    idx = dialog.ai_provider_combo.findData(current_provider)
    if idx >= 0:
        dialog.ai_provider_combo.setCurrentIndex(idx)
    dialog.ai_provider_combo.currentIndexChanged.connect(dialog._on_provider_changed)
    ai_layout.addRow(tr("settings.aiProvider"), dialog.ai_provider_combo)

    provider_cfg = AI_PROVIDER_DEFAULTS[current_provider]
    default_model = ai_advanced.get("model") or provider_cfg["model"]
    dialog.ai_model_edit = combo_box_cls()
    dialog.ai_model_edit.setEditable(True)
    dialog.ai_model_edit.setInsertPolicy(QComboBox.NoInsert)
    dialog.ai_model_edit.setObjectName("settingsModelPreview")
    dialog._refresh_model_options(current_provider, selected_model=default_model)
    ai_layout.addRow(tr("settings.aiModel"), dialog.ai_model_edit)

    dialog.ai_max_steps = spin_box_cls()
    dialog.ai_max_steps.setRange(1, MAX_AGENT_STEPS)
    dialog.ai_max_steps.setValue(ai_advanced.get("max_steps", DEFAULT_MAX_STEPS))
    ai_layout.addRow(tr("settings.aiMaxSteps"), dialog.ai_max_steps)

    dialog.ai_thinking_enabled = dialog._checkbox_cls()
    dialog.ai_thinking_enabled.setChecked(ai_advanced.get("thinking_enabled", True))
    ai_layout.addRow(tr("settings.aiThinking"), dialog.ai_thinking_enabled)

    dialog.ai_custom_prompt = text_edit_cls()
    dialog.ai_custom_prompt.setPlaceholderText(tr("settings.customPromptPlaceholder"))
    dialog.ai_custom_prompt.setPlainText(ai_advanced.get("custom_prompt", ""))
    dialog.ai_custom_prompt.setMaximumHeight(100)
    ai_layout.addRow(tr("settings.customPrompt"), dialog.ai_custom_prompt)

    custom_prompt_hint = QLabel(tr("settings.customPromptHint"))
    custom_prompt_hint.setProperty("role", "settingsHint")
    custom_prompt_hint.setWordWrap(True)
    ai_layout.addRow("", custom_prompt_hint)

    return ai_group


def provider_models(provider):
    normalized_provider = normalize_ai_provider(provider)
    cfg = AI_PROVIDER_DEFAULTS[normalized_provider]
    models = []
    seen = set()
    for raw in cfg.get("models") or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        models.append(text)
    default_model = str(cfg.get("model") or "").strip()
    if default_model and default_model.casefold() not in seen:
        models.append(default_model)
    return models, default_model


def refresh_model_options(dialog, provider, selected_model=None) -> None:
    models, default_model = provider_models(provider)
    target_model = str(selected_model or "").strip() or default_model

    dialog.ai_model_edit.blockSignals(True)
    dialog.ai_model_edit.clear()
    for model in models:
        dialog.ai_model_edit.addItem(model, model)
    if target_model and dialog.ai_model_edit.findText(target_model) < 0:
        dialog.ai_model_edit.addItem(target_model, target_model)
    idx = dialog.ai_model_edit.findText(target_model)
    if idx >= 0:
        dialog.ai_model_edit.setCurrentIndex(idx)
    elif target_model:
        dialog.ai_model_edit.setEditText(target_model)
    dialog.ai_model_edit.setPlaceholderText(default_model)
    dialog.ai_model_edit.blockSignals(False)


def build_locked_api_key_row(dialog, initial_value):
    row_widget = QWidget()
    row_layout = QHBoxLayout(row_widget)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(4)

    key_edit = QLineEdit(initial_value or "")
    key_edit.setEchoMode(QLineEdit.Password)
    key_edit.setPlaceholderText("sk-...")
    key_edit.setReadOnly(True)
    row_layout.addWidget(key_edit, 1)

    lock_btn = QPushButton("🔒")
    lock_btn.setObjectName("inlineLockBtn")
    lock_btn.setFixedSize(16, 16)
    lock_btn.setToolTip(tr("operations.edit"))
    lock_btn.clicked.connect(
        lambda _checked=False, edit=key_edit, btn=lock_btn: toggle_api_key_lock(edit, btn)
    )
    row_layout.addWidget(lock_btn)

    return row_widget, key_edit, lock_btn


def toggle_api_key_lock(key_edit, lock_btn) -> None:
    if key_edit.isReadOnly():
        key_edit.setReadOnly(False)
        key_edit.setEchoMode(QLineEdit.Normal)
        lock_btn.setText("🔓")
        key_edit.setFocus()
        key_edit.selectAll()
        return

    key_edit.setReadOnly(True)
    key_edit.setEchoMode(QLineEdit.Password)
    lock_btn.setText("🔒")
