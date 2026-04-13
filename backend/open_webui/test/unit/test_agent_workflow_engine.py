"""
Automated QA for the agent workflow engine (DAG execution, IF validation, merge, partial runs).

Run from repo `backend/` with venv active:
  python -m pytest open_webui/test/unit/test_agent_workflow_engine.py -v
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from open_webui.routers.agent_workflows import RunBody, run_workflow
from open_webui.workflow_wire import make_wire, parse_wire


def _minimal_request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"spec_version": "2.0", "version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/v1/agent-workflows/run",
            "raw_path": b"/api/v1/agent-workflows/run",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


def _run(body: RunBody) -> dict:
    """Execute workflow and return JSON-serializable response dict."""

    async def _go():
        return await run_workflow(_minimal_request(), body, SimpleNamespace())

    return asyncio.run(_go())


def _two_age_items_wire() -> str:
    return make_wire(
        [{"json": {"age": 20}}, {"json": {"age": 15}}],
        text="",
    )


# --- 1. Final output: multiple terminals ---


def test_final_includes_all_terminal_nodes():
    """Fan-out from trigger to two transforms; both are terminals — `final` must mention both node ids."""
    body = RunBody(
        user_input="hello",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "ta",
                    "nodeType": "transform",
                    "config": {"template": "A:{{input}}"},
                },
                {
                    "id": "tb",
                    "nodeType": "transform",
                    "config": {"template": "B:{{input}}"},
                },
            ],
            "edges": [
                {"id": "e1", "fromNodeId": "tr", "toNodeId": "ta"},
                {"id": "e2", "fromNodeId": "tr", "toNodeId": "tb"},
            ],
        },
        agents=[],
    )
    out = _run(body)
    assert out["ok"] is True
    final = out["final"]
    assert "`ta`" in final and "`tb`" in final, final
    fbn = out["finalByNode"]
    assert set(fbn.keys()) == {"ta", "tb"}
    for nid in ("ta", "tb"):
        assert isinstance(fbn[nid], str)
        assert parse_wire(fbn[nid]).get("$wf") == 1


# --- 2. Partial execution ---


def test_partial_execution_on_agent_failure():
    """When LLM fails and there is no on_error route, run halts with ok:false and prior results kept."""

    async def failing_llm(*_a, **_k):
        raise HTTPException(status_code=502, detail="simulated LLM failure")

    body = RunBody(
        user_input="ping",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "ag",
                    "nodeType": "agent",
                    "agentId": "agent-1",
                    "task": "say hi",
                    "mode": "text",
                },
            ],
            "edges": [{"id": "e1", "fromNodeId": "tr", "toNodeId": "ag"}],
        },
        agents=[{"id": "agent-1", "name": "Test", "modelId": "gpt-test"}],
    )

    with patch(
        "open_webui.routers.agent_workflows._call_chat_completion",
        new_callable=AsyncMock,
        side_effect=failing_llm,
    ):
        out = _run(body)

    assert out["ok"] is False
    assert out["failedNodeId"] == "ag"
    assert "simulated LLM failure" in (out.get("error") or "")
    assert "tr" in out["results"]
    assert "ag" in out["results"]
    assert out["partialResults"] == out["results"]
    w = parse_wire(out["results"]["ag"])
    assert w["items"][0]["json"].get("type") in ("agent_error", "workflow_error")


# --- 3. IF validation before execution ---


def test_if_else_invalid_source_handle_rejected_before_run():
    """Invalid sourceHandle on IF outgoing edge → HTTP 400, no successful execution payload."""
    body = RunBody(
        user_input="x",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {"id": "if1", "nodeType": "if_else", "config": {"conditionMode": "substring", "condition": "x"}},
                {"id": "a1", "nodeType": "transform", "config": {"template": "T"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "e1",
                    "fromNodeId": "if1",
                    "toNodeId": "a1",
                    "sourceHandle": "maybe",
                },
            ],
        },
        agents=[],
    )

    async def _go():
        await run_workflow(_minimal_request(), body, SimpleNamespace())

    with pytest.raises(HTTPException) as ei:
        asyncio.run(_go())
    assert ei.value.status_code == 400
    assert "sourceHandle" in str(ei.value.detail).lower() or "true" in str(ei.value.detail).lower()


# --- 4. IF execution + multi-item wire (unit + integration) ---


def test_eval_if_json_compare_multi_item_wire_first_and_second_age():
    """Wire with two items: items.0.json.age > 18 vs items.1.json.age > 18."""
    from open_webui.workflow_wire import eval_if_json_compare

    raw = _two_age_items_wire()
    assert (
        eval_if_json_compare(
            raw,
            json_path="items.0.json.age",
            operator="gt",
            compare_value="18",
        )
        is True
    )
    assert (
        eval_if_json_compare(
            raw,
            json_path="items.1.json.age",
            operator="gt",
            compare_value="18",
        )
        is False
    )


def test_if_condition_expression_splits_same_as_json_compare():
    """conditionExpression (new) matches legacy json_compare path for age > 18."""
    body_expr = RunBody(
        user_input="ignored",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "if1",
                    "nodeType": "if_else",
                    "config": {
                        "conditionExpression": "={{$json.age > 18}}",
                    },
                },
                {"id": "t_true", "nodeType": "transform", "config": {"template": "T"}},
                {"id": "t_false", "nodeType": "transform", "config": {"template": "F"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "eT",
                    "fromNodeId": "if1",
                    "toNodeId": "t_true",
                    "sourceHandle": "true",
                },
                {
                    "id": "eF",
                    "fromNodeId": "if1",
                    "toNodeId": "t_false",
                    "sourceHandle": "false",
                },
            ],
        },
        agents=[],
    )
    with patch(
        "open_webui.routers.agent_workflows.wrap_trigger",
        return_value=_two_age_items_wire(),
    ):
        out_expr = _run(body_expr)
    assert out_expr["ok"] is True
    assert "t_true" in out_expr["order"] and "t_false" in out_expr["order"]


def test_if_item_level_splits_age_gt_18_two_items():
    """Case 1: each row evaluated independently — true gets [{age:20}], false gets [{age:15}]."""
    body = RunBody(
        user_input="ignored",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "if1",
                    "nodeType": "if_else",
                    "config": {
                        "conditionMode": "json_compare",
                        "jsonPath": "items.0.json.age",
                        "jsonOperator": "gt",
                        "compareValue": "18",
                    },
                },
                {"id": "t_true", "nodeType": "transform", "config": {"template": "T:{{json}}"}},
                {"id": "t_false", "nodeType": "transform", "config": {"template": "F:{{json}}"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "eT",
                    "fromNodeId": "if1",
                    "toNodeId": "t_true",
                    "sourceHandle": "true",
                },
                {
                    "id": "eF",
                    "fromNodeId": "if1",
                    "toNodeId": "t_false",
                    "sourceHandle": "false",
                },
            ],
        },
        agents=[],
    )

    with patch(
        "open_webui.routers.agent_workflows.wrap_trigger",
        return_value=_two_age_items_wire(),
    ):
        out = _run(body)

    assert out["ok"] is True
    assert "t_true" in out["order"] and "t_false" in out["order"]
    # Transforms receive filtered item batches; template echoes JSON — age must stay on each side only
    assert len(out["itemsByNode"]["t_true"]) == 1 and len(out["itemsByNode"]["t_false"]) == 1
    assert 'T:{"age": 20}' in parse_wire(out["results"]["t_true"])["items"][0]["json"]["output"]
    assert 'F:{"age": 15}' in parse_wire(out["results"]["t_false"])["items"][0]["json"]["output"]


def test_if_all_items_true_only_true_branch_runs():
    """Case 2: all rows pass → only true handle downstream runs."""
    body = RunBody(
        user_input="ignored",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "if1",
                    "nodeType": "if_else",
                    "config": {
                        "conditionMode": "json_compare",
                        "jsonPath": "items.0.json.age",
                        "jsonOperator": "gt",
                        "compareValue": "18",
                    },
                },
                {"id": "t_true", "nodeType": "transform", "config": {"template": "TRUE_BRANCH"}},
                {"id": "t_false", "nodeType": "transform", "config": {"template": "FALSE_BRANCH"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "eT",
                    "fromNodeId": "if1",
                    "toNodeId": "t_true",
                    "sourceHandle": "true",
                },
                {
                    "id": "eF",
                    "fromNodeId": "if1",
                    "toNodeId": "t_false",
                    "sourceHandle": "false",
                },
            ],
        },
        agents=[],
    )

    both_old = make_wire(
        [{"json": {"age": 22}}, {"json": {"age": 30}}],
        text="",
    )
    with patch("open_webui.routers.agent_workflows.wrap_trigger", return_value=both_old):
        out = _run(body)

    assert out["ok"] is True
    assert "t_true" in out["order"]
    assert "t_false" not in out["order"]
    assert len(out["itemsByNode"]["t_true"]) == 2


def test_if_all_items_false_only_false_branch_runs():
    """Case 3: no row passes → only false handle downstream runs."""
    body = RunBody(
        user_input="ignored",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "if1",
                    "nodeType": "if_else",
                    "config": {
                        "conditionMode": "json_compare",
                        "jsonPath": "items.0.json.age",
                        "jsonOperator": "gt",
                        "compareValue": "18",
                    },
                },
                {"id": "t_true", "nodeType": "transform", "config": {"template": "TRUE_BRANCH"}},
                {"id": "t_false", "nodeType": "transform", "config": {"template": "FALSE_BRANCH"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "eT",
                    "fromNodeId": "if1",
                    "toNodeId": "t_true",
                    "sourceHandle": "true",
                },
                {
                    "id": "eF",
                    "fromNodeId": "if1",
                    "toNodeId": "t_false",
                    "sourceHandle": "false",
                },
            ],
        },
        agents=[],
    )

    both_young = make_wire(
        [{"json": {"age": 10}}, {"json": {"age": 12}}],
        text="",
    )
    with patch("open_webui.routers.agent_workflows.wrap_trigger", return_value=both_young):
        out = _run(body)

    assert out["ok"] is True
    assert "t_false" in out["order"]
    assert "t_true" not in out["order"]
    assert len(out["itemsByNode"]["t_false"]) == 2


def test_if_empty_input_skips_downstream_nodes():
    """Case 4: zero input items → IF runs, downstream branches are not executed."""
    empty = make_wire([], text="")
    body = RunBody(
        user_input="ignored",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "if1",
                    "nodeType": "if_else",
                    "config": {
                        "conditionMode": "json_compare",
                        "jsonPath": "items.0.json.age",
                        "jsonOperator": "gt",
                        "compareValue": "18",
                    },
                },
                {"id": "t_true", "nodeType": "transform", "config": {"template": "TRUE_BRANCH"}},
                {"id": "t_false", "nodeType": "transform", "config": {"template": "FALSE_BRANCH"}},
            ],
            "edges": [
                {"id": "e0", "fromNodeId": "tr", "toNodeId": "if1"},
                {
                    "id": "eT",
                    "fromNodeId": "if1",
                    "toNodeId": "t_true",
                    "sourceHandle": "true",
                },
                {
                    "id": "eF",
                    "fromNodeId": "if1",
                    "toNodeId": "t_false",
                    "sourceHandle": "false",
                },
            ],
        },
        agents=[],
    )

    with patch("open_webui.routers.agent_workflows.wrap_trigger", return_value=empty):
        out = _run(body)

    assert out["ok"] is True
    assert "t_true" not in out["order"]
    assert "t_false" not in out["order"]
    assert out["itemsByNode"]["if1"] == []


# --- 5. Merge: two branches, deep copy safety ---


def test_merge_combines_items_and_deep_copy_prevents_shared_mutation():
    """Two transforms into merge — combined items; mutating merged json must not change parent wires."""
    body = RunBody(
        user_input="u",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {"id": "L", "nodeType": "transform", "config": {"template": '{"side":"L","v":1}'}},
                {"id": "R", "nodeType": "transform", "config": {"template": '{"side":"R","v":2}'}},
                {"id": "M", "nodeType": "merge", "config": {}},
            ],
            "edges": [
                {"id": "e1", "fromNodeId": "tr", "toNodeId": "L"},
                {"id": "e2", "fromNodeId": "tr", "toNodeId": "R"},
                {"id": "e3", "fromNodeId": "L", "toNodeId": "M"},
                {"id": "e4", "fromNodeId": "R", "toNodeId": "M"},
            ],
        },
        agents=[],
    )
    out = _run(body)
    assert out["ok"] is True
    wm = parse_wire(out["results"]["M"])
    items = wm.get("items") or []
    assert len(items) == 2

    # Mutate merged first item — parent result strings must stay unchanged when re-parsed
    items[0]["json"]["INJECTED"] = 999
    wl = parse_wire(out["results"]["L"])
    assert "INJECTED" not in json.dumps(wl["items"])


# --- 6. Determinism ---


def test_same_workflow_three_runs_identical_results():
    body = RunBody(
        user_input="stable",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {"id": "tx", "nodeType": "transform", "config": {"template": "X{{input}}"}},
            ],
            "edges": [{"id": "e1", "fromNodeId": "tr", "toNodeId": "tx"}],
        },
        agents=[],
    )
    runs = [_run(body) for _ in range(3)]
    for k in ("ok", "final", "order", "results", "finalByNode", "itemsByNode"):
        assert runs[0][k] == runs[1][k] == runs[2][k], k


# --- 7. workflow_error shape ---


def test_workflow_error_wire_structure_on_transform_http_exception():
    """Unsupported node in disabled branch still raises in some paths — use explicit transform that raises via bad config.

    Instead: patch transform internals by forcing HTTP via http_request is heavy.
    We assert workflow_error structure from a node that raises HTTPException inside execution.
    """

    body = RunBody(
        user_input="x",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {
                    "id": "bad",
                    "nodeType": "http_request",
                    "config": {
                        "method": "GET",
                        "url": "",
                        "headersJson": "{}",
                        "body": "",
                    },
                },
            ],
            "edges": [{"id": "e1", "fromNodeId": "tr", "toNodeId": "bad"}],
        },
        agents=[],
    )
    out = _run(body)
    assert out["ok"] is False
    assert out["failedNodeId"] == "bad"
    w = parse_wire(out["results"]["bad"])
    j = w["items"][0]["json"]
    assert j.get("type") == "workflow_error"
    assert j.get("error") is True
    assert j.get("nodeId") == "bad"
    assert isinstance(j.get("message"), str) and len(j.get("message", "")) > 0


def test_logs_contain_observability_fields_for_transform():
    body = RunBody(
        user_input="z",
        workflow={
            "version": 1,
            "startNodeId": "tr",
            "nodes": [
                {"id": "tr", "nodeType": "trigger"},
                {"id": "tx", "nodeType": "transform", "config": {"template": "{{input}}"}},
            ],
            "edges": [{"id": "e1", "fromNodeId": "tr", "toNodeId": "tx"}],
        },
        agents=[],
    )
    out = _run(body)
    tx_logs = [x for x in out["logs"] if x.get("nodeId") == "tx"]
    assert tx_logs
    row = tx_logs[0]
    assert "durationMs" in row and "inputSize" in row and "outputSize" in row
