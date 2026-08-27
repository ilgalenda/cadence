#!/usr/bin/env node
/**
 * Optical consistency of the app symbols.
 *
 * The launcher draws each agent as an application: an inlaid symbol on a wash
 * tile. What makes eleven of those read as one set is not stroke weight — it is
 * how much ink each one puts on its tile. The rail glyphs, scaled up, ranged from
 * 12.7% to 25.9% coverage, so half the set looked bold beside the other half. You
 * cannot see a 2× difference in ink by looking at one symbol at a time; you can
 * only measure it.
 *
 * So this rasterises every symbol's face and reports:
 *
 *   coverage   the fraction of the canvas that is ink — the optical weight.
 *              JUDGED: the band is the rule that makes the set one family.
 *   extent     the ink bounding box. JUDGED: it must stay inside the safe area,
 *              which is geometry rather than taste.
 *   centre     both the ink centroid and the bounding-box centre. REPORTED, not
 *              judged — see below.
 *
 * Centring stopped being a verdict with the inlaid set (2026-08-20). The marks
 * are abstractions of what an agent does to the data, and three of them are
 * *directionally* asymmetric on purpose: Lead scoring is a wedge anchored left,
 * Campaign selection a fan opening right, Recap the same fan closing. Their ink
 * mass therefore sits 1.7–2.0 units off centre by construction while reading
 * perfectly centred on the tile — verified by eye at 3× before this check was
 * demoted. Neither the centroid nor the box centre is a valid gate for a set
 * like that: a rule that fires on every run for three intentional drawings is
 * noise, and noise is how a rig stops being read. Both numbers are still
 * printed, and a wide deviation is still flagged for a human, because "what does
 * centred mean for an asymmetric mark" is a question the design project owns.
 *
 * NOT wired into `npm run build`: it needs a browser to rasterise, and the build
 * must not depend on one. `src/lib/appSymbols.test.ts` enforces what can be
 * checked without rendering. Run this when drawing or changing a symbol.
 *
 * Reads `dist/`, so run a build first.
 *
 * Run: npm run build && node scripts/check-symbols.mjs [--json]
 */

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const ROOT = new URL('..', import.meta.url).pathname;

/** The band a symbol's ink must fall in to belong to the set. */
const COVERAGE = { min: 0.095, max: 0.12 };
/** The canvas, and the box inside it that the ink may occupy. */
const CANVAS = 32;
const SAFE = { min: 4, max: 28 };
/**
 * How far the ink's centroid may sit from the canvas centre before the run says
 * so. Reported rather than failed — see the note at the top of this file.
 */
const CENTRE_NOTICE = 1.0;

/**
 * The symbols as they ship, read out of the built page.
 *
 * This used to re-derive them by parsing `appSymbols.ts` as text, which measured
 * a reconstruction rather than the artefact — and broke silently the moment a
 * path became a template literal, reporting one symbol at 0% ink. The built HTML
 * is what the browser gets, so it is what gets measured.
 *
 * Only the FACE is measured. A shipped mark is inlaid — four stepped copies of
 * the drawing in the stage's edge hue, then the face on top — so rasterising the
 * whole symbol would measure the light as though it were ink, and a heavy mark
 * could hide behind its own edge. The face carries `data-face` for exactly this,
 * and it is the layer the ink band is defined against.
 */
function symbols() {
  const html = readFileSync(`${ROOT}dist/work/agents/index.html`, 'utf8');
  const seen = new Set();
  const out = [];
  // Scoped to the launcher's tiles: the rail also carries `data-agent`, on the
  // hidden pinned rows, and those hold the *rail* glyph — a different set at a
  // different optical size. Matching on the attribute alone measured one of those.
  for (const [, slug, block] of html.matchAll(
    /<article class="ag-tile[^"]*"[^>]*data-agent="([a-z0-9-]+)"([\s\S]*?)<\/article>/g,
  )) {
    if (seen.has(slug)) continue;            // the pinned row mirrors the stages
    const svg = block.match(/<svg[\s\S]*?<\/svg>/)?.[0];
    if (!svg) continue;
    seen.add(slug);
    // The face layer, and the solved drawing inside it.
    const face = svg.match(/<g data-face[^>]*>([\s\S]*)<\/g><\/svg>$/)?.[1] ?? '';
    const transform = face.match(/<g transform="([^"]+)">/)?.[1] ?? '';
    const body = face.replace(/^<g transform="[^"]*">/, '').replace(/<\/g>$/, '');
    const pen = Number(svg.match(/stroke-width="([\d.]+)"/)?.[1] ?? 0);
    out.push({ slug, body, transform, pen });
  }
  return out;
}

/** Playwright is a developer tool here, not a dependency of the app. */
function browser() {
  try {
    const require = createRequire(import.meta.url);
    return require('playwright').chromium;
  } catch {
    console.error(
      'check-symbols needs Playwright to rasterise.\n'
      + '  npx playwright@1.62.1 --version   # then re-run\n'
      + 'It is deliberately not a project dependency: the build does not need a browser.',
    );
    process.exit(2);
  }
}

const RASTER = 256; // 8 device pixels per canvas unit — enough to measure thin gaps

async function measure(page, { body, transform, pen }) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${RASTER}" height="${RASTER}" viewBox="0 0 ${CANVAS} ${CANVAS}"`
    + ` fill="none" stroke="#000" stroke-width="${pen}" stroke-linecap="round" stroke-linejoin="round">`
    + `<g transform="${transform}">${body.replace(/currentColor/g, '#000')}</g></svg>`;
  return page.evaluate(async ([markup, size, canvasUnits]) => {
    const image = new Image();
    image.src = `data:image/svg+xml;base64,${btoa(markup)}`;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0, size, size);
    const { data } = context.getImageData(0, 0, size, size);

    let ink = 0, minX = size, minY = size, maxX = -1, maxY = -1, sumX = 0, sumY = 0;
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        if (data[(y * size + x) * 4 + 3] > 40) {
          ink += 1;
          sumX += x + 0.5;
          sumY += y + 0.5;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    const unit = size / canvasUnits;
    return {
      coverage: ink / (size * size),
      left: minX / unit, right: (maxX + 1) / unit,
      top: minY / unit, bottom: (maxY + 1) / unit,
      boxX: (minX + maxX + 1) / 2 / unit, boxY: (minY + maxY + 1) / 2 / unit,
      centreX: sumX / ink / unit, centreY: sumY / ink / unit,
    };
  }, [svg, RASTER, CANVAS]);
}

const chromium = browser();
const instance = await chromium.launch({ channel: 'chrome' });
const page = await instance.newPage();
await page.setContent('<body></body>');

const rows = [];
for (const symbol of symbols()) rows.push({ ...symbol, ...await measure(page, symbol) });
await instance.close();

if (process.argv.includes('--json')) {
  console.log(JSON.stringify(rows, null, 2));
  process.exit(0);
}

const problems = [];
const offCentre = [];
console.log('\nApp symbols — optical consistency\n');
console.log(
  `  ${'symbol'.padEnd(24)} ${'ink'.padStart(6)}  ${'extent'.padEnd(13)}`
  + `${'ink centre'.padEnd(12)} ${'box centre'.padStart(12)}`,
);
for (const row of rows) {
  const faults = [];
  if (row.coverage < COVERAGE.min || row.coverage > COVERAGE.max) faults.push('ink');
  if (row.left < SAFE.min - 0.05 || row.right > SAFE.max + 0.05
      || row.top < SAFE.min - 0.05 || row.bottom > SAFE.max + 0.05) faults.push('safe area');

  const extent = `${(row.right - row.left).toFixed(1)}×${(row.bottom - row.top).toFixed(1)}`;
  console.log(
    `  ${row.slug.padEnd(24)} ${(row.coverage * 100).toFixed(1).padStart(5)}%  ${extent.padEnd(13)}`
    + `${row.centreX.toFixed(1)},${row.centreY.toFixed(1)}`
    + ` ${`${row.boxX.toFixed(1)},${row.boxY.toFixed(1)}`.padStart(12)}`
    + (faults.length ? `   ← ${faults.join(', ')}` : ''),
  );
  if (faults.length) problems.push(`${row.slug}: ${faults.join(', ')}`);
  if (Math.abs(row.centreX - CANVAS / 2) > CENTRE_NOTICE
      || Math.abs(row.centreY - CANVAS / 2) > CENTRE_NOTICE) {
    offCentre.push(`${row.slug}: ink centre ${row.centreX.toFixed(1)},${row.centreY.toFixed(1)}`);
  }
}

const inks = rows.map((r) => r.coverage);
console.log(
  `\n  ink ${(Math.min(...inks) * 100).toFixed(1)}–${(Math.max(...inks) * 100).toFixed(1)}%`
  + ` (band ${COVERAGE.min * 100}–${COVERAGE.max * 100}%),`
  + ` heaviest is ${(Math.max(...inks) / Math.min(...inks)).toFixed(2)}× the lightest`,
);

if (offCentre.length) {
  console.log(`\n  ink centre sits over ${CENTRE_NOTICE} unit off on ${offCentre.length} symbol(s) —`
    + ' reported, not a fault (directional marks are asymmetric by design):');
  for (const note of offCentre) console.log(`    ${note}`);
}

if (problems.length) {
  console.log(`\n  ${problems.length} symbol(s) outside the system:\n    ${problems.join('\n    ')}\n`);
  process.exit(1);
}
console.log('\n  PASSED — the set is optically one family\n');
