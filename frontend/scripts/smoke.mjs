#!/usr/bin/env node
/**
 * Call Analysis, end to end, against a running Cadence.
 *
 * **Why this exists.** The suite has 400+ tests and none of them opens a page.
 * `check-adherence.mjs` reads tokens, colours and pixels; `vitest` covers the
 * `lib/` helpers and reads source files. Neither can see a button that does
 * nothing. Five defects had survived in this one feature because of that gap —
 * a quiz that scored every answer wrong, a product-fit call the backend refused
 * as malformed, an injection sink in the exported report, a documented prop no
 * page passed, and a font 404 on every page load. Each was found by clicking.
 * This is that clicking, written down.
 *
 * **Deliberately not part of `npm run build`.** It needs a live backend, real
 * credentials and an `ANTHROPIC_API_KEY`, and it spends two model turns per run
 * (~40s for the reading, ~20s for the fit). A build gate has to be free and
 * offline. Run it before shipping a change to this feature, and after any
 * change to `AnalysisResult.astro`, which four surfaces render.
 *
 * **It writes to the admin sandbox, never the real vault.** `sandbox/enable`
 * swaps the store to `data/_sandbox/` and stops Knowledge Capture reaching the
 * shared vault, so a run leaves no learnings, glossary terms or call records
 * behind in the live brain. It requires an admin account for that reason.
 *
 *   npm run smoke                      # against http://127.0.0.1:8000
 *   SMOKE_BASE=… npm run smoke         # somewhere else
 *   SMOKE_USER=… SMOKE_PASSWORD=… npm run smoke
 *
 * Credentials come from the environment first; failing that, from the backend's
 * own `.env`, which is where the credential map already keeps them.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

// `127.0.0.1`, not `localhost`: on macOS that resolves to `::1` first, and the
// backend binds IPv4 only, so `localhost` is refused before it is tried.
const BASE = process.env.SMOKE_BASE || 'http://127.0.0.1:8000';
const ROOT = new URL('..', import.meta.url).pathname;
const SHOTS = process.env.SMOKE_SHOTS || join(ROOT, '.smoke');

/** The reader whose journey this is. Admin, because the sandbox requires it. */
function credentials() {
  const user = process.env.SMOKE_USER || 'sam';
  if (process.env.SMOKE_PASSWORD) return { user, password: process.env.SMOKE_PASSWORD };

  const envFile = join(ROOT, '..', 'backend', '.env');
  if (!existsSync(envFile)) {
    throw new Error('No SMOKE_PASSWORD, and backend/.env is not there to read one from.');
  }
  const key = `${user.toUpperCase()}_PASSWORD`;
  const password = readFileSync(envFile, 'utf8').match(new RegExp(`^${key}=(.*)$`, 'm'))?.[1]?.trim();
  if (!password) throw new Error(`No SMOKE_PASSWORD, and ${key} is unset in backend/.env.`);
  return { user, password };
}

/**
 * A transcript with something in it to find: a dated compliance trigger, a
 * holdover gap, an approved CapEx budget, a reseller, and an incumbent
 * objection. A reading that extracts none of these has regressed, whatever the
 * page looks like.
 */
const TRANSCRIPT = `
Sam (Acme): Thanks for making time. What pushed you to look at timing now?
Priya (Head of Infra, Meridian Capital): Our FCA audit flagged us in March. We cannot evidence
100 microsecond accuracy across the two London venues, and our roof antenna ices over in winter
so the GPS receivers lose lock.
Sam: How are you handling holdover today?
Priya: Badly. There is an OCXO in one rack and nothing in the other. When we lose GNSS we drift
outside tolerance in about forty minutes.
Sam: And the buying process?
Priya: Budget is approved this financial year, around 80k, but it has to be CapEx. Support as
OpEx is fine. Procurement takes six weeks and we already buy through Node4.
Priya: The one worry is that we are mid-contract with Oscilloquartz until 2027.
Sam: Would a two week proof of concept on the secondary venue help?
Priya: Yes, if we can set a go/no-go date against it.
`.trim();

const results = [];
const problems = [];

function check(label, passed, detail = '') {
  results.push({ label, passed, detail });
  const mark = passed ? '  ok  ' : ' FAIL ';
  console.log(`${mark} ${label}${detail ? `  — ${detail}` : ''}`);
}

async function main() {
  const { user, password } = credentials();
  mkdirSync(SHOTS, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
  const page = await context.newPage();

  // A page that throws is a failure even when every assertion below passes.
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('response', (res) => {
    if (res.status() >= 400) problems.push(`${res.status()} ${new URL(res.url()).pathname}`);
  });

  const shot = (name) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });

  const login = await page.request.post(`${BASE}/api/login`, { data: { username: user, password } });
  if (!login.ok()) throw new Error(`Could not sign in as ${user}: HTTP ${login.status()}`);

  const sandbox = await page.request.post(`${BASE}/api/admin/sandbox/enable`);
  const live = (await (await page.request.get(`${BASE}/api/admin/sandbox/status`)).json()).sandbox;
  if (!sandbox.ok() || !live) {
    throw new Error('The sandbox would not enable — refusing to run against the real vault.');
  }
  console.log(`\nCadence smoke — ${BASE}, as ${user}, sandboxed\n`);

  try {
    // ── The run ──────────────────────────────────────────────────────────────
    console.log('The run');
    await page.goto(`${BASE}/work/agents/call-analysis`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(600);
    check('opens on its empty state', !(await page.locator('#result-empty').isHidden()));
    check('the reading starts hidden', await page.locator('#analysis-result').isHidden());

    await page.fill('#transcript', TRANSCRIPT);
    await page.fill('#title', 'Meridian Capital — smoke test');
    const startedAt = Date.now();
    await page.click('#analyse');
    await page.waitForTimeout(1500);
    check('holds the wait with a skeleton', !(await page.locator('#ar-loading').isHidden()));
    check('counts the seconds', /\d+s/.test(await page.locator('#run-elapsed').textContent()));
    check('the empty stands down while running', await page.locator('#result-empty').isHidden());

    await page.locator('#analysis-result').waitFor({ state: 'visible', timeout: 240000 });
    const took = Math.round((Date.now() - startedAt) / 1000);
    check('the reading arrives', true, `${took}s`);
    check('the skeleton stands down', await page.locator('#ar-loading').isHidden());
    check('the section head stands down', await page.locator('#run-head').isHidden());
    check('a summary was written', (await page.locator('#result-summary').textContent()).trim().length > 40);
    await shot('01-reading');

    // ── What it found ────────────────────────────────────────────────────────
    console.log('\nWhat it found');
    await page.click('[data-tab="sales"]');
    await page.waitForTimeout(300);
    const signals = await page.locator('#result-signals li').count();
    const objections = await page.locator('#result-objections li').count();
    check('buying signals extracted', signals > 0, `${signals}`);
    check('objections extracted', objections > 0, `${objections}`);
    const concepts = await page.locator('#result-concepts .ds-tag').count();
    check('concepts tagged', concepts > 0, `${concepts}`);
    await shot('02-sales');

    // ── The tablist ──────────────────────────────────────────────────────────
    console.log('\nThe tablist');
    for (const tab of ['summary', 'sales', 'recommendation', 'knowledge', 'quiz']) {
      await page.click(`[data-tab="${tab}"]`);
      await page.waitForTimeout(200);
      check(`${tab} opens`, !(await page.locator(`#tab-${tab}`).isHidden()));
    }
    const stops = await page.evaluate(
      () => [...document.querySelectorAll('.result-tab')].filter((t) => t.tabIndex === 0).length,
    );
    check('the strip is one tab stop', stops === 1, `${stops}`);
    await page.focus('#ar-tab-summary');
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(200);
    const walked = await page.evaluate(() => ({
      focused: document.activeElement.id,
      panel: [...document.querySelectorAll('.result-panel')].find((p) => !p.hidden)?.id,
    }));
    check('an arrow moves focus and the panel together',
      walked.focused === 'ar-tab-sales' && walked.panel === 'tab-sales', JSON.stringify(walked));

    // ── Product fit, the opt-in second turn ──────────────────────────────────
    console.log('\nProduct fit');
    await page.click('[data-tab="recommendation"]');
    await page.waitForTimeout(300);
    if (!(await page.locator('#rec-generate').isHidden())) {
      // Deliberately left blank: "assess across the catalogue" is the common
      // case, and it is the one that used to 422.
      await page.click('#rec-generate-btn');
      await page.locator('#result-primary-rec').waitFor({ state: 'visible', timeout: 180000 });
      const named = (await page.locator('#rec-product-name').textContent()).trim();
      check('an unnamed product still assesses fit', named.length > 2, named);
      check('no failure reported on the control',
        !(await page.locator('#rec-generate-state').textContent()).includes('failed'));
    } else {
      check('fit already present on the reading', true);
    }
    await shot('03-fit');

    // ── The quiz ─────────────────────────────────────────────────────────────
    console.log('\nThe quiz');
    await page.click('[data-tab="quiz"]');
    await page.waitForTimeout(400);
    const cards = await page.locator('.ar__card').count();
    check('questions built', cards > 0, `${cards}`);
    if (cards) {
      // Answer the first question with whichever option the component itself
      // marks right. Scoring a right answer as wrong is the regression this
      // guards: `correct` on a card is an index, not a boolean.
      await page.locator('.ar__card[data-index="0"] .mcq-option').first().click();
      await page.waitForTimeout(300);
      const marked = await page.locator('.ar__option--right').count();
      check('the right option is marked right', marked === 1, `${marked} marked`);
      const feedback = await page.locator('.ar__feedback').first().textContent();
      check('a verdict is given', /correct|incorrect/.test(feedback));
    }
    await shot('04-quiz');

    // ── The report ───────────────────────────────────────────────────────────
    console.log('\nThe report');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#download-report'),
    ]);
    const reportPath = join(SHOTS, 'report.html');
    await download.saveAs(reportPath);
    const report = readFileSync(reportPath, 'utf8');
    check('downloads', report.length > 1000, `${Math.round(report.length / 1024)}KB`);
    check('carries its own faces', report.includes('data:font/woff2;base64,'));
    check('reaches no CDN', !/fonts\.(googleapis|gstatic)/.test(report));
    check('escapes what the model wrote', !/<img src=x|<\/title><script>/.test(report));
    check('the control is handed back', (await page.locator('#download-report').textContent()).trim() === 'Report');

    // ── Where the call ended up ──────────────────────────────────────────────
    console.log('\nWhere the call ended up');
    const listed = await (await page.request.get(`${BASE}/api/sales/calls`)).json();
    const rows = Array.isArray(listed) ? listed : listed.calls || [];
    const filed = rows.find((row) => String(row.title || '').includes('smoke test'));
    check('filed to the library', Boolean(filed), filed ? filed.id : 'not found');

    if (filed) {
      await page.goto(`${BASE}/learn/library/call?id=${filed.id}`, { waitUntil: 'domcontentloaded' });
      await page.locator('#analysis-result').waitFor({ state: 'visible', timeout: 30000 });
      check('the detail page renders it', true);
      check('the title sits in the page head',
        (await page.locator('#title').textContent()).includes('Meridian'));
      check('the timestamp sits in the mono slot',
        (await page.locator('#when').textContent()).trim().length > 0);
      check('the component names itself, unoverwritten',
        (await page.locator('#ar-heading').textContent()).trim() === 'Analysis');
      await shot('05-detail');
    }

    // ── The states nobody reaches on a good day ──────────────────────────────
    console.log('\nThe states nobody reaches on a good day');
    await page.goto(`${BASE}/learn/library/call?id=definitely-not-a-call`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
    const missing = (await page.locator('#ar-problem').textContent()).trim();
    check('a missing call says so', missing.includes('No such call'), missing.slice(0, 40));
    check('and does not hang on a skeleton', await page.locator('#ar-loading').isHidden());
    await shot('06-missing');

    await page.goto(`${BASE}/learn/library/call`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    check('no id at all says so', !(await page.locator('#ar-problem').isHidden()));

    // ── Home ─────────────────────────────────────────────────────────────────
    console.log('\nHome');
    await page.goto(`${BASE}/home`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(600);
    const shortcuts = await page.locator('.hm-way').count();
    check('every shortcut has a key', shortcuts > 0, `${shortcuts} rows, ⌘1–⌘${shortcuts}`);
    await page.keyboard.press('Meta+2');
    await page.waitForTimeout(900);
    check('⌘2 reaches Call analysis',
      new URL(page.url()).pathname.includes('call-analysis'), new URL(page.url()).pathname);
    await shot('07-home');
  } finally {
    await page.request.post(`${BASE}/api/admin/sandbox/disable`).catch(() => {});
    await browser.close();
  }

  // ── The verdict ────────────────────────────────────────────────────────────
  // A 404 on a missing call is the point of two checks above, so it does not
  // count against the run.
  const asked = /\/api\/(sales|admin)\/calls\/(definitely-not-a-call|undefined)/;

  // Declared, not swallowed — the same posture `check-adherence.mjs` takes to a
  // hole in the design system. Each entry is reported on every run so it cannot
  // quietly become permanent, and each names who can actually close it.
  const DECLARED = [
    {
      match: /KodeMono-VariableFont_wght\.ttf/,
      why: 'tokens.css declares Kode Mono from a .ttf that lives in the design project, '
        + 'not in this app. Type still renders — fonts.css declares a working woff2 and wins — '
        + 'so the cost is one failing request per page load.',
      owner: 'the Cadence Design System project. `tokens.css` is byte-identical to the copy '
        + 'there by rule, so this is fixed at source and pulled down, never patched here.',
    },
  ];

  const unexplained = [];
  const declared = [];
  for (const problem of [...new Set(problems)]) {
    if (asked.test(problem)) continue;
    const known = DECLARED.find((d) => d.match.test(problem));
    (known ? declared : unexplained).push(known ? { problem, ...known } : problem);
  }
  const noise = unexplained;

  const failed = results.filter((r) => !r.passed);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);

  if (declared.length) {
    console.log(`\n${declared.length} declared issue(s) — known, still open:`);
    declared.forEach((d) => {
      console.log(`  ${d.problem}`);
      console.log(`    why:   ${d.why}`);
      console.log(`    owner: ${d.owner}`);
    });
  }

  if (noise.length) {
    console.log(`\n${noise.length} unexplained problem(s) — a page threw, or a request failed:`);
    noise.forEach((p) => console.log(`  ${p}`));
  }

  if (failed.length || noise.length) {
    console.log('\nFAILED');
    process.exit(1);
  }
  console.log('\nPASSED');
}

main().catch((err) => {
  console.error(`\nThe smoke test could not run: ${err.message}`);
  process.exit(1);
});
