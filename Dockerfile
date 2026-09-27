FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv git make ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global @opencode/cli

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python3 -m pip install --break-system-packages --no-cache-dir .

ENTRYPOINT ["codex-free-worker", "stdio"]
