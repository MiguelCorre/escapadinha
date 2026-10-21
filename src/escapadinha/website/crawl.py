"""Crawl an old sitemap: does every URL still answer with a page, or one 301 to a page? (D35)

Two ways, one result type:

- `check_build(urls, dist)`: against a local build, applying its `_redirects` the way
  Cloudflare Pages does (a matching rule wins over a file; exact paths only, which is all the
  generated file has). `tests/test_crawl.py` runs it on the old site's URLs.
- `check_live(urls, client)`: against the live site (`escapadinha site crawl`), without
  following redirects: 200 is fine, 301 is fine when its `Location` answers 200; anything else
  (404, 302, 308, 5xx, a redirect chain or loop) is reported. The cutover week (#23) crawled
  `docs/cutover/jinja-sitemap-2026-10-14.xml` daily with it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


@dataclass(frozen=True)
class Result:
    url: str
    status: int                  # first answer: 200, 301, 404, ...
    target: str | None = None    # where a redirect points
    detail: str = ""             # why it isn't ok

    @property
    def path(self) -> str:
        return urlsplit(self.url).path or "/"

    @property
    def ok(self) -> bool:
        return not self.detail and self.status in (200, 301)


def sitemap_urls(source: str, client: httpx.Client | None = None) -> list[str]:
    """The <loc> URLs of a sitemap given as a file path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        if client is None:
            with httpx.Client(timeout=30) as own:       # closed here: we made it
                return sitemap_urls(source, own)
        response = client.get(source)
        response.raise_for_status()
        text = response.text
    else:
        text = Path(source).read_text("utf-8")
    return LOC.findall(text)


def parse_redirects(text: str) -> dict[str, str]:
    """`_redirects` rules: source -> target (301 rules; comments and blank lines skipped)."""
    rules = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("#"):
            rules.setdefault(parts[0], parts[1])
    return rules


def _serves(dist: Path, path: str) -> bool:
    rel = path.lstrip("/")
    target = dist / rel
    return (target / "index.html").is_file() if path.endswith("/") else target.is_file() or (
        target / "index.html").is_file()


def check_build(urls: list[str], dist: Path) -> list[Result]:
    redirects_file = dist / "_redirects"
    rules = parse_redirects(redirects_file.read_text("utf-8")) if redirects_file.is_file() else {}
    results = []
    for url in urls:
        path = urlsplit(url).path or "/"
        if path in rules:
            target = rules[path]
            target_path = urlsplit(target).path
            fine = target_path not in rules and _serves(dist, target_path)
            results.append(Result(url, 301, target, "" if fine else
                                  f"redirects to {target}, which is not a page of the build"))
        elif _serves(dist, path):
            results.append(Result(url, 200))
        else:
            results.append(Result(url, 404, detail="no page and no redirect"))
    return results


def _on(base: str | None, url: str) -> str:
    """The URL on another host (a preview deployment), same path and query."""
    if not base:
        return url
    parts = urlsplit(url)
    return base.rstrip("/") + parts.path + (f"?{parts.query}" if parts.query else "")


def check_live(urls: list[str], client: httpx.Client, *, base: str | None = None,
               pause: float = 0.0) -> list[Result]:
    results = []
    for original in urls:
        url = _on(base, original)
        try:
            response = client.get(url, follow_redirects=False)
        except httpx.HTTPError as exc:
            results.append(Result(url, 0, detail=f"no answer: {type(exc).__name__}"))
            continue
        status = response.status_code
        if status in (301, 302, 307, 308):
            target = urljoin(url, response.headers.get("location", ""))
            detail = "" if status == 301 else f"{status} instead of 301"
            if not detail:
                try:
                    final = client.get(target, follow_redirects=False).status_code
                except httpx.HTTPError as exc:
                    final, detail = 0, f"redirect target gave no answer: {type(exc).__name__}"
                if not detail and final != 200:
                    detail = f"redirects to {target}, which answers {final}"
            results.append(Result(url, status, target, detail))
        else:
            results.append(Result(url, status, detail="" if status == 200 else f"answers {status}"))
        if pause:
            time.sleep(pause)
    return results
