# clickup-mcp

ClickUp MCP server for Claude — exposes ClickUp tasks, spaces, folders, lists, and comments as MCP tools.

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/FastAPI)

## Quick Start

```powershell
# Install dependencies
cd D:\leo\mcp-server\clickup-mcp
uv sync

# Run in stdio mode (for Claude Desktop)
$env:CLICKUP_API_TOKEN="pk_xxxxx"
uv run clickup-mcp
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLICKUP_API_TOKEN` | — | ClickUp personal API token (`pk_xxxxx`) |
| `AUTH_MODE` | `env` | `env` = token from env var; `gateway` = token per-request from `X-Clickup-Token` header |
| `MCP_TRANSPORT` | `stdio` | `stdio` (Claude Desktop) or `http` (gateway) |
| `MCP_HTTP_PORT` | `8080` | HTTP server port |
| `CLICKUP_BASE_URL` | `https://api.clickup.com/api/v2` | API base URL |

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

### stdio (Claude Desktop / CLI)
```powershell
$env:CLICKUP_API_TOKEN="pk_xxxxx"
uv run clickup-mcp
```

### HTTP — single-tenant
```powershell
$env:CLICKUP_API_TOKEN="pk_xxxxx"
$env:MCP_TRANSPORT="http"
$env:MCP_HTTP_PORT="8080"
uv run clickup-mcp
```

### HTTP — gateway / multi-tenant
```powershell
$env:MCP_TRANSPORT="http"
$env:AUTH_MODE="gateway"
uv run clickup-mcp
# Each request must include: X-Clickup-Token: pk_xxxxx
```

## Available Tools (28)

| Tool | Description |
|------|-------------|
| `clickup_get_workspaces` | List all workspaces/teams |
| `clickup_list_members` | List workspace members, flattened to id/username/email/team_id/role — resolve a person's email to the user_id `assignees` filters expect |
| `clickup_list_spaces` | List spaces in a workspace |
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
| `clickup_get_task` | Get task by ID |
| `clickup_search_tasks` | Search tasks with filters (single workspace, team_id required) |
| `clickup_list_tasks_for_person` | List a person's tasks across ALL visible workspaces in one call, by email or user_id — no team_id, no manual pagination/dedup needed |
| `clickup_create_task` | Create a task |
| `clickup_update_task` | Update a task |
| `clickup_delete_task` | Delete a task |
| `clickup_move_task` | Move task to a different list |
| `clickup_get_task_comments` | Get task comments |
| `clickup_create_task_comment` | Add a comment to a task |
| `clickup_get_doc_page` | Get a single page from a Doc (v3) |
| `clickup_attach_task_file` | Upload a file (e.g. an image) as an attachment on a task |
| `clickup_create_comment_with_image` | Upload a file and post it inline inside a new task comment, in one call |
| `clickup_list_rocks_for_org` | List all EOS Rocks (quarterly goals) org-wide in one call, normalized to a fixed status enum |

### Finding a person's ClickUp user ID

`clickup_get_workspaces` already passes through ClickUp's native `GET /team`
response unmodified, which includes each workspace's member list
(`teams[].members[].user.{id,username,email}`) — so no new data source was
needed. `clickup_list_members` is a thin, purpose-built projection of that
same data (flattened to id/username/email/team_id/role) so callers don't
have to dig the member list out of the full workspace/team object
themselves. `clickup_list_tasks_for_person` uses the same underlying lookup
internally to resolve `email` -> `user_id`.

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
  unconfirmed business-logic assumption, so it isn't done here).
- **`measurable`**: no dedicated field exists on this list. Falls back to
  the task description; `null` if that's empty too (never fabricated).
- **`weekly_status`**: no structured source was found anywhere (not a
  custom field, nothing comment-derived either) — always returned as `[]`.
  If the org starts tracking this in ClickUp some other way, revisit.

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
