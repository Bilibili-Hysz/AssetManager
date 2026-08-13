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

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('share.url_missing', 'error'));
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

  it('shows loading text while creating', async () => {
    create.mockReturnValue(new Promise(() => {})); // never resolves
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));

    await waitFor(() => expect(screen.getByText('browse.loading')).toBeDefined());
  });

  it('disables the create button while creating', async () => {
    create.mockReturnValue(new Promise(() => {}));
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));

    await waitFor(() => {
      const btn = screen.getByRole('button', { name: 'browse.loading' });
      expect((btn as HTMLButtonElement).disabled).toBe(true);
    });
  });

  it('displays API error message', async () => {
    create.mockRejectedValue(new Error('quota exceeded'));
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('quota exceeded', 'error'));
  });

  it('displays generic error for non-Error exceptions', async () => {
    create.mockRejectedValue('something');
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('share.create_failed', 'error'));
  });

  it('shows toast on clipboard copy failure', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    create.mockResolvedValue({ id: 'share-1', url: 'http://server/s/share-1' });
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));
    await waitFor(() => expect(screen.getByDisplayValue('http://server/s/share-1')).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'action.copy' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('share.copy_failed', 'error'));
  });

  it('shows success toast after copy', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    create.mockResolvedValue({ id: 'share-1', url: 'http://server/s/share-1' });
    render(<ShareDialog open onClose={vi.fn()} paths={['a.png']} />);

    fireEvent.click(screen.getByRole('button', { name: 'share.create_btn' }));
    await waitFor(() => expect(screen.getByDisplayValue('http://server/s/share-1')).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'action.copy' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('action.copied', 'success'));
  });
});
