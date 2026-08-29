import { describe, expect, it, vi } from 'vitest';
import { mapWithConcurrency } from './concurrency';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(resolvePromise => { resolve = resolvePromise; });
  return { promise, resolve };
}

const flush = () => new Promise(resolve => { setTimeout(resolve, 0); });

describe('mapWithConcurrency', () => {
  it('maps every item on success and preserves input order', async () => {
    const worker = vi.fn(async (_item: string, index: number) => {
      // Completion order deliberately diverges from the input order.
      await new Promise(resolve => { setTimeout(resolve, (3 - index) * 5); });
    });
    const results = await mapWithConcurrency(['a', 'b', 'c'], 4, worker);
    expect(results.map(result => result.item)).toEqual(['a', 'b', 'c']);
    expect(results.every(result => result.ok)).toBe(true);
    expect(worker).toHaveBeenCalledTimes(3);
  });

  it('continues with the remaining items when one rejects', async () => {
    const worker = vi.fn(async (item: string) => {
      if (item === 'b') throw new Error('item b failed');
    });
    const results = await mapWithConcurrency(['a', 'b', 'c', 'd'], 2, worker);
    expect(worker).toHaveBeenCalledTimes(4);
    expect(results.map(result => result.ok)).toEqual([true, false, true, true]);
    expect(results[1]?.error).toEqual(new Error('item b failed'));
  });

  it('reports progress after every settle with the final call at (total, total)', async () => {
    const progress = vi.fn();
    const gates = ['a', 'b', 'c', 'd', 'e'].map(() => deferred());
    let index = 0;
    const pending = mapWithConcurrency(['a', 'b', 'c', 'd', 'e'], 2, () => gates[index++]!.promise, progress);

    for (const gate of gates) gate.resolve();
    await pending;

    expect(progress).toHaveBeenCalledTimes(5);
    expect(progress).toHaveBeenLastCalledWith(5, 5);
    const completedValues = progress.mock.calls.map(call => call[0]);
    expect(completedValues.every(value => value >= 1 && value <= 5)).toBe(true);
  });

  it('never exceeds the concurrency cap and queues the remainder', async () => {
    const paths = Array.from({ length: 10 }, (_, i) => `p${i}`);
    const gates = paths.map(() => deferred());
    let started = 0;
    const pending = mapWithConcurrency(paths, 4, (_item, index) => {
      started += 1;
      return gates[index]!.promise;
    });

    await flush();
    expect(started).toBe(4);

    for (let i = 0; i < 4; i += 1) gates[i]!.resolve();
    await flush();
    expect(started).toBe(8);

    for (const gate of gates) gate.resolve();
    const results = await pending;
    expect(started).toBe(10);
    expect(results).toHaveLength(10);
    expect(results.every(result => result.ok)).toBe(true);
  });

  it('resolves immediately for an empty list without touching the worker', async () => {
    const worker = vi.fn();
    const progress = vi.fn();
    const results = await mapWithConcurrency([], 4, worker, progress);
    expect(results).toEqual([]);
    expect(worker).not.toHaveBeenCalled();
    expect(progress).not.toHaveBeenCalled();
  });

  it('uses a single lane when the limit is smaller than one or the list', async () => {
    const gates = ['a', 'b', 'c'].map(() => deferred());
    let started = 0;
    const pending = mapWithConcurrency(['a', 'b', 'c'], 0, (_item, index) => {
      started += 1;
      return gates[index]!.promise;
    });
    await flush();
    expect(started).toBe(1);
    for (const gate of gates) gate.resolve();
    await pending;
  });
});
