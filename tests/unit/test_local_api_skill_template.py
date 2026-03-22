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


def test_render_local_api_skill_template_uses_chinese_labels():
    template = f"# Header\n\n## API 说明\n\n{LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER}\n"

    rendered = render_local_api_skill_template(template, language="zh-CN")

    assert "查询参数" in rendered
    assert "请求体参数" in rendered
    assert "`summary_only`" in rendered


def test_render_local_api_skill_template_keeps_plain_text_without_placeholder():
    template = "plain template text"

    rendered = render_local_api_skill_template(template, language="en")

    assert rendered == template
