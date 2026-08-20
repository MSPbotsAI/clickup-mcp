"""Workspace (team) ID resolution.

These cover the behaviour that replaced "team_id is a required parameter the
caller has to guess": an omitted ID resolves from the API token, a wrong ID is
either corrected or answered with the legal set, and a wrong ID never surfaces
as an authentication failure. The end-to-end cases drive the real tools through
FastMCP with the ClickUp API mocked, so they exercise the tool signatures the
agent actually sees.
"""

import base64
import json

import httpx
import pytest
import respx

from clickup_mcp.api_client import DEFAULT_BASE_URL, ClickUpClient, ClickUpError
from clickup_mcp.config import Settings
from clickup_mcp.server import create_mcp_server
from clickup_mcp.tools import _teams

ONE_TEAM = [{"id": "111", "name": "Acme"}]
TWO_TEAMS = [{"id": "111", "name": "Acme"}, {"id": "222", "name": "Globex"}]


@pytest.fixture(autouse=True)
def clear_team_cache():
    _teams._cache.clear()
    yield
    _teams._cache.clear()


def _teams_route(teams):
    return respx.get(f"{DEFAULT_BASE_URL}/team").mock(
        return_value=httpx.Response(200, json={"teams": teams})
    )


def _spaces_route(team_id, spaces=()):
    """Task search resolves space names per workspace; stub that lookup."""
    return respx.get(f"{DEFAULT_BASE_URL}/team/{team_id}/space").mock(
        return_value=httpx.Response(200, json={"spaces": list(spaces)})
    )


async def _call(tool: str, **arguments):
    """Invoke a tool the way the gateway would and return its parsed JSON."""
    mcp = create_mcp_server(Settings(mcp_transport="stdio", clickup_api_token="pk_test"))
    blocks, _structured = await mcp.call_tool(tool, arguments)
    return json.loads(blocks[0].text)


# ─────────────────────────────────────────────────────────────────────────────
# Resolution logic, no HTTP
# ─────────────────────────────────────────────────────────────────────────────


def test_omitted_team_id_targets_every_authorized_workspace():
    scope = _teams.pick_team_ids(TWO_TEAMS, None)
    assert scope.error is None
    assert scope.team_ids == ["111", "222"]
    assert scope.corrected_from is None


def test_valid_team_id_is_used_as_given():
    scope = _teams.pick_team_ids(TWO_TEAMS, "222")
    assert scope.error is None
    assert scope.team_ids == ["222"]


def test_blank_team_id_is_treated_as_omitted():
    assert _teams.pick_team_ids(ONE_TEAM, "   ").team_ids == ["111"]


def test_wrong_team_id_is_corrected_when_only_one_workspace_exists():
    scope = _teams.pick_team_ids(ONE_TEAM, "999")
    assert scope.error is None
    assert scope.team_ids == ["111"]
    assert scope.corrected_from == "999"
    # The substitution is reported rather than hidden.
    assert _teams.annotate({"tasks": []}, scope)["team_id_corrected"] == {
        "requested": "999",
        "used": "111",
    }


def test_wrong_team_id_lists_the_legal_set_when_ambiguous():
    scope = _teams.pick_team_ids(TWO_TEAMS, "999")
    assert scope.team_ids == []
    error = json.loads(scope.error)["error"]
    assert error["code"] == "invalid_argument"  # the point: not "unauthorized"
    assert error["retryable"] is False
    assert error["authorized_workspaces"] == TWO_TEAMS


def test_token_with_no_workspaces_reports_not_found():
    assert json.loads(_teams.pick_team_ids([], None).error)["error"]["code"] == "not_found"


def test_summarize_teams_drops_member_lists_and_stringifies_ids():
    raw = [{"id": 111, "name": "Acme", "members": [{"user": {"id": 1}}]}, {"name": "no id"}]
    assert _teams.summarize_teams(raw) == [{"id": "111", "name": "Acme"}]


@pytest.mark.parametrize(
    "status_code,message,expected",
    [
        (401, "Team not authorized", True),
        (401, "OAUTH_027", True),
        (401, "Token invalid", False),
        (403, "team not authorized", True),
        (404, "team not authorized", False),
    ],
)
def test_workspace_rejection_is_told_apart_from_a_dead_token(status_code, message, expected):
    assert _teams.is_team_not_authorized(ClickUpError(status_code, message)) is expected


@pytest.mark.parametrize(
    "status_code,message,expected",
    [
        (404, "Task not found", True),
        (401, "not_found_or_authorized", True),  # ClickUp v3 Docs says this for a miss
        (401, "Token invalid", False),
        (500, "boom", False),
    ],
)
def test_a_missing_resource_is_told_apart_from_a_dead_token(status_code, message, expected):
    assert _teams.is_workspace_miss(ClickUpError(status_code, message)) is expected


def test_a_dead_token_still_reports_unauthorized():
    envelope = json.loads(_teams.team_error_envelope(ClickUpError(401, "Token invalid"), ONE_TEAM))
    assert envelope["error"]["code"] == "unauthorized"


# ─────────────────────────────────────────────────────────────────────────────
# Caching (SOP §3.4: fingerprinted key + expiry, never the plaintext token)
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_workspace_list_is_cached_per_credential_fingerprint():
    route = respx.get(f"{DEFAULT_BASE_URL}/team").mock(
        side_effect=[
            httpx.Response(200, json={"teams": ONE_TEAM}),
            httpx.Response(200, json={"teams": TWO_TEAMS}),
        ]
    )
    a, b = ClickUpClient("pk_a"), ClickUpClient("pk_b")
    assert a.token_fingerprint != b.token_fingerprint

    assert await _teams.list_authorized_teams(a) == ONE_TEAM
    assert await _teams.list_authorized_teams(a) == ONE_TEAM
    assert route.call_count == 1, "second lookup for the same token should hit the cache"

    # A different credential must never read the first one's entry.
    assert await _teams.list_authorized_teams(b) == TWO_TEAMS
    assert route.call_count == 2
    assert "pk_a" not in _teams._cache and "pk_b" not in _teams._cache


@respx.mock
async def test_invalidate_forces_a_refetch():
    route = _teams_route(ONE_TEAM)
    client = ClickUpClient("pk_a")
    await _teams.list_authorized_teams(client)
    _teams.invalidate(client)
    await _teams.list_authorized_teams(client)
    assert route.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end through the real tools
# ─────────────────────────────────────────────────────────────────────────────


@respx.mock
async def test_search_tasks_without_team_id_resolves_the_single_workspace():
    _teams_route(ONE_TEAM)
    _spaces_route("111", [{"id": "sp1", "name": "Product"}])
    route = respx.get(f"{DEFAULT_BASE_URL}/team/111/task").mock(
        return_value=httpx.Response(
            200,
            json={"tasks": [{"id": "t1", "name": "Ship it", "space": {"id": "sp1"}}]},
        )
    )
    payload = await _call("clickup_search_tasks")
    assert route.called
    assert payload["team_id"] == "111"
    assert payload["truncated"] is False
    (task,) = payload["tasks"]
    assert (task["id"], task["name"], task["space_name"], task["team_id"]) == (
        "t1",
        "Ship it",
        "Product",
        "111",
    )


@respx.mock
async def test_search_tasks_corrects_a_wrong_team_id_instead_of_401ing():
    _teams_route(ONE_TEAM)
    _spaces_route("111")
    respx.get(f"{DEFAULT_BASE_URL}/team/111/task").mock(
        return_value=httpx.Response(200, json={"tasks": []})
    )
    payload = await _call("clickup_search_tasks", team_id="90210hallucinated")
    assert "error" not in payload
    assert payload["team_id_corrected"] == {"requested": "90210hallucinated", "used": "111"}


@respx.mock
async def test_search_tasks_with_a_wrong_team_id_lists_workspaces_when_ambiguous():
    _teams_route(TWO_TEAMS)
    payload = await _call("clickup_search_tasks", team_id="90210hallucinated")
    error = payload["error"]
    assert error["code"] == "invalid_argument"
    assert error["authorized_workspaces"] == TWO_TEAMS


@respx.mock
async def test_search_tasks_fans_out_across_every_workspace_when_ambiguous():
    _teams_route(TWO_TEAMS)
    _spaces_route("111")
    _spaces_route("222")
    respx.get(f"{DEFAULT_BASE_URL}/team/111/task").mock(
        return_value=httpx.Response(200, json={"tasks": [{"id": "a"}]})
    )
    respx.get(f"{DEFAULT_BASE_URL}/team/222/task").mock(
        return_value=httpx.Response(200, json={"tasks": [{"id": "b"}]})
    )
    payload = await _call("clickup_search_tasks")
    assert [(t["id"], t["team_id"]) for t in payload["tasks"]] == [("a", "111"), ("b", "222")]
    assert payload["truncated"] is False
    assert payload["searched_workspaces"] == TWO_TEAMS


@respx.mock
async def test_search_results_survive_clickups_oversized_task_objects():
    """Regression: raw ClickUp tasks embed the workspace's whole custom-field
    schema, so a single task could exceed the 20,000-char response budget and
    dump_json_capped truncated the list down to zero rows — the tool reported
    original_count=100 and returned nothing. Projection keeps rows readable.
    """
    _teams_route(ONE_TEAM)
    _spaces_route("111")
    bloat = [{"id": f"cf{i}", "name": "x" * 200, "type_config": {"options": ["y" * 200]}}
             for i in range(60)]
    respx.get(f"{DEFAULT_BASE_URL}/team/111/task").mock(
        return_value=httpx.Response(
            200,
            json={"tasks": [{"id": f"t{i}", "name": f"Task {i}", "custom_fields": bloat}
                            for i in range(20)]},
        )
    )
    payload = await _call("clickup_search_tasks")
    assert len(payload["tasks"]) == 20, "every matched task should come back"
    assert payload["truncated"] is False
    assert "custom_fields" not in payload["tasks"][0]


@respx.mock
async def test_search_honours_the_limit_and_flags_truncation():
    _teams_route(ONE_TEAM)
    _spaces_route("111")
    respx.get(f"{DEFAULT_BASE_URL}/team/111/task").mock(
        return_value=httpx.Response(
            200, json={"tasks": [{"id": f"t{i}"} for i in range(10)]}
        )
    )
    payload = await _call("clickup_search_tasks", limit=3)
    assert len(payload["tasks"]) == 3
    assert payload["truncated"] is True


@respx.mock
async def test_get_task_by_native_id_never_looks_up_workspaces():
    teams = respx.get(f"{DEFAULT_BASE_URL}/team")
    respx.get(f"{DEFAULT_BASE_URL}/task/abc123").mock(
        return_value=httpx.Response(200, json={"id": "abc123"})
    )
    assert (await _call("clickup_get_task", task_id="abc123"))["id"] == "abc123"
    assert teams.call_count == 0, "a native task ID needs no workspace context"


@respx.mock
async def test_get_task_by_custom_id_finds_the_right_workspace_unaided():
    _teams_route(TWO_TEAMS)
    respx.get(f"{DEFAULT_BASE_URL}/task/ABC-123", params={"team_id": "111"}).mock(
        return_value=httpx.Response(404, json={"err": "Task not found"})
    )
    respx.get(f"{DEFAULT_BASE_URL}/task/ABC-123", params={"team_id": "222"}).mock(
        return_value=httpx.Response(200, json={"id": "real", "name": "Found it"})
    )
    payload = await _call("clickup_get_task", task_id="ABC-123", custom_task_ids=True)
    assert payload["id"] == "real"
    assert payload["team_id"] == "222"


@respx.mock
async def test_get_task_by_custom_id_reports_not_found_with_the_workspaces_tried():
    _teams_route(TWO_TEAMS)
    respx.get(url__startswith=f"{DEFAULT_BASE_URL}/task/NOPE-1").mock(
        return_value=httpx.Response(404, json={"err": "Task not found"})
    )
    error = (await _call("clickup_get_task", task_id="NOPE-1", custom_task_ids=True))["error"]
    assert error["code"] == "not_found"
    assert error["authorized_workspaces"] == TWO_TEAMS


@respx.mock
async def test_list_spaces_merges_every_workspace_when_none_is_named():
    _teams_route(TWO_TEAMS)
    respx.get(f"{DEFAULT_BASE_URL}/team/111/space").mock(
        return_value=httpx.Response(200, json={"spaces": [{"id": "s1"}]})
    )
    respx.get(f"{DEFAULT_BASE_URL}/team/222/space").mock(
        return_value=httpx.Response(200, json={"spaces": [{"id": "s2"}]})
    )
    payload = await _call("clickup_list_spaces")
    assert [(s["id"], s["team_id"], s["team_name"]) for s in payload["spaces"]] == [
        ("s1", "111", "Acme"),
        ("s2", "222", "Globex"),
    ]


@respx.mock
async def test_list_members_rejects_an_unreachable_team_instead_of_returning_nothing():
    respx.get(f"{DEFAULT_BASE_URL}/team").mock(
        return_value=httpx.Response(
            200,
            json={
                "teams": [
                    {"id": "111", "name": "Acme", "members": [{"user": {"id": 1}}]},
                    {"id": "222", "name": "Globex", "members": []},
                ]
            },
        )
    )
    error = (await _call("clickup_list_members", team_id="999"))["error"]
    assert error["code"] == "invalid_argument"
    assert error["authorized_workspaces"] == TWO_TEAMS


@respx.mock
async def test_attaching_by_custom_id_refuses_to_guess_between_workspaces():
    _teams_route(TWO_TEAMS)
    upload = respx.post(url__startswith=f"{DEFAULT_BASE_URL}/task/ABC-123/attachment")
    error = (
        await _call(
            "clickup_attach_task_file",
            task_id="ABC-123",
            file_content_base64=base64.b64encode(b"hello").decode(),
            filename="note.txt",
            custom_task_ids=True,
        )
    )["error"]
    assert error["code"] == "invalid_argument"
    assert error["authorized_workspaces"] == TWO_TEAMS
    assert upload.call_count == 0, "a write must not be attempted against a guessed workspace"


@respx.mock
async def test_attaching_by_custom_id_resolves_the_only_workspace():
    _teams_route(ONE_TEAM)
    upload = respx.post(url__startswith=f"{DEFAULT_BASE_URL}/task/ABC-123/attachment").mock(
        return_value=httpx.Response(200, json={"id": "att1"})
    )
    payload = await _call(
        "clickup_attach_task_file",
        task_id="ABC-123",
        file_content_base64=base64.b64encode(b"hello").decode(),
        filename="note.txt",
        custom_task_ids=True,
    )
    assert payload["id"] == "att1"
    assert "team_id=111" in str(upload.calls[0].request.url)


@respx.mock
async def test_get_doc_page_probes_workspaces_when_none_is_named():
    _teams_route(TWO_TEAMS)
    v3 = DEFAULT_BASE_URL.replace("/v2", "/v3")
    # ClickUp v3 reports an unreachable doc as 401 not_found_or_authorized, which
    # must not abort the probe before the workspace that actually holds it.
    respx.get(f"{v3}/workspaces/111/docs/d1/pages/p1").mock(
        return_value=httpx.Response(401, json={"err": "not_found_or_authorized"})
    )
    respx.get(f"{v3}/workspaces/222/docs/d1/pages/p1").mock(
        return_value=httpx.Response(200, json={"id": "p1", "name": "Runbook"})
    )
    payload = await _call("clickup_get_doc_page", doc_id="d1", page_id="p1")
    assert payload["id"] == "p1"
    assert payload["workspace_id"] == "222"


@respx.mock
async def test_get_doc_page_reports_not_found_rather_than_unauthorized():
    _teams_route(ONE_TEAM)
    v3 = DEFAULT_BASE_URL.replace("/v2", "/v3")
    respx.get(f"{v3}/workspaces/111/docs/gone/pages/gone").mock(
        return_value=httpx.Response(401, json={"err": "not_found_or_authorized"})
    )
    error = (await _call("clickup_get_doc_page", doc_id="gone", page_id="gone"))["error"]
    assert error["code"] == "not_found"  # the point: not "unauthorized"
    assert error["authorized_workspaces"] == ONE_TEAM
