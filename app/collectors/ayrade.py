"""Bounded reader for AYRADE's official recruitment pages, respecting robots.txt."""

import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.collectors.base import CollectionResult
from app.processing.alerts import AlertHTML, Node
from app.processing.careers import clean_job_text
from app.processing.locality import location_country

ORIGIN = "https://www.ayrade.com"
AGENT = "AIJobHunter/0.3"


def recruitment_links(html: str) -> list[tuple[str, str]]:
    parser = AlertHTML()
    parser.feed(html)
    result = {}
    expected = set()
    for anchor in parser.root.links():
        url = anchor.attrs.get("href", "")
        parsed = urlsplit(url)
        if anchor.text().strip().casefold() != "postuler" or parsed.netloc != "www.ayrade.com":
            continue
        if (
            parsed.scheme != "https"
            or parsed.query
            or not re.fullmatch(r"/[a-z0-9-]+/", parsed.path)
        ):
            continue
        if parsed.path == "/candidature-spontanee/":
            continue
        expected.add(url)
        node = anchor.parent
        while node is not None:
            links = {
                a.attrs.get("href")
                for a in node.links()
                if a.text().strip().casefold() == "postuler"
            }
            if len(links) > 1:
                break
            headings = []
            stack = [node]
            while stack:
                item = stack.pop()
                if item.tag in {"h1", "h2", "h3", "h4", "h5"}:
                    headings.append(item.text().strip())
                stack.extend(child for child in item.children if isinstance(child, Node))
            if headings:
                result[url] = " ".join(headings[0].split())
                break
            if "et_pb_row" in node.attrs.get("class", "").split():
                lines = [line.strip() for line in node.text().splitlines() if line.strip()]
                if lines and lines[0].casefold() != "postuler":
                    result[url] = " ".join(lines[0].split())
                    break
            node = node.parent
    if expected - result.keys():
        raise ValueError("Some recruitment cards could not be interpreted")
    return list(result.items())


def ayrade_record(html: str, url: str, title: str) -> dict:
    full = clean_job_text(html)
    title_match = re.search(re.escape(title), full, re.I)
    if title_match is None:
        raise ValueError("Recruitment title missing from detail page")
    start = title_match.start()
    body = re.split(r"\n(?:Nom\s*\*?|Prénom\s*\*?|Nos partenaires)\n", full[start:], maxsplit=1)[0]
    # The job must explicitly reference the headquarters before its published address is used.
    headquarters = re.search(r"poste bas[eé] au si[eè]ge", body, re.I)
    address = re.search(r"Mohammadia Mall[^\n]*Alger[^\n]*(?:Algérie|Algerie)", full, re.I)
    location = "Alger, Algérie (siège AYRADE)" if headquarters and address else None
    return {
        "source_name": "ayrade:ayrade",
        "external_id": hashlib.sha256(url.encode()).hexdigest(),
        "title": title,
        "company": "AYRADE",
        "url": url,
        "description": body,
        "location": location,
        "country": location_country(location),
        "remote_type": "onsite" if location else "unknown",
    }


class AyradeCollector:
    name = "ayrade:ayrade"

    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    def collect(self):
        result = CollectionResult()
        try:
            response = self.client.get(
                ORIGIN + "/robots.txt",
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            robot = RobotFileParser()
            robot.parse(response.text.splitlines())
            index = ORIGIN + "/recrutement/"
            if not robot.can_fetch(AGENT, index):
                raise ValueError("Recruitment path not available to this agent")
            response = self.client.get(
                index,
                headers={"User-Agent": AGENT},
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            links = recruitment_links(response.text)
            if not links:
                raise ValueError("Recruitment layout changed; no job cards found")
            result.pages_fetched += 1
            result.truncated = len(links) > self.settings.career_max_pages
            for url, title in links[: self.settings.career_max_pages]:
                if not robot.can_fetch(AGENT, url):
                    result.error = "Some recruitment pages disallow retrieval"
                    continue
                time.sleep(self.settings.request_interval_seconds)
                try:
                    content, canonical = self._detail(url, robot)
                    result.records.append(ayrade_record(content, canonical, title))
                    result.pages_fetched += 1
                except (httpx.HTTPError, ValueError):
                    result.error = "Some AYRADE detail pages unavailable; collection is partial"
        except (httpx.HTTPError, ValueError, TypeError):
            result.error = "AYRADE recruitment feed unavailable or changed; no expiration inferred"
        return result

    def _detail(self, url, robot):
        for _ in range(3):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "www.ayrade.com"
                or parsed.query
                or not re.fullmatch(r"/[a-z0-9-]+/", parsed.path)
                or not robot.can_fetch(AGENT, url)
            ):
                raise ValueError("Unsupported recruitment redirect")
            response = self.client.get(
                url,
                headers={"User-Agent": AGENT},
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            return response.text, url
        raise ValueError("Too many recruitment redirects")
