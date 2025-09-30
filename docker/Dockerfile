# Define base image build arguments (must be before any FROM)
ARG REPO_OWNER=dispatcharr
ARG REPO_NAME=dispatcharr
ARG BASE_TAG=base

# --- Build frontend ---

FROM node:24 AS frontend-builder
ARG TARGETOS=linux
ARG TARGETARCH=amd64
WORKDIR /app/frontend
COPY ./frontend /app/frontend
RUN set -eux; \
    # remove any node_modules that may have been copied from the host (x86)
    rm -rf node_modules || true; \
    # When building under emulation (buildx qemu) ensure npm downloads
    # the esbuild binary for the target platform rather than the host.
    # Also increase Node's memory for the build to avoid EPIPE/OOM
    export NODE_OPTIONS="--max-old-space-size=4096"; \
    # If TARGETOS/TARGETARCH are provided by buildx, use those so this Dockerfile
    # is multi-arch friendly; otherwise fall back to linux/amd64 defaults.
    npm_config_platform="$TARGETOS" npm_config_arch="$TARGETARCH" npm install --no-audit --progress=false; \
    # Run build with the increased memory setting in the environment
    NODE_OPTIONS="$NODE_OPTIONS" npm run build; \
    rm -rf node_modules .cache

# --- Redeclare build arguments for the next stage ---
ARG REPO_OWNER
ARG REPO_NAME
ARG BASE_TAG

# --- Final image based on the dynamic base ---
FROM ghcr.io/${REPO_OWNER}/${REPO_NAME}:${BASE_TAG} AS final
ENV VIRTUAL_ENV=/dispatcharrpy
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

# Copy application code
COPY . /app
# Copy nginx configuration
COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default
# Clean out existing frontend folder
RUN rm -rf /app/frontend
# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Run Django collectstatic
RUN python manage.py collectstatic --noinput

# Add timestamp argument
ARG TIMESTAMP

# Update version.py with build timestamp if provided
RUN if [ -n "$TIMESTAMP" ]; then \
    echo "Updating timestamp to ${TIMESTAMP} in version.py" && \
    sed -i "s|__timestamp__ = None.*|__timestamp__ = '${TIMESTAMP}'    # Set during CI/CD build process|" /app/version.py && \
    cat /app/version.py; \
    fi

ENTRYPOINT ["/app/docker/entrypoint.sh"]