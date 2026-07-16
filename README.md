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

## Available Tools (22)

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

## API Reference

- [ClickUp API v2 Docs](https://developer.clickup.com/reference/getaccesstoken)
