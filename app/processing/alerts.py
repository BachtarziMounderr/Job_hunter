"""Read personal job-alert emails without visiting LinkedIn or following tracking links."""

import hashlib
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from app.processing.locality import location_country

SENDER_DOMAINS = {
    "linkedin.com": "linkedin",
    "emploitic.com": "emploitic",
    "emploipartner.com": "emploipartner",
    "algeriejob.com": "algeriejob",
}


def source_from_sender(sender: str) -> str | None:
    domain = parseaddr(sender)[1].rpartition("@")[2].lower()
    return next(
        (
            name
            for host, name in SENDER_DOMAINS.items()
            if domain == host or domain.endswith("." + host)
        ),
        None,
    )


def canonical_alert_url(url: str, source: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            return None
        host = (parsed.hostname or "").lower()
        if source == "linkedin" and host in {"linkedin.com", "www.linkedin.com", "dz.linkedin.com"}:
            match = re.search(r"/(?:comm/)?jobs/view/(?:[^/?]*-)?(\d+)(?:/|$)", parsed.path)
            return "https://www.linkedin.com/jobs/view/" + match[1] if match else None
        domain = next((host for host, name in SENDER_DOMAINS.items() if name == source), "")
        if not domain or host not in {domain, "www." + domain}:
            return None
        if source == "emploitic" and (
            not parsed.path.startswith("/offres-d-emploi/") or "/q-" in parsed.path
        ):
            return None
        if source != "emploitic" and not re.search(r"/(?:offre|job)[^/]*?/[^/]+", parsed.path):
            return None
        return urlunsplit(("https", domain, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return None


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    parent: "Node | None" = None
    children: list = field(default_factory=list)

    def text(self):
        separator = "\n" if self.tag in {"div", "tr", "td", "p", "li", "section", "root"} else " "
        return separator.join(
            child.text() if isinstance(child, Node) else child for child in self.children
        ).strip()

    def links(self):
        result = [self] if self.tag == "a" else []
        for child in self.children:
            if isinstance(child, Node):
                result.extend(child.links())
        return result


class AlertHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in {"br", "img", "hr", "meta", "link", "input", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not any(node.tag in {"script", "style", "head"} for node in self.stack):
            self.stack[-1].children.append(data)


def parse_alert_html(html: str, source: str) -> list[dict]:
    tree = AlertHTML()
    tree.feed(html)
    records, seen = [], set()
    for anchor in tree.root.links():
        url = canonical_alert_url(anchor.attrs.get("href", ""), source)
        title = " ".join(anchor.text().split())
        if (
            not url
            or not title
            or url in seen
            or re.fullmatch(r"(?:voir|view|apply|postuler|en savoir|consulter).*", title, re.I)
        ):
            continue
        node, card = anchor.parent, anchor
        while node is not None:
            links = {
                u
                for link in node.links()
                if (u := canonical_alert_url(link.attrs.get("href", ""), source))
            }
            if len(links) != 1 or len(node.text()) > 2500:
                break
            card, node = node, node.parent
        lines = [" ".join(line.split()) for line in card.text().splitlines() if line.strip()]
        location = next(
            (
                line
                for line in lines
                if line != title
                and len(line) <= 150
                and location_country(line)
                and not re.search(r"alerte|recherche|recevez|unsubscribe|vous|jobs? in", line, re.I)
            ),
            None,
        )
        # A foreign place in the job title must not be overridden by an email footer.
        title_country = location_country(title)
        country = (
            title_country if title_country and title_country != "DZ" else location_country(location)
        )
        company = card.attrs.get("data-company") or anchor.attrs.get("data-company")
        if not company:
            after = next((i for i, line in enumerate(lines) if title in line), -1)
            candidate = lines[after + 1] if after >= 0 and after + 1 < len(lines) else ""
            if (
                candidate
                and len(candidate) <= 100
                and not location_country(candidate)
                and "@" not in candidate
                and len(candidate.split()) < 8
                and not re.search(r"apply|postuler|offres|jobs|voir", candidate, re.I)
            ):
                company = candidate
        records.append(
            {
                "source_name": "alert:" + source,
                "external_id": hashlib.sha256(url.encode()).hexdigest(),
                "title": title[:512],
                "company": company,
                "location": location,
                "country": country,
                "url": url,
                "description": card.text()[:1800],
                "description_complete": False,
                "source_tags": ["personal-alert", "partial-description"],
            }
        )
        seen.add(url)
    return records


def parse_alert_email(raw: bytes) -> list[dict]:
    if len(raw) > 2_000_000:
        raise ValueError("Alert email exceeds size limit")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    source = source_from_sender(str(message.get("From", "")))
    if not source:
        return []
    records = {}
    for part in message.walk():
        if (
            part.get_content_type() == "text/html"
            and part.get_content_disposition() != "attachment"
        ):
            for record in parse_alert_html(part.get_content(), source):
                records[record["url"]] = record
    return list(records.values())
