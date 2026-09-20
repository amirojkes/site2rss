#!/usr/bin/env python3
"""
site2rss.py — Generic RSS generator for websites that don't publish a feed.

Each site is described by a small YAML config (CSS selectors, no code).
The script fetches the page, extracts items with BeautifulSoup, and writes
a standard RSS 2.0 file you can point any feed reader at.

Usage:
    # Process a single site config, write feed next to it or to --out
    python3 site2rss.py --config configs/armyrecognition_news.yaml

    # Process every *.yaml config in a directory (for cron)
    python3 site2rss.py --configdir configs --outdir output

Config file format (see configs/armyrecognition_news.yaml for a full example):

    feed:
      title: "Army Recognition - Land Defense News"
      link: "https://www.armyrecognition.com/news/army-news"
      description: "Auto-generated feed"
      language: "en"

    source:
      url: "https://www.armyrecognition.com/news/army-news"
      base_url: "https://www.armyrecognition.com"
      user_agent: "Mozilla/5.0 (compatible; site2rss/1.0)"

    selectors:
      item: ".el-item"                # one CSS selector per news item/card
      title: {selector: ".el-title a"}
      link:  {selector: ".el-title a", attr: "href"}
      date:  {selector: "time", attr: "datetime"}   # optional
      description: {selector: "p"}                  # optional
      image: {selector: "img", attr: "src"}          # optional

    output: "output/armyrecognition_news.xml"
    limit: 40
"""

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from feedgen.feed import FeedGenerator

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 site2rss/1.0"
)
DEFAULT_TIMEOUT = 20


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for required in ("feed", "source", "selectors"):
        if required not in cfg:
            raise ValueError(f"{path}: missing required top-level key '{required}'")
    if "item" not in cfg["selectors"]:
        raise ValueError(f"{path}: selectors.item is required")
    for required_field in ("title", "link"):
        if required_field not in cfg["selectors"]:
            raise ValueError(f"{path}: selectors.{required_field} is required")
    return cfg


def fetch_html(url: str, user_agent: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.8"},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.text


def extract_field(item, field_cfg, base_url: str):
    """field_cfg is a dict like {selector: '...', attr: 'href'} or None."""
    if not field_cfg:
        return None
    selector = field_cfg.get("selector")
    attr = field_cfg.get("attr")
    node = item.select_one(selector) if selector else item
    if node is None:
        return None
    if attr:
        value = node.get(attr)
    else:
        value = node.get_text(strip=True)
    if not value:
        return None
    value = value.strip()
    # Resolve relative URLs for link/image style fields
    if attr in ("href", "src") and base_url:
        value = urljoin(base_url, value)
    return value


def parse_date(raw: str):
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
    except (ValueError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def make_guid(link: str, title: str) -> str:
    basis = link or title or ""
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def scrape_items(cfg: dict) -> list:
    source = cfg["source"]
    selectors = cfg["selectors"]
    base_url = source.get("base_url", source["url"])
    user_agent = source.get("user_agent", DEFAULT_UA)

    html = fetch_html(source["url"], user_agent)
    soup = BeautifulSoup(html, "html.parser")

    nodes = soup.select(selectors["item"])
    items = []
    seen_links = set()

    for node in nodes:
        title = extract_field(node, selectors.get("title"), base_url)
        link = extract_field(node, selectors.get("link"), base_url)
        if not title or not link:
            continue  # skip anything we can't meaningfully render
        if link in seen_links:
            continue
        seen_links.add(link)

        description = extract_field(node, selectors.get("description"), base_url)
        image = extract_field(node, selectors.get("image"), base_url)
        date_raw = extract_field(node, selectors.get("date"), base_url)
        pub_date = parse_date(date_raw)

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "image": image,
                "pub_date": pub_date,
                "guid": make_guid(link, title),
            }
        )

    limit = cfg.get("limit")
    if limit:
        items = items[:limit]
    return items


def build_feed(cfg: dict, items: list) -> bytes:
    feed_cfg = cfg["feed"]
    fg = FeedGenerator()
    fg.title(feed_cfg["title"])
    fg.link(href=feed_cfg["link"], rel="alternate")
    fg.description(feed_cfg.get("description") or feed_cfg["title"])
    fg.language(feed_cfg.get("language", "en"))
    fg.lastBuildDate(datetime.now(timezone.utc))

    # feedgen wants entries added in the order they'll appear; most feeds
    # expect newest-first, which matches how the site usually lists items.
    for it in items:
        fe = fg.add_entry()
        fe.title(it["title"])
        fe.link(href=it["link"])
        fe.guid(it["guid"], permalink=False)
        if it["description"]:
            fe.description(it["description"])
        if it["image"]:
            fe.enclosure(it["image"], 0, "image/jpeg")
        if it["pub_date"]:
            fe.pubDate(it["pub_date"])

    return fg.rss_str(pretty=True)


def process_config(path: Path, outdir: Path = None) -> Path:
    cfg = load_config(path)
    items = scrape_items(cfg)
    if not items:
        print(f"[warn] {path}: no items extracted — check your selectors", file=sys.stderr)
    xml_bytes = build_feed(cfg, items)

    if outdir:
        out_path = outdir / (cfg.get("output") and Path(cfg["output"]).name or f"{path.stem}.xml")
    else:
        out_path = Path(cfg.get("output", f"output/{path.stem}.xml"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(xml_bytes)
    print(f"[ok] {path} -> {out_path} ({len(items)} items)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", type=Path, help="Path to a single site config YAML file")
    group.add_argument("--configdir", type=Path, help="Directory containing one or more *.yaml site configs")
    parser.add_argument("--outdir", type=Path, default=None, help="Override output directory for generated feeds")
    args = parser.parse_args()

    configs = [args.config] if args.config else sorted(args.configdir.glob("*.yaml"))
    if not configs:
        print("No config files found.", file=sys.stderr)
        sys.exit(1)

    exit_code = 0
    for cfg_path in configs:
        try:
            process_config(cfg_path, outdir=args.outdir)
        except Exception as exc:  # noqa: BLE001 - report and keep going in batch mode
            print(f"[error] {cfg_path}: {exc}", file=sys.stderr)
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
