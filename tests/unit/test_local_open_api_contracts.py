import copy

from app_gui.application.open_api.contracts import (
    LOCAL_OPEN_API_STAGE_PLAN_PAYLOAD_SCHEMA,
    describe_local_open_api_route,
    iter_local_open_api_route_descriptions,
)
from app_gui.application.open_api.service import _backfill_plan_payload
from lib.plan_gate import _validate_item_payload_schema
from lib.plan_validation import validate_plan_item


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


def test_stage_plan_schema_required_keys_match_plan_gate_enforcement():
    # Drift guard: the documented schema must stay in lock-step with the runtime
    # validators in lib/plan_gate.py. For every action, the documented example
    # validates cleanly, and removing any payload key marked required must make
    # plan_gate reject the item.
    actions = LOCAL_OPEN_API_STAGE_PLAN_PAYLOAD_SCHEMA["actions"]
    for action, spec in actions.items():
        example = _backfill_plan_payload(copy.deepcopy(spec["example"]))
        # Both schema layers run at stage time (lib/plan_gate.validate_plan_batch):
        # the item-level schema first, then the payload schema. The documented
        # example must clear both after server-side backfill.
        assert validate_plan_item(example) is None, (action, "item schema must validate")
        assert _validate_item_payload_schema(example) is None, (action, "baseline must validate")

        required_keys = [key for key, meta in spec["payload"].items() if meta.get("required")]
        assert required_keys, (action, "must document at least one required key")
        for key in required_keys:
            broken = _backfill_plan_payload(copy.deepcopy(spec["example"]))
            broken["payload"].pop(key, None)
            alias = spec["payload"][key].get("alias")
            if alias:
                broken["payload"].pop(alias, None)
            assert _validate_item_payload_schema(broken) is not None, (
                action,
                key,
                "removing a required key must be rejected",
            )
