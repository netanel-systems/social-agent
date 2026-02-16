# Dockerfile for the Nathan Dashboard Server
# Serves the public dashboard for monitoring the agent.
#
# Build:  docker build -t nathan-dashboard .
# Run:    docker run -p 8080:8080 \
#           -e E2B_API_KEY=... \
#           -e DASHBOARD_TOKEN=... \
#           -e SANDBOX_ID=sbx_... \
#           nathan-dashboard
#
# Environment variables:
#   E2B_API_KEY       - E2B API key for sandbox communication
#   DASHBOARD_TOKEN   - Admin token for kill/inject actions
#   SANDBOX_ID        - Sandbox ID to monitor (REQUIRED)
#   PORT              - Server port (default: 8080)

FROM python:3.12-slim

WORKDIR /app

# Install the package
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Default port
ENV PORT=8080

EXPOSE 8080

# Start the dashboard server — SANDBOX_ID must be set at runtime
CMD python -m social_agent serve "${SANDBOX_ID}" --port "${PORT}"
