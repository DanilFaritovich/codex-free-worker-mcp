FROM node:24-bookworm-slim AS node-runtime

RUN npm install --global @opencode/cli @openai/codex

FROM python:3.14-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git make ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/opencode /usr/local/bin/opencode
COPY --from=node-runtime /usr/local/bin/codex /usr/local/bin/codex
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

ENTRYPOINT ["codex-free-worker", "stdio"]
