#!/usr/bin/env node
/**
 * Design-system adherence gate.
 *
 * The Cadence Design System project on claude.ai/design is the source of truth,
 * and it ships `_adherence.oxlintrc.json`: a token inventory plus three rules.
 * That config targets JSX through oxlint; this platform is Astro, CSS and
 * TypeScript, so the same rules are enforced here over the files we write.
 *
 * Three severities, because a rebrand lands over several slices and a gate that
 * is permanently red enforces nothing:
 *
 *   ERROR    — the token inventory drifting, an off-brand colour, or a font
 *              outside the system. Zero tolerance; these make the product wrong.
 *   RATCHET  — raw px values. Hundreds predate the design system in pages
 *              scheduled for rebuild. A per-file baseline is recorded; the gate
 *              fails if any count *grows* or a new file appears. Debt cannot be
 *              paid off instantly, but it must never deepen.
 *   GAP      — a declared hole in the design system itself, with the decision it
 *              is waiting on. Reported loudly every run so it cannot be
 *              forgotten, and never silently.
 *
 * `tokens.css` is where literal values legitimately live, so the design system
 * is exempt from the literal rules and is instead checked by the inventory.
 *
 * Run: npm run check:design      Refresh the ratchet: --update-baseline
 */

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative, extname } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const SRC = join(ROOT, 'src');
const DESIGN_SYSTEM = join(SRC, 'design-system');
const BASELINE_PATH = join(ROOT, 'scripts', 'adherence-baseline.json');
const UPDATING = process.argv.includes('--update-baseline');

/** The approved inventory, from `_adherence.oxlintrc.json` → `x-omelette.tokens`. */
const APPROVED_TOKENS = [
  '--accent', '--accent-hairline', '--accent-ink', '--accent-on-chrome', '--accent-pressed',
  '--accent-wash', '--canvas', '--chrome', '--chrome-ink', '--chrome-ink-muted', '--chrome-raised',
  '--chrome-rule', '--dur-beat', '--dur-reveal', '--dur-shift', '--dur-stage', '--dur-step',
  '--dur-tap', '--dur-tick', '--ease-depart', '--ease-phase', '--ease-settle', '--font-mono',
  '--font-sans', '--gold', '--gold-deep', '--gold-on-chrome', '--ink', '--ink-muted',
  '--ink-on-ink', '--ink-secondary', '--leading-normal', '--leading-relaxed', '--leading-snug',
  '--leading-tight', '--measure-form', '--measure-page', '--measure-read',
  '--rail-closed', '--rail-open', '--radius-full', '--radius-app',
  // App marks — a wash and an edge per stage plus the one face, kept in step
  // with STAGES by platform.test.ts. Revised 2026-08-20 with the inlaid set.
  '--app-find', '--app-find-edge',
  '--app-engage', '--app-engage-edge',
  '--app-learn', '--app-learn-edge',
  '--app-face',
  '--radius-lg', '--radius-md', '--radius-sm', '--radius-xs', '--rule', '--rule-hairline',
  '--rule-strong', '--shadow-flat', '--shadow-lifted', '--shadow-overlay', '--shadow-raised',
  '--signal-drift', '--signal-drift-on-chrome', '--signal-drift-wash', '--signal-fault',
  '--signal-fault-on-chrome', '--signal-fault-wash', '--signal-locked',
  // Categorical series palette — added 2026-07-28 to close the declared
  // data-visualisation gap. Derived and validated; see tokens.css.
  '--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6',
  '--series-other',
  '--signal-locked-on-chrome', '--signal-locked-wash', '--space-1', '--space-10', '--space-12',
  '--space-16', '--space-2', '--space-24', '--space-3', '--space-4', '--space-5', '--space-6',
  '--space-8', '--space-px',
  // Colour fields — added 2026-08-19 with "the studio" rebuild. Full-bleed
  // featured surfaces from the brand secondaries, each naming its own ink;
  // at most one field per view, never for state. See tokens.css.
  '--field-amber', '--field-amber-ink', '--field-blue', '--field-blue-ink',
  '--field-gold', '--field-gold-ink', '--field-sky', '--field-sky-ink',
  // Material — added 2026-08-14 with the doctrine revision. Blur radii and the
  // tint alphas for the floating layer; see tokens.css.
  '--blur-regular', '--blur-thick', '--blur-thin',
  '--glass-dark', '--glass-light', '--glass-saturate',
  // The ground the glass reveals. `--ground` holds a gradient rather than a
  // colour triple, so the palette check ignores it by construction.
  '--ground', '--ground-deep',
  // Spring vocabulary — added 2026-08-14 with the motion doctrine revision.
  // Damping and response, read by design-system/springs.ts; see tokens.css.
  '--spring-carry-damping', '--spring-carry-response',
  '--spring-settle-damping', '--spring-settle-response',
  '--surface', '--surface-ink', '--surface-raised', '--surface-sunken',
  '--text-body', '--text-caption', '--text-display', '--text-heading', '--text-lead',
  '--text-micro', '--text-small', '--text-title', '--tracking-body', '--tracking-display',
  '--tracking-label', '--tracking-mono', '--tracking-title', '--weight-bold', '--weight-light',
  '--weight-medium', '--weight-regular', '--weight-thin', '--z-base', '--z-dialog', '--z-drawer',
  '--z-overlay', '--z-sticky', '--z-toast',
];

const SYSTEM_FONTS = ['Roboto', 'Kode Mono'];

/**
 * The brand palette as hex, derived from `tokens.css` rather than hand-listed, so
 * it can never fall out of step with the system.
 *
 * A literal hex is normally a defect — but a standalone exported document (a
 * downloaded report, an email) has no access to our stylesheet and must carry its
 * own values. Allowing exactly the palette, and nothing else, keeps that possible
 * while still catching every off-brand colour.
 */
function brandHexSet() {
  const css = readFileSync(join(DESIGN_SYSTEM, 'tokens.css'), 'utf8');
  const hex = new Set(['#ffffff', '#000000']); // pure white/black: legal ink on any surface
  for (const [, r, g, b] of css.matchAll(/--[a-z0-9-]+:\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*;/g)) {
    const value = [r, g, b].map((c) => Number(c).toString(16).padStart(2, '0')).join('');
    hex.add(`#${value}`);
  }
  return hex;
}

const BRAND_HEX = brandHexSet();

/**
 * Declared gaps in the design system: places where no token can express what the
 * code needs, and the decision that would close them. Exempt from the colour
 * rule and reported on every run.
 */
const DECLARED_GAPS = {};

const CHECKED_EXTENSIONS = new Set(['.astro', '.css', '.ts', '.js', '.mjs']);

// ── Collect files ───────────────────────────────────────────────────────────

function walk(dir, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, found);
    else if (CHECKED_EXTENSIONS.has(extname(path))) found.push(path);
  }
  return found;
}

/** Strip comments so a value quoted in prose is never a violation. */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ');
}

// ── Rule 1 (ERROR): the token inventory ─────────────────────────────────────

function checkInventory() {
  const css = readFileSync(join(DESIGN_SYSTEM, 'tokens.css'), 'utf8');
  // Declarations only — a name followed by a colon, not a var() usage.
  const declared = new Set([...css.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((m) => m[1]));
  const approved = new Set(APPROVED_TOKENS);

  const errors = [];
  const missing = [...approved].filter((t) => !declared.has(t)).sort();
  const extra = [...declared].filter((t) => !approved.has(t)).sort();
  if (missing.length) errors.push(`missing approved token(s): ${missing.join(', ')}`);
  if (extra.length) errors.push(`unapproved token(s) declared: ${extra.join(', ')}`);
  return { errors, count: declared.size };
}

// ── Rules 2–4: literals outside the design system ───────────────────────────

const RULES = [
  {
    id: 'raw-hex',
    severity: 'error',
    pattern: /(?<![&\w])#[0-9a-fA-F]{3,8}\b/g,
    message: 'off-brand colour — use a colour token via rgb(var(--token))',
    // Only genuinely off-palette values are violations; a brand hex in a
    // standalone export is legitimate (see brandHexSet).
    keep: (hit) => /^#[0-9a-fA-F]{3,8}$/.test(hit) && !BRAND_HEX.has(hit.toLowerCase()),
  },
  {
    id: 'font-family',
    severity: 'error',
    pattern: /font-family\s*:\s*([^;}\n]+)/gi,
    message: 'font outside the design system — use var(--font-sans) or var(--font-mono)',
    keep: (hit) =>
      !/var\(--font-(sans|mono)\)|inherit/i.test(hit) &&
      !SYSTEM_FONTS.some((f) => hit.includes(f)),
  },
  {
    id: 'raw-px',
    severity: 'ratchet',
    pattern: /\b\d+px\b/g,
    message: 'raw px — use a spacing or radius token via var()',
    // Hairlines and optical nudges have no token and never will: 1px is the rule
    // weight, 2px the signal weight, 3px a scrollbar inset.
    keep: (hit) => !['0px', '1px', '2px', '3px'].includes(hit),
  },
];

function scan(files) {
  const found = { error: [], ratchet: [], gap: [] };

  for (const file of files) {
    const rel = relative(ROOT, file);
    if (file.startsWith(DESIGN_SYSTEM)) continue; // where literals legitimately live
    if (rel.startsWith('scripts/')) continue;     // this checker quotes the patterns

    const source = stripComments(readFileSync(file, 'utf8'));
    const gap = DECLARED_GAPS[rel];

    for (const rule of RULES) {
      for (const match of source.matchAll(rule.pattern)) {
        const hit = (match[1] ?? match[0]).trim();
        if (!rule.keep(hit)) continue;
        const line = source.slice(0, match.index).split('\n').length;
        const entry = { rel, line, rule: rule.id, hit, message: rule.message };
        // A declared gap only excuses colour, never a stray font or px value.
        if (gap && rule.id === 'raw-hex') found.gap.push(entry);
        else found[rule.severity].push(entry);
      }
    }
  }
  return found;
}

// ── Ratchet ─────────────────────────────────────────────────────────────────

function countsByFile(entries) {
  const counts = {};
  for (const e of entries) counts[e.rel] = (counts[e.rel] ?? 0) + 1;
  return counts;
}

function compareRatchet(counts) {
  if (!existsSync(BASELINE_PATH)) {
    return { regressions: [], improvements: [], missingBaseline: true };
  }
  const baseline = JSON.parse(readFileSync(BASELINE_PATH, 'utf8')).rawPx ?? {};
  const regressions = [];
  const improvements = [];

  for (const [rel, count] of Object.entries(counts)) {
    const allowed = baseline[rel];
    if (allowed === undefined) regressions.push(`${rel} — new file with ${count} raw px value(s)`);
    else if (count > allowed) regressions.push(`${rel} — ${count} raw px, baseline allows ${allowed}`);
    else if (count < allowed) improvements.push(`${rel} — down to ${count} from ${allowed}`);
  }
  for (const rel of Object.keys(baseline)) {
    if (!(rel in counts)) improvements.push(`${rel} — now clean`);
  }
  return { regressions, improvements, missingBaseline: false };
}

// ── Run ─────────────────────────────────────────────────────────────────────

const inventory = checkInventory();
const found = scan(walk(SRC));
const rawPxCounts = countsByFile(found.ratchet);

if (UPDATING) {
  const total = found.ratchet.length;
  writeFileSync(
    BASELINE_PATH,
    `${JSON.stringify({
      note: 'Raw-px debt per file, ratcheted by scripts/check-adherence.mjs. '
          + 'Counts may only go down. Regenerate with: npm run check:design -- --update-baseline',
      total,
      rawPx: Object.fromEntries(Object.entries(rawPxCounts).sort()),
    }, null, 2)}\n`,
  );
  console.log(`Baseline written — ${total} raw px value(s) across ${Object.keys(rawPxCounts).length} file(s).`);
  process.exit(0);
}

const ratchet = compareRatchet(rawPxCounts);

console.log('\nDesign-system adherence — Cadence\n');

console.log(`  inventory   ${inventory.errors.length ? 'FAIL' : 'ok  '}  ${inventory.count} tokens, matching the approved list`);
inventory.errors.forEach((e) => console.log(`              ${e}`));

console.log(`  colour      ${found.error.filter((e) => e.rule === 'raw-hex').length ? 'FAIL' : 'ok  '}  no off-brand colours outside the design system`);
console.log(`  fonts       ${found.error.filter((e) => e.rule === 'font-family').length ? 'FAIL' : 'ok  '}  no fonts outside the design system`);
for (const e of found.error) {
  console.log(`              ${e.rel}:${e.line}  ${e.rule}  ${JSON.stringify(e.hit)}`);
  console.log(`                → ${e.message}`);
}

const ratchetOk = !ratchet.regressions.length && !ratchet.missingBaseline;
console.log(`  raw px      ${ratchetOk ? 'ok  ' : 'FAIL'}  ${found.ratchet.length} in ${Object.keys(rawPxCounts).length} file(s), ratcheted`);
if (ratchet.missingBaseline) console.log('              no baseline recorded — run with --update-baseline');
ratchet.regressions.forEach((r) => console.log(`              regression: ${r}`));
if (ratchet.improvements.length) {
  console.log(`              ${ratchet.improvements.length} file(s) improved — run --update-baseline to lock the gain in:`);
  ratchet.improvements.slice(0, 10).forEach((i) => console.log(`                ${i}`));
}

if (found.gap.length) {
  console.log('\n  Declared gaps in the design system — awaiting a decision:\n');
  for (const [rel, gap] of Object.entries(DECLARED_GAPS)) {
    const hits = found.gap.filter((g) => g.rel === rel);
    if (!hits.length) continue;
    console.log(`    ${rel}  (${hits.length} colour value(s))`);
    console.log(`      needs     ${gap.what}`);
    console.log(`      why       ${gap.why}`);
    console.log(`      decision  ${gap.decision}\n`);
  }
}

const failures = inventory.errors.length + found.error.length + (ratchetOk ? 0 : 1);
console.log(failures ? `FAILED — ${failures} problem(s)\n` : 'PASSED\n');
process.exit(failures ? 1 : 0);
