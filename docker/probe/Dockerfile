# The PC probe in a container (D50): the same `escapadinha probe` as on Windows, with Google
# Chrome for Linux on a virtual display (Xvfb: headed, not headless; nothing hidden from the
# sites, only from Miguel's desktop). The code is baked in: rebuild after a change
# (`docker compose -f docker/probe/compose.yaml build`); the profile lives in a volume mounted
# at /root/.pontonomada (the CLI's default profile_dir is ~/.pontonomada/probe-chrome); the R2
# keys come from .env at run time (compose `env_file`), never into the image.
FROM python:3.14-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PYTHONIOENCODING=utf-8 \
    TZ=Europe/Lisbon

WORKDIR /app

# Dependencies first (cached until the lock changes), then Chrome and the virtual display.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth curl ca-certificates gnupg \
    && uv run --no-sync playwright install --with-deps chrome \
    && rm -rf /var/lib/apt/lists/*

# The project itself (see .dockerignore: no .env, data/, output/, node_modules, .venv).
COPY . .
RUN uv sync --frozen --no-dev

# `docker compose run --rm probe <setup|run|status>`: a visible Chrome on the virtual screen.
ENTRYPOINT ["xvfb-run", "-a", "--server-args=-screen 0 1280x900x24", \
            "uv", "run", "--no-sync", "escapadinha", "probe"]
CMD ["status"]
