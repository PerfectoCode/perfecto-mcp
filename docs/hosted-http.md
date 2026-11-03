# Hosted HTTP (streamable-http)

Operator and advanced client guide for running Perfecto MCP over HTTP. For the standard local install (binary, uvx, Docker stdio), see the [README](../README.md).

## Client configuration

### Official hosted endpoint

Perfecto hosts a streamable HTTP server at `https://mcp.perfectomobile.com/mcp`.

[![Add to Cursor (HTTP)](https://img.shields.io/badge/Add_to_Cursor-HTTP_install-blue?style=for-the-badge)](https://cursor.com/en-US/install-mcp?name=Perfecto%20MCP&config=eyJ1cmwiOiJodHRwczovL21jcC5wZXJmZWN0b21vYmlsZS5jb20vbWNwIiwiaGVhZGVycyI6eyJBdXRob3JpemF0aW9uIjoiQmVhcmVyIDxzZWN1cml0eVRva2VuPiIsIlBlcmZlY3RvLUNsb3VkLU5hbWUiOiI8Y2xvdWROYW1lPiJ9fQ%3D%3D) [![Add to VS Code (HTTP)](https://img.shields.io/badge/Add_to_VS_Code-HTTP_install-007ACC?style=for-the-badge&logo=visualstudiocode)](https://insiders.vscode.dev/redirect/mcp/install?name=Perfecto%20MCP&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.perfectomobile.com%2Fmcp%22%2C%22headers%22%3A%7B%22Authorization%22%3A%22Bearer%20%3CsecurityToken%3E%22%2C%22Perfecto-Cloud-Name%22%3A%22%3CcloudName%3E%22%7D%7D)

```json
{
  "mcpServers": {
    "Perfecto MCP": {
      "url": "https://mcp.perfectomobile.com/mcp",
      "headers": {
        "Authorization": "Bearer <securityToken>",
        "Perfecto-Cloud-Name": "<cloudName>"
      }
    }
  }
}
```

After installing, replace `<securityToken>` and `<cloudName>`.

### Local server

Configure the MCP client with the server URL, your Perfecto security token as Bearer credentials, and the Perfecto cloud to target:

```json
{
  "mcpServers": {
    "Perfecto MCP": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <securityToken>",
        "Perfecto-Cloud-Name": "<cloudName>"
      }
    }
  }
}
```

### Auth behavior

- Over HTTP, credentials are resolved **per request** from the `Authorization` header.
- Missing or malformed Bearer credentials return `401` before any tool runs.
- Well-formed but wrong security tokens fail later inside Perfecto API calls (same as stdio).
- Stdio / local Docker transport uses the security token file / env vars instead of Bearer auth.

### Cloud name header

- Header: `Perfecto-Cloud-Name`
- Resolution precedence: **`Perfecto-Cloud-Name` header > `PERFECTO_CLOUD_NAME` env var**.
- A missing cloud name is **not** rejected at the auth gate. The request is accepted and tools return the
  usual "Perfecto Environment Cloud Name not set" error, exactly as stdio does. This keeps `401` meaning
  "bad credentials" only.
- Each request resolves its own cloud, so a single server can serve several Perfecto clouds concurrently.

### Health probes

`GET /health` and `GET /healthz` bypass authentication and return `{"status": "ok"}`, for orchestrators and load balancers.

## Local / operator run

Transport resolution precedence: **CLI `--mcp` > `PERFECTO_MCP_TRANSPORT` > stdio**.

```bash
# From source
uv run python main.py --mcp http
# or
PERFECTO_MCP_TRANSPORT=http FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8000 uv run python main.py --mcp

# Container image (stdio by default; pass hosted HTTP env vars)
docker run --rm -p 8000:8000 \
  -e PERFECTO_MCP_TRANSPORT=http \
  -e FASTMCP_HOST=0.0.0.0 \
  -e FASTMCP_PORT=8000 \
  -e FASTMCP_STREAMABLE_HTTP_PATH=/mcp \
  ghcr.io/perfectocode/perfecto-mcp:latest
```

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PERFECTO_MCP_TRANSPORT` | Logical transport: `stdio`, `http`, or `docker` | `stdio` |
| `FASTMCP_HOST` | Bind address (HTTP only) | `127.0.0.1` |
| `FASTMCP_PORT` | Listen port (HTTP only). Also accepts `PORT` (e.g. Cloud Run) | `8000` |
| `FASTMCP_STREAMABLE_HTTP_PATH` | HTTP path for the MCP endpoint | `/mcp` |
| `PERFECTO_CLOUD_NAME` | Fallback cloud when the `Perfecto-Cloud-Name` header is absent | *(unset)* |

## Limitations

- No session storage service: session state is not shared across server instances.
- File upload / local file access is not supported by Perfecto MCP on any transport.
