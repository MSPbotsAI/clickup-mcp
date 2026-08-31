"""custom_fields support on clickup_create_task / clickup_update_task
(PRD-17840): Create Task accepts custom_fields inline in its own POST body;
Update Task has no such body field upstream, so it's set via a separate
per-field POST, one call per field, continuing past individual failures.
"""

import json

import httpx
import pytest
import respx

from clickup_mcp.api_client import DEFAULT_BASE_URL
from clickup_mcp.config import Settings
from clickup_mcp.server import create_mcp_server

REQUESTER_FIELD_ID = "024ba696-b139-459b-838f-525c73c5e965"


async def _call(tool: str, **arguments):
    mcp = create_mcp_server(Settings(mcp_transport="stdio", clickup_api_token="pk_test"))
    blocks, _structured = await mcp.call_tool(tool, arguments)
    return json.loads(blocks[0].text)


@pytest.mark.asyncio
@respx.mock
async def test_create_task_sends_custom_fields_inline():
    route = respx.post(f"{DEFAULT_BASE_URL}/list/900/task").mock(
        return_value=httpx.Response(200, json={"id": "1", "name": "t"})
    )
    await _call(
        "clickup_create_task",
        list_id="900",
        name="t",
        custom_fields=[{"id": REQUESTER_FIELD_ID, "value": '{"add":["123"]}'}],
    )
    assert route.called
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["custom_fields"] == [{"id": REQUESTER_FIELD_ID, "value": {"add": ["123"]}}]


@pytest.mark.asyncio
@respx.mock
async def test_update_task_sets_each_custom_field_via_its_own_endpoint():
    put_route = respx.put(f"{DEFAULT_BASE_URL}/task/abc").mock(
        return_value=httpx.Response(200, json={"id": "abc", "name": "t"})
    )
    field_route = respx.post(f"{DEFAULT_BASE_URL}/task/abc/field/{REQUESTER_FIELD_ID}").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await _call(
        "clickup_update_task",
        task_id="abc",
        custom_fields=[{"id": REQUESTER_FIELD_ID, "value": '{"add":["123"]}'}],
    )
    assert put_route.called
    assert field_route.called
    sent_body = json.loads(field_route.calls[0].request.content)
    assert sent_body == {"value": {"add": ["123"]}}
    assert result["custom_fields"] == [{"id": REQUESTER_FIELD_ID, "status": "set"}]


@pytest.mark.asyncio
@respx.mock
async def test_update_task_custom_field_failure_does_not_block_other_fields():
    respx.put(f"{DEFAULT_BASE_URL}/task/abc").mock(
        return_value=httpx.Response(200, json={"id": "abc"})
    )
    respx.post(f"{DEFAULT_BASE_URL}/task/abc/field/bad-id").mock(
        return_value=httpx.Response(400, json={"err": "field not found"})
    )
    respx.post(f"{DEFAULT_BASE_URL}/task/abc/field/good-id").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await _call(
        "clickup_update_task",
        task_id="abc",
        custom_fields=[
            {"id": "bad-id", "value": "1"},
            {"id": "good-id", "value": "1"},
        ],
    )
    by_id = {cf["id"]: cf for cf in result["custom_fields"]}
    assert by_id["bad-id"]["status"] == "error"
    assert by_id["good-id"]["status"] == "set"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"add":["1"],"rem":["2"]}', {"add": ["1"], "rem": ["2"]}),
        ('["uuid1","uuid2"]', ["uuid1", "uuid2"]),
        ("42", 42),
        ("true", True),
        ("some plain text", "some plain text"),
        ("d53e5f2e-3681-4fb9-8562-41392075c0f5", "d53e5f2e-3681-4fb9-8562-41392075c0f5"),
    ],
)
def test_coerce_custom_field_value(raw, expected):
    from clickup_mcp.tools.tasks import _coerce_custom_field_value

    assert _coerce_custom_field_value(raw) == expected
