/**
 * Trigger a browser download for an already-fetched blob.
 *
 * Lives outside the api layer on purpose: the api modules return data
 * (blob + filename), while this UI helper owns the DOM side effects.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Delay the revoke: Firefox grabs the blob URL from the download engine
  // asynchronously, and revoking too early can abort the save dialog.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
