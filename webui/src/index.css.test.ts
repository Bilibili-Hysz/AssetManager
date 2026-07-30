import { describe, expect, it } from 'vitest';
// @ts-expect-error The webui intentionally does not ship Node types.
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('./index.css', import.meta.url), 'utf8');

describe('light theme surface contract', () => {
  it('prevents UI images from being text-selected or browser-dragged', () => {
    const imageRuleStart = css.indexOf('img {');
    expect(imageRuleStart).toBeGreaterThanOrEqual(0);
    const imageRule = css.slice(imageRuleStart, css.indexOf('}', imageRuleStart) + 1);
    expect(imageRule).toContain('user-select: none');
    expect(imageRule).toContain('-webkit-user-drag: none');
  });

  it('keeps the image preview surface visible and unaffected by browser color transforms', () => {
    const surfaceStart = css.indexOf('.asset-preview-surface');
    expect(surfaceStart).toBeGreaterThanOrEqual(0);
    const surface = css.slice(surfaceStart, css.indexOf('}', surfaceStart) + 1);
    expect(surface).toContain('display: block');
    expect(surface).toContain('max-height: 100%');
    expect(surface).toContain('max-width: 100%');
    expect(surface).toContain('color-scheme: only light');
    expect(surface).toContain('forced-color-adjust: none');
    expect(surface).toContain('filter: none');
  });

  it('maps the fixed slate classes used by the primary UI to light tokens', () => {
    for (const className of [
      'bg-slate-950', 'bg-slate-900', 'bg-slate-900/80', 'bg-slate-800', 'bg-slate-800/50',
      'bg-slate-900/30', 'bg-slate-900/50', 'bg-slate-900/90', 'bg-slate-900/20',
      'bg-slate-800/20', 'bg-slate-800/30', 'bg-slate-800/40', 'bg-slate-800/80', 'bg-slate-800/90',
      'bg-slate-600', 'bg-slate-600/50', 'bg-slate-600/70', 'bg-slate-700', 'bg-slate-700/20', 'bg-slate-700/30', 'bg-slate-700/50', 'bg-slate-700/80', 'bg-slate-700/70',
      'text-slate-100', 'text-slate-200', 'text-slate-300', 'text-slate-400', 'text-slate-500', 'text-slate-600', 'text-white', 'text-white/60', 'text-white/70',
      'border-slate-700', 'border-slate-700/50', 'border-slate-600/50',
      'hover:bg-slate-700', 'hover:bg-slate-700/50', 'hover:bg-slate-700/80', 'hover:bg-slate-800/30', 'hover:bg-slate-800/50', 'hover:bg-slate-900/30', 'hover:text-white',
    ]) {
      expect(css).toContain(`html.light .${className.replace(':', '\\:').replace('/', '\\/')}`);
    }
  });

  it('uses light theme tokens in the overrides', () => {
    const lightOverrides = css.slice(css.indexOf('html.light'));
    expect(lightOverrides).toContain('var(--color-bg)');
    expect(lightOverrides).toContain('var(--color-surface)');
    expect(lightOverrides).toContain('var(--color-text)');
    expect(lightOverrides).toContain('var(--color-border)');
  });
});
