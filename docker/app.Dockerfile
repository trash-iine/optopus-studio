# syntax=docker/dockerfile:1
# An app's image (docs/adr/0010): `optopus-studio image <package.zip>` builds it, passing the
# package as the build context "package". The studio is installed without the agent, and the
# package's Rust port, if any, is built here so the image needs no cargo.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*
# optopus is built from optopus-py's git source (maturin), and a Rust port with cargo.
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE-MIT LICENSE-APACHE ./
RUN uv sync --frozen --no-default-groups --no-install-project
COPY src/ src/
COPY workers/rust/Cargo.toml workers/rust/Cargo.lock workers/rust/
COPY workers/rust/src/ workers/rust/src/
RUN uv sync --frozen --no-default-groups
COPY --from=package package.zip /opt/optopus-app/package.zip
RUN OPTOPUS_STUDIO_HOME=/tmp/prepare OPTOPUS_STUDIO_RUST_DIR=/opt/optopus-app/rust \
    .venv/bin/optopus-studio app /opt/optopus-app/package.zip --prepare \
    && rm -rf /tmp/prepare /opt/optopus-app/rust/crates /opt/optopus-app/rust/target

FROM ${PYTHON_IMAGE}
ARG OPTOPUS_APP_IMAGE
ARG SELF_TEST=1
RUN useradd --create-home --uid 1000 app && mkdir /data && chown app /data
WORKDIR /app
COPY --from=build /app/.venv .venv/
COPY --from=build /app/src src/
# The port's binary is found by a hash of these, so they come along; cargo does not.
COPY --from=build /app/workers/rust/Cargo.toml workers/rust/
COPY --from=build /app/workers/rust/src workers/rust/src/
COPY --from=build /opt/optopus-app /opt/optopus-app
COPY --from=frontend /app/frontend/dist frontend/dist/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    OPTOPUS_STUDIO_HOME=/data \
    OPTOPUS_STUDIO_RUST_DIR=/opt/optopus-app/rust \
    OPTOPUS_APP_IMAGE=${OPTOPUS_APP_IMAGE}
# Solve the packaged data once, as the image's user would, before the image is handed over.
RUN test -f frontend/dist/index.html \
    && if [ "$SELF_TEST" = 1 ]; then \
        OPTOPUS_STUDIO_HOME=/tmp/self-test optopus-studio app /opt/optopus-app/package.zip \
            --self-test && rm -rf /tmp/self-test; \
    fi
USER app
VOLUME /data
EXPOSE 8766
CMD ["optopus-studio", "app", "/opt/optopus-app/package.zip", "--host", "0.0.0.0", "--port", "8766"]
