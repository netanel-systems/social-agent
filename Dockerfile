# Dockerfile for the Nathan Dashboard Server
# Serves the public dashboard for monitoring the agent.
#
# Auto-discovers active sandbox from nathan-brain repository.
#
# Build:  docker build -t nathan-dashboard .
# Run:    docker run -p 8080:8080 \
#           -e E2B_API_KEY=... \
#           -e DASHBOARD_TOKEN=... \
#           -e GITHUB_TOKEN=... \
#           nathan-dashboard
#
# Environment variables:
#   E2B_API_KEY       - E2B API key for sandbox communication
#   DASHBOARD_TOKEN   - Admin token for kill/inject actions
#   GITHUB_TOKEN      - GitHub token for nathan-brain access
#   PORT              - Server port (default: 8080)
#   BRAIN_REPO_URL    - nathan-brain repo URL (default: https://github.com/netanel-systems/nathan-brain.git)
#   BRAIN_REPO_PATH   - Path to clone nathan-brain (default: /app/nathan-brain)

FROM python:3.12-slim

WORKDIR /app

# Install git for nathan-brain cloning
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dashboard dependencies only (minimal, no netanel-core)
COPY requirements-dashboard.txt .
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -r requirements-dashboard.txt && \
    pip install --no-cache-dir --no-deps -e .

# Environment variables for nathan-brain
ENV BRAIN_REPO_URL=https://github.com/netanel-systems/nathan-brain.git
ENV BRAIN_REPO_PATH=/app/nathan-brain
ENV PORT=8080

# Create unprivileged user for runtime
RUN groupadd --system app && useradd --system --gid app --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8080

# Entrypoint: clone nathan-brain if needed, then start server
CMD set -e && \
    if [ ! -d "$BRAIN_REPO_PATH" ]; then \
        echo "Cloning nathan-brain..."; \
        git clone "https://${GITHUB_TOKEN}@github.com/netanel-systems/nathan-brain.git" "$BRAIN_REPO_PATH"; \
    else \
        echo "nathan-brain already exists"; \
    fi && \
    python -m social_agent serve --brain-repo "$BRAIN_REPO_PATH" --port "${PORT}"
