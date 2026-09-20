"""Heuristic detection of repeated "item cards" and their field selectors."""

import re
from collections import defaultdict

from bs4 import BeautifulSoup

_SAFE_CLASS = re.compile(r"^[A-Za-z_][\w-]*$")
_DATE_HINT = re.compile(r"date|time|posted|published|meta|byline", re.I)


def _sig(node):
    classes = [c for c in node.get("class", []) if _SAFE_CLASS.match(c)]
    return node.name + "".join("." + c for c in classes)


def _text(node):
    return node.get_text(" ", strip=True)


def _sig_short(node):
    """Tag plus only the first safe class: less brittle than the full class list."""
    classes = [c for c in node.get("class", []) if _SAFE_CLASS.match(c)]
    return node.name + ("." + classes[0] if classes else "")


def _css_for(node, item):
    """Shortest selector (relative to `item`) that finds `node` first."""
    chains = []
    for fn in (_sig_short, _sig):
        chain = []
        cur = node
        while cur is not None and cur is not item:
            chain.append(fn(cur))
            cur = cur.parent
        chain.reverse()
        chains.append(chain)
    for chain in chains:
        for start in range(len(chain) - 1, -1, -1):
            sel = " ".join(chain[start:])
            if item.select_one(sel) is node:
                return sel
    return " ".join(chains[-1])


def _shorten_item_selector(soup, node, full_sig):
    short = _sig_short(node)
    if short != full_sig and len(soup.select(short)) == len(soup.select(full_sig)):
        return short
    return full_sig


def _works(selector, samples, check):
    ok = 0
    for s in samples:
        try:
            n = s.select_one(selector)
        except Exception:  # noqa: BLE001 - invalid selector
            return 0
        if n is not None and check(n):
            ok += 1
    return ok / len(samples)


def _guess_fields(items):
    samples = items[:10]
    first = samples[0]
    fields = {}

    # Title/link: prefer the link with the longest text, ideally inside a heading
    anchors = [a for a in first.select("a[href]") if len(_text(a)) >= 10]
    heading_anchors = [a for a in anchors if a.find_parent(re.compile(r"^h[1-6]$"))
                       and first in a.parents]
    pool = heading_anchors or anchors
    if pool:
        best = max(pool, key=lambda a: len(_text(a)))
        sel = _css_for(best, first)
        if _works(sel, samples, lambda n: n.get("href")) >= 0.7:
            fields["title"] = {"selector": sel}
            fields["link"] = {"selector": sel, "attr": "href"}

    t = first.select_one("time")
    if t is not None:
        attr = "datetime" if t.get("datetime") else None
        fields["date"] = {"selector": "time", **({"attr": attr} if attr else {})}
    else:
        for n in first.find_all(True):
            cls = " ".join(n.get("class", []))
            if _DATE_HINT.search(cls) and re.search(r"\d", _text(n)) and len(_text(n)) < 40:
                fields["date"] = {"selector": _css_for(n, first)}
                break

    img = first.select_one("img")
    if img is not None:
        attr = "src" if img.get("src") else "data-src"
        fields["image"] = {"selector": _css_for(img, first), "attr": attr}

    for p in first.find_all(["p", "div", "span"]):
        if p.find(["p", "div"]):
            continue
        if len(_text(p)) >= 50 and not p.find_parent("a"):
            sel = _css_for(p, first)
            if _works(sel, samples, lambda n: len(_text(n)) >= 20) >= 0.6:
                fields["description"] = {"selector": sel}
                break
    return fields


def detect_candidates(html: str, max_candidates: int = 5):
    """Return candidate item selectors, best first, each with guessed fields."""
    soup = BeautifulSoup(html, "html.parser")
    groups = defaultdict(list)
    for node in soup.find_all(True):
        if node.name in ("html", "body", "head", "a", "script", "style"):
            continue
        if not node.select_one("a[href]"):
            continue
        groups[_sig(node)].append(node)

    results = []
    for sig, nodes in groups.items():
        if not 3 <= len(nodes) <= 300:
            continue
        # Reject nested repeats (e.g. a wrapper whose children are the real cards)
        if any(a in b.parents for a in nodes[:3] for b in nodes[:3] if a is not b):
            continue
        with_title = [n for n in nodes if any(len(_text(a)) >= 15 for a in n.select("a[href]"))]
        if len(with_title) < 3:
            continue
        fields = _guess_fields(with_title)
        sig = _shorten_item_selector(soup, nodes[0], sig)
        if "title" not in fields:
            continue
        score = len(with_title) * 1.0
        score += 8 if "date" in fields else 0
        score += 3 if "image" in fields else 0
        score += 3 if "description" in fields else 0
        score += 5 if sig.split(".")[0] in ("article", "li") else 0
        if len(nodes) - len(with_title) > len(with_title):
            score *= 0.5
        results.append({
            "item": sig,
            "count": len(with_title),
            "fields": fields,
            "sample_titles": [_text(n.select_one(fields["title"]["selector"]))
                              for n in with_title[:3] if n.select_one(fields["title"]["selector"])],
            "score": score,
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_candidates]
