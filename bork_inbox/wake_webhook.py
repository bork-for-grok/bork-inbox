"""Best-effort wake-up POST when a message lands in a party's inbox.

Each party may have a webhook URL and a bearer key in the environment:

    BORK_INBOX_WEBHOOK_URL_<PARTY>
    BORK_INBOX_WEBHOOK_KEY_<PARTY>

where <PARTY> is the party name upper-cased with "-" turned into "_"
(alice-bot -> ALICE_BOT). This module never logs the URL, the key or the
message body. A missing setting is a quiet skip. A webhook failure never
raises into send_task. The POST carries only id, sender, subject, title and
created time, so the woken bot must call check_replies to read the body.

The URL must use https. Redirects are never followed: a 3xx answer counts as a
failure, so the key is never sent to a redirect target.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

from bork_inbox import config

TIMEOUT_S = 5.0

log = logging.getLogger("bork_inbox")



class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so the Authorization header never leaves the configured URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _open(request: urllib.request.Request, timeout: float):
    """Open a request with the no-redirect opener. Tests patch this function."""

    return _OPENER.open(request, timeout=timeout)


def is_https_url(url: str) -> bool:
    """True only for an https URL with a host name."""

    try:
        parts = urllib.parse.urlsplit(url)
        return parts.scheme == "https" and bool(parts.hostname)
    except ValueError:
        return False


_pending_lock = threading.Lock()
_pending: list[threading.Thread] = []


def wait_pending(timeout: float = 2.0) -> None:
    """Join wake-up threads. Tests use this so a mocked POST has finished."""

    with _pending_lock:
        threads = list(_pending)
        _pending.clear()
    for thread in threads:
        thread.join(timeout=timeout)


def schedule_wake(*, recipient: str, task_id: str, sender: str, subject: str, created: str) -> None:
    """Start a daemon thread that may POST the recipient's wake-up. Never raises."""

    try:
        if recipient not in config.parties():
            return
    except config.ConfigError:
        return
    payload = {
        "id": task_id,
        "sender": sender,
        "subject": subject,
        "title": subject,
        "created": created,
    }
    thread = threading.Thread(target=_run_wake, args=(recipient, payload), daemon=True, name="wake-webhook")
    with _pending_lock:
        _pending.append(thread)
    try:
        thread.start()
    except Exception:
        log.warning("%s webhook failed status=error", recipient)


def _post_once(url: str, key: str, body: bytes) -> int | None:
    """POST once and return the HTTP status, or None. Never logs the URL or key.

    urllib error strings often contain the URL, so exceptions are not logged.
    Only https URLs are used, and a redirect is returned as its 3xx status
    (never followed).
    """

    if not is_https_url(url):
        return None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with _open(request, TIMEOUT_S) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code)
        except Exception:
            return None
        finally:
            exc.close()
    except Exception:
        return None


def _run_wake(recipient: str, payload: dict[str, str]) -> None:
    try:
        loaded = config.webhook_for(recipient)
        if loaded is None:
            log.info("%s webhook skipped: not configured", recipient)
            return
        url, key = loaded
        if not is_https_url(url):
            log.warning("%s webhook skipped: URL must be https", recipient)
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status = _post_once(url, key, body)
        if status is None or status >= 400:
            status = _post_once(url, key, body)
        if status is not None and 200 <= status < 300:
            log.info("%s webhook posted status=%s", recipient, status)
        elif status is None:
            log.warning("%s webhook failed status=error", recipient)
        else:
            log.warning("%s webhook failed status=%s", recipient, status)
    except Exception:
        log.warning("%s webhook failed status=error", recipient)
