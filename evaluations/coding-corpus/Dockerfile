FROM python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 AS corpus-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --disable-pip-version-check \
      attrs==26.1.0 \
      jsonschema==4.25.1 \
      jsonschema-specifications==2025.9.1 \
      pytest==9.1.0 \
      referencing==0.37.0 \
      rpds-py==2026.6.3

WORKDIR /workspace/repo
CMD ["sleep", "infinity"]

FROM corpus-base AS aider-builder

ENV UV_PYTHON_INSTALL_DIR=/opt/aider-python \
    UV_CACHE_DIR=/tmp/uv-cache

# The Aider version is exact, while its transitive dependency closure remains
# intentionally non-hermetic for this pilot and must be captured by image digest.
RUN python -m pip install --no-cache-dir --disable-pip-version-check uv==0.12.3 \
    && uv python install 3.12.11 \
    && uv venv --python 3.12.11 /opt/aider \
    && uv pip install --python /opt/aider/bin/python --no-cache aider-chat==0.86.2 \
    && /opt/aider/bin/python -c "import sys; assert sys.version_info[:3] == (3, 12, 11)" \
    && /opt/aider/bin/aider --version \
    && rm -rf /tmp/uv-cache

FROM corpus-base AS aider

COPY --from=aider-builder /opt/aider-python /opt/aider-python
COPY --from=aider-builder /opt/aider /opt/aider

# Keep the verifier-visible runtime at the corpus contract's Python 3.13.5,
# while Aider executes exclusively through /opt/aider/bin/aider on Python 3.12.11.
RUN python -c "import sys; assert sys.version_info[:3] == (3, 13, 5)" \
    && /opt/aider/bin/python -c "import sys; assert sys.version_info[:3] == (3, 12, 11)" \
    && test -x /opt/aider/bin/aider

FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f AS gateway-builder

WORKDIR /build

COPY package.json pnpm-lock.yaml tsconfig.json tsconfig.gateway.json ./
RUN npm install --global pnpm@11.21.0 \
    && pnpm install --frozen-lockfile --ignore-scripts

COPY src ./src
RUN pnpm run build:gateway \
    && pnpm prune --prod

FROM node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f AS gateway

WORKDIR /opt/model-gateway
COPY --from=gateway-builder /build/dist ./dist
COPY --from=gateway-builder /build/node_modules ./node_modules
COPY --from=gateway-builder /build/package.json ./package.json

USER node
ENTRYPOINT ["node", "--no-strip-types", "/opt/model-gateway/dist/gateway-cli.js"]
CMD ["serve"]

# Preserve the original no-target build behavior used by compose.yaml.
FROM corpus-base AS default
