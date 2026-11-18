"""File inboxes for bot-to-bot task passing.

Each message is one Markdown file with simple front matter. The sender is the
authenticated party. Nothing is ever deleted: marking a message read renames
the file from ``inbox/unread`` to ``inbox/read`` on the same filesystem.

Layout under the data directory::

    <party>/inbox/unread/<id>.md
    <party>/inbox/read/<id>.md
    <party>/tmp/<id>.md        (staging for atomic writes)
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bork_inbox import config, wake_webhook

SUBJECT_MAX = 200
BODY_MAX_BYTES = 64 * 1024
CLIENT_ID_MAX = 200
LIMIT_DEFAULT = 20
LIMIT_MAX = 50

_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
_CLIENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
# A token is one line of URL-safe characters. A body line that is only such a
# run, or "Bearer" plus such a run, is refused so secrets do not leak by mistake.
_TOKEN_LINE_RE = re.compile(r"^(?:Bearer\s+)?[A-Za-z0-9_-]{32,256}$", re.IGNORECASE)

_thread_lock = threading.Lock()


class TaskError(Exception):
    """A rejected task operation. The message is safe to return to a client."""


def tasks_root() -> Path:
    return config.data_dir()


def ensure_layout(root: Path | None = None) -> Path:
    """Create the inbox directories (mode 770) for every configured party."""

    root = (root or tasks_root()).resolve()
    directories = [root]
    for party in config.parties():
        directories += [
            root / party,
            root / party / "inbox",
            root / party / "inbox" / "unread",
            root / party / "inbox" / "read",
            root / party / "tmp",
        ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o770)
    return root


def looks_like_bearer_token(body: str, live_tokens: tuple[bytes, ...] | list[bytes] = ()) -> bool:
    """Return true when a body line looks like a token, or contains a live token."""

    for line in body.splitlines():
        if _TOKEN_LINE_RE.fullmatch(line.strip()):
            return True
    raw = body.encode("utf-8", errors="replace")
    for token in live_tokens:
        if isinstance(token, bytes) and len(token) >= config.MIN_TOKEN_LEN and token in raw:
            return True
    return False


def send_task(
    *,
    role: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    client_id: str | None = None,
    root: Path | None = None,
    live_tokens: tuple[bytes, ...] | list[bytes] = (),
) -> dict[str, str]:
    """Write one message into the recipient inbox and return id, path and recipient."""

    sender = _role(role)
    recipient = _recipient(sender, to)
    subject = _subject(subject, live_tokens)
    body = _body(body, live_tokens)
    reply_to = _optional_id(in_reply_to)
    caller_key = _optional_client_id(client_id, live_tokens)
    base = ensure_layout(root)

    with _exclusive(base):
        if caller_key is not None:
            existing = _find_client_id(base, sender, caller_key)
            if existing is not None:
                return existing
        result, created = _create(base, sender, recipient, subject, body, reply_to, caller_key)
    try:
        wake_webhook.schedule_wake(
            recipient=recipient,
            task_id=result["id"],
            sender=sender,
            subject=subject,
            created=created,
        )
    except Exception:
        pass
    return result


def check_replies(
    *,
    role: str,
    limit: int = LIMIT_DEFAULT,
    mark_read: bool = True,
    root: Path | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Return unread messages for ``role`` only, oldest first. Mark them read when asked."""

    owner = _role(role)
    count = _limit(limit)
    if not isinstance(mark_read, bool):
        raise TaskError("mark_read must be a boolean")
    base = ensure_layout(root)
    unread = base / owner / "inbox" / "unread"
    read_dir = base / owner / "inbox" / "read"

    with _exclusive(base):
        chosen = _message_files(unread)[:count]
        messages: list[dict[str, str]] = []
        for path in chosen:
            fields, text = _read_message(path)
            if mark_read:
                destination = read_dir / path.name
                if destination.exists():
                    raise TaskError("could not mark a message read")
                os.rename(path, destination)
                location = "read"
            else:
                location = "unread"
            messages.append(_public_message(fields, text, location))
        return {"messages": messages}


def _role(value: str) -> str:
    if value not in config.parties():
        raise TaskError("authenticated role is not allowed")
    return value


def _recipient(sender: str, to: object) -> str:
    if not isinstance(to, str) or to not in config.parties():
        raise TaskError("recipient is not allowed")
    if (sender, to) not in config.routes():
        raise TaskError("sender cannot send to that recipient")
    return to


def _subject(value: object, live_tokens: tuple[bytes, ...] | list[bytes] = ()) -> str:
    if not isinstance(value, str) or value == "" or len(value) > SUBJECT_MAX:
        raise TaskError(f"subject must be 1 to {SUBJECT_MAX} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise TaskError("subject must be one line")
    if looks_like_bearer_token(value, live_tokens):
        raise TaskError("subject looks like a bearer token")
    return value


def _body(value: object, live_tokens: tuple[bytes, ...] | list[bytes]) -> str:
    if not isinstance(value, str) or value == "":
        raise TaskError("body is required")
    if "\x00" in value:
        raise TaskError("body rejected")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise TaskError("body rejected") from exc
    if len(encoded) > BODY_MAX_BYTES:
        raise TaskError("body exceeds 64 KiB")
    if looks_like_bearer_token(value, live_tokens):
        raise TaskError("body looks like a bearer token")
    return value


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise TaskError("in_reply_to is not a message id")
    return value


def _optional_client_id(value: object, live_tokens: tuple[bytes, ...] | list[bytes] = ()) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > CLIENT_ID_MAX or not _CLIENT_RE.fullmatch(value):
        raise TaskError("client_id is not allowed")
    if looks_like_bearer_token(value, live_tokens):
        raise TaskError("client_id looks like a bearer token")
    return value


def _limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > LIMIT_MAX:
        raise TaskError(f"limit must be an integer from 1 to {LIMIT_MAX}")
    return value


@contextmanager
def _exclusive(root: Path):
    lock_path = root / ".lock"
    handle = open(lock_path, "a+")
    os.chmod(lock_path, 0o660)
    _thread_lock.acquire()
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        _thread_lock.release()
        handle.close()


def _new_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def _timestamp() -> str:
    try:
        zone = ZoneInfo(config.timezone_name())
    except Exception:
        zone = timezone.utc
    return datetime.now(zone).isoformat(timespec="seconds")


def _dump(value: str | None) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def _render(message_id, timestamp, sender, recipient, subject, body, in_reply_to, client_id) -> bytes:
    front = "\n".join(
        [
            "---",
            f"id: {_dump(message_id)}",
            f"timestamp: {_dump(timestamp)}",
            f"from: {_dump(sender)}",
            f"to: {_dump(recipient)}",
            f"subject: {_dump(subject)}",
            f"in_reply_to: {_dump(in_reply_to)}",
            f"client_id: {_dump(client_id)}",
            "---",
            "",
        ]
    )
    return (front + "\n" + body).encode("utf-8")


def _create(root, sender, recipient, subject, body, in_reply_to, client_id) -> tuple[dict[str, str], str]:
    for _ in range(5):
        message_id = _new_id()
        tmp = root / recipient / "tmp" / f"{message_id}.md"
        final = root / recipient / "inbox" / "unread" / f"{message_id}.md"
        if tmp.exists() or final.exists():
            continue
        created = _timestamp()
        payload = _render(message_id, created, sender, recipient, subject, body, in_reply_to, client_id)
        try:
            _write_exclusive(tmp, payload)
        except FileExistsError:
            continue
        if final.exists():
            tmp.unlink(missing_ok=True)
            continue
        os.rename(tmp, final)
        return {"id": message_id, "path": _relative(root, final), "to": recipient}, created
    raise TaskError("could not allocate a message id")


def _write_exclusive(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    try:
        os.fchmod(fd, 0o660)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise TaskError("could not write message")
            view = view[written:]
    except Exception:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    os.close(fd)


def _find_client_id(root: Path, sender: str, client_id: str) -> dict[str, str] | None:
    for party in config.parties():
        for folder in ("inbox/unread", "inbox/read", "tmp"):
            for path in _message_files(root / party / folder):
                try:
                    fields, _text = _read_message(path)
                except TaskError:
                    continue
                if fields.get("from") != sender or fields.get("client_id") != client_id:
                    continue
                landed = _promote_tmp(root, path, fields)
                return {"id": str(fields["id"]), "path": _relative(root, landed), "to": str(fields["to"])}
    return None


def _promote_tmp(root: Path, path: Path, fields: dict[str, str | None]) -> Path:
    if path.parent.name != "tmp":
        return path
    recipient = fields.get("to")
    message_id = fields.get("id")
    if recipient not in config.parties() or not isinstance(message_id, str):
        return path
    destination = root / recipient / "inbox" / "unread" / f"{message_id}.md"
    if destination.exists():
        return destination
    os.rename(path, destination)
    return destination


def _message_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    try:
        names = sorted(entry.name for entry in directory.iterdir())
    except OSError as exc:
        raise TaskError("cannot list inbox") from exc
    root_real = directory.resolve(strict=True)
    found: list[Path] = []
    for name in names:
        if not name.endswith(".md"):
            continue
        path = directory / name
        try:
            info = path.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            continue
        try:
            real = path.resolve(strict=True)
            real.relative_to(root_real)
        except (OSError, ValueError):
            continue
        if real.is_file():
            found.append(real)
    return found


def _read_message(path: Path) -> tuple[dict[str, str | None], str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TaskError("cannot read message") from exc
    if len(data) > BODY_MAX_BYTES + 4096:
        raise TaskError("message file is too large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TaskError("message file is not text") from exc
    if not text.startswith("---\n"):
        raise TaskError("message file is missing front matter")
    rest = text[4:]
    index = rest.find("\n---\n")
    if index < 0:
        raise TaskError("message file is missing the end of front matter")
    raw_front = rest[:index]
    body = rest[index + 5 :]
    if body.startswith("\n"):
        body = body[1:]
    fields: dict[str, str | None] = {}
    for line in raw_front.split("\n"):
        if line == "":
            continue
        key, sep, raw_value = line.partition(":")
        if sep != ":" or key.strip() == "":
            raise TaskError("message file has a bad front-matter line")
        fields[key.strip()] = _parse_scalar(raw_value.strip())
    for required in ("id", "timestamp", "from", "to", "subject"):
        if not fields.get(required):
            raise TaskError("message file is missing a required field")
    message_id = fields["id"]
    if not isinstance(message_id, str) or path.stem != message_id or not _ID_RE.fullmatch(message_id):
        raise TaskError("message file id does not match its name")
    names = config.parties()
    if fields.get("from") not in names or fields.get("to") not in names:
        raise TaskError("message file has a bad sender or recipient")
    return fields, body


def _parse_scalar(raw: str) -> str | None:
    if raw == "null":
        return None
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaskError("message file has a bad field") from exc
        if not isinstance(value, str):
            raise TaskError("message file has a bad field")
        return value
    return raw


def _public_message(fields: dict[str, str | None], body: str, location: str) -> dict[str, str]:
    message = {
        "id": str(fields["id"]),
        "timestamp": str(fields["timestamp"]),
        "from": str(fields["from"]),
        "to": str(fields["to"]),
        "subject": str(fields["subject"]),
        "body": body,
        "location": location,
    }
    reply_to = fields.get("in_reply_to")
    if isinstance(reply_to, str) and reply_to:
        message["in_reply_to"] = reply_to
    return message


def _relative(root: Path, path: Path) -> str:
    try:
        rel = path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as exc:
        raise TaskError("path rejected") from exc
    if rel.startswith("/") or rel.startswith("..") or "/../" in rel:
        raise TaskError("path rejected")
    return rel
