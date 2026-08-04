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

## Available Tools (25)

| Tool | Description |
|------|-------------|
| `clickup_get_workspaces` | List all workspaces/teams |
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
| `clickup_search_tasks` | Search tasks with filters |
| `clickup_create_task` | Create a task |
| `clickup_update_task` | Update a task |
| `clickup_delete_task` | Delete a task |
| `clickup_move_task` | Move task to a different list |
| `clickup_get_task_comments` | Get task comments |
| `clickup_create_task_comment` | Add a comment to a task |
| `clickup_get_doc_page` | Get a single page from a Doc (v3) |
| `clickup_attach_task_file` | Upload a file (e.g. an image) as an attachment on a task |
| `clickup_create_comment_with_image` | Upload a file and post it inline inside a new task comment, in one call |

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
