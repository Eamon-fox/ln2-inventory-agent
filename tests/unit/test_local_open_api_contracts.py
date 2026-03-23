from app_gui.application.open_api.contracts import (
    describe_local_open_api_route,
    iter_local_open_api_route_descriptions,
)


def test_describe_local_open_api_route_projects_public_fields_from_contract():
    route = describe_local_open_api_route(("POST", "/api/v1/gui/prefill-add"))

    assert route["method"] == "POST"
    assert route["path"] == "/api/v1/gui/prefill-add"
    assert route["effect"] == "gui_handoff"
    assert route["constraints"] == [{"kind": "at_least_one_of", "params": ["position", "positions"]}]
    assert "handler" not in route
    assert "request_arg" not in route


def test_iter_local_open_api_route_descriptions_returns_defensive_copies():
    routes = list(iter_local_open_api_route_descriptions())
    stage_plan_route = next(item for item in routes if item["path"] == "/api/v1/gui/stage-plan")

    stage_plan_route["params"].append({"name": "mutated"})
    fresh = describe_local_open_api_route(("GET", "/api/v1/gui/stage-plan"))

    assert all(param.get("name") != "mutated" for param in fresh["params"])
    assert fresh["effect"] == "gui_stage_state"
