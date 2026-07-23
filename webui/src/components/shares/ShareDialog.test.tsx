// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShareDialog } from './ShareDialog';

const create = vi.fn();
const showToast = vi.fn();

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => ({ api: {} }) }));
vi.mock('../../api/shares', () => ({ createSharesApi: () => ({ create }) }));
vi.mock('../../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('../ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../ui/Modal', () => ({ Modal: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

describe('ShareDialog', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    create.mockReset();
    showToast.mockReset();
  });

  it('does not offer a copy action when the server response has no share URL', async () => {
    create.mockResolvedValue({ id: 'share-1' });
    render(<ShareDialog open onClose={vi.fn()} paths={['asset.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('Share URL was not returned by the server', 'error'));
    expect(screen.queryByRole('button', { name: 'action.copy' })).toBeNull();
  });

  it('copies only the URL returned by the server', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    create.mockResolvedValue({ id: 'share-1', url: 'http://server/s/share-1' });
    render(<ShareDialog open onClose={vi.fn()} paths={['asset.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));
    await waitFor(() => expect(screen.getByDisplayValue('http://server/s/share-1')).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'action.copy' }));

    expect(writeText).toHaveBeenCalledWith('http://server/s/share-1');
  });
});
