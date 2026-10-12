"""A polite HTTP client for administrador judicial (AJ) websites (#845).

Every request the RJ collector sends goes through ``PoliteClient``:

* at most one request per second per host;
* ``robots.txt`` is read once per host and obeyed; a disallowed URL raises
  ``RobotsDisallowed`` and is never fetched;
* the User-Agent names the repository, so a site owner can find us;
* anything but HTTP 200 raises ``FetchError`` with the status. Nothing is
  returned for a failed page, so a caller can never mistake a failure for an
  empty case list (integrity rule 1).
"""

from __future__ import annotations

import codecs
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from urllib.parse import urlsplit

import httpx

USER_AGENT = "SILO-BZ RJ collector (+https://github.com/PedroDnT/SILO-BZ)"
MIN_INTERVAL_S = 1.0


def _percent_bytes(err: UnicodeDecodeError):
    """Keep the bytes of an invalid UTF-8 sequence as %XX rather than U+FFFD.

    Some sites print a file name in a legacy encoding inside a UTF-8 page. As %XX
    the link is the exact bytes the site wrote and still opens; as U+FFFD it
    would be a different, dead address.
    """
    return "".join(f"%{b:02X}" for b in err.object[err.start:err.end]), err.end


codecs.register_error("rj_percent_bytes", _percent_bytes)


def decode_body(resp: httpx.Response) -> str:
    """The body as text: the declared charset when there is one, else UTF-8."""
    if resp.charset_encoding:
        return resp.text
    return resp.content.decode("utf-8", errors="rj_percent_bytes")


class FetchError(RuntimeError):
    """A page did not answer HTTP 200."""

    def __init__(self, url: str, status: Optional[int], reason: str = ""):
        self.url, self.status = url, status
        super().__init__(f"{url}: HTTP {status} {reason}".strip())


class RobotsDisallowed(RuntimeError):
    """robots.txt disallows the URL for our User-Agent."""


@dataclass
class Page:
    url: str  # the final URL, after redirects
    status: int
    text: str


class PoliteClient:
    def __init__(self, transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 timeout: float = 60.0) -> None:
        self._http = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True,
                                  headers={"User-Agent": USER_AGENT})
        self._sleep, self._clock = sleep, clock
        self._last: Dict[str, float] = {}
        self._robots: Dict[str, urllib.robotparser.RobotFileParser] = {}

    def close(self) -> None:
        self._http.close()

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = MIN_INTERVAL_S - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._clock()

    def _get(self, url: str) -> httpx.Response:
        self._wait(urlsplit(url).netloc)
        try:
            return self._http.get(url)
        except httpx.HTTPError as e:
            raise FetchError(url, None, f"({type(e).__name__}: {e})") from e

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            resp = self._get(f"{base}/robots.txt")
            # RFC 9309 2.3.1: a 4xx means there is no robots.txt to obey (S3
            # answers 403 for a missing one); a 5xx means it is unreachable, and
            # the crawler must then assume everything is disallowed.
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                rp.allow_all = True
            else:
                rp.disallow_all = True
            self._robots[base] = rp
        return rp.can_fetch(USER_AGENT, url)

    def status(self, url: str) -> Optional[int]:
        """The HTTP status of a HEAD on ``url`` (GET when HEAD is refused).

        None when robots.txt disallows it or the network failed, so the link
        stays unchecked and is tried again on a later run.
        """
        try:
            if not self.allowed(url):
                return None
            self._wait(urlsplit(url).netloc)
            resp = self._http.head(url)
            if resp.status_code in (403, 405, 501):
                self._wait(urlsplit(url).netloc)
                with self._http.stream("GET", url) as r:
                    return r.status_code
            return resp.status_code
        except (httpx.HTTPError, FetchError):
            return None

    def get(self, url: str) -> Page:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        resp = self._get(url)
        if resp.status_code != 200:
            raise FetchError(url, resp.status_code)
        return Page(url=str(resp.url), status=resp.status_code, text=decode_body(resp))
