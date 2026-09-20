# site2rss

A small, generic tool that turns any listing page (news, blog, search
results...) into a standard RSS 2.0 feed, using CSS selectors defined in a
YAML config file — no code changes needed per site.

## Install

```bash
pip install -r requirements.txt --break-system-packages
```

## Run

Single site:

```bash
python3 site2rss.py --config configs/armyrecognition_news.yaml
```

All configs in a folder (useful for cron, one command regenerates every
feed):

```bash
python3 site2rss.py --configdir configs --outdir output
```

Each run overwrites the output XML file in place, so pointing a cron job or
a feed reader's polling interval at it keeps it current.

## Adding a new site

1. Open the listing page you want (e.g. the site's "News" page) in a
   browser and use "Inspect Element" on one item in the list.
2. Find:
   - A CSS selector that matches **every** repeated item (a card, `<li>`,
     `<article>`, etc.) — this is `selectors.item`.
   - Within one item, the selector for the title/link (usually the same
     `<a>` tag), and, if present, a date element and an image.
3. Copy `configs/armyrecognition_news.yaml` to a new file, e.g.
   `configs/mysite_news.yaml`, and adjust:
   - `feed.title` / `feed.link` / `feed.description`
   - `source.url` (the page to scrape) and `source.base_url` (for
     resolving relative links/images)
   - `selectors.item`, `selectors.title`, `selectors.link`
   - `selectors.date` and `selectors.image` if available (optional)
   - `output` — where to write the generated `.xml`
4. Run `python3 site2rss.py --config configs/mysite_news.yaml` and check
   the output file opens correctly in a feed reader.

### Selector field format

Every field (`title`, `link`, `date`, `description`, `image`) is either
omitted, or a small object:

```yaml
title:
  selector: ".card-title a"   # CSS selector, relative to the item node
  attr: "href"                # optional: read this attribute instead of
                               # the element's text (e.g. href, src,
                               # datetime)
```

If `attr` is omitted, the element's visible text is used. `href` and `src`
values are automatically resolved against `source.base_url` so relative
links become absolute.

### Notes and limitations

- This scrapes static server-rendered HTML. If a site loads its list via
  JavaScript after page load (infinite scroll, React-rendered cards with
  no content in the initial HTML), this approach won't see the items —
  that needs a headless browser instead, which is a different tool.
- Respect the target site's robots.txt and terms of use, and keep your
  polling interval reasonable (e.g. every 30–60 minutes) to avoid
  hammering their server.
- If a site changes its HTML/CSS, the selectors in that site's config
  will need updating — this is the same maintenance cost every
  scraper-based RSS generator (RSS-Bridge included) has.

## Web UI for adding sites (GitHub Codespaces)

You can add and manage feeds from a browser UI, with no local install:

1. On the repo page click **Code → Codespaces → Create codespace on main**.
2. The Streamlit UI starts automatically and opens in a browser tab
   (or open the forwarded port 8501 from the *Ports* tab).
3. **Add a site**: paste a listing-page URL and press *Analyze page*. The
   tool detects repeated article blocks and guesses the title, link, date,
   image and description selectors. Edit them, check the live preview, then
   press *Save site*. This writes `configs/<name>.yaml`, commits and pushes,
   and the *Update RSS feeds* workflow publishes the feed.
4. **Existing feeds**: view, test, edit or delete the configured feeds.

To run it locally instead: `pip install -r requirements-ui.txt && streamlit run ui/app.py`.

If the analyzer finds no article blocks, the site most likely renders its
list with JavaScript (see limitations below).

## Cron example

Regenerate every configured feed every 30 minutes and serve `output/` with
any static file server (nginx, `python -m http.server`, etc.):

```
*/30 * * * * cd /path/to/site2rss && /usr/bin/python3 site2rss.py --configdir configs --outdir output >> site2rss.log 2>&1
```
