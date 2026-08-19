"""tools/list snapshot + error-envelope mapping tests.

No network calls: tool enumeration goes through FastMCP's in-process
list_tools(), and the error-code mapping is tested directly against
ClickUpError, independent of any real HTTP request.
"""

import json

import pytest

from clickup_mcp.api_client import ClickUpError
from clickup_mcp.config import Settings
from clickup_mcp.server import create_mcp_server

# Every tool this server registers, with its required (non-default) params.
EXPECTED_REQUIRED: dict[str, set[str]] = {
    "clickup_get_task": {"task_id"},
    "clickup_search_tasks": {"team_id"},
    "clickup_create_task": {"list_id", "name"},
    "clickup_update_task": {"task_id"},
    "clickup_delete_task": {"task_id"},
    "clickup_move_task": {"task_id", "list_id"},
    "clickup_get_task_comments": {"task_id"},
    "clickup_create_task_comment": {"task_id", "comment_text"},
    "clickup_get_doc_page": {"workspace_id", "doc_id", "page_id"},
    "clickup_get_folder": {"folder_id"},
    "clickup_get_folder_lists": {"folder_id"},
    "clickup_create_folder": {"space_id", "name"},
    "clickup_update_folder": {"folder_id", "name"},
    "clickup_delete_folder": {"folder_id"},
    "clickup_get_list": {"list_id"},
    "clickup_create_list_in_folder": {"folder_id", "name"},
    "clickup_create_folderless_list": {"space_id", "name"},
    "clickup_update_list": {"list_id"},
    "clickup_list_tasks_for_person": set(),
    "clickup_list_rocks_for_org": set(),
    "clickup_get_space": {"space_id"},
    "clickup_get_space_folders": {"space_id"},
    "clickup_get_space_lists": {"space_id"},
    "clickup_get_workspaces": set(),
    "clickup_list_members": set(),
    "clickup_list_spaces": {"team_id"},
    "clickup_attach_task_file": {"task_id", "file_content_base64", "filename"},
    "clickup_create_comment_with_image": {"task_id", "file_content_base64", "filename"},
}

READ_ONLY_TOOLS = {
    "clickup_get_task",
    "clickup_search_tasks",
    "clickup_get_task_comments",
    "clickup_get_doc_page",
    "clickup_get_folder",
    "clickup_get_folder_lists",
    "clickup_get_list",
    "clickup_list_tasks_for_person",
    "clickup_list_rocks_for_org",
    "clickup_get_space",
    "clickup_get_space_folders",
    "clickup_get_space_lists",
    "clickup_get_workspaces",
    "clickup_list_members",
    "clickup_list_spaces",
}

DESTRUCTIVE_TOOLS = {"clickup_delete_task", "clickup_delete_folder"}

IDEMPOTENT_TOOLS = {
    "clickup_update_task",
    "clickup_move_task",
    "clickup_update_folder",
    "clickup_update_list",
}


@pytest.mark.asyncio
async def test_tools_list_snapshot():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED_REQUIRED), f"unexpected tool set: {names}"
    assert len(tools) == 28


@pytest.mark.asyncio
async def test_every_tool_required_params_and_description_bounds():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    for name, expected_required in EXPECTED_REQUIRED.items():
        tool = by_name[name]
        required = set(tool.inputSchema.get("required", []))
        assert required == expected_required, f"{name}: required={required}"

        description = tool.description or ""
        assert len(description) <= 500, f"{name}: description too long ({len(description)})"
        first_line = description.strip().splitlines()[0] if description.strip() else ""
        assert len(first_line) <= 100, f"{name}: first line too long: {first_line!r}"
        assert "API:" not in description, f"{name}: leaked an 'API:' line"


@pytest.mark.asyncio
async def test_read_only_tools_are_annotated():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    for name in READ_ONLY_TOOLS:
        tool = by_name[name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True, f"{name} should be readOnlyHint=True"


@pytest.mark.asyncio
async def test_destructive_tools_are_annotated_and_gated_by_confirm():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    for name in DESTRUCTIVE_TOOLS:
        tool = by_name[name]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is True, f"{name} should be destructiveHint=True"
        properties = tool.inputSchema.get("properties", {})
        assert "confirm" in properties, f"{name} must expose a confirm param"
        assert "confirm" not in tool.inputSchema.get("required", []), (
            f"{name}: confirm must default to False, not be required"
        )


@pytest.mark.asyncio
async def test_idempotent_tools_are_annotated():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    for name in IDEMPOTENT_TOOLS:
        tool = by_name[name]
        assert tool.annotations is not None
        assert tool.annotations.idempotentHint is True, f"{name} should be idempotentHint=True"


@pytest.mark.asyncio
async def test_service_instructions_present_and_bounded():
    mcp = create_mcp_server(Settings(mcp_transport="http"))
    assert mcp.instructions
    assert len(mcp.instructions) <= 2000


@pytest.mark.parametrize(
    "status_code,expected_code,expected_retryable",
    [
        (0, "upstream_error", True),
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
def test_error_envelope_mapping(status_code, expected_code, expected_retryable):
    err = ClickUpError(status_code, "boom")
    envelope = json.loads(err.to_envelope())
    assert envelope["error"]["code"] == expected_code
    assert envelope["error"]["retryable"] is expected_retryable
    assert envelope["error"]["message"] == "boom"


@pytest.mark.asyncio
async def test_no_credentials_diagnostic_tool_in_stdio_mode_without_token():
    mcp = create_mcp_server(Settings(mcp_transport="stdio", clickup_api_token=None))
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"clickup_test_connection"}
