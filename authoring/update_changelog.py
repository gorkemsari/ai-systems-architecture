#!/usr/bin/env python3
"""Regenerate the "What's New" pages and the RSS feeds from the generation queue.

Outputs (all fully rewritten, deterministic for the same queue):
  src/content/docs/en/whats-new.mdx   newest published pages first, grouped by date
  src/content/docs/tr/whats-new.mdx   the same in Turkish
  public/rss.xml                      English feed (latest 50 pages)
  public/rss-tr.xml                   Turkish feed (latest 50 pages)

A page counts as published when its row in authoring/queue.md is `done`; its
date is the yyyy-mm-dd at the start of the row's Note. Titles and descriptions
come from each page's own frontmatter, so both languages stay accurate.

Usage: python3 authoring/update_changelog.py
"""
import html
import importlib.util
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "authoring/queue.md"
CONFIG = ROOT / "astro.config.mjs"
DOCS = ROOT / "src/content/docs"
SITE = "https://gorkemsari.github.io/ai-systems-architecture"
BASE = "/ai-systems-architecture"
FEED_ITEMS = 50

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

TEXT = {
    "en": {
        "title": "What's New",
        "description": "Pages published or rewritten in the AI Systems Architecture Handbook, "
                       "newest first, with an RSS feed to follow new topics as they appear.",
        "intro": "New pages are published regularly, in English and Turkish, and earlier pages "
                 "are rewritten as the writing standard improves. This list shows the most recent "
                 "first. To follow along, subscribe to the [RSS feed]({feed}) in any feed reader.",
        "feed": f"{BASE}/rss.xml",
        "feed_title": "AI Systems Architecture Handbook",
        "feed_desc": "New and rewritten pages of the AI Systems Architecture Handbook.",
        "overview": {"part-overview": "Part overview", "chapter-overview": "Chapter overview"},
        "empty": "No pages have been published yet.",
    },
    "tr": {
        "title": "Yenilikler",
        "description": "AI Systems Architecture Handbook'ta yayımlanan ya da yeniden yazılan sayfalar, "
                       "en yeniden eskiye; yeni konuları takip etmek için RSS beslemesiyle.",
        "intro": "Yeni sayfalar düzenli olarak İngilizce ve Türkçe yayımlanıyor; yazım standardı "
                 "geliştikçe önceki sayfalar da yeniden yazılıyor. Liste en yeniden eskiye "
                 "sıralıdır. Takip etmek için [RSS beslemesine]({feed}) herhangi bir okuyucudan "
                 "abone olabilirsiniz.",
        "feed": f"{BASE}/rss-tr.xml",
        "feed_title": "AI Systems Architecture Handbook (Türkçe)",
        "feed_desc": "AI Systems Architecture Handbook'un yeni ve yeniden yazılan sayfaları.",
        "overview": {"part-overview": "Bölüm genel bakışı", "chapter-overview": "Alt bölüm genel bakışı"},
        "empty": "Henüz yayımlanmış sayfa yok.",
    },
}


def load_parse():
    spec = importlib.util.spec_from_file_location("build_queue", ROOT / "authoring/build_queue.py")
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, sys.argv[:1]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod.parse


def published():
    """Return [(date, queue_index, slug, type)] for done rows."""
    out = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not (cells and cells[0].isdigit()) or cells[1] != "done":
            continue
        slug = (cells[4] if len(cells) == 7 else cells[3]).strip("`")
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", cells[-1])
        if m:
            out.append((m.group(1), int(cells[0]), slug, cells[2]))
    return sorted(out, key=lambda r: (r[0], r[1]), reverse=True)


def frontmatter(locale, slug):
    for p in (DOCS / locale / f"{slug}.mdx", DOCS / locale / slug / "index.mdx"):
        if p.exists():
            fm = re.match(r"^---\n(.*?)\n---", p.read_text(encoding="utf-8"), re.S).group(1)
            def field(name):
                m = re.search(rf"^{name}:\s*(.*)$", fm, re.M)
                if not m:
                    return ""
                v = m.group(1).strip()
                if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                    v = v[1:-1]
                return v.replace('\\"', '"')
            return field("title"), field("description")
    return slug, ""


def mdx_text(s):
    # Escape characters that MDX would parse as JSX or expressions.
    return s.replace("{", "&#123;").replace("}", "&#125;").replace("<", "&lt;")


def human_date(d, locale):
    y, m, day = (int(x) for x in d.split("-"))
    months = TR_MONTHS if locale == "tr" else EN_MONTHS
    return f"{day} {months[m - 1]} {y}"


def render_page(locale, rows, context):
    t = TEXT[locale]
    lines = ["---", f'title: "{t["title"]}"', f'description: "{t["description"]}"']
    if rows:
        lines.append(f"lastUpdated: {rows[0][0]}")
    lines += ["---", "", t["intro"].format(feed=t["feed"]), ""]
    if not rows:
        lines.append(t["empty"])
    current = None
    for date, _, slug, typ in rows:
        if date != current:
            current = date
            if lines[-1] != "":
                lines.append("")
            lines += [f"## {human_date(date, locale)}", ""]
        title, _ = frontmatter(locale, slug)
        where = context[slug][locale]
        kind = t["overview"].get(typ)
        suffix = kind if kind else where  # an overview's title already names its chapter or part
        lines.append(f"- [{mdx_text(title)}]({BASE}/{locale}/{slug}/) · {mdx_text(suffix)}")
    return "\n".join(lines).rstrip() + "\n"


def render_feed(locale, rows):
    t = TEXT[locale]
    items = []
    for date, _, slug, _ in rows[:FEED_ITEMS]:
        title, desc = frontmatter(locale, slug)
        url = f"{SITE}/{locale}/{slug}/"
        when = datetime.strptime(date, "%Y-%m-%d").replace(hour=6, tzinfo=timezone.utc)
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(title)}</title>\n"
            f"      <link>{url}</link>\n"
            f'      <guid isPermaLink="false">{slug}#{date}</guid>\n'
            f"      <pubDate>{format_datetime(when)}</pubDate>\n"
            f"      <description>{html.escape(desc)}</description>\n"
            "    </item>")
    last = format_datetime(datetime.strptime(rows[0][0], "%Y-%m-%d").replace(hour=6, tzinfo=timezone.utc)) if rows else ""
    feed_url = f"{SITE}/{t['feed'].split('/', 2)[-1]}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{html.escape(t['feed_title'])}</title>\n"
        f"    <link>{SITE}/{locale}/whats-new/</link>\n"
        f'    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>\n'
        f"    <description>{html.escape(t['feed_desc'])}</description>\n"
        f"    <language>{locale}</language>\n"
        + (f"    <lastBuildDate>{last}</lastBuildDate>\n" if last else "")
        + "\n".join(items) + ("\n" if items else "")
        + "  </channel>\n</rss>\n")


def main():
    entries = load_parse()(CONFIG.read_text(encoding="utf-8"))
    context = {}
    for e in entries:
        if e["type"] == "part-overview" or not e["chapter"]:
            en, tr = e["part"]
        else:
            en, tr = e["chapter"]
        strip = lambda s: re.sub(r"^([IVXLC]+|\d+(\.\d+)*)\.\s*", "", s)
        context[e["slug"]] = {"en": strip(en), "tr": strip(tr)}
    rows = [r for r in published() if r[2] in context]
    for locale in ("en", "tr"):
        (DOCS / locale / "whats-new.mdx").write_text(render_page(locale, rows, context), encoding="utf-8")
    (ROOT / "public/rss.xml").write_text(render_feed("en", rows), encoding="utf-8")
    (ROOT / "public/rss-tr.xml").write_text(render_feed("tr", rows), encoding="utf-8")
    print(f"What's New: {len(rows)} published pages; feeds: {min(len(rows), FEED_ITEMS)} items each")


if __name__ == "__main__":
    main()
