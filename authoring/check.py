#!/usr/bin/env python3
"""Validate an EN/TR page pair against the handbook rules.

Usage:
  python3 authoring/check.py <slug> [--type topic|chapter-overview|part-overview]
                                    [--depth standard|deep]

--depth applies to topic pages only and must match the tier chosen for the page
(see project-instruction.md section 2.1).

Links to the companion Distributed Systems Handbook
(https://gorkemsari.github.io/distributed-systems/<locale>/<slug>/) are verified against
its sidebar when --ds-config points to a local copy of its astro.config.mjs
(or the DS_CONFIG environment variable is set); otherwise they produce a warning.

Resolves both files under src/content/docs/{en,tr}/, checks each page on its own,
then checks that the pair is structurally identical. Exit code 0 = pass, 1 = errors.
Warnings never fail the run but should be read.
"""
import argparse
import os
import re
import sys
from pathlib import Path

DOCS = Path("src/content/docs")
CONFIG = Path("astro.config.mjs")
ALLOWED_TAGS = {"text", "go", "java", "csharp", "python", "typescript", "rust", "yaml",
                "json", "sql", "shell", "toml", "proto", "mermaid"}
ASIDE = re.compile(r"^:::(note|tip|caution|danger)\b", re.M)
# EN prose words (hard min, soft min, max), mermaid (min, max), asides (min, max)
TIERS = {
    "standard": ((2000, 3000, 4500), (3, 6), (2, 3)),
    "deep": ((4500, 4500, 7000), (3, 8), (2, 4)),
}
LIMITS = {  # EN prose words (min, max), mermaid (min, max)
    "topic": ((2000, 4500), (3, 6)),
    "chapter-overview": ((700, 1800), (1, 3)),
    "part-overview": ((800, 2000), (1, 3)),
}


def resolve(locale, slug):
    for p in (DOCS / locale / f"{slug}.mdx", DOCS / locale / slug / "index.mdx"):
        if p.exists():
            return p
    return None


DS_SITE = "https://gorkemsari.github.io/distributed-systems"


def known_slugs(config=CONFIG):
    if config is None or not Path(config).exists():
        return None
    return set(re.findall(r"slug:\s*'([^']+)'", Path(config).read_text(encoding="utf-8")))


def split(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    return (m.group(1), m.group(2)) if m else (None, text)


def analyze(path, locale, slugs, ds_slugs=None):
    errors, warnings = [], []
    text = path.read_text(encoding="utf-8")
    fm, body = split(text)
    if fm is None:
        return {"errors": ["missing frontmatter"], "warnings": []}

    for key in ("title", "description", "lastUpdated"):
        if not re.search(rf"^{key}:\s*\S", fm, re.M):
            errors.append(f"frontmatter: missing {key}")
    if not re.search(r"^lastUpdated: \d{4}-\d{2}-\d{2}\s*$", fm, re.M):
        errors.append("frontmatter: lastUpdated must be an unquoted yyyy-mm-dd date")
    desc = re.search(r"^description:\s*(.*)$", fm, re.M)
    if desc:
        dv = desc.group(1).strip()
        if dv[:1] in "\"'" and dv[-1:] == dv[:1]:
            dv = dv[1:-1]
        if len(dv) > 160:
            errors.append(f"frontmatter: description is {len(dv)} characters (max 160)")
        elif len(dv) < 110:
            warnings.append(f"frontmatter: description is {len(dv)} characters (target 120-160)")
    title = re.search(r"^title:\s*(.*)$", fm, re.M)
    if title and re.match(r"""^["']?\d+(\.\d+)*\.?\s""", title.group(1)):
        errors.append("frontmatter: title must not carry the numeric prefix")
    for key in ("title", "description"):
        m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
        if m and ":" in m.group(1) and not m.group(1).startswith(('"', "'")):
            errors.append(f"frontmatter: {key} contains ':' and must be quoted")

    lines = text.split("\n")
    if any(l != "" and l.strip() == "" for l in lines):
        errors.append("blank line containing only whitespace")
    if "<!--" in text:
        errors.append("HTML comment found (unsupported in MDX)")

    blocks, prose_lines, in_fence, cur = [], [], False, None
    for l in body.split("\n"):
        if l.startswith("```"):
            if not in_fence:
                in_fence, cur = True, {"tag": l[3:].strip(), "lines": []}
            else:
                in_fence = False
                blocks.append(cur)
            continue
        if in_fence:
            cur["lines"].append(l)
        else:
            prose_lines.append(l)
    if in_fence:
        errors.append("unbalanced code fence")

    mermaid = [b for b in blocks if b["tag"] == "mermaid"]
    code = [b for b in blocks if b["tag"] != "mermaid"]
    for b in blocks:
        if not b["tag"]:
            errors.append("untagged code fence")
        elif b["tag"] not in ALLOWED_TAGS:
            errors.append(f"fence tag not allowed: {b['tag']}")
        bad = [l for l in b["lines"] if any(ord(c) > 127 for c in l)]
        if bad:
            errors.append(f"non-ASCII inside ```{b['tag']} fence: {bad[0][:60]!r}")
    if len(code) > 2:
        errors.append(f"{len(code)} code blocks (max 2)")
    for b in code:
        if len(b["lines"]) > 25:
            errors.append(f"```{b['tag']} block has {len(b['lines'])} lines (max ~20)")

    prose = "\n".join(prose_lines)
    stripped = re.sub(r"`[^`\n]*`", "", prose)
    stripped = re.sub(r"\]\([^)]*\)", "]", stripped)
    if re.search(r"[{}]", stripped):
        errors.append("unescaped { or } in prose (wrap in inline code)")
    m = re.search(r"<[A-Za-z/]", stripped)
    if m:
        errors.append(f"'<' followed by a letter in prose: {stripped[m.start():m.start()+30]!r}")

    words_text = "\n".join(l for l in stripped.split("\n")
                           if not l.lstrip().startswith("|") and not l.startswith(":::"))
    words = len(re.findall(r"[^\s#*_>\-|]+", words_text))

    # every diagram must be followed by an italic caption
    for m in re.finditer(r"```mermaid\n.*?\n```\n+([^\n]*)", body, re.S):
        if not re.match(r"^\*[^*].*\*$", m.group(1).strip()):
            errors.append("mermaid diagram not followed by an italic caption line")
            break

    links = re.findall(r"\]\((/ai-systems-architecture/[^)\s]+)\)", text)
    for link in links:
        lm = re.match(r"^/ai-systems-architecture/(en|tr)/(.+?)/?(#.*)?$", link)
        if not lm:
            errors.append(f"malformed link: {link}")
            continue
        if lm.group(1) != locale:
            errors.append(f"link points to wrong locale: {link}")
        if slugs is not None and lm.group(2) not in slugs:
            errors.append(f"link to unknown slug: {link}")
        if not link.endswith("/") and "#" not in link:
            warnings.append(f"link without trailing slash: {link}")

    ds_links = re.findall(r"\]\((" + re.escape(DS_SITE) + r"/[^)\s]+)\)", text)
    for link in ds_links:
        lm = re.match(r"^" + re.escape(DS_SITE) + r"/(en|tr)/(.+?)/?(#.*)?$", link)
        if not lm:
            errors.append(f"malformed DS handbook link: {link}")
            continue
        if lm.group(1) != locale:
            errors.append(f"DS handbook link points to wrong locale: {link}")
        if ds_slugs is not None and lm.group(2) not in ds_slugs:
            errors.append(f"DS handbook link to unknown slug: {link}")
        if not link.endswith("/") and "#" not in link:
            warnings.append(f"DS handbook link without trailing slash: {link}")
    if ds_links and ds_slugs is None:
        warnings.append(f"{len(ds_links)} DS handbook link(s) not verified (pass --ds-config)")

    headings = re.findall(r"^(#{2,4}) ", body, re.M)
    levels = [len(h) for h in headings]
    for a, b in zip([2] + levels, levels):
        if b > a + 1:
            errors.append("heading level skipped")
            break
    h2 = [h for h in re.findall(r"^## (.*)$", body, re.M)]

    return {
        "errors": errors, "warnings": warnings, "words": words,
        "mermaid": mermaid, "code": code, "h2": h2, "levels": levels,
        "asides": ASIDE.findall(body), "tables": len(re.findall(r"^\|[-| :]+\|$", body, re.M)),
        "links": [re.sub(r"/ai-systems-architecture/(en|tr)/", "/", l) for l in links]
                 + [re.sub(r"/(en|tr)/", "/ds/", l, count=1) for l in ds_links],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--type", default="topic", choices=list(LIMITS))
    ap.add_argument("--depth", default="standard", choices=list(TIERS))
    ap.add_argument("--ds-config", default=os.environ.get("DS_CONFIG"),
                    help="path to the Distributed Systems Handbook astro.config.mjs")
    a = ap.parse_args()
    slugs = known_slugs()
    ds_slugs = known_slugs(a.ds_config) if a.ds_config else None
    errors, warnings = [], []
    if slugs is None:
        warnings.append("astro.config.mjs not found; link targets not verified")
    elif a.slug not in slugs:
        errors.append(f"slug not in sidebar: {a.slug}")

    res = {}
    for loc in ("en", "tr"):
        p = resolve(loc, a.slug)
        if not p:
            errors.append(f"[{loc}] file not found for slug {a.slug}")
            continue
        r = analyze(p, loc, slugs, ds_slugs)
        res[loc] = r
        errors += [f"[{loc}] {e}" for e in r["errors"]]
        warnings += [f"[{loc}] {w}" for w in r["warnings"]]

    (wmin, wmax), (dmin, dmax) = LIMITS[a.type]
    amin, amax = 2, 3
    if a.type == "topic":
        (hard_min, soft_min, wmax), (dmin, dmax), (amin, amax) = TIERS[a.depth]
    if "en" in res:
        en = res["en"]
        w = en["words"]
        if a.type != "topic":
            if w < wmin:
                errors.append(f"[en] prose {w} words, below minimum {wmin}")
            elif w > wmax:
                warnings.append(f"[en] prose {w} words, above target {wmax}")
        elif a.depth == "standard":
            if w < hard_min:
                errors.append(f"[en] prose {w} words: below {hard_min}, the page is incomplete")
            elif w < soft_min:
                warnings.append(f"[en] prose {w} words, below {soft_min}: re-check the depth standard")
            elif w > wmax:
                errors.append(f"[en] prose {w} words exceeds the standard tier ({wmax}): if the content "
                              "genuinely needs it, classify the page as deep (with justification); "
                              "otherwise remove repetition, never substance")
        else:
            if w > wmax:
                errors.append(f"[en] prose {w} words exceeds the deep tier ({wmax}): the page covers more "
                              "than one topic; refocus it and record a split proposal")
            elif w < 4000:
                errors.append(f"[en] prose {w} words is a standard-length page; classify it as standard")
            elif w < soft_min:
                warnings.append(f"[en] prose {w} words fits the standard tier; deep is not justified by length")
        n = len(en["mermaid"])
        if not dmin <= n <= dmax:
            errors.append(f"[en] {n} mermaid diagrams (expected {dmin}-{dmax})")
        kinds = {b["lines"][0].split()[0] for b in en["mermaid"] if b["lines"]}
        if a.type == "topic" and len(kinds) < 2:
            errors.append("[en] diagrams must use at least two diagram types")
        if a.type == "topic":
            if not amin <= len(en["asides"]) <= amax:
                errors.append(f"[en] {len(en['asides'])} asides (expected {amin}-{amax} for {a.depth})")
            if en["tables"] < 1:
                errors.append("[en] no table found")
            if not any(h.strip().lower() == "further reading" for h in en["h2"]):
                errors.append("[en] missing '## Further Reading'")
            if not 4 <= len(en["h2"]) - 1 <= 7:
                warnings.append(f"[en] {len(en['h2']) - 1} ## sections (target 4-6)")

    if "en" in res and "tr" in res:
        en, tr = res["en"], res["tr"]
        if [b["lines"] for b in en["mermaid"]] != [b["lines"] for b in tr["mermaid"]]:
            errors.append("pair: mermaid diagrams differ between EN and TR (must be identical)")
        en_code = [[l for l in b["lines"]] for b in en["code"]]
        tr_code = [[l for l in b["lines"]] for b in tr["code"]]
        if en_code != tr_code:
            errors.append("pair: code blocks differ between EN and TR (must be identical)")
        if en["levels"] != tr["levels"]:
            errors.append(f"pair: heading structure differs (en {en['levels']} vs tr {tr['levels']})")
        if en["asides"] != tr["asides"]:
            errors.append(f"pair: asides differ (en {en['asides']} vs tr {tr['asides']})")
        if en["tables"] != tr["tables"]:
            errors.append("pair: table count differs")
        if sorted(en["links"]) != sorted(tr["links"]):
            errors.append("pair: cross-reference targets differ")
        ratio = tr["words"] / max(en["words"], 1)
        if not 0.75 <= ratio <= 1.15:
            warnings.append(f"pair: TR/EN word ratio {ratio:.2f} (expected ~0.85-1.0); check for omissions")

    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    if "en" in res:
        print(f"en words={res['en']['words']} diagrams={len(res['en']['mermaid'])} "
              f"code={len(res['en']['code'])} asides={len(res['en']['asides'])} tables={res['en']['tables']}")
    if a.type == "topic":
        print(f"depth={a.depth}")
    print("PASS" if not errors else f"FAIL ({len(errors)} errors)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
