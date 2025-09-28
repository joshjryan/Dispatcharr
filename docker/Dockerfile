# Define base image build arguments (must be before any FROM)
ARG REPO_OWNER=dispatcharr
ARG REPO_NAME=dispatcharr
ARG BASE_TAG=base

# --- Build frontend ---
FROM node:24 AS frontend-builder

# Make builds platform-aware for buildx caching and optional native deps
ARG TARGETPLATFORM
WORKDIR /app/frontend
COPY frontend/package*.json ./
# include platform marker so install layer is different per platform
RUN echo "platform=${TARGETPLATFORM:-$(uname -m)}" > .platform
RUN npm ci --prefer-offline --no-audit --unsafe-perm || (rm -rf node_modules package-lock.json && npm install --unsafe-perm)

# Ensure platform-specific optional native modules are present (rebuild or reinstall if necessary)
RUN npm rebuild || (rm -rf node_modules package-lock.json && npm install --unsafe-perm)

COPY frontend/ ./
RUN npm run build
RUN rm -rf node_modules .cache

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