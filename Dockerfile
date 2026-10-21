# syntax=docker/dockerfile:1

# deps: resolve wheels for the *target* architecture on the *build* host, so
# multi-arch builds never run pip under QEMU. Wheels only: a dependency without
# cp314 manylinux wheels for both amd64 and arm64 fails the build.
FROM --platform=$BUILDPLATFORM python:3.14-slim AS deps
ARG TARGETARCH
WORKDIR /build
COPY requirements.txt .
RUN case "$TARGETARCH" in \
        amd64) a=x86_64 ;; \
        arm64) a=aarch64 ;; \
        *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && pip install --no-cache-dir --disable-pip-version-check \
        --only-binary=:all: \
        --implementation cp \
        --python-version "$(python -c 'import sys;print("%d.%d"%sys.version_info[:2])')" \
        --platform manylinux2014_$a \
        --platform manylinux_2_17_$a \
        --platform manylinux_2_28_$a \
        --platform manylinux_2_34_$a \
        --target /deps \
        -r requirements.txt

# base: shared runtime layer (non-root user, dependencies, healthcheck)
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/deps \
    PORT=5001
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /app /app/data
WORKDIR /app
COPY --from=deps /deps /deps
EXPOSE 5001
# hadolint ignore=DL3025
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','5001'), timeout=4)"

# dev: test tools and hot reload; the code arrives through a bind mount
FROM base AS dev
COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements-dev.txt
USER 1000:1000
# hadolint ignore=DL3025
CMD ["sh", "-c", "exec python -m uvicorn --factory app:create_app --host 0.0.0.0 --port \"$PORT\" --reload"]

# runtime: the default (last) stage
FROM base AS runtime
# pip is not needed at runtime; dropping it clears Trivy findings in its vendored libs
RUN python -m pip uninstall -y pip
COPY . .
USER 1000:1000
# hadolint ignore=DL3025
CMD ["sh", "-c", "exec python -m uvicorn --factory app:create_app --host 0.0.0.0 --port \"${PORT:-5001}\""]
