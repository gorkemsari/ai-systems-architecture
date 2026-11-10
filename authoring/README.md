# Authoring Pipeline

Pages are generated one EN/TR pair per scheduled run and pushed directly to `main`. Each push
triggers the GitHub Pages deploy; queue-only commits (failed runs, empty queue) carry
`[skip ci]` and do not deploy. Commit subjects are the page titles.

| File | Purpose |
|---|---|
| `project-instruction.md` | Binding writing specification for every page |
| `examples/{en,tr}/` | Quality reference pages |
| `RUN.md` | Step-by-step procedure each scheduled run follows |
| `queue.md` | Generation order and status, built from the sidebar |
| `log.md` | One line per run |
| `check.py` | Validator: `python3 authoring/check.py <slug> --type <type> --depth <tier> [--ds-config <path>]`; `--ds-config` points to a local copy of the Distributed Systems Handbook's `astro.config.mjs` and verifies links into it |
| `build_queue.py` | Rebuilds `queue.md` from `astro.config.mjs`, keeping statuses |
| `update_changelog.py` | Rebuilds the What's New pages (EN/TR) and the RSS feeds from `queue.md` |
| `update_readme.py` | Rebuilds the Roadmap & Progress Tracker in the repo `README.md` from the sidebar and `queue.md` |

Operating it:

- Regenerate a page: set its row in `queue.md` back to `todo`. Rows are taken from the top.
- Depth: each run picks `standard` (3,000-4,500 words) or `deep` (4,500-7,000) per topic page and records it in the `Depth` column; `deep` pages carry a `Deep because:` justification in `log.md`. Review those justifications, and treat any split proposal in the log as a sidebar decision for you.
- Skip a page: set it to `done` (or move it lower by editing the file).
- After changing the sidebar: run `python3 authoring/build_queue.py`, then
  `python3 authoring/update_readme.py` and `python3 authoring/update_changelog.py`, and commit.
- Sidebar entries outside the numbered parts (such as What's New) are not handbook pages and never enter the queue.
- Change how runs behave: edit `RUN.md`; the scheduled task only points to it.
- Review: read new pages on the live site; `git log` on `main` lists them by title. To
  revert a page, `git revert` its commit (this redeploys) and set its row back to `todo`.

Mermaid diagrams:

- Production renders every diagram to inline SVG at build time (light and dark variants,
  switched by the site theme), so readers download no Mermaid JavaScript. This runs in
  the deploy workflow with `MERMAID_SSR=1`; see `src/plugins/rehype-mermaid-themes.mjs`.
- Rendered SVGs are cached by content in `.cache/mermaid` (restored between CI builds).
- Local `pnpm build` / `pnpm dev` without `MERMAID_SSR=1` falls back to client-side
  rendering. To preview production output locally: `MERMAID_SSR=1 pnpm build`.
- A diagram that fails to render is published as a code block and the deploy run shows a
  "Mermaid" warning annotation.
