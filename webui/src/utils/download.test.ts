// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { triggerBlobDownload } from './download';

describe('triggerBlobDownload', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('creates an object URL, clicks a temporary anchor, and revokes it', () => {
    vi.useFakeTimers();
    const createObjectURL = vi.fn().mockReturnValue('blob:dl-1');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    triggerBlobDownload(new Blob(['data']), 'hero.zip');

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    // The anchor carries the filename and was removed from the document.
    expect(document.querySelector('a[download="hero.zip"]')).toBeNull();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:dl-1');
    click.mockRestore();
  });
});
