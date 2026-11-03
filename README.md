![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/perfectocode/perfecto-mcp/total?style=for-the-badge&link=https%3A%2F%2Fgithub.com%2FPerfectoCode%2Fperfecto-mcp%2Freleases)
[![GHCR Pulls](https://ghcr-badge.elias.eu.org/shield/PerfectoCode/perfecto-mcp/perfecto-mcp?style=for-the-badge)](https://github.com/PerfectoCode/perfecto-mcp/pkgs/container/perfecto-mcp)

---

# Perfecto MCP Server

The Perfecto MCP Server connects AI tools directly to Perfecto's cloud-based testing platform. This gives AI agents, assistants, and chatbots the ability to manage complete testing workflows from creation to execution and reporting. All through natural language interactions.

---

## Prerequisites

- Perfecto Security Token
- Compatible MCP host (VS Code, Claude Desktop, Cursor, Windsurf, etc.)

## Setup

### **Get Perfecto Security Token**
1. Follow the [Perfecto Security Token guide](https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/generate_security_tokens.htm) to obtain your Security Token.
2. Save the token into a file named `perfecto-security-token.txt` file in the same folder where you'll place the MCP binary.
> [!IMPORTANT]
> Make sure to locate the binary along with the token file in a safe place.
> It is possible to configure another site for the file location, you can use the environment variable `PERFECTO_SECURITY_TOKEN_FILE` with the full path including the name of the file you want to use.

### **Quick Setup with CLI Tool** ⚡

The easiest way to configure your MCP client is using our interactive CLI tool:

1. **Download the appropriate binary** for your operating system from the [Releases](https://github.com/PerfectoCode/perfecto-mcp/releases) page

> [!NOTE]
> Choose the binary that matches your OS (Windows, macOS, Linux)
2. **Place the binary** in the same folder as your `perfecto-security-token.txt` file
3. **Execute or Double-click the binary** to launch the interactive configuration tool
4. **The tool automatically generates** the JSON configuration file for you
5. **Setup cloud name** in the JSON configuration `PERFECTO_CLOUD_NAME` with the name of your Perfecto Cloud environment. 



https://github.com/user-attachments/assets/10fffeee-b01d-4138-af7a-ea0018471730



---

**Docker MCP Client Configuration**

1. **Prerequisites:** [Docker](https://www.docker.com/products/docker-desktop/)
2. **One-click install** or configure your MCP client manually:

[![Add to Cursor (Docker)](https://img.shields.io/badge/Add_to_Cursor-Docker_install-blue?style=for-the-badge)](https://cursor.com/en-US/install-mcp?name=Perfecto%20MCP&config=eyJjb21tYW5kIjoiZG9ja2VyIiwiYXJncyI6WyJydW4iLCItLXB1bGw9YWx3YXlzIiwiLS1ybSIsIi1pIiwiLWUiLCJQRVJGRUNUT19DTE9VRF9OQU1FIiwiLWUiLCJQRVJGRUNUT19TRUNVUklUWV9UT0tFTiIsImdoY3IuaW8vcGVyZmVjdG9jb2RlL3BlcmZlY3RvLW1jcDpsYXRlc3QiXSwiZW52Ijp7IlBFUkZFQ1RPX0NMT1VEX05BTUUiOiIiLCJQRVJGRUNUT19TRUNVUklUWV9UT0tFTiI6IiJ9fQ%3D%3D) [![Add to VS Code (Docker)](https://img.shields.io/badge/Add_to_VS_Code-Docker_install-007ACC?style=for-the-badge&logo=visualstudiocode)](https://insiders.vscode.dev/redirect/mcp/install?name=Perfecto%20MCP&config=%7B%22command%22%3A%22docker%22%2C%22args%22%3A%5B%22run%22%2C%22--pull%3Dalways%22%2C%22--rm%22%2C%22-i%22%2C%22-e%22%2C%22PERFECTO_CLOUD_NAME%22%2C%22-e%22%2C%22PERFECTO_SECURITY_TOKEN%22%2C%22ghcr.io%2Fperfectocode%2Fperfecto-mcp%3Alatest%22%5D%2C%22env%22%3A%7B%22PERFECTO_CLOUD_NAME%22%3A%22%22%2C%22PERFECTO_SECURITY_TOKEN%22%3A%22%22%7D%7D)

After installing, set `PERFECTO_CLOUD_NAME` and `PERFECTO_SECURITY_TOKEN` in your client's MCP settings.

**Or configure manually** with the following settings:

```json
{
  "mcpServers": {
    "Docker Perfecto MCP": {
      "command": "docker",
      "args": [
        "run",
        "--pull=always",
        "--rm",
        "-i",
        "-e",
        "PERFECTO_CLOUD_NAME=your_cloud_name",
        "-e",
        "PERFECTO_SECURITY_TOKEN=your_security_token",
        "ghcr.io/perfectocode/perfecto-mcp:latest"
      ]
    }
  }
}
```
> [!IMPORTANT]
> For Windows OS, paths must use backslashes (`\`) and be properly escaped as double backslashes (`\\`) in the JSON configuration.
> E.g.: `C:\\User\\Desktop\\mcp_test_folder`

> [!NOTE]
> In order to obtain the `PERFECTO_SECURITY_TOKEN` refere to [Generate a security token](https://help.perfecto.io/perfecto-help/content/perfecto/automation-testing/generate_security_tokens.htm) page

---

**Manual Client Configuration (From Remote Source Code)**

1. **Prerequisites:** [uv](https://docs.astral.sh/uv/) and Python 3.11+
2. **One-click install** or configure your MCP client manually:

[![Add to Cursor (uvx)](https://img.shields.io/badge/Add_to_Cursor-uvx_install-blue?style=for-the-badge)](https://cursor.com/en-US/install-mcp?name=Perfecto%20MCP&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL1BlcmZlY3RvQ29kZS9wZXJmZWN0by1tY3AuZ2l0QHYxLjIuMCIsIi1xIiwicGVyZmVjdG8tbWNwIiwiLS1tY3AiXSwiZW52Ijp7IlBFUkZFQ1RPX0NMT1VEX05BTUUiOiIiLCJQRVJGRUNUT19TRUNVUklUWV9UT0tFTl9GSUxFIjoiIn19) [![Add to VS Code (uvx)](https://img.shields.io/badge/Add_to_VS_Code-uvx_install-007ACC?style=for-the-badge&logo=visualstudiocode)](https://insiders.vscode.dev/redirect/mcp/install?name=Perfecto%20MCP&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22git%2Bhttps%3A%2F%2Fgithub.com%2FPerfectoCode%2Fperfecto-mcp.git%40v1.2.0%22%2C%22-q%22%2C%22perfecto-mcp%22%2C%22--mcp%22%5D%2C%22env%22%3A%7B%22PERFECTO_CLOUD_NAME%22%3A%22%22%2C%22PERFECTO_SECURITY_TOKEN_FILE%22%3A%22%22%7D%7D)

After installing, set `PERFECTO_CLOUD_NAME` and `PERFECTO_SECURITY_TOKEN_FILE` (full path to `perfecto-security-token.txt`) in your client's MCP settings.

**Or configure manually** with the following settings:

```json
{
  "mcpServers": {
    "Perfecto MCP": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/PerfectoCode/perfecto-mcp.git@v1.2.0",
        "-q", "perfecto-mcp", "--mcp"
      ],
      "env": {
        "PERFECTO_CLOUD_NAME": "your_cloud_name",
        "PERFECTO_SECURITY_TOKEN_FILE": "/path/to/perfecto-security-token.txt"
      }
    }
  }
}
```

> [!NOTE]
> uvx installs and runs the package and its dependencies in a temporary environment.
> You can change to any version that has been released or any branch you want. Package support for uvx command is supported from version 1.0 onwards.
> For more details on the uv/uvx arguments used, please refer to the official [uv documentation](https://docs.astral.sh/uv/).

</details>

---

**Custom CA Certificates (Corporate Environments) for Docker**

**When you need this:**
- Your organization uses self-signed certificates
- You're behind a corporate proxy with SSL inspection
- You have a custom Certificate Authority (CA)
- You encounter SSL certificate verification errors when running tests

**Required Configuration:**

When using custom CA certificate bundles, you must configure both:

1. **Certificate Volume Mount**: Mount your custom CA certificate bundle into the container
2. **SSL_CERT_FILE Environment Variable**: Explicitly set the `SSL_CERT_FILE` environment variable to point to the certificate location inside the container

<details><summary><strong>Example Configuration</strong></summary>

```json
{
  "mcpServers": {
    "Docker Perfecto MCP": {
      "command": "docker",
      "args": [
        "run",
        "--pull=always",
        "--rm",
        "-i",
        "-v",
        "/path/to/your/ca-bundle.crt:/etc/ssl/certs/custom-ca-bundle.crt",
        "-e",
        "SSL_CERT_FILE=/etc/ssl/certs/custom-ca-bundle.crt",
        "-e",
        "PERFECTO_CLOUD_NAME=your_cloud_name",
        "-e",
        "PERFECTO_SECURITY_TOKEN=your_security_token",
        "ghcr.io/perfectocode/perfecto-mcp:latest"
      ]
    }
  }
}
```

**Replace:**
- `/path/to/your/ca-bundle.crt` with your host system's CA certificate file path
- The container path `/etc/ssl/certs/custom-ca-bundle.crt` can be any path you prefer (just ensure it matches `SSL_CERT_FILE`)

> The `SSL_CERT_FILE` environment variable must be set to point to your custom CA certificate bundle. The `httpx` library [automatically respects the `SSL_CERT_FILE` environment variable](https://www.python-httpx.org/advanced/ssl/#working-with-ssl_cert_file-and-ssl_cert_dir) for SSL certificate verification.
</details>

---

## Transports

Perfecto MCP runs over **stdio** by default. It can also serve **streamable HTTP**, where credentials are
resolved per request from an `Authorization: Bearer` header and the target cloud from a `Perfecto-Cloud-Name`
header, so one server can serve several users and clouds.

**Hosted streamable HTTP** (`https://mcp.perfectomobile.com/mcp`):

[![Add to Cursor (HTTP)](https://img.shields.io/badge/Add_to_Cursor-HTTP_install-blue?style=for-the-badge)](https://cursor.com/en-US/install-mcp?name=Perfecto%20MCP&config=eyJ1cmwiOiJodHRwczovL21jcC5wZXJmZWN0b21vYmlsZS5jb20vbWNwIiwiaGVhZGVycyI6eyJBdXRob3JpemF0aW9uIjoiQmVhcmVyIDxzZWN1cml0eVRva2VuPiIsIlBlcmZlY3RvLUNsb3VkLU5hbWUiOiI8Y2xvdWROYW1lPiJ9fQ%3D%3D) [![Add to VS Code (HTTP)](https://img.shields.io/badge/Add_to_VS_Code-HTTP_install-007ACC?style=for-the-badge&logo=visualstudiocode)](https://insiders.vscode.dev/redirect/mcp/install?name=Perfecto%20MCP&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.perfectomobile.com%2Fmcp%22%2C%22headers%22%3A%7B%22Authorization%22%3A%22Bearer%20%3CsecurityToken%3E%22%2C%22Perfecto-Cloud-Name%22%3A%22%3CcloudName%3E%22%7D%7D)

After installing, replace `<securityToken>` and `<cloudName>` in the client configuration.

To run your own server:

```bash
perfecto-mcp --mcp http
```

Transport resolution precedence: **CLI `--mcp` > `PERFECTO_MCP_TRANSPORT` > stdio**.

See [docs/hosted-http.md](docs/hosted-http.md) for client configuration, auth behavior, health probes and
environment variables.

---

## OpenTelemetry

Perfecto MCP reports traces and metrics for MCP tool calls using [OpenTelemetry](https://opentelemetry.io/). This gives you visibility into which tools are used, how long they take, and when errors occur.

Telemetry is enabled by default. You do not need to configure anything unless you want to change where data is sent or turn it off.

### Default behavior

By default, telemetry is exported over gRPC to:

`https://grpc.public.prd.shared.perforce.com`

The service is identified as `perfecto-mcp` with the current release version. If telemetry fails to start or export, the MCP server continues to work as usual.

### Turn off telemetry

Add `OTEL_SDK_DISABLED=true` to your MCP client environment:

```json
"env": {
  "OTEL_SDK_DISABLED": "true"
}
```

For Docker, pass it with `-e`:

```json
"-e",
"OTEL_SDK_DISABLED=true"
```

### Send data to your own collector

Use these environment variables to point at a different OpenTelemetry collector (for example, a local one during development):

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector URL | `https://grpc.public.prd.shared.perforce.com` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc`, `http/protobuf`, or `http/json` | `grpc` |

gRPC example (typical local collector on port 4317):

```json
"env": {
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"
}
```

HTTP example (typical local collector on port 4318):

```json
"env": {
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"
}
```

### What gets reported

Each MCP tool call creates:

- **Traces** — one span per call with the tool name, action, MCP client name and version, session ID, and error type when applicable.
- **Metrics** — `mcp.tool.calls` (count) and `mcp.tool.duration` (seconds), broken down by tool and action.

Security tokens and other credentials are not included in telemetry data.

If your MCP client sends `traceparent` or `tracestate` in the request metadata, Perfecto MCP links its spans to that parent trace.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/PerfectoCode/perfecto-mcp/issues)
- **Support**: Contact Perfecto support for enterprise assistance

---

## License

This project is licensed under the Apache License, Version 2.0. Please refer to [LICENSE](./LICENSE) for the full terms.
