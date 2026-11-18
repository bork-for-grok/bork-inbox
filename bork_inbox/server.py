"""Streamable HTTP MCP server for bot-to-bot task inboxes.

The process binds a loopback address only. Every HTTP request must carry a
bearer token that matches exactly one party's token (from the environment).
The matched token selects the role. Tokens are never written to a log.
send_task and check_replies write only under the data directory.
"""

from __future__ import annotations

import contextvars
import hmac
import json
import logging

import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.types import Receive, Scope, Send

from bork_inbox import config, tasks

ENDPOINT = "/mcp"

log = logging.getLogger("bork_inbox")
_role: contextvars.ContextVar[str | None] = contextvars.ContextVar("bork_inbox_role", default=None)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_TASK = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

mcp = MCPServer(
    "bork-inbox",
    version="0.1.0",
    instructions=(
        "A small inbox for messages between bots. "
        "send_task delivers one message from the authenticated bot to one allowed recipient. "
        "check_replies (alias check_inbox) reads only the authenticated bot's unread messages. "
        "whoami returns the caller's party name and allowed recipients. "
        "There is no delete, shell, file, or mail tool."
    ),
)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            return True
        lowered = text.lower()
        if "bearer " in lowered or "authorization:" in lowered or "authorization=" in lowered:
            record.msg = "redacted a log line that contained an authorization header"
            record.args = ()
        return True


def _digest_eq(presented: bytes, expected: bytes) -> bool:
    if not expected:
        return False
    if len(presented) != len(expected):
        hmac.compare_digest(expected, expected)
        return False
    return hmac.compare_digest(presented, expected)


def match_role(presented: bytes) -> str | None:
    """Map bearer token bytes to exactly one party. Never log the bytes."""

    if not presented:
        return None
    matches = [party for party in config.parties() if _digest_eq(presented, config.token_for(party))]
    return matches[0] if len(matches) == 1 else None


def _bearer_bytes(header_value: str) -> bytes:
    if not header_value.lower().startswith("bearer "):
        return b""
    token = header_value[7:].strip()
    if not token:
        return b""
    try:
        return token.encode("utf-8")
    except UnicodeError:
        return b""


def _bearer_from_scope(scope: Scope) -> bytes:
    for key, value in scope.get("headers", []):
        if key.lower() == b"authorization":
            try:
                return _bearer_bytes(value.decode("latin1"))
            except Exception:
                return b""
    return b""


def _live_tokens() -> list[bytes]:
    return [tok for tok in (config.token_for(p) for p in config.parties()) if len(tok) >= config.MIN_TOKEN_LEN]


def _role_from_context(ctx: Context | None) -> str:
    presented = b""
    request = None
    if ctx is not None:
        try:
            request = ctx.request_context.request
        except Exception:
            request = None
    if request is not None:
        try:
            header = request.headers.get("authorization", "")
        except Exception:
            header = ""
        if isinstance(header, str):
            presented = _bearer_bytes(header)
    role = match_role(presented) if presented else None
    if role is None:
        role = _role.get()
    if role not in config.parties():
        raise ToolError("no authenticated role")
    return role


class BearerGate:
    """Reject every HTTP request that lacks a known bearer token.

    Lifespan and other non-HTTP scopes pass through so the MCP session manager
    still starts. A match stores only the party name for this request.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        role = match_role(_bearer_from_scope(scope))
        if role is None:
            body = b'{"error":"unauthorized"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"www-authenticate", b"Bearer"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["bork_inbox_role"] = role
        token = _role.set(role)
        try:
            await self.app(scope, receive, send)
        finally:
            _role.reset(token)


def _task_error(exc: Exception) -> ToolError:
    if isinstance(exc, tasks.TaskError):
        return ToolError(str(exc))
    log.exception("task tool failed")
    return ToolError("task tool failed")


def require_loopback(host: str) -> str:
    """Exit unless the process is asked to bind a loopback address."""

    if host not in config.LOOPBACK_HOSTS:
        raise SystemExit(
            "refusing to bind a non-loopback address; put a TLS reverse proxy or tunnel in front instead"
        )
    return host


@mcp.tool(annotations=_READ_ONLY)
def whoami(ctx: Context | None = None) -> str:
    """Return the authenticated party name and the recipients it may send to."""

    role = _role_from_context(ctx)
    allowed = sorted(recipient for sender, recipient in config.routes() if sender == role)
    return json.dumps({"party": role, "can_send_to": allowed}, ensure_ascii=False)


@mcp.tool(annotations=_TASK)
def send_task(
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    client_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Post one message to one recipient inbox.

    The authenticated bot is the sender. Only configured routes are allowed.
    A client_id makes a retry return the existing message instead of a duplicate.
    """

    role = _role_from_context(ctx)
    try:
        payload = tasks.send_task(
            role=role,
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            client_id=client_id,
            live_tokens=_live_tokens(),
        )
    except tasks.TaskError as exc:
        raise _task_error(exc) from exc
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(name="check_replies", annotations=_TASK)
def check_replies(limit: int = 20, mark_read: bool = True, ctx: Context | None = None) -> str:
    """Read unread messages in the authenticated bot's inbox, oldest first.

    check_inbox is an alias. limit defaults to 20 and cannot exceed 50.
    mark_read defaults to true. When false, the messages stay unread.
    """

    role = _role_from_context(ctx)
    try:
        payload = tasks.check_replies(role=role, limit=limit, mark_read=mark_read)
    except tasks.TaskError as exc:
        raise _task_error(exc) from exc
    return json.dumps(payload, ensure_ascii=False)


mcp.add_tool(
    check_replies,
    name="check_inbox",
    title="Check inbox",
    description=(
        "Alias of check_replies. Read unread messages in the authenticated bot's inbox. "
        "limit defaults to 20 and cannot exceed 50. "
        "mark_read defaults to true. When mark_read is false, the messages stay unread."
    ),
    annotations=_TASK,
)


def build_app():
    """Build the ASGI app: MCP streamable HTTP behind the bearer gate.

    DNS rebinding protection stays on. Extra Host names for a reverse proxy
    come from BORK_INBOX_PUBLIC_HOSTS.
    """

    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for name in config.public_hosts():
        hosts += [name, f"{name}:*"]
        origins += [f"https://{name}", f"https://{name}:*"]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
    inner = mcp.streamable_http_app(
        streamable_http_path=ENDPOINT,
        json_response=True,
        stateless_http=True,
        host=config.host(),
        transport_security=transport_security,
    )
    return BearerGate(inner)


def check_tokens() -> None:
    """Exit unless every party has a distinct token of at least 32 characters."""

    loaded: list[bytes] = []
    for party in config.parties():
        token = config.token_for(party)
        if len(token) < config.MIN_TOKEN_LEN:
            raise SystemExit(
                f"BORK_INBOX_TOKEN_{config.env_suffix(party)} is missing or shorter than "
                f"{config.MIN_TOKEN_LEN} characters"
            )
        if any(_digest_eq(token, other) for other in loaded):
            raise SystemExit("every party needs a distinct token")
        loaded.append(token)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    logging.getLogger().addFilter(_RedactFilter())
    try:
        host = require_loopback(config.host())
        port = config.port()
        names = config.parties()
        config.routes()
    except config.ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    check_tokens()
    try:
        root = tasks.ensure_layout()
    except (tasks.TaskError, OSError) as exc:
        raise SystemExit(f"cannot prepare the data directory: {exc}") from exc
    log.info("listening on %s:%s path %s", host, port, ENDPOINT)
    log.info("parties %s", ", ".join(names))
    log.info("data dir %s", root)
    uvicorn.run(
        build_app(),
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        server_header=False,
        date_header=False,
    )


if __name__ == "__main__":
    main()
