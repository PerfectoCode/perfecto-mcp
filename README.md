![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/perfectocode/perfecto-mcp/total?style=for-the-badge&link=https%3A%2F%2Fgithub.com%2FBlazemeter%2Fbzm-mcp%2Freleases)
[![GHCR Pulls](https://ghcr-badge.elias.eu.org/shield/PerfectoCode/perfecto-mcp/perfecto-mcp?style=for-the-badge)](https://github.com/PerfectoCode/perfecto-mcp/pkgs/container/perfecto-mcp)

---

# Perfecto MCP Server

The Perfecto MCP Server connects AI tools directly to Perfecto's cloud-based testing platform. This gives AI agents, assistants, and chatbots the ability to manage complete testing workflows from creation to execution and reporting. All through natural language interactions.

## Use Cases

- **Cross-Platform Device Testing**: Validate applications on real, virtual, and desktop devices

- **Live Test Monitoring**: Track execution status and intervene in real time

- **Execution History Analysis**: Review and filter past test runs for trends and troubleshooting

- **Automated Test Management**: Integrate device and execution operations into CI/CD workflows

- **Centralized Device Inventory**: Maintain an up-to-date catalog of available testing devices

- **In-Platform Troubleshooting**: Access help content and command references directly within the platform

This MCP server essentially transforms Perfecto's enterprise-grade  testing platform into an AI-accessible service, enabling intelligent automation of complex testing workflows that would typically require significant manual intervention and knowledge.

---

## Prerequisites

- Perfecto Security Token
- Compatible MCP host (VS Code, Claude Desktop, Cursor, Windsurf, etc.)
- Docker (only for Docker-based deployment)
- [uv](https://docs.astral.sh/uv/) and Python 3.11+ (only for installation from source code distribution)

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

> [!IMPORTANT]
> For macOS: You may encounter a security alert saying "Apple could not verify 'perfecto-mcp-darwin' is free of malware." To resolve this:
> 1. Go to **System Settings** → **Privacy & Security** → **Security**
> 2. Look for the blocked application and click **"Allow Anyway"**
> 3. Try running the binary again

![CLI Demo](/docs/cli-tool.gif)

---

**Manual Client Configuration (Binary Installation)**

1. **Download the binary** for your operating system from the [Releases](https://github.com/PerfectoCode/perfecto-mcp/releases) page
2. **Configure your MCP client** with the following settings:

```json
{
  "mcpServers": {
    "Perfecto MCP": {
      "command": "/path/to/perfecto-mcp-binary",
      "args": ["--mcp"],
      "env": {
        "PERFECTO_CLOUD_NAME": "Set the cloud name value here"
      }
    }
  }
}
```
---

**Manual Client Configuration (From Remote Source Code)**

1. **Prerequisites:** [uv](https://docs.astral.sh/uv/) and Python 3.11+
2. **Configure your MCP client** with the following settings:

```json
{
  "mcpServers": {
    "Perfecto MCP": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/PerfectoCode/perfecto-mcp.git@v1.0",
        "-q", "perfecto-mcp", "--mcp"
      ],
      "env": {
        "PERFECTO_CLOUD_NAME": "Set the cloud name value here"
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

**Docker MCP Client Configuration**

```json
{
  "mcpServers": {
    "Docker Perfecto MCP": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "PERFECTO_CLOUD_NAME=your_cloud_name",
        "-e",
        "PERFECTO_SECURITY_TOKEN=your_security_token",
        "ghcr.io/PerfectoCode/perfecto-mcp:latest"
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
        "ghcr.io/PerfectoCode/perfecto-mcp:latest"
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

## Available Tools

The Perfecto MCP Server provides comprehensive access to Perfecto's API through four main tools:
TODO:

| Tool          | Purpose           | Key Capabilities                                                                                         |
|---------------|-------------------|----------------------------------------------------------------------------------------------------------|
| **User**      | User Information  | Get current user details                                                                                 |
| **Devices**   | Device Management | Lists real, virtual, and browser devices required for use with RemoteWebDriver (selenium capabilities)   |
| **Execution** | Test Execution    | Live view of running devices (Live Stream), View reports with search capabilities (Report Library)       |
| **Help**      | Help Management   | Allows you to list or search for command capabilities and other information in the Perfecto help system. |

---

### **User Management**
**What it does:** Get information about your Perfecto account and default settings.

| Action | What you get |
|--------|-------------|
| Get user info | Read current user details from Perfecto |

**When to use:** Start here to get your user information.

---

### **Device Management**
**What it does:** Lists real, virtual, and browser devices required for use with RemoteWebDriver (selenium capabilities) .

| Action | What you get                                              |
|--------|-----------------------------------------------------------|
| Selenium Grid Info | Retrieve main Selenium Grid details, including URLs for Selenium and Appium |
| Real Device Listing | List all available real devices (iOS/Android, mobile/tablet) |
| Real Device Details | Read comprehensive information for a specific real device |
| Virtual Device Listing | List all available virtual devices (iOS Simulators, Android Emulators) |
| Desktop Device Listing | List all available desktop browser devices |

**When to use:** When you need to know what devices area available to use

---

### **Test Execution**
**What it does:** Live view of running devices (Live Stream), View reports with search capabilities (Report Library).

| Action | What you get |
|--------|-------------|
| Live Execution Listing | List all ongoing executions (mobile, tablet, desktop browser) |
| Execution Control | Stop one or more live executions by ID |
| Execution History | List finished executions with advanced filtering (by device, OS, platform, browser, job, trigger, tag, owner, OS version, failure reason, and time frame) |
| Report Name Listing | List all available report names for executions |
| Filter Value Discovery | Retrieve valid filter values for execution queries (device IDs, OS, browsers, etc.) |

**When to use:** When you need to see what is running or the result of completed runs.

---

### **Help Management**
**What it does:** Allows you to list or search for command capabilities and other information in the Perfecto help system.

| Action | What you get                                                        |
|--------|---------------------------------------------------------------------|
| Help Category Listing | List all help categories and their subcategories                    |
| Help Content Discovery | List all help topics within a category and subcategory              |
| Help Content Reading | Retrieve detailed help content by category, subcategory, and topic  |
| Extended Command Listing | List all supported extended RemoteWebDriver commands (Perfecto function references)  |
| Extended Command Details | Read comprehensive information for a specific extended command  |

**When to use:** When you need to know the parameters to be used in automation scripts or know details about the platform.

---

## License

This project is licensed under the Apache License, Version 2.0. Please refer to [LICENSE](./LICENSE) for the full terms.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/PerfectoCode/perfecto-mcp/issues)
- **Support**: Contact Perfecto support for enterprise assistance