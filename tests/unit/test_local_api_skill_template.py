from pathlib import Path

from app_gui.application.open_api.skill_template import (
    LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER,
    render_local_api_skill_template,
)


def test_render_local_api_skill_template_injects_route_contract_reference():
    template = f"# Header\n\n## API Reference\n\n{LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER}\n"

    rendered = render_local_api_skill_template(template, language="en")

    assert "### `GET /api/v1/inventory/search`" in rendered
    assert "`case_sensitive`" in rendered
    assert "`summary_only`" in rendered
    assert "`keywords`" in rendered
    assert "### `GET /api/v1/capabilities`" in rendered
    assert "### `GET /api/v1/gui/stage-plan`" in rendered
    assert "at least one required" in rendered


def test_render_local_api_skill_template_uses_chinese_labels():
    template = f"# Header\n\n## API 说明\n\n{LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER}\n"

    rendered = render_local_api_skill_template(template, language="zh-CN")

    assert "查询参数" in rendered
    assert "请求体参数" in rendered
    assert "至少提供一个" in rendered
    assert "`summary_only`" in rendered


def test_render_local_api_skill_template_keeps_plain_text_without_placeholder():
    template = "plain template text"

    rendered = render_local_api_skill_template(template, language="en")

    assert rendered == template


def test_default_english_local_api_skill_template_mentions_capabilities_schema_guidance():
    root = Path(__file__).resolve().parents[2]
    template = (root / "app_gui" / "assets" / "local_api_skill_template.en.md").read_text(encoding="utf-8")

    rendered = render_local_api_skill_template(template, language="en")

    assert "call `/api/v1/capabilities` before assuming field names or response keys" in rendered
    assert "`dataset_schema`" in rendered
    assert "`response_shapes`" in rendered


def test_default_chinese_local_api_skill_template_mentions_capabilities_schema_guidance():
    root = Path(__file__).resolve().parents[2]
    template = (root / "app_gui" / "assets" / "local_api_skill_template.zh-CN.md").read_text(encoding="utf-8")

    rendered = render_local_api_skill_template(template, language="zh-CN")

    assert "`/api/v1/capabilities`" in rendered
    assert "`dataset_schema`" in rendered
    assert "`response_shapes`" in rendered
