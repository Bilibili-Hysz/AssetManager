/**
 * mapWithConcurrency — run an async worker over a list with a bounded number
 * of in-flight promises (built for the backend's per-item tag endpoints: the
 * route accepts a single file_path, so bulk tagging loops client-side).
 *
 * Contract:
 * - at most `limit` worker calls are in flight at any moment;
 * - one rejection never cancels or short-circuits the remaining items
 *   (failures are captured per item);
 * - results keep the input order regardless of completion order;
 * - `onProgress` fires after every settle with (completed, total), so the
 *   caller can render "i / N" style progress.
 */
export interface BatchItemResult<T> {
  item: T;
  ok: boolean;
  error?: unknown;
}

export async function mapWithConcurrency<T>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>,
  onProgress?: (completed: number, total: number) => void,
): Promise<Array<BatchItemResult<T>>> {
  const total = items.length;
  const results: Array<BatchItemResult<T>> = new Array(total);
  if (total === 0) return results;
  const laneCount = Math.max(1, Math.min(limit, total));
  let next = 0;
  let completed = 0;

  const runLane = async () => {
    while (next < total) {
      const index = next;
      next += 1;
      const item = items[index] as T;
      try {
        await worker(item, index);
        results[index] = { item, ok: true };
      } catch (error) {
        results[index] = { item, ok: false, error };
      }
      completed += 1;
      onProgress?.(completed, total);
    }
  };

  await Promise.all(Array.from({ length: laneCount }, () => runLane()));
  return results;
}
