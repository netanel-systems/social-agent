"""Moltbook API client — all calls execute inside E2B sandbox.

The agent's HTTP interactions with Moltbook happen in the sandbox,
not on the host machine. This is the architecture's safety boundary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import SecretStr

    from social_agent.sandbox import SandboxClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.moltbook.com/api/v1"


# --- Response types ---


@dataclass(frozen=True)
class MoltbookPost:
    """A single post from a submolt feed."""

    id: str
    title: str
    body: str
    submolt: str
    author: str
    upvotes: int = 0
    comments_count: int = 0
    created_at: str = ""


@dataclass(frozen=True)
class FeedResult:
    """Result of reading a submolt feed."""

    posts: list[MoltbookPost] = field(default_factory=list)
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class PostResult:
    """Result of creating a post or reply."""

    post_id: str | None = None
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class EngagementResult:
    """Engagement stats for a post."""

    upvotes: int = 0
    downvotes: int = 0
    comments: int = 0
    views: int = 0
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class RegisterResult:
    """Result of agent registration."""

    api_key: str | None = None
    claim_url: str | None = None
    success: bool = True
    error: str | None = None


@dataclass(frozen=True)
class HeartbeatResult:
    """Result of heartbeat ping."""

    success: bool = True
    error: str | None = None


def _build_http_code(
    method: str,
    path: str,
    api_key: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    """Generate Python code that makes an HTTP request inside E2B.

    The code prints a JSON object with 'status' and 'body' keys,
    or an 'error' key on failure. This is parsed by the caller.

    Note: The API key is embedded in the generated code string. This is
    acceptable because the code only executes inside the E2B sandbox,
    which is ephemeral and isolated. However, avoid logging the generated
    code at DEBUG level to prevent accidental key exposure in log files.
    """
    url = f"{_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    lines = [
        "import httpx, json",
        "try:",
        f"    resp = httpx.{method}(",
        f"        {url!r},",
        f"        headers={headers!r},",
    ]

    if body is not None:
        lines.append(f"        json={body!r},")
    if params is not None:
        lines.append(f"        params={params!r},")

    lines.extend([
        "        timeout=30,",
        "    )",
        "    try:",
        "        data = resp.json()",
        "    except Exception:",
        "        data = resp.text",
        '    print(json.dumps({"status": resp.status_code, "body": data}))',
        "except Exception as e:",
        '    print(json.dumps({"error": str(e)}))',
    ])

    return "\n".join(lines)


def _parse_response(result_text: str | None) -> dict[str, Any]:
    """Parse the JSON output from sandbox execution."""
    if not result_text:
        return {"error": "No output from sandbox"}
    try:
        # Take the last line that looks like JSON (skip any print noise)
        for line in reversed(result_text.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)  # type: ignore[no-any-return]
        return {"error": f"No JSON in output: {result_text[:200]}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}


class MoltbookClient:
    """Moltbook API client. All HTTP calls run inside E2B sandbox.

    Usage::

        client = MoltbookClient(sandbox=sandbox, api_key="molt_xxx")
        feed = client.get_feed("agents", limit=10)
        for post in feed.posts:
            print(post.title)
    """

    def __init__(self, sandbox: SandboxClient, api_key: str | SecretStr) -> None:
        self._sandbox = sandbox
        # Accept both str and SecretStr for flexibility
        self._api_key = (
            api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else api_key
        )

    def _execute(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an HTTP call in the sandbox and return parsed response."""
        code = _build_http_code(method, path, self._api_key, body=body, params=params)
        result = self._sandbox.execute_code(code)

        if not result.success:
            logger.error("Sandbox execution failed: %s", result.error)
            return {"error": result.error or "Sandbox execution failed"}

        # Parse from stdout (printed JSON)
        output = "\n".join(result.stdout) if result.stdout else result.text
        return _parse_response(output)

    def register(self, name: str, description: str) -> RegisterResult:
        """Register agent on Moltbook. Returns API key and claim URL.

        Args:
            name: Agent display name.
            description: Agent description.
        """
        logger.info("Registering agent '%s' on Moltbook", name)
        resp = self._execute(
            "post", "/agents/register", body={"name": name, "description": description}
        )

        if "error" in resp:
            return RegisterResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        body = resp.get("body", {})

        if status not in (200, 201):
            return RegisterResult(success=False, error=f"HTTP {status}: {body}")

        if isinstance(body, dict):
            return RegisterResult(
                api_key=body.get("api_key"),
                claim_url=body.get("claim_url"),
            )
        return RegisterResult(success=False, error=f"Unexpected response: {body}")

    def check_status(self) -> dict[str, Any]:
        """Check agent claim status.

        Returns:
            Dict with 'status' key ('pending_claim' or 'claimed') and other info.
        """
        logger.info("Checking agent status")
        resp = self._execute("get", "/agents/status")
        if "error" in resp:
            return {"status": "unknown", "error": resp["error"]}
        body = resp.get("body", {})
        if isinstance(body, dict):
            return body
        return {"status": "unknown", "error": f"Unexpected response: {body}"}

    def get_feed(self, submolt: str = "", limit: int = 10) -> FeedResult:
        """Read posts from the global feed or a submolt.

        Args:
            submolt: Submolt name to filter by (empty for global feed).
            limit: Max posts to return.
        """
        if submolt:
            logger.info("Reading submolt feed: %s (limit=%d)", submolt, limit)
            resp = self._execute(
                "get", "/posts", params={"submolt": submolt, "sort": "new", "limit": limit}
            )
        else:
            logger.info("Reading global feed (limit=%d)", limit)
            resp = self._execute("get", "/posts", params={"sort": "new", "limit": limit})

        if "error" in resp:
            return FeedResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        body = resp.get("body", [])

        if status != 200:
            return FeedResult(success=False, error=f"HTTP {status}: {body}")

        posts: list[MoltbookPost] = []
        if isinstance(body, list):
            for item in body:
                if isinstance(item, dict):
                    posts.append(MoltbookPost(
                        id=str(item.get("id", "")),
                        title=str(item.get("title", "")),
                        body=str(item.get("body", "")),
                        submolt=submolt,
                        author=str(item.get("author", "")),
                        upvotes=int(item.get("upvotes", 0)),
                        comments_count=int(item.get("comments_count", 0)),
                        created_at=str(item.get("created_at", "")),
                    ))

        return FeedResult(posts=posts)

    def create_post(self, title: str, body: str, submolt: str) -> PostResult:
        """Create an original post in a submolt.

        Args:
            title: Post title (10-120 chars per Moltbook rules).
            body: Post body content.
            submolt: Target submolt.
        """
        if not 10 <= len(title) <= 120:
            return PostResult(
                success=False,
                error=f"Title must be 10-120 chars, got {len(title)}",
            )

        logger.info("Creating post in %s: '%s'", submolt, title[:50])
        resp = self._execute(
            "post",
            "/posts",
            body={"title": title, "body": body, "submolt": submolt},
        )

        if "error" in resp:
            return PostResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        resp_body = resp.get("body", {})

        if status not in (200, 201):
            return PostResult(success=False, error=f"HTTP {status}: {resp_body}")

        post_id = resp_body.get("id") if isinstance(resp_body, dict) else None
        return PostResult(post_id=str(post_id) if post_id else None)

    def reply(self, post_id: str, body: str) -> PostResult:
        """Reply to a post.

        Args:
            post_id: ID of the post to reply to.
            body: Reply content.
        """
        logger.info("Replying to post %s", post_id)
        resp = self._execute("post", f"/posts/{post_id}/comments", body={"body": body})

        if "error" in resp:
            return PostResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        resp_body = resp.get("body", {})

        if status not in (200, 201):
            return PostResult(success=False, error=f"HTTP {status}: {resp_body}")

        comment_id = resp_body.get("id") if isinstance(resp_body, dict) else None
        return PostResult(post_id=str(comment_id) if comment_id else None)

    def get_engagement(self, post_id: str) -> EngagementResult:
        """Get engagement stats for a post.

        Args:
            post_id: Post ID.
        """
        logger.info("Getting engagement for post %s", post_id)
        resp = self._execute("get", f"/posts/{post_id}/engagement")

        if "error" in resp:
            return EngagementResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        body = resp.get("body", {})

        if status != 200:
            return EngagementResult(success=False, error=f"HTTP {status}: {body}")

        if isinstance(body, dict):
            return EngagementResult(
                upvotes=int(body.get("upvotes", 0)),
                downvotes=int(body.get("downvotes", 0)),
                comments=int(body.get("comments", 0)),
                views=int(body.get("views", 0)),
            )
        return EngagementResult(success=False, error=f"Unexpected response: {body}")

    def heartbeat(self) -> HeartbeatResult:
        """Send heartbeat by checking agent status."""
        logger.debug("Sending heartbeat")
        resp = self._execute("get", "/agents/status")

        if "error" in resp:
            return HeartbeatResult(success=False, error=resp["error"])

        status = resp.get("status", 0)
        if status != 200:
            return HeartbeatResult(
                success=False, error=f"HTTP {status}: {resp.get('body')}"
            )

        return HeartbeatResult()
