#!/usr/bin/env node
/**
 * WebUI inline-hex-color ratchet (webui-style-governance-2026-09, W1).
 *
 * Enforced rule:
 *   Per-file #hex color literal counts in webui/src/**\/*.{ts,tsx} may only
 *   DECREASE against webui/webui-style-ledger.json. A count above the
 *   ledger allowance fails with exit 1.
 *
 * Not counted:
 *   - hex values inside var(--name, #fallback) — the compliant fallback form;
 *   - lines carrying the `inline-color: exempt` marker (each marker must
 *     state a reason inline; unexplained markers are a review flag);
 *   - test files (*.test.*, *.spec.*).
 *
 * The ledger `_comment` / `_notes` record WHY each allowance exists
 * (A-class illustration assets vs B-class data-driven values). Regenerate
 * allowances after a legitimate decrease with: node scripts/check-inline-colors.mjs --update
 */
import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join, dirname, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const WEBUI_ROOT = join(SCRIPT_DIR, '..');
const SRC_ROOT = join(WEBUI_ROOT, 'src');
const LEDGER_PATH = join(WEBUI_ROOT, 'webui-style-ledger.json');

const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g;
const VAR_FALLBACK_RE = /var\(--[^)]*\)/g;
const EXEMPT_MARKER = 'inline-color: exempt';
const TEST_FILE_RE = /\.(test|spec)\.[cm]?[jt]sx?$/;

function listSourceFiles(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      listSourceFiles(full, acc);
    } else if (/\.[cm]?[jt]sx?$/.test(name) && !TEST_FILE_RE.test(name)) {
      acc.push(full);
    }
  }
  return acc;
}

function countHexLiterals(filePath) {
  const lines = readFileSync(filePath, 'utf8').split(/\r?\n/);
  const hits = [];
  lines.forEach((line, index) => {
    if (line.includes(EXEMPT_MARKER)) return;
    const withoutFallbacks = line.replace(VAR_FALLBACK_RE, 'var()');
    let match;
    while ((match = HEX_RE.exec(withoutFallbacks)) !== null) {
      hits.push({ line: index + 1, value: match[0] });
    }
  });
  return hits;
}

function buildCounts() {
  const counts = {};
  for (const file of listSourceFiles(SRC_ROOT)) {
    const rel = relative(WEBUI_ROOT, file).split(sep).join('/');
    const hits = countHexLiterals(file);
    if (hits.length > 0) counts[rel] = hits;
  }
  return counts;
}

const updateMode = process.argv.includes('--update');
const ledger = JSON.parse(readFileSync(LEDGER_PATH, 'utf8'));
const allowances = ledger.entries ?? {};
const counts = buildCounts();

if (updateMode) {
  const entries = {};
  for (const [file, hits] of Object.entries(counts)) {
    entries[file] = hits.length;
  }
  // Never raise an allowance above its current value via --update.
  for (const [file, allowance] of Object.entries(allowances)) {
    if (!(file in entries)) entries[file] = 0;
    entries[file] = Math.min(entries[file], allowance);
  }
  ledger.entries = Object.fromEntries(Object.entries(entries).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(LEDGER_PATH, JSON.stringify(ledger, null, 2) + '\n');
  console.log(`check-inline-colors: ledger updated — ${Object.values(ledger.entries).reduce((a, b) => a + b, 0)} allowance(s) across ${Object.keys(ledger.entries).length} file(s) (ratchet only decreases)`);
  process.exit(0);
}

const violations = [];
const files = new Set([...Object.keys(allowances), ...Object.keys(counts)]);
for (const file of [...files].sort()) {
  const allowance = allowances[file] ?? 0;
  const hits = counts[file] ?? [];
  if (hits.length > allowance) {
    violations.push({ file, allowance, actual: hits.length, hits: hits.slice(0, 12) });
  }
}

if (violations.length > 0) {
  console.error('check-inline-colors: VIOLATIONS — inline hex colors above ledger allowance.');
  console.error('Migrate to CSS variables (src/index.css or themes.generated.css tokens), or,');
  console.error('for data-driven values only, add a `// inline-color: exempt — <reason>` line marker.');
  for (const v of violations) {
    console.error(`\n${v.file}: ${v.actual} > allowance ${v.allowance}`);
    for (const hit of v.hits) console.error(`  line ${hit.line}: ${hit.value}`);
    if (v.hits.length === 12 && v.actual > 12) console.error(`  ... and ${v.actual - 12} more`);
  }
  process.exit(1);
}

const total = Object.values(counts).reduce((a, hits) => a + hits.length, 0);
console.log(`check-inline-colors: clean — ${total} inline hex literal(s), ratchet baseline held (${Object.keys(allowances).length} ledger file(s))`);
