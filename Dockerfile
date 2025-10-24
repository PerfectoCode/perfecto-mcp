# Copyright 2025 Perfecto MCP author
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM ubuntu:25.10

WORKDIR /app

# Install system dependencies for building
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    binutils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN groupadd -r perfecto-mcp && useradd -r -g perfecto-mcp perfecto-mcp

ARG TARGETPLATFORM

# Copy all pre-built binaries
COPY dist/ ./dist/

# Select and copy the appropriate binary based on target platform
RUN echo "Available binaries in dist/:" && ls -la ./dist/ && \
    case "${TARGETPLATFORM}" in \
    "linux/amd64") \
        if [ -f "./dist/perfecto-mcp-linux-amd64" ]; then \
            echo "Using Linux AMD64 binary"; \
            cp ./dist/perfecto-mcp-linux-amd64 ./perfecto-mcp; \
        else \
            echo "ERROR: Linux AMD64 binary not found. Available binaries:"; \
            ls -la ./dist/; \
            echo "Please build Linux binaries first with: DOCKER_BUILD=true uv run python build.py"; \
            exit 1; \
        fi ;; \
    "linux/arm64") \
        if [ -f "./dist/perfecto-mcp-linux-arm64" ]; then \
            echo "Using Linux ARM64 binary"; \
            cp ./dist/perfecto-mcp-linux-arm64 ./perfecto-mcp; \
        else \
            echo "ERROR: Linux ARM64 binary not found. Available binaries:"; \
            ls -la ./dist/; \
            echo "Please build Linux binaries first with: DOCKER_BUILD=true uv run python build.py"; \
            exit 1; \
        fi ;; \
    *) echo "Unsupported platform: ${TARGETPLATFORM}. Supported: linux/amd64, linux/arm64" && exit 1 ;; \
    esac && \
    echo "Selected binary for platform: ${TARGETPLATFORM}" && \
    chmod +x ./perfecto-mcp && \
    rm -rf ./dist/

# Create tokens directory and set permissions
RUN mkdir -p /app/tokens && \
    chown -R perfecto-mcp:perfecto-mcp ./perfecto-mcp /app/tokens

# Switch to non-root user
USER perfecto-mcp

ENV PERFECTO_TOKEN_FILE=/app/tokens/token.json
ENV MCP_DOCKER=true

# Command to run the application
ENTRYPOINT ["./perfecto-mcp"]
CMD ["--token-file", "/app/tokens/token.json"]
