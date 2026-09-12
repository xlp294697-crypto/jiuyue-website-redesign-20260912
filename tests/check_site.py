#!/usr/bin/env python3
"""Read-only production checks; run with Python 3.12: python tests/check_site.py.

These checks validate the files that will be deployed. They do not send bookings,
contact production services, or replace the separate JavaScript behaviour tests.
"""

from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET


ORIGIN = "https://jiuyue.club"
SITEMAP_NAMESPACE = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PREVIEW_TEXT = (
    "设计预览", "网站设计原型", "不会发送或保存信息", "信息尚未提交",
    "正式网站接入预约服务后", "预览咨询信息", "prototype-note",
)


class Page(HTMLParser):
    def __init__(self, path: Path, relative: str):
        super().__init__(convert_charrefs=True)
        self.relative = relative
        self.url = ORIGIN + ("/" if relative == "index.html" else "/" + relative)
        self.raw = path.read_text(encoding="utf-8")
        self.title_parts: list[str] = []
        self.title_count = 0
        self.h1_count = 0
        self.metas: list[dict] = []
        self.canonicals: list[str] = []
        self.ids: set[str] = set()
        self.duplicate_ids: set[str] = set()
        self.references: list[tuple[str, str, bool]] = []
        self.scripts: list[str] = []
        self.jsonld: list[str] = []
        self.elements: list[tuple[str, dict, str | None]] = []
        self._in_title = False
        self._json_buffer: list[str] | None = None
        self._form: str | None = None
        self.feed(self.raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self._form = values.get("id", "")
        self.elements.append((tag, values, self._form))
        identifier = values.get("id")
        if identifier:
            if identifier in self.ids:
                self.duplicate_ids.add(identifier)
            self.ids.add(identifier)
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"])
        if tag == "title":
            self.title_count += 1
            self._in_title = True
        if tag == "h1":
            self.h1_count += 1
        if tag == "meta":
            self.metas.append(values)
            if values.get("property") in {"og:image", "og:video"}:
                self.references.append(("social media", values.get("content", ""), False))
        if tag == "link":
            rel = values.get("rel", "").lower().split()
            if "canonical" in rel:
                self.canonicals.append(values.get("href", ""))
            if any(item in rel for item in ("stylesheet", "icon", "preload", "modulepreload")):
                self.references.append(("link", values.get("href", ""), False))
        if tag == "script":
            if values.get("src"):
                self.scripts.append(values["src"])
                self.references.append(("script", values["src"], False))
            if values.get("type", "").lower() == "application/ld+json":
                self._json_buffer = []
        if tag in {"a", "area"} and values.get("href"):
            self.references.append(("anchor", values["href"], True))
        if tag in {"img", "source", "video", "audio", "track", "iframe", "input"} and values.get("src"):
            self.references.append((tag, values["src"], False))
        for attribute in ("poster", "data-poster", "data-video", "data-image"):
            if values.get(attribute):
                self.references.append((attribute, values[attribute], False))
        if values.get("srcset") and not values["srcset"].lstrip().startswith("data:"):
            for candidate in values["srcset"].split(","):
                if candidate.strip():
                    self.references.append(("srcset", candidate.strip().split()[0], False))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._json_buffer is not None:
            self.jsonld.append("".join(self._json_buffer))
            self._json_buffer = None
        if tag == "form":
            self._form = None

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._json_buffer is not None:
            self._json_buffer.append(data)

    @property
    def title(self):
        return " ".join("".join(self.title_parts).split())

    def meta(self, name):
        return [m.get("content", "") for m in self.metas if m.get("name", "").lower() == name]


def json_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from json_objects(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from json_objects(value["@graph"])


def local_reference(dist: Path, base_url: str, value: str):
    """Resolve public same-origin URLs while keeping every lookup inside dist."""
    target = urlsplit(urljoin(base_url, value))
    if target.scheme not in {"http", "https"} or target.hostname not in {"jiuyue.club", "www.jiuyue.club"}:
        return None
    relative = unquote(target.path).lstrip("/")
    if not relative or relative.endswith("/"):
        relative += "index.html"
    path = (dist / relative).resolve()
    if not path.is_relative_to(dist):
        raise ValueError("URL escapes the deployment directory")
    return path, unquote(target.fragment)


def robot_rules(lines):
    """Extract the generic crawler group; production uses User-agent: *.

    Resolve rules by longest match, with Allow winning a tie. The standard
    library's RobotFileParser uses first-match order and misreads this site's
    valid Allow: / followed by more specific Disallow entries.
    """
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    sitemaps: list[str] = []
    directives_started = False
    for raw in lines:
        raw = raw.split("#", 1)[0].strip()
        if ":" not in raw:
            continue
        key, value = (part.strip() for part in raw.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if directives_started:
                agents = []
                directives_started = False
            agents.append(value.lower())
        elif key == "sitemap":
            sitemaps.append(value)
        elif key in {"allow", "disallow"}:
            directives_started = True
            if "*" in agents and value:
                rules.append((key == "allow", value))
    return rules, sitemaps


def robots_allow(rules, url):
    parsed = urlsplit(url)
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    matches = []
    for allowed, pattern in rules:
        anchored = pattern.endswith("$")
        literal = pattern[:-1] if anchored else pattern
        expression = "^" + re.escape(literal).replace(r"\*", ".*") + ("$" if anchored else "")
        if re.search(expression, path):
            matches.append((len(literal.replace("*", "").encode("utf-8")), allowed))
    return max(matches)[1] if matches else True


def check(dist: Path):
    errors: list[str] = []
    warnings: list[str] = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    if not dist.is_dir():
        return {"ok": False, "errors": ["Deployment directory does not exist."], "warnings": [], "counts": {}}
    pages: dict[str, Page] = {}
    for path in sorted(dist.rglob("*.html")):
        relative = path.relative_to(dist).as_posix()
        try:
            pages[relative] = Page(path, relative)
        except (UnicodeError, OSError) as exc:
            errors.append(f"{relative}: cannot parse UTF-8 HTML ({type(exc).__name__}).")
    require(len(pages) == 17, f"Expected 17 HTML files including 404.html; found {len(pages)}.")
    require("404.html" in pages, "Missing 404.html.")
    indexed = {name: page for name, page in pages.items() if name != "404.html"}
    sitemap_urls: list[str] = []
    try:
        tree = ET.parse(dist / "sitemap.xml")
        sitemap_urls = [node.text.strip() for node in tree.findall("s:url/s:loc", SITEMAP_NAMESPACE) if node.text]
        require(len(sitemap_urls) == 16, f"Expected 16 sitemap URLs; found {len(sitemap_urls)}.")
        require(len(set(sitemap_urls)) == len(sitemap_urls), "Sitemap contains duplicate URLs.")
        expected = {page.url for page in indexed.values()}
        require(set(sitemap_urls) == expected, "Sitemap URLs must exactly match the 16 indexable HTML pages.")
        for url in sitemap_urls:
            require(url.startswith(ORIGIN + "/"), f"Sitemap has a noncanonical origin: {url}")
            resolved = local_reference(dist, ORIGIN + "/", url)
            require(resolved is not None and resolved[0].is_file() and resolved[0].suffix == ".html", f"Sitemap HTML is missing: {url}")
    except (OSError, ET.ParseError, ValueError):
        errors.append("sitemap.xml is missing or invalid.")

    descriptions: list[str] = []
    titles: list[str] = []
    references_checked = 0
    jsonld_checked = 0
    for relative, page in pages.items():
        public = relative != "404.html"
        require(page.title_count == 1 and bool(page.title), f"{relative}: expected one nonempty title.")
        require(page.h1_count == 1, f"{relative}: expected one H1; found {page.h1_count}.")
        description = page.meta("description")
        require(len(description) == 1 and bool(description[0].strip()), f"{relative}: expected one nonempty description.")
        require(not page.duplicate_ids, f"{relative}: duplicate IDs: {', '.join(sorted(page.duplicate_ids))}.")
        require(len(page.canonicals) == 1, f"{relative}: expected one canonical URL.")
        if public:
            require(page.canonicals == [page.url], f"{relative}: canonical must be {page.url}.")
            titles.append(page.title)
            descriptions.extend(description)
            robots = ",".join(page.meta("robots")).lower()
            require(not re.search(r"\b(noindex|none)\b", robots), f"{relative}: public page prohibits indexing.")
        for meta in page.metas:
            if meta.get("http-equiv", "").lower() == "content-security-policy":
                require(not re.search(r"(?:form-action|connect-src)\s+'none'", meta.get("content", ""), re.I), f"{relative}: preview CSP blocks submissions or API connections.")
        for phrase in PREVIEW_TEXT:
            require(phrase not in page.raw, f"{relative}: prototype content remains: {phrase}.")
        organizations = []
        require(bool(page.jsonld), f"{relative}: no JSON-LD organization data.")
        for block in page.jsonld:
            try:
                value = json.loads(block)
                jsonld_checked += 1
                for obj in json_objects(value):
                    kind = obj.get("@type", [])
                    kind = [kind] if isinstance(kind, str) else kind
                    if "Organization" in kind:
                        organizations.append(obj)
            except (ValueError, TypeError):
                errors.append(f"{relative}: malformed JSON-LD.")
        require(bool(organizations), f"{relative}: Organization is missing from JSON-LD.")
        for organization in organizations:
            require(organization.get("url") == ORIGIN + "/" and bool(organization.get("name")), f"{relative}: Organization needs its name and canonical website URL.")
        for kind, value, check_fragment in page.references:
            if not value:
                errors.append(f"{relative}: empty {kind} URL.")
                continue
            try:
                resolved = local_reference(dist, page.url, value)
            except ValueError:
                errors.append(f"{relative}: invalid local {kind} URL: {value}")
                continue
            if resolved is None:
                continue
            references_checked += 1
            target, fragment = resolved
            if not target.is_file():
                errors.append(f"{relative}: missing {kind} target: {value}")
                continue
            if check_fragment and fragment and not fragment.startswith(":~:text=") and target.suffix == ".html":
                destination = pages.get(target.relative_to(dist).as_posix())
                require(destination is not None and fragment in destination.ids, f"{relative}: missing anchor target: {value}")
    for label, values in (("title", titles), ("description", descriptions)):
        duplicates = [value for value, count in Counter(values).items() if count > 1]
        require(not duplicates, f"Indexable pages have duplicate {label}s: {duplicates}")

    for path in sorted(dist.rglob("*")):
        if path.suffix not in {".html", ".js", ".css"}:
            continue
        relative = path.relative_to(dist).as_posix()
        source = path.read_text(encoding="utf-8")
        require(not re.search(r"https?://(?:127\.\d+\.\d+\.\d+|localhost|\[::1\])(?=[:/\s\"']|$)", source, re.I), f"{relative}: a local preview URL remains.")
        if path.suffix == ".css":
            for match in re.finditer(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", source):
                value = match.group(1).strip()
                if value.startswith("#"):
                    continue
                try:
                    resolved = local_reference(dist, ORIGIN + "/" + relative, value)
                    if resolved is not None:
                        references_checked += 1
                        require(resolved[0].is_file(), f"{relative}: missing CSS asset: {value}")
                except ValueError:
                    errors.append(f"{relative}: invalid CSS asset URL: {value}")

    booking = pages.get("booking/index.html")
    if booking:
        booking_scripts = {urlsplit(urljoin(booking.url, value)).path for value in booking.scripts}
        require("/assets/booking.js" in booking_scripts, "booking/index.html: real booking.js is not loaded.")
        fields = {attributes.get("name"): attributes for tag, attributes, form in booking.elements if form == "booking-form" and tag in {"input", "select", "textarea"}}
        for field in ("parentName", "phone", "grade", "course", "concern", "preferredTime", "website", "privacyConsent"):
            require(field in fields, f"booking/index.html: backend field {field} is missing.")
        consent = fields.get("privacyConsent", {})
        require(consent.get("type") == "checkbox" and "required" in consent and "checked" not in consent and consent.get("value") == "yes", "booking/index.html: privacy consent must be required, explicitly selected, and use the backend value yes.")
        require(any(tag == "a" and form == "booking-form" and urlsplit(urljoin(booking.url, attr.get("href", ""))).path == "/privacy/index.html" for tag, attr, form in booking.elements), "booking/index.html: the form must link to the information processing notice.")
        require("booking-preview" not in booking.ids, "booking/index.html: prototype-only confirmation dialog remains.")
    else:
        errors.append("Missing booking/index.html.")
    booking_js = dist / "assets/booking.js"
    if booking_js.is_file():
        script = booking_js.read_text(encoding="utf-8")
        require(bool(re.search(r"fetch\(\s*['\"]/api/inquiries['\"]", script)), "assets/booking.js: missing existing /api/inquiries integration.")
        require(bool(re.search(r"method\s*:\s*['\"]POST['\"]", script)), "assets/booking.js: booking submission must use POST.")
    else:
        errors.append("Missing assets/booking.js.")

    for relative, page in pages.items():
        require("analytics-consent" in page.ids and "analytics-settings" in page.ids, f"{relative}: missing analytics consent choices/settings.")
        for action in ("data-analytics-accept", "data-analytics-reject"):
            require(any(tag == "button" and action in attr for tag, attr, _ in page.elements), f"{relative}: missing {action} button.")
    try:
        robots_lines = (dist / "robots.txt").read_text(encoding="utf-8").splitlines()
        rules, advertised_sitemaps = robot_rules(robots_lines)
        for page in indexed.values():
            require(robots_allow(rules, page.url), f"robots.txt blocks public page: {page.url}")
        for path in ("/admin", "/admin/", "/api/", "/api/inquiries"):
            require(not robots_allow(rules, ORIGIN + path), f"robots.txt must block {path}.")
        require(ORIGIN + "/sitemap.xml" in advertised_sitemaps, "robots.txt must advertise the production sitemap.")
    except OSError:
        errors.append("Missing robots.txt.")

    return {
        "ok": not errors,
        "counts": {"html_pages": len(pages), "sitemap_urls": len(sitemap_urls), "local_references_checked": references_checked, "jsonld_blocks": jsonld_checked},
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / "dist")
    parser.add_argument("--json", action="store_true", help="Print a JSON report to standard output.")
    arguments = parser.parse_args()
    report = check(arguments.dist.resolve())
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("PASS: production static checks" if report["ok"] else "FAIL: production static checks")
        for key, count in report["counts"].items():
            print(f"  {key}: {count}")
        for error in report["errors"]:
            print(f"  ERROR: {error}")
        print("Scope: static files only; run the JavaScript tests and verify deployed HTTP behaviour separately.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
