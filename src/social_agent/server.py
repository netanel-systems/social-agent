"""Dashboard API server for external monitoring and control.

REST endpoints served by Python's http.server (stdlib, zero deps).
See ARCHITECTURE.md Section 7.4 for endpoint specification.

Public endpoints: read-only status, activity, stats, heartbeat.
Admin endpoints: kill switch, rule injection (require DASHBOARD_TOKEN).

Usage:
    server = DashboardServer(sandbox_id="sbx_123", port=8080)
    server.start()   # Starts in background thread
    server.stop()    # Graceful shutdown
"""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path as _PathLib
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from social_agent.control import SandboxController
from social_agent.dashboard import build_dashboard, compute_action_stats, load_activity_log

if TYPE_CHECKING:
    from pathlib import Path

    from social_agent.cost import CostTracker

# Resolve the static files directory at import time.
_STATIC_DIR = _PathLib(__file__).parent / "static"

logger = logging.getLogger("social_agent.server")

# Max activity records returned per request.
_MAX_ACTIVITY_LIMIT = 200
_DEFAULT_ACTIVITY_LIMIT = 50
# Max request body size (64KB — ample for rule injection).
_MAX_BODY_SIZE = 65536


class _RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard API.

    Route dispatch is done via a path-to-handler mapping.
    Admin routes check the Authorization header against DASHBOARD_TOKEN.
    """

    # Set by DashboardServer via partial()
    sandbox_id: str
    controller: SandboxController
    cost_tracker: CostTracker | None
    dashboard_token: str
    state_path: Path
    activity_log_path: Path
    heartbeat_path: Path

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Route http.server logs through our logger."""
        logger.debug(format, *args)

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET requests — API routes, static files, and index."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # API routes
        routes: dict[str, Any] = {
            "/api/status": self._handle_status,
            "/api/activity": self._handle_activity,
            "/api/stats": self._handle_stats,
            "/api/heartbeat": self._handle_heartbeat,
            "/api/cost": self._handle_cost,
        }

        handler = routes.get(path)
        if handler is not None:
            handler()
            return

        # Index page
        if path == "/":
            self._serve_static_file("index.html")
            return

        # Static files: /static/<filename>
        if path.startswith("/static/"):
            filename = path[len("/static/"):]
            self._serve_static_file(filename)
            return

        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests (admin actions)."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        routes: dict[str, Any] = {
            "/api/kill": self._handle_kill,
            "/api/inject-rule": self._handle_inject_rule,
        }

        handler = routes.get(path)
        if handler is None:
            self._send_json({"error": "Not found"}, status=404)
            return

        # Admin auth check
        if not self._check_admin_auth():
            return

        handler()

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    # --- Public endpoints ---

    def _handle_status(self) -> None:
        """GET /api/status — Agent state + health + sandbox info."""
        health = self.controller.check_health(self.sandbox_id)
        state = self.controller.read_state(self.sandbox_id)

        self._send_json({
            "sandbox_id": self.sandbox_id,
            "health": {
                "status": health.status.value,
                "last_heartbeat": health.last_heartbeat,
                "current_action": health.current_action,
                "seconds_since_heartbeat": health.seconds_since_heartbeat,
                "error": health.error,
            },
            "state": state,
        })

    def _handle_activity(self) -> None:
        """GET /api/activity?limit=50 — Recent activity records."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        limit_str = params.get("limit", [str(_DEFAULT_ACTIVITY_LIMIT)])[0]

        try:
            limit = min(int(limit_str), _MAX_ACTIVITY_LIMIT)
        except ValueError:
            limit = _DEFAULT_ACTIVITY_LIMIT

        if limit <= 0:
            limit = _DEFAULT_ACTIVITY_LIMIT

        records = self.controller.read_activity(
            self.sandbox_id, last_n=limit
        )
        self._send_json({
            "records": records,
            "count": len(records),
            "limit": limit,
        })

    def _handle_stats(self) -> None:
        """GET /api/stats — Aggregated action statistics."""
        records = load_activity_log(self.activity_log_path)
        stats_by_action = compute_action_stats(records)
        dashboard = build_dashboard(
            state_path=self.state_path,
            log_path=self.activity_log_path,
        )

        # Aggregate across all actions
        total_actions = sum(s.total for s in stats_by_action.values())
        total_successes = sum(s.successes for s in stats_by_action.values())
        quality_scores = [
            s.avg_quality
            for s in stats_by_action.values()
            if s.avg_quality > 0
        ]
        success_rate = (
            (total_successes / total_actions * 100)
            if total_actions > 0
            else 0.0
        )
        avg_quality = (
            sum(quality_scores) / len(quality_scores)
            if quality_scores
            else 0.0
        )

        self._send_json({
            "total_actions": total_actions,
            "success_rate": round(success_rate, 1),
            "avg_quality": round(avg_quality, 2),
            "action_counts": {
                name: s.total for name, s in stats_by_action.items()
            },
            "dashboard": {
                "cycle_count": dashboard.cycle_count,
                "posts_today": dashboard.posts_today,
                "replies_today": dashboard.replies_today,
            },
        })

    def _handle_heartbeat(self) -> None:
        """GET /api/heartbeat — Last heartbeat + health status."""
        health = self.controller.check_health(self.sandbox_id)
        self._send_json({
            "sandbox_id": self.sandbox_id,
            "status": health.status.value,
            "last_heartbeat": health.last_heartbeat,
            "current_action": health.current_action,
            "seconds_since_heartbeat": health.seconds_since_heartbeat,
            "error": health.error,
        })

    def _handle_cost(self) -> None:
        """GET /api/cost — Cost tracking + budget remaining."""
        if self.cost_tracker is None:
            self._send_json({
                "configured": False,
                "total_cost_usd": 0.0,
                "budget_limit_usd": 0.0,
                "budget_remaining_usd": 0.0,
                "within_budget": True,
                "alert_triggered": False,
                "summary": {},
            })
            return

        summary = self.cost_tracker.daily_summary()
        self._send_json({
            "configured": True,
            "total_cost_usd": self.cost_tracker.total_cost_usd,
            "budget_limit_usd": self.cost_tracker.budget_limit_usd,
            "budget_remaining_usd": self.cost_tracker.budget_remaining_usd,
            "within_budget": self.cost_tracker.within_budget,
            "alert_triggered": self.cost_tracker.alert_triggered,
            "summary": summary,
        })

    # --- Admin endpoints ---

    def _handle_kill(self) -> None:
        """POST /api/kill — Kill the sandbox."""
        result = self.controller.kill(self.sandbox_id)
        self._send_json({
            "killed": result,
            "sandbox_id": self.sandbox_id,
        })

    def _handle_inject_rule(self) -> None:
        """POST /api/inject-rule — Inject a rule into DOS.md."""
        body = self._read_body()
        if body is None:
            return

        rule = body.get("rule")
        if not rule or not isinstance(rule, str):
            self._send_json(
                {"error": "Missing or invalid 'rule' field"},
                status=400,
            )
            return

        self.controller.inject_rule(self.sandbox_id, rule)
        self._send_json({
            "injected": True,
            "rule": rule,
            "sandbox_id": self.sandbox_id,
        })

    # --- Static files ---

    def _serve_static_file(self, filename: str) -> None:
        """Serve a file from the static/ directory.

        Security: only serves files directly inside _STATIC_DIR.
        Path traversal (../) is blocked by resolving and checking
        that the result is still within the static directory.
        """
        # Reject path traversal attempts
        if ".." in filename or filename.startswith("/"):
            self._send_json({"error": "Not found"}, status=404)
            return

        file_path = (_STATIC_DIR / filename).resolve()

        # Ensure the resolved path is still inside _STATIC_DIR
        try:
            file_path.relative_to(_STATIC_DIR.resolve())
        except ValueError:
            self._send_json({"error": "Not found"}, status=404)
            return

        if not file_path.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            body = file_path.read_bytes()
        except OSError:
            self._send_json({"error": "Internal server error"}, status=500)
            return

        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Cache static assets for 5 minutes (browser refresh friendly)
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    # --- Helpers ---

    def _check_admin_auth(self) -> bool:
        """Verify admin token. Returns True if authorized."""
        if not self.dashboard_token:
            self._send_json(
                {"error": "Admin actions disabled (no DASHBOARD_TOKEN configured)"},
                status=403,
            )
            return False

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json({"error": "Unauthorized"}, status=401)
            return False

        token = auth_header[len("Bearer "):]
        if not secrets.compare_digest(token, self.dashboard_token):
            self._send_json({"error": "Unauthorized"}, status=401)
            return False

        return True

    def _read_body(self) -> dict[str, Any] | None:
        """Read and parse JSON request body.

        Rejects bodies larger than _MAX_BODY_SIZE (64KB) to prevent
        memory exhaustion from oversized payloads.
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json({"error": "Empty request body"}, status=400)
            return None

        if content_length > _MAX_BODY_SIZE:
            self._send_json(
                {"error": f"Request body too large (max {_MAX_BODY_SIZE} bytes)"},
                status=413,
            )
            return None

        try:
            raw = self.rfile.read(content_length)
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "Invalid JSON body"}, status=400)
            return None

    def _send_json(
        self,
        data: dict[str, Any],
        *,
        status: int = 200,
    ) -> None:
        """Send a JSON response with CORS headers."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        """Add CORS headers to allow browser access."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization",
        )


class DashboardServer:
    """Dashboard API server wrapping HTTPServer.

    Runs in a background thread. Start/stop from the main thread.

    Args:
        sandbox_id: ID of the sandbox to monitor.
        controller: SandboxController for E2B operations.
        cost_tracker: CostTracker for cost data (optional).
        state_path: Path to local state.json.
        activity_log_path: Path to local activity.jsonl.
        heartbeat_path: Path to local heartbeat.json.
        dashboard_token: Admin token for kill/inject actions.
        port: Port to serve on (default: 8080).
        host: Host to bind to (default: 0.0.0.0).
    """

    def __init__(
        self,
        *,
        sandbox_id: str,
        controller: SandboxController | None = None,
        cost_tracker: CostTracker | None = None,
        state_path: Path | None = None,
        activity_log_path: Path | None = None,
        heartbeat_path: Path | None = None,
        dashboard_token: str = "",
        port: int = 8080,
        host: str = "0.0.0.0",  # noqa: S104
    ) -> None:
        from pathlib import Path as _Path

        self._sandbox_id = sandbox_id
        self._controller = controller or SandboxController()
        self._cost_tracker = cost_tracker
        self._state_path = state_path or _Path("state.json")
        self._activity_log_path = activity_log_path or _Path("logs/activity.jsonl")
        self._heartbeat_path = heartbeat_path or _Path("heartbeat.json")
        self._dashboard_token = dashboard_token
        self._port = port
        self._host = host
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._server is not None and self._thread is not None

    @property
    def port(self) -> int:
        """Server port.

        When the server is running, returns the actual bound port
        (useful when initialized with port=0 to let the OS pick).
        Otherwise returns the configured port.
        """
        if self._server is not None:
            return self._server.server_address[1]
        return self._port

    def _make_handler(self) -> type[_RequestHandler]:
        """Create a request handler class with bound config."""
        sandbox_id = self._sandbox_id
        controller = self._controller
        cost_tracker = self._cost_tracker
        dashboard_token = self._dashboard_token
        state_path = self._state_path
        activity_log_path = self._activity_log_path
        heartbeat_path = self._heartbeat_path

        class BoundHandler(_RequestHandler):
            pass

        BoundHandler.sandbox_id = sandbox_id  # type: ignore[attr-defined]
        BoundHandler.controller = controller  # type: ignore[attr-defined]
        BoundHandler.cost_tracker = cost_tracker  # type: ignore[attr-defined]
        BoundHandler.dashboard_token = dashboard_token  # type: ignore[attr-defined]
        BoundHandler.state_path = state_path  # type: ignore[attr-defined]
        BoundHandler.activity_log_path = activity_log_path  # type: ignore[attr-defined]
        BoundHandler.heartbeat_path = heartbeat_path  # type: ignore[attr-defined]
        return BoundHandler

    def start(self) -> None:
        """Start the server in a background thread."""
        if self._server is not None:
            return

        handler_class = self._make_handler()
        self._server = HTTPServer((self._host, self._port), handler_class)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="dashboard-server",
        )
        self._thread.start()
        logger.info(
            "Dashboard server started on %s:%d", self._host, self._port
        )

    def stop(self) -> None:
        """Stop the server gracefully."""
        if self._server is None:
            return

        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server.server_close()
        self._server = None
        self._thread = None
        logger.info("Dashboard server stopped")

    def wait(self, timeout: float | None = None) -> None:
        """Block until the server stops.

        Provides a public API for blocking on the server thread,
        avoiding direct access to the private _thread attribute.
        """
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def __enter__(self) -> DashboardServer:
        """Context manager: start server."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager: stop server."""
        self.stop()
