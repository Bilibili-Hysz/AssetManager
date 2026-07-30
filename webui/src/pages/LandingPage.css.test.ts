import { describe, expect, it } from 'vitest';
// @ts-expect-error The webui intentionally does not ship Node types.
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('./LandingPage.css', import.meta.url), 'utf8');

describe('Gate non-selectable decoration contract', () => {
  it('prevents selecting the background image wall and decorative effect layers', () => {
    for (const className of [
      '.gate-image-wall',
      '.gate-overlay',
      '.gate-decoration',
      '.gate-sweep',
      '.gate-cursor-glow',
      '.gate-particle',
      '.gate-ripple',
      '.gate-avatar-ring',
    ]) {
      const start = css.indexOf(`${className} `);
      expect(start, `${className} rule should exist`).toBeGreaterThanOrEqual(0);
      const rule = css.slice(start, css.indexOf('}', start) + 1);
      expect(rule, `${className} should not be selectable`).toContain('user-select: none');
    }
  });
});
