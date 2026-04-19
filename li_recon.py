
#!/usr/bin/env python3
"""
li_recon.py — LinkedIn Public Profile Reconnaissance Tool
AGPL-3.0 License

Usage:
    python li_recon.py <profile_url_or_username>
    python li_recon.py --batch targets.txt
    python li_recon.py --help

Output: JSON to stdout, or to file with --output flag.
"""

import argparse
import json
import re
import sys
import time
import random
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, quote

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] Missing dependencies. Install with: pip install requests beautifulsoup4")
    sys.exit(1)


# --- Constants ---
VERSION = "0.1.0"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
DELAY_RANGE = (2, 5)
BASE_URL = "https://www.linkedin.com/in/"


class ReconResult:
    """Container for a single profile recon pass."""

    def __init__(self, target: str):
        self.target = target
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.target_hash = hashlib.sha256(target.encode()).hexdigest()[:12]
        self.status = "pending"
        self.profile = {}
        self.errors = []
        self.metadata = {
            "tool": "li_recon",
            "version": VERSION,
            "collection_ts": self.timestamp,
        }

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "target_hash": self.target_hash,
            "status": self.status,
            "timestamp": self.timestamp,
            "profile": self.profile,
            "errors": self.errors,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def normalize_target(raw: str) -> str:
    """Extract LinkedIn username from URL or raw input."""
    raw = raw.strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.netloc and "linkedin.com" in parsed.netloc:
        path = parsed.path.strip("/")
        if path.startswith("in/"):
            return path[3:].split("/")
        return path.split("/")
    return raw


def build_session() -> requests.Session:
    """Build a requests session with randomized headers."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def fetch_public_profile(session: requests.Session, username: str) -> tuple:
    """
    Fetch the public-facing LinkedIn profile page.
    Returns (html_content, status_code) or (None, error_msg).
    """
    url = f"{BASE_URL}{quote(username)}"
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
        return resp.text, resp.status_code
    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.ConnectionError:
        return None, "connection_error"
    except requests.exceptions.RequestException as e:
        return None, str(e)


def parse_profile(html: str) -> dict:
    """
    Parse public profile HTML for structured data.
    LinkedIn public profiles expose limited data without auth.
    This parser targets the public view — no login required.
    """
    soup = BeautifulSoup(html, "html.parser")
    profile = {}

    # --- Name ---
    name_tag = soup.find("h1")
    if name_tag:
        profile["name"] = name_tag.get_text(strip=True)

    # --- Headline ---
    headline_tag = soup.find("div", class_=re.compile(r"top-card-layout__headline"))
    if headline_tag:
        profile["headline"] = headline_tag.get_text(strip=True)

    # --- Location ---
    location_tag = soup.find("span", class_=re.compile(r"top-card__subline-item"))
    if not location_tag:
        location_tag = soup.find("div", class_=re.compile(r"top-card--list"))
    if location_tag:
        profile["location"] = location_tag.get_text(strip=True)

    # --- About / Summary ---
    about_section = soup.find("section", class_=re.compile(r"summary"))
    if about_section:
        about_text = about_section.find("p") or about_section.find("div", class_=re.compile(r"inline-show-more"))
        if about_text:
            profile["about"] = about_text.get_text(strip=True)

    # --- Experience ---
    experience_section = soup.find("section", class_=re.compile(r"experience"))
    if experience_section:
        positions = []
        items = experience_section.find_all("li", class_=re.compile(r"experience-item"))
        if not items:
            items = experience_section.find_all("li")
        for item in items[:10]:
            pos = {}
            title = item.find("h3")
            if title:
                pos["title"] = title.get_text(strip=True)
            company = item.find("h4") or item.find("a", class_=re.compile(r"experience-item__subtitle"))
            if company:
                pos["company"] = company.get_text(strip=True)
            date_range = item.find("span", class_=re.compile(r"date-range"))
            if date_range:
                pos["date_range"] = date_range.get_text(strip=True)
            if pos:
                positions.append(pos)
        if positions:
            profile["experience"] = positions

    # --- Education ---
    education_section = soup.find("section", class_=re.compile(r"education"))
    if education_section:
        schools = []
        items = education_section.find_all("li")
        for item in items[:5]:
            edu = {}
            school_name = item.find("h3")
            if school_name:
                edu["school"] = school_name.get_text(strip=True)
            degree = item.find("h4") or item.find("span", class_=re.compile(r"education__item--degree"))
            if degree:
                edu["degree"] = degree.get_text(strip=True)
            date_range = item.find("span", class_=re.compile(r"date-range"))
            if date_range:
                edu["date_range"] = date_range.get_text(strip=True)
            if edu:
                schools.append(edu)
        if schools:
            profile["education"] = schools

    # --- Skills ---
    skills_section = soup.find("section", class_=re.compile(r"skills"))
    if skills_section:
        skill_items = skills_section.find_all("span", class_=re.compile(r"skill-category"))
        if not skill_items:
            skill_items = skills_section.find_all("li")
        skills = [s.get_text(strip=True) for s in skill_items[:20] if s.get_text(strip=True)]
        if skills:
            profile["skills"] = skills

    # --- Certifications ---
    cert_section = soup.find("section", class_=re.compile(r"certifications"))
    if cert_section:
        certs = []
        items = cert_section.find_all("li")
        for item in items[:10]:
            cert = {}
            cert_name = item.find("h3")
            if cert_name:
                cert["name"] = cert_name.get_text(strip=True)
            issuer = item.find("h4")
            if issuer:
                cert["issuer"] = issuer.get_text(strip=True)
            if cert:
                certs.append(cert)
        if certs:
            profile["certifications"] = certs

    # --- Connection count (if visible) ---
    connections = soup.find("span", class_=re.compile(r"connections"))
    if connections:
        profile["connections"] = connections.get_text(strip=True)

    # --- Profile photo URL ---
    img_tag = soup.find("img", class_=re.compile(r"top-card__photo|profile-photo"))
    if img_tag and img_tag.get("src"):
        profile["photo_url"] = img_tag["src"]

    # --- JSON-LD structured data (LinkedIn sometimes embeds this) ---
    json_ld = soup.find("script", type="application/ld+json")
    if json_ld:
        try:
            ld_data = json.loads(json_ld.string)
            profile["_structured_data"] = ld_data
        except (json.JSONDecodeError, TypeError):
            pass

    return profile


def recon_single(username: str, session: requests.Session = None) -> ReconResult:
    """Run recon on a single target."""
    result = ReconResult(username)

    if session is None:
        session = build_session()

    normalized = normalize_target(username)
    result.target = normalized

    html, status = fetch_public_profile(session, normalized)

    if html is None:
        result.status = "error"
        result.errors.append(f"fetch_failed: {status}")
        return result

    if status == 999:
        result.status = "rate_limited"
        result.errors.append("LinkedIn returned 999 — rate limited. Rotate IP or wait.")
        return result

    if status == 404:
        result.status = "not_found"
        result.errors.append("Profile not found (404)")
        return result

    if status == 403:
        result.status = "blocked"
        result.errors.append("Access denied (403) — possible bot detection")
        return result

    if status != 200:
        result.status = "error"
        result.errors.append(f"unexpected_status: {status}")
        return result

    # Check for auth wall
    if "authwall" in html.lower() or "join linkedin" in html.lower():
        result.status = "auth_wall"
        result.errors.append("Profile behind auth wall — public view restricted")
        result.profile = parse_profile(html)
        return result

    result.profile = parse_profile(html)
    result.status = "success" if result.profile else "empty"

    return result


def recon_batch(targets: list, delay: tuple = DELAY_RANGE) -> list:
    """Run recon on multiple targets with delay between requests."""
    session = build_session()
    results = []

    for i, target in enumerate(targets):
        target = target.strip()
        if not target or target.startswith("#"):
            continue

        print(f"[*] ({i+1}/{len(targets)}) Recon: {target}", file=sys.stderr)
        result = recon_single(target, session)
        results.append(result)

        if result.status == "rate_limited":
            print("[!] Rate limited. Backing off 60s...", file=sys.stderr)
            time.sleep(60)
            session = build_session()
        elif i < len(targets) - 1:
            wait = random.uniform(*delay)
            print(f"    [{result.status}] Waiting {wait:.1f}s...", file=sys.stderr)
            time.sleep(wait)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="li_recon — LinkedIn Public Profile Reconnaissance Tool",
        epilog="OSINT tool for public data only. Respect rate limits. AGPL-3.0.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="LinkedIn profile URL or username",
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="File containing one target per line",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write JSON output to file instead of stdout",
    )
    parser.add_argument(
        "--delay",
        type=float,
        nargs=2,
        default=list(DELAY_RANGE),
        metavar=("MIN", "MAX"),
        help=f"Delay range between batch requests (default: {DELAY_RANGE})",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"li_recon {VERSION}",
    )

    args = parser.parse_args()

    if not args.target and not args.batch:
        parser.print_help()
        sys.exit(1)

    if args.batch:
        with open(args.batch, "r") as f:
            targets = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        results = recon_batch(targets, tuple(args.delay))
        output = json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False)
    else:
        result = recon_single(args.target)
        output = result.to_json()

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[+] Output written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()

