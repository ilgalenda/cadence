#!/usr/bin/env node
/**
 * Capture the images in `docs/images/`.
 *
 * The first set of these was shot by hand and left no script behind, so the next
 * person had to recover the parameters from the PNG dimensions. This exists so
 * that never happens again.
 *
 * Two families, two methods, and they must not be confused:
 *
 *   previews  Static HTML from `frontend/src/design-system/preview/`. No app, no
 *             backend, no data. Each page declares its own viewport in an
 *             `@dsCard` comment on line 1; a page without one is shot full-page
 *             at width 1280, which is what the originals did.
 *
 *   app       The running platform, on a seeded throwaway DATA_ROOT. These are
 *             the only images that show real software, and they are the reason
 *             the seed exists: the live database holds real shows and real
 *             colleagues, and is never opened.
 *
 * **The HTML comes from this repository, never from the internal one.** The two
 * trees' preview files differ: the public copies carry invented names where the
 * internal ones carry the author's and real accounts. Shooting the internal
 * previews would publish exactly what `genericise.py` exists to remove.
 *
 * Playwright is not a dependency of this repo. Run with the internal checkout's
 * node_modules on the path, or `npx playwright@1.62.1`:
 *
 *     PLAYWRIGHT_DIR=~/Developer/<internal>/frontend/node_modules \
 *       node tools/shoot-screenshots.mjs [previews|app|all]
 *
 * `app` additionally needs a backend running and `SHOOT_BASE` pointing at it.
 */
import { createServer } from 'node:http';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { extname, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// ESM ignores NODE_PATH, so the location is explicit. Playwright is deliberately
// not a dependency of this repository — it exists to be read, not built — so the
// module is borrowed from wherever the operator has one.
const PLAYWRIGHT = process.env.PLAYWRIGHT_DIR
  ? new URL(`${process.env.PLAYWRIGHT_DIR.replace(/\/$/, '')}/playwright/index.mjs`, 'file://').href
  : 'playwright';
const { chromium } = await import(PLAYWRIGHT);

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PREVIEWS = join(ROOT, 'frontend', 'src', 'design-system');
const OUT = join(ROOT, 'docs', 'images');

/** Every published image was shot at 2x. Anything less looks soft beside them. */
const SCALE = 2;
/** Pages with no declared viewport are shot full-page at this width. */
const DEFAULT_WIDTH = 1280;

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2',
};

/**
 * The preview pages pull `../tokens.css` and Google Fonts, so `file://` will not
 * do — they need an origin. One static server over the design system directory
 * is the whole requirement.
 */
function serve(dir) {
  const server = createServer((req, res) => {
    const path = join(dir, decodeURIComponent(req.url.split('?')[0]));
    if (!existsSync(path) || !path.startsWith(dir)) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(path)] ?? 'application/octet-stream' });
    res.end(readFileSync(path));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

/** The viewport a preview page was designed for, from its own `@dsCard` header. */
function declaredViewport(file) {
  const first = readFileSync(join(PREVIEWS, 'preview', file), 'utf8').split('\n', 1)[0];
  const match = first.match(/viewport="(\d+)x(\d+)"/);
  return match ? { width: +match[1], height: +match[2] } : null;
}

async function shootPreviews(browser) {
  const { server, port } = await serve(PREVIEWS);
  const files = readdirSync(join(PREVIEWS, 'preview')).filter((f) => f.endsWith('.html'));

  for (const file of files.sort()) {
    const name = file.replace(/\.html$/, '');
    const viewport = declaredViewport(file);
    const page = await browser.newPage({
      viewport: viewport ?? { width: DEFAULT_WIDTH, height: 900 },
      deviceScaleFactor: SCALE,
    });
    await page.goto(`http://127.0.0.1:${port}/preview/${file}`, { waitUntil: 'networkidle' });
    // The motion and material pages animate; let them settle before the shutter.
    await page.waitForTimeout(600);
    await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: !viewport });
    await page.close();
    console.log(`  ${name}.png  ${viewport ? `${viewport.width}x${viewport.height}` : 'full page'}`);
  }
  server.close();
}

/**
 * The running platform. Every one of these is captured on seeded demo data — see
 * `tools/seed-demo.py`. Signing in is a form post, so the session cookie is
 * whatever the app sets.
 */
const VIEWPORT = { width: 1440, height: 900 };
const APP_SHOTS = [
  // Events opens on the registration form, and the calendar it exists for is
  // both below the fold and collapsed. Open it, then anchor the shot to it —
  // otherwise the image shows an empty form and none of the point.
  ['screen-events', '/work/events', VIEWPORT, 'text=The calendar'],
  ['screen-agents', '/work/agents', VIEWPORT, null],
  // Named for the tracker, so it must show the tracker: the campaign section
  // sits under the proposal form and its empty state.
  ['screen-gtm-tracker', '/work/agents/gtm', VIEWPORT, 'text=Active campaign'],
];

async function shootApp(browser) {
  const base = process.env.SHOOT_BASE ?? 'http://127.0.0.1:8123';
  const user = process.env.SHOOT_USER ?? 'demo';
  const password = process.env.SHOOT_PASSWORD ?? 'demo';

  for (const [name, path, viewport, anchor] of APP_SHOTS) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: SCALE });
    const page = await context.newPage();
    const login = await page.request.post(`${base}/api/login`, {
      data: { username: user, password },
    });
    if (!login.ok()) throw new Error(`could not sign in to ${base}: ${login.status()}`);

    await page.goto(`${base}${path}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(900);
    if (anchor) {
      const target = page.locator(anchor).first();
      await target.scrollIntoViewIfNeeded();
      // A collapsed disclosure has to be opened before it is worth
      // photographing. Both shapes: a native <details>, and a button carrying
      // aria-expanded, which is what the calendar is.
      const control = target.locator(
        'xpath=ancestor-or-self::*[@aria-expanded or self::details][1]',
      );
      if (await control.count()) {
        const open = await control.first().evaluate(
          (el) => (el.tagName === 'DETAILS' ? el.open : el.getAttribute('aria-expanded') === 'true'),
        );
        if (!open) await control.first().click();
      }
      // Align the anchor's whole section to the top of the frame. Scrolling it
      // minimally into view puts the heading on the last row of pixels and
      // everything it introduces off-screen, which is how the first attempt
      // produced a picture of an empty form.
      await target.evaluate((el) => {
        (el.closest('section') ?? el).scrollIntoView({ block: 'start' });
      });
      await page.waitForTimeout(700);
    }
    await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: false });
    await context.close();
    console.log(`  ${name}.png  ${path}`);
  }
}

const what = process.argv[2] ?? 'all';
const browser = await chromium.launch();
try {
  if (what === 'previews' || what === 'all') {
    console.log('\npreview pages (static HTML, no backend):');
    await shootPreviews(browser);
  }
  if (what === 'app' || what === 'all') {
    console.log('\nthe running platform (seeded demo data):');
    await shootApp(browser);
  }
} finally {
  await browser.close();
}
console.log('\nDone.');
