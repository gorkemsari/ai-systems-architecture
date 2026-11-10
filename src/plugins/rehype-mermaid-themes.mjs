// Build-time Mermaid rendering with light and dark variants.
//
// Every ```mermaid block is rendered twice in a headless browser (light theme
// and dark theme) and replaced by inline SVG. src/styles/mermaid.css shows the
// variant that matches Starlight's <html data-theme>, so the theme toggle works
// and no Mermaid JavaScript ships to readers.
//
// Speed: each rendered SVG is cached by a hash of (renderer version, theme,
// diagram source) in MERMAID_CACHE_DIR (default .cache/mermaid). EN and TR pages
// share diagrams, and CI restores the cache between builds, so a build only
// renders diagrams that are new or changed. Each diagram gets an ID prefix
// derived from its hash, so cached SVGs never collide on a page.
//
// Stability: renders share one browser and run at most RENDER_CONCURRENCY at a
// time; Vite transforms many MDX files in parallel and opening a page per file
// crashes Chromium.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createMermaidRenderer } from 'mermaid-isomorphic';
import { fromHtmlIsomorphic } from 'hast-util-from-html-isomorphic';

const CACHE_VERSION = 'mermaid-isomorphic-3.1.0/v1';
const CACHE_DIR = path.resolve(process.env.MERMAID_CACHE_DIR ?? '.cache/mermaid');
const RENDER_CONCURRENCY = 2;

let renderer;
const inflight = new Map();
const stats = { rendered: 0, cached: 0, failed: 0 };

let active = 0;
const waiting = [];
async function limited(task) {
  if (active >= RENDER_CONCURRENCY) await new Promise((resolve) => waiting.push(resolve));
  active++;
  try {
    return await task();
  } finally {
    active--;
    waiting.shift()?.();
  }
}

function keyFor(source, config) {
  return createHash('sha256')
    .update(JSON.stringify([CACHE_VERSION, config, source]))
    .digest('hex')
    .slice(0, 20);
}

async function renderOne(source, config) {
  const key = keyFor(source, config);
  if (inflight.has(key)) return inflight.get(key);
  const job = (async () => {
    const file = path.join(CACHE_DIR, `${key}.svg`);
    try {
      const svg = await readFile(file, 'utf8');
      stats.cached++;
      return svg;
    } catch {}
    renderer ??= createMermaidRenderer({ launchOptions: { args: ['--disable-dev-shm-usage'] } });
    const [result] = await limited(() =>
      renderer([source], { prefix: `m${key.slice(0, 12)}`, mermaidConfig: config }),
    );
    if (result.status !== 'fulfilled') {
      stats.failed++;
      throw result.reason ?? new Error('mermaid render failed');
    }
    stats.rendered++;
    await mkdir(CACHE_DIR, { recursive: true });
    await writeFile(file, result.value.svg);
    return result.value.svg;
  })();
  inflight.set(key, job);
  return job;
}

function classList(node) {
  const c = node?.properties?.className;
  return Array.isArray(c) ? c : typeof c === 'string' ? c.split(/\s+/) : [];
}

function textOf(node) {
  if (node.type === 'text') return node.value;
  return (node.children ?? []).map(textOf).join('');
}

function findMermaidBlocks(tree) {
  const found = [];
  const walk = (node) => {
    for (let i = 0; i < (node.children?.length ?? 0); i++) {
      const child = node.children[i];
      if (child.type === 'element' && child.tagName === 'pre') {
        const code = child.children?.find((c) => c.type === 'element' && c.tagName === 'code');
        if (code && classList(code).includes('language-mermaid')) {
          found.push({ parent: node, index: i, source: textOf(code).replace(/\n$/, '') });
          continue;
        }
      }
      walk(child);
    }
  };
  walk(tree);
  return found;
}

function svgNode(svg) {
  const root = fromHtmlIsomorphic(svg, { fragment: true });
  return root.children.find((c) => c.type === 'element') ?? root.children[0];
}

function variant(name, child) {
  return {
    type: 'element',
    tagName: 'div',
    properties: { className: ['mermaid-diagram', `mermaid-${name}`] },
    children: [child],
  };
}

function fallback(source) {
  return {
    type: 'element',
    tagName: 'pre',
    properties: { className: ['mermaid-error'] },
    children: [{ type: 'element', tagName: 'code', properties: {}, children: [{ type: 'text', value: source }] }],
  };
}

export function mermaidRenderStats() {
  return { ...stats };
}

export default function rehypeMermaidThemes(options = {}) {
  const light = options.light ?? { theme: 'default' };
  const dark = options.dark ?? { theme: 'dark' };
  return async (tree, file) => {
    const blocks = findMermaidBlocks(tree);
    if (blocks.length === 0) return;
    const rendered = await Promise.all(
      blocks.map((b) =>
        Promise.allSettled([renderOne(b.source, light), renderOne(b.source, dark)]),
      ),
    );
    // Replace from the end so earlier indexes stay valid within a shared parent.
    for (let k = blocks.length - 1; k >= 0; k--) {
      const { parent, index, source } = blocks[k];
      const [l, d] = rendered[k];
      if (l.status !== 'fulfilled' || d.status !== 'fulfilled') {
        const reason = (l.status === 'rejected' ? l.reason : d.reason)?.message ?? 'unknown error';
        console.warn(`[mermaid] render failed in ${file?.path ?? 'unknown file'}: ${reason}`);
        parent.children[index] = fallback(source);
        continue;
      }
      parent.children[index] = {
        type: 'element',
        tagName: 'figure',
        properties: { className: ['mermaid-figure', 'not-content'] },
        children: [variant('light', svgNode(l.value)), variant('dark', svgNode(d.value))],
      };
    }
  };
}
