"""Streamlit UI for adding and managing site2rss feeds.

Run locally:  streamlit run ui/app.py
In a Codespace it starts automatically (see .devcontainer/devcontainer.json).
"""

import re
import subprocess
import sys
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import site2rss  # noqa: E402
from detect import detect_candidates  # noqa: E402

CONFIGS = ROOT / "configs"
UA_DEFAULT = "Mozilla/5.0 (compatible; site2rss/1.0)"

st.set_page_config(page_title="site2rss", page_icon="📡", layout="wide")


# ---------- helpers ----------

def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def pages_base():
    """https://<owner>.github.io/<repo>/ derived from the git remote."""
    out = git("remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", out)
    return f"https://{m.group(1)}.github.io/{m.group(2)}/" if m else None


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "feed"


def publish(message, paths):
    """Commit the given paths and push; returns (ok, log)."""
    log = []
    for cmd in (["add", "-A", *paths], ["commit", "-m", message],
                ["pull", "--rebase", "--autostash"], ["push"]):
        r = git(*cmd)
        log.append(f"$ git {' '.join(cmd)}\n{r.stdout}{r.stderr}".strip())
        if r.returncode != 0 and cmd[0] != "commit":
            return False, "\n\n".join(log)
        if r.returncode != 0 and "nothing to commit" not in r.stdout + r.stderr:
            return False, "\n\n".join(log)
    return True, "\n\n".join(log)


def field(cfg_field):
    cfg_field = cfg_field or {}
    return cfg_field.get("selector", ""), cfg_field.get("attr", "")


def build_cfg(v):
    def f(sel, attr=""):
        if not sel.strip():
            return None
        d = {"selector": sel.strip()}
        if attr.strip():
            d["attr"] = attr.strip()
        return d

    sel = {"item": v["item"].strip(), "title": f(v["title"]), "link": f(v["link"], v["link_attr"])}
    for name in ("date", "description", "image"):
        d = f(v[name], v[name + "_attr"])
        if d:
            sel[name] = d
    return {
        "feed": {"title": v["title_text"], "link": v["url"],
                 "description": v["desc"] or f"Unofficial feed for {v['url']}",
                 "language": v["lang"]},
        "source": {"url": v["url"], "base_url": v["base_url"], "user_agent": v["ua"]},
        "selectors": sel,
        "output": f"output/{v['slug']}.xml",
        "limit": int(v["limit"]),
    }


def show_preview(cfg):
    try:
        items = site2rss.scrape_items(cfg)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Preview failed: {exc}")
        return None
    if not items:
        st.warning("No items extracted. Check the item/title/link selectors.")
        return items
    st.success(f"{len(items)} items extracted")
    rows = [{"title": i["title"], "link": i["link"],
             "date": i["pub_date"].strftime("%Y-%m-%d %H:%M") if i["pub_date"] else "",
             "image": bool(i["image"])} for i in items]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    return items


# ---------- pages ----------

def page_add():
    st.header("Add a site")
    c1, c2 = st.columns([4, 1])
    url = c1.text_input("Page URL (listing page with the articles)", placeholder="https://example.com/news")
    ua = c2.text_input("User-Agent", UA_DEFAULT)

    if st.button("Analyze page", type="primary", disabled=not url):
        try:
            html = site2rss.fetch_html(url, ua)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not fetch the page: {exc}")
            st.stop()
        st.session_state.html_len = len(html)
        st.session_state.candidates = detect_candidates(html)
        st.session_state.url = url
        st.session_state.ua = ua
        st.session_state.pop("chosen", None)
        for k in [k for k in st.session_state if k.startswith("f_")]:
            del st.session_state[k]

    cands = st.session_state.get("candidates")
    if cands is None:
        st.info("Paste a URL and press *Analyze page*.")
        return
    if not cands:
        st.warning(
            f"No repeated article cards were found in the {st.session_state.html_len:,}-byte HTML. "
            "The site probably renders its list with JavaScript, which this tool can't see yet. "
            "You can still try entering selectors manually below."
        )
        cands = [{"item": "", "count": 0, "fields": {}, "sample_titles": []}]

    labels = [f"{c['item'] or '(manual)'}  -  {c['count']} items  -  e.g. {(c['sample_titles'] or [''])[0][:60]}"
              for c in cands]
    idx = st.selectbox("Detected article blocks", range(len(cands)), format_func=labels.__getitem__)
    chosen = cands[idx]
    if st.session_state.get("chosen") != (url, idx):
        st.session_state.chosen = (url, idx)
        fl = chosen["fields"]
        defaults = {
            "item": chosen["item"],
            "title": field(fl.get("title"))[0], "link": field(fl.get("link"))[0],
            "link_attr": field(fl.get("link"))[1] or "href",
            "date": field(fl.get("date"))[0], "date_attr": field(fl.get("date"))[1],
            "description": field(fl.get("description"))[0], "description_attr": "",
            "image": field(fl.get("image"))[0], "image_attr": field(fl.get("image"))[1],
        }
        for k, val in defaults.items():
            st.session_state["f_" + k] = val

    src_url = st.session_state.url
    base = re.match(r"https?://[^/]+", src_url)
    st.subheader("Selectors")
    a, b = st.columns(2)
    v = {"url": src_url, "ua": st.session_state.ua, "base_url": base.group(0) if base else src_url}
    v["item"] = a.text_input("Item (one per article)", key="f_item")
    for name, label in (("title", "Title"), ("link", "Link"), ("date", "Date (optional)"),
                        ("description", "Description (optional)"), ("image", "Image (optional)")):
        col = a if name in ("title", "date", "image") else b
        v[name] = col.text_input(label + " selector", key="f_" + name)
    v["link_attr"] = b.text_input("Link attribute", key="f_link_attr")
    v["date_attr"] = b.text_input("Date attribute (e.g. datetime)", key="f_date_attr")
    v["description_attr"] = ""
    v["image_attr"] = b.text_input("Image attribute (src / data-src)", key="f_image_attr")

    st.subheader("Feed details")
    d1, d2, d3, d4 = st.columns([3, 3, 1, 1])
    host = re.sub(r"^https?://(www\.)?", "", src_url).split("/")[0]
    v["title_text"] = d1.text_input("Feed title", value=host, key="f_feedtitle")
    v["slug"] = slugify(d2.text_input("File name (slug)", value=slugify(host + "_" + src_url.rstrip("/").split("/")[-1]),
                                      key="f_slug"))
    v["lang"] = d3.text_input("Language", "en", key="f_lang")
    v["limit"] = d4.number_input("Max items", 5, 200, 40, key="f_limit")
    v["desc"] = ""

    if not (v["item"] and v["title"] and v["link"]):
        st.info("Item, title and link selectors are required.")
        return
    cfg = build_cfg(v)
    st.subheader("Preview")
    items = show_preview(cfg)

    with st.expander("Generated YAML"):
        st.code(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), language="yaml")

    path = CONFIGS / f"{v['slug']}.yaml"
    if path.exists():
        st.warning(f"configs/{path.name} already exists and will be overwritten.")
    push = st.checkbox("Commit and push (publishes the feed via GitHub Actions)", value=True)
    if st.button("Save site", type="primary", disabled=not items):
        CONFIGS.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        st.success(f"Saved configs/{path.name}")
        if push:
            ok, log = publish(f"Add feed: {v['slug']}", [f"configs/{path.name}"])
            (st.success if ok else st.error)("Pushed. The workflow will publish it shortly." if ok else "Push failed.")
            st.code(log)
            base_url = pages_base()
            if ok and base_url:
                st.write(f"Feed URL (after the workflow finishes): {base_url}{v['slug']}.xml")


def page_manage():
    st.header("Existing feeds")
    files = sorted(CONFIGS.glob("*.yaml"))
    if not files:
        st.info("No feeds configured yet.")
        return
    base_url = pages_base()
    for p in files:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
        out_name = Path(cfg.get("output", f"{p.stem}.xml")).name
        with st.expander(f"{cfg['feed']['title']}  ({p.name})"):
            st.write(f"Source: {cfg['source']['url']}")
            if base_url:
                st.write(f"Feed: {base_url}{out_name}")
            text = st.text_area("YAML", p.read_text(encoding="utf-8"), height=320, key="y_" + p.name)
            c1, c2, c3 = st.columns(3)
            if c1.button("Test now", key="t_" + p.name):
                try:
                    show_preview(yaml.safe_load(text))
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
            if c2.button("Save and push", key="s_" + p.name):
                try:
                    yaml.safe_load(text)  # validate that it parses
                except yaml.YAMLError as exc:
                    st.error(f"Invalid YAML: {exc}")
                else:
                    p.write_text(text, encoding="utf-8")
                    ok, log = publish(f"Update feed: {p.stem}", [f"configs/{p.name}"])
                    (st.success if ok else st.error)("Saved and pushed." if ok else "Push failed.")
                    st.code(log)
            if c3.button("Delete", key="d_" + p.name):
                p.unlink()
                ok, log = publish(f"Remove feed: {p.stem}", [f"configs/{p.name}"])
                (st.success if ok else st.error)("Deleted and pushed." if ok else "Push failed.")
                st.code(log)


st.title("📡 site2rss")
page = st.sidebar.radio("Menu", ["Add a site", "Existing feeds"])
(page_add if page == "Add a site" else page_manage)()
