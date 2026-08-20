"""Server-side resolution of the ClickUp workspace (team) ID.

The workspace ID is not something a caller needs to know: `GET /team` returns
every workspace the API token is authorized for, so the server can work it out
itself. Declaring it as a required tool parameter only pushes that lookup onto
the agent, which has no way to know the answer and therefore guesses. ClickUp
answers a wrong guess with 401, which api_client maps to `unauthorized` — so a
bad workspace ID reads as "bad credentials" and sends debugging the wrong way.

This module moves the lookup back to where the information lives. Callers may
omit team_id entirely; if they pass one the token cannot see, an unambiguous
single workspace is substituted, and anything else returns an error that lists
the legal workspaces so the caller can correct itself in one step instead of
retrying blind.
"""

import time
from typing import NamedTuple

from .._json import error_envelope
from ..api_client import ClickUpClient, ClickUpError

# SOP §3.4 forbids caching tenant data across requests unless the cache key
# carries a credential fingerprint and the entry expires. Both hold here: the
# key is a hash prefix of the token and the plaintext token is never stored.
_TTL_SECONDS = 300.0
_MAX_ENTRIES = 256
_cache: dict[str, tuple[float, list[dict]]] = {}

# ClickUp returns 401 both for a dead token and for a workspace the token is
# simply not a member of. These markers separate the second case from the first.
_NOT_AUTHORIZED_MARKERS = ("oauth_027", "team not authorized")


class TeamScope(NamedTuple):
    """The workspace(s) a single tool call should target.

    Either `error` is set and `team_ids` is empty, or `team_ids` holds at least
    one workspace. `corrected_from` records a team_id the caller asked for that
    the token could not see, in the case where exactly one replacement existed.
    """

    team_ids: list[str]
    teams: list[dict]
    error: str | None = None
    corrected_from: str | None = None


def summarize_teams(raw_teams: list[dict]) -> list[dict]:
    """Reduce ClickUp's `GET /team` payload to [{"id", "name"}].

    The native response embeds a full member list per team; drop it, both to
    keep responses small and because nothing here needs it.
    """
    return [
        {"id": str(team["id"]), "name": team.get("name")}
        for team in raw_teams or []
        if team.get("id") is not None
    ]


def _prune(now: float) -> None:
    for key in [k for k, (expires_at, _) in _cache.items() if expires_at <= now]:
        _cache.pop(key, None)


async def list_authorized_teams(client: ClickUpClient) -> list[dict]:
    """Every workspace this token can access, as [{"id", "name"}].

    Raises ClickUpError, like the rest of the api_client surface.
    """
    now = time.monotonic()
    cached = _cache.get(client.token_fingerprint)
    if cached and cached[0] > now:
        return cached[1]

    result = await client.get("/team")
    teams = summarize_teams((result or {}).get("teams", []) or [])

    if len(_cache) >= _MAX_ENTRIES:
        _prune(now)
    _cache[client.token_fingerprint] = (now + _TTL_SECONDS, teams)
    return teams


def pick_team_ids(teams: list[dict], team_id: str | None) -> TeamScope:
    """Decide which workspaces to target, given the token's authorized set.

    The pure half of resolve_team_scope, for callers that already hold the
    result of `GET /team` and should not pay for a second round trip.
    """
    if not teams:
        return TeamScope(
            [],
            [],
            error=error_envelope(
                "not_found", "this API token can access no ClickUp workspaces", False
            ),
        )

    authorized = [team["id"] for team in teams]
    requested = (team_id or "").strip()

    if not requested:
        return TeamScope(authorized, teams)
    if requested in authorized:
        return TeamScope([requested], teams)
    if len(authorized) == 1:
        # The caller guessed wrong, but only one answer is possible — take it,
        # and let the caller report the substitution via annotate().
        return TeamScope(authorized, teams, corrected_from=requested)
    return TeamScope([], teams, error=not_authorized_envelope(requested, teams))


async def resolve_team_scope(client: ClickUpClient, team_id: str | None) -> TeamScope:
    """Resolve `team_id` against the workspaces this token is authorized for."""
    try:
        teams = await list_authorized_teams(client)
    except ClickUpError as e:
        return TeamScope([], [], error=e.to_envelope())
    return pick_team_ids(teams, team_id)


def not_authorized_envelope(requested: str | None, teams: list[dict]) -> str:
    """The actionable form of ClickUp's "team not authorized" 401."""
    subject = (
        f"workspace/team ID '{requested}' is not accessible with this API token"
        if requested
        else "no workspace/team ID resolved for this call"
    )
    return error_envelope(
        "invalid_argument",
        f"{subject}; pass one of authorized_workspaces instead",
        False,
        authorized_workspaces=teams,
    )


def ambiguous_write_envelope(teams: list[dict]) -> str:
    """Write paths must not guess between workspaces — make the caller choose."""
    return error_envelope(
        "invalid_argument",
        "this token can access several workspaces, so team_id cannot be inferred "
        "for a write; pass one of authorized_workspaces explicitly",
        False,
        authorized_workspaces=teams,
    )


def is_workspace_miss(e: ClickUpError) -> bool:
    """True when the resource simply is not in the workspace just tried.

    A plain 404 says so directly. ClickUp's v3 Docs API instead answers with
    401 `not_found_or_authorized`, which is indistinguishable from "wrong
    workspace" — treating it as an auth failure would abort a probe that still
    had other workspaces left to try, and report the wrong cause.
    """
    if e.status_code == 404:
        return True
    return e.status_code in (401, 403) and "not_found_or_authorized" in (e.message or "").lower()


def is_team_not_authorized(e: ClickUpError) -> bool:
    """True when ClickUp rejected the workspace rather than the token itself."""
    if e.status_code not in (401, 403):
        return False
    message = (e.message or "").lower()
    return any(marker in message for marker in _NOT_AUTHORIZED_MARKERS)


def team_error_envelope(e: ClickUpError, teams: list[dict], target: str | None = None) -> str:
    """Report a team-scoped failure as an argument problem, not an auth problem."""
    if is_team_not_authorized(e):
        return not_authorized_envelope(target, teams)
    return e.to_envelope()


def invalidate(client: ClickUpClient) -> None:
    """Drop this token's cached workspace list.

    Called when ClickUp contradicts the cache — a workspace we believed was
    authorized rejected the call — so the next lookup re-reads the truth.
    """
    _cache.pop(client.token_fingerprint, None)


def annotate(payload, scope: TeamScope):
    """Record an auto-corrected team_id on an otherwise successful result."""
    if scope.corrected_from and isinstance(payload, dict):
        payload["team_id_corrected"] = {
            "requested": scope.corrected_from,
            "used": scope.team_ids[0],
        }
    return payload
