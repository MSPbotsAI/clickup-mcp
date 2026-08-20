# clickup-mcp

ClickUp MCP server for Claude — exposes ClickUp tasks, spaces, folders, lists, and comments as MCP tools.

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/FastAPI)

## Quick Start

```powershell
# Install dependencies
cd D:\leo\mcp-server\clickup-mcp
uv sync

# Run in HTTP/gateway mode (the default) — each request supplies its own
# token via the X-Clickup-Token header, nothing to set locally
uv run clickup-mcp

# Or run in stdio mode for local single-user tools like Claude Desktop
$env:MCP_TRANSPORT="stdio"
$env:CLICKUP_API_TOKEN="pk_xxxxx"
uv run clickup-mcp
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `http` | `http` (gateway, default) or `stdio` (Claude Desktop / local dev only) |
| `CLICKUP_API_TOKEN` | — | ClickUp personal API token (`pk_xxxxx`). Only read when `MCP_TRANSPORT=stdio` — the HTTP/gateway path never reads it, by design (no header = 401, never a silent fallback to this value) |
| `MCP_HTTP_PORT` | `8080` | HTTP server port |
| `CLICKUP_BASE_URL` | `https://api.clickup.com/api/v2` | API base URL |

Note: there is no `AUTH_MODE` setting anymore. HTTP transport is always
gateway mode (per-request `X-Clickup-Token` header, enforced by middleware);
stdio transport is always local-token mode. Credential source now follows
transport directly, so there is no way to accidentally run an HTTP/gateway
deployment that falls back to a shared env-var token.

Get your API token: ClickUp → Settings → Apps → API Token

## Claude Desktop Setup

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "clickup": {
      "command": "uv",
      "args": ["run", "--directory", "D:/leo/mcp-server/clickup-mcp", "clickup-mcp"],
      "env": {
        "CLICKUP_API_TOKEN": "pk_xxxxx"
      }
    }
  }
}
```

## Transport Modes

### HTTP — gateway / multi-tenant (default)
```powershell
uv run clickup-mcp
# Each request must include: X-Clickup-Token: pk_xxxxx
# A request with no header gets 401 — there is no env-var fallback.
```

### stdio (Claude Desktop / CLI, local dev only)
```powershell
$env:MCP_TRANSPORT="stdio"
$env:CLICKUP_API_TOKEN="pk_xxxxx"
uv run clickup-mcp
```

## Available Tools (28)

| Tool | Description |
|------|-------------|
| `clickup_get_workspaces` | List all workspaces/teams |
| `clickup_list_members` | List workspace members, flattened to id/username/email/team_id/role — resolve a person's email to the user_id `assignees` filters expect |
| `clickup_list_spaces` | List spaces in a workspace, or across every workspace the token can see when `team_id` is omitted |
| `clickup_get_space` | Get space details |
| `clickup_get_space_folders` | List folders in a space |
| `clickup_get_space_lists` | List folderless lists in a space |
| `clickup_get_folder` | Get folder details |
| `clickup_get_folder_lists` | List lists in a folder |
| `clickup_create_folder` | Create a folder |
| `clickup_update_folder` | Update a folder |
| `clickup_delete_folder` | Delete a folder |
| `clickup_get_list` | Get list details |
| `clickup_create_list_in_folder` | Create list in a folder |
| `clickup_create_folderless_list` | Create list in a space |
| `clickup_update_list` | Update a list |
| `clickup_get_task` | Get task by native ID, or by custom ID with the workspace resolved automatically |
| `clickup_search_tasks` | Search tasks with filters; searches every workspace the token can see when `team_id` is omitted |
| `clickup_list_tasks_for_person` | List a person's tasks across ALL visible workspaces in one call, by email or user_id — no team_id, no manual pagination/dedup needed |
| `clickup_create_task` | Create a task |
| `clickup_update_task` | Update a task |
| `clickup_delete_task` | Delete a task |
| `clickup_move_task` | Move task to a different list |
| `clickup_get_task_comments` | Get task comments |
| `clickup_create_task_comment` | Add a comment to a task |
| `clickup_get_doc_page` | Get a single page from a Doc (v3); `workspace_id` optional |
| `clickup_attach_task_file` | Upload a file (e.g. an image) as an attachment on a task |
| `clickup_create_comment_with_image` | Upload a file and post it inline inside a new task comment, in one call |
| `clickup_list_rocks_for_org` | List all EOS Rocks (quarterly goals) org-wide in one call, normalized to a fixed status enum |

### Workspace (team) IDs are resolved from the token

No tool requires a workspace/team ID. `GET /team` already tells the server every
workspace the API token is authorized for, so the server resolves it rather than
asking the caller to supply an ID it has no way of knowing.

- Omit `team_id` and the call covers every workspace the token can reach. Reads
  fan out and merge; each returned row carries its own `team_id`.
- Pass a `team_id` the token cannot see and, when only one workspace exists, it
  is substituted and the response reports `team_id_corrected`.
- When several workspaces exist and the given ID matches none, the error lists
  the legal ones in `authorized_workspaces` — so one retry is enough. Writes
  (`clickup_attach_task_file`) never guess between workspaces.

A workspace the token cannot reach is reported as `invalid_argument`, not
`unauthorized`; only a genuinely bad token yields `unauthorized`.

### Finding a person's ClickUp user ID

Use `clickup_list_members`. ClickUp's native `GET /team` response embeds a
full member list per team (`teams[].members[].user.{id,username,email}`), but
`clickup_get_workspaces` strips that out to keep its response small, so it is
not the place to look up people. `clickup_list_members` reads the same
underlying endpoint and projects the member list to a flat, purpose-built
shape (id/username/email/team_id/role) so callers don't have to dig it out of
the full workspace/team object themselves. `clickup_list_tasks_for_person`
uses the same underlying lookup internally to resolve `email` -> `user_id`.

Known gap: ClickUp's team-member object has no reliable "is this member
deactivated" field — `clickup_list_members` does not return an `active`
field, since nothing real would back it (the only `status` field present
on the raw object, `invited_by.status`, describes the inviter, not the
member).

### `clickup_search_tasks` already returns `status.type`

Like every other read tool here, `clickup_search_tasks` and
`clickup_get_task` pass through ClickUp's raw task object unmodified —
including the `status` object's `type` field (`open` / `custom` / `closed` /
`done`), which is the only reliable way to tell whether a custom-named
status counts as done. No code change was needed for this; it was already
there. `clickup_list_tasks_for_person` surfaces it explicitly as
`status_type` on each returned task for convenience.

### How EOS Rocks are represented in this ClickUp workspace

Confirmed 2026-08-18 by inspecting a real rock task's fields directly (not
guessed): **Rocks are regular ClickUp tasks living in a list literally named
"Rocks"** (found under Space "Company" > Folder "EOS Traction"), each
carrying dedicated custom fields: `Quarter` (dropdown, "Q1 2024".."Q4 2026"),
`Rocks Status` (On Hold / Off Track / On Track / Completed / Blocked / At
Risk), `Rock Type` (Company / Individual / Departmental / Team Rock),
`Department`, and progress via either `Progress` (manual) or `Progress %`
(auto, checklist-rollup). This is neither the ClickUp Goals API nor a
plain task list with no metadata — it's tasks-plus-custom-fields.

`clickup_list_rocks_for_org` discovers every list named "Rocks" (by name,
not a hardcoded ID, in case spaces/folders get reorganized) across every
workspace visible to the token, reads these fields, and normalizes them:

- `quarter`: ClickUp's "Q3 2026" label is converted to `2026-Q3` (and back,
  for the `quarter` input filter).
- `status`: ClickUp's 6 raw options are mapped down to the 5-value contract
  (`on_track`/`off_track`/`done`/`missed`/`open`) — see the `_STATUS_MAP`
  comment in `rocks.py` for the exact mapping and why `missed` is never
  emitted (nothing in ClickUp's data distinguishes "ran out of time" from
  generic "off track"; deriving it from an overdue due_date would be an
  unconfirmed business-logic assumption, so it isn't done here). The raw
  ClickUp label (e.g. `"At Risk"`) is also returned as `status_raw`,
  alongside the normalized `status`, so a UI can show ClickUp's own wording
  without it looking out of sync with the mapped value.
- **`measurable`**: no dedicated field exists on this list. Falls back to
  the task description; `null` if that's empty too (never fabricated).
- **`weekly_status`**: no structured source was found anywhere (not a
  custom field, nothing comment-derived either) — always returned as `[]`.
  If the org starts tracking this in ClickUp some other way, revisit.
- **`owner_email` / `owner_user_id` (optional filter args)**: this tool is
  org-wide by default (every rock returned), but a caller building a
  single-person view can pass either to scope the results to one owner's
  rocks — the org-wide fetch itself still happens (this doesn't reduce
  upstream ClickUp API calls), it just narrows what's returned. Omit both
  for the original org-wide behavior.

### Discovery performance: parallel, not sequential

`clickup_list_rocks_for_org`'s list-discovery walk (every workspace, every
space, each space's folderless lists + folder lists) runs concurrently via
`asyncio.gather`, not one request after another. A sequential version of
this was measured to time out against MSPbots' own workspace (15+ spaces
x 2 calls each, run one at a time, comfortably exceeded the caller's MCP
timeout) — parallelizing brought it down to ~7s. ClickUp's rate limit
(developer.clickup.com/docs/rate-limits) is a per-minute budget with no
separate burst cap (100/min on the lowest plan tier), and this fires on
the order of 2 x (space count) requests once, so a few dozen concurrent
calls stays well inside it even combined with other concurrent usage of
the same token — `api_client.py`'s shared retry logic (see below) also
backs off on a real 429 rather than assuming this burst is the only
traffic on the token.

### Rate-limit retries are centralized, not per-tool

Every tool's HTTP calls go through `ClickUpClient`'s shared `_request`
method (`api_client.py`), which retries `429`/`500`/`502`/`503`/`504`
with backoff — added here once so every tool benefits, since a token's
rate-limit budget is shared across whatever else is calling the ClickUp
API with it, not dedicated to any single tool. On a `429`, the delay
prefers ClickUp's own `X-RateLimit-Reset` header (a Unix timestamp for
when the per-minute window resets — the header ClickUp's rate-limit docs
actually document) over a generic `Retry-After` or blind exponential
backoff, so retries wait exactly as long as ClickUp says to, not a guess.

### Attachments and images

ClickUp's REST API has no way to attach a file directly to a comment —
only to a task (`POST /task/{task_id}/attachment`, what
`clickup_attach_task_file` wraps). There is also no delete/update
attachment endpoint; re-uploading adds a new attachment rather than
replacing the old one, and removing one requires the ClickUp web/desktop
app. Confirmed by checking ClickUp's own official MCP server's tool
descriptions too — same split (a `Create Task Comment` tool with no
attachment support, and a separate `Attach File to Task` tool).

**To make an image show up inline inside a comment**, the underlying
trick is: upload the file to the task first, then reference the
returned URL from the file's response using Markdown image syntax in
the comment text — ClickUp's comment renderer inlines it as a real
image, not just a link. `clickup_create_comment_with_image` does both
steps in one call:

```
clickup_create_comment_with_image(task_id, file_content_base64, filename)
# internally:
#   1. POST /task/{task_id}/attachment  -> {"url": "...", ...}
#   2. POST /task/{task_id}/comment     comment_text = "![filename](url)"
```

To do it manually instead (e.g. to add other text around the image),
call the two tools yourself:

```
1. result = clickup_attach_task_file(task_id, file_content_base64, filename)
   -> result["url"] is the uploaded file's URL

2. clickup_create_task_comment(
     task_id,
     comment_text=f"![{filename}]({result['url']})"
   )
```

## API Reference

- [ClickUp API v2 Docs](https://developer.clickup.com/reference/getaccesstoken)
- [Create Task Attachment](https://developer.clickup.com/reference/createtaskattachment)
