"""Render the external local API skill template from route contracts."""

from __future__ import annotations

from collections import OrderedDict

from .contracts import iter_local_open_api_route_descriptions


LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER = "{{LOCAL_OPEN_API_ROUTE_REFERENCE}}"

_LANGUAGE_LABELS = {
    "en": {
        "query": "Query params",
        "body": "Body params",
        "none": "Request params: none",
        "constraints": "Constraints",
        "required": "required",
        "optional": "optional",
        "accepted": "accepted",
        "type": "type",
        "constraint_at_least_one_of": "{params} (at least one required)",
    },
    "zh-CN": {
        "query": "查询参数",
        "body": "请求体参数",
        "none": "请求参数：无",
        "constraints": "约束",
        "required": "必填",
        "optional": "可选",
        "accepted": "可选值",
        "type": "类型",
        "constraint_at_least_one_of": "{params}（至少提供一个）",
    },
}


def _normalize_language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized.startswith("zh"):
        return "zh-CN"
    return "en"


def _format_literal_values(values) -> str:
    return ", ".join(f"`{value}`" for value in list(values or []))


def _format_param(param: dict, labels: dict[str, str]) -> str:
    parts = [
        f"`{param.get('name')}`",
        f"{labels['type']}: `{param.get('type')}`",
        labels["required"] if bool(param.get("required")) else labels["optional"],
    ]
    accepted_values = list(param.get("accepted_values") or [])
    if accepted_values:
        parts.append(f"{labels['accepted']}: {_format_literal_values(accepted_values)}")
    return "  - " + " ; ".join(parts)


def _format_constraint(constraint: dict, labels: dict[str, str]) -> str:
    kind = str(constraint.get("kind") or "").strip().lower()
    params = [f"`{name}`" for name in list(constraint.get("params") or []) if str(name or "").strip()]
    if kind == "at_least_one_of" and params:
        return "  - " + labels["constraint_at_least_one_of"].format(params=" / ".join(params))
    return "  - " + ", ".join(params)


def _render_route_reference(language: str) -> str:
    labels = _LANGUAGE_LABELS[_normalize_language(language)]
    lines: list[str] = []

    for spec in iter_local_open_api_route_descriptions():
        method = str(spec.get("method") or "").strip()
        path = str(spec.get("path") or "").strip()
        lines.append(f"### `{method} {path}`")
        lines.append("")

        params = list(spec.get("params") or [])
        if not params:
            lines.append(f"- {labels['none']}")
            lines.append("")
            continue

        grouped: OrderedDict[str, list[dict]] = OrderedDict()
        for param in params:
            location = str(param.get("in") or "query")
            grouped.setdefault(location, []).append(dict(param))

        for location, group in grouped.items():
            lines.append(f"- {labels.get(location, labels['query'])}:")
            for param in group:
                lines.append(_format_param(param, labels))
        constraints = list(spec.get("constraints") or [])
        if constraints:
            lines.append(f"- {labels['constraints']}:")
            for constraint in constraints:
                lines.append(_format_constraint(dict(constraint), labels))
        lines.append("")

    return "\n".join(lines).rstrip()


def render_local_api_skill_template(template_text: str, *, language: str) -> str:
    """Inject the generated route reference into a localized template skeleton."""

    text = str(template_text or "")
    if LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER not in text:
        return text
    return text.replace(
        LOCAL_OPEN_API_ROUTE_REFERENCE_PLACEHOLDER,
        _render_route_reference(language),
    )
