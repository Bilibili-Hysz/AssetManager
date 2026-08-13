import { X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';

interface TagChipProps {
  name: string;
  count?: number;
  onRemove?: () => void;
  onClick?: () => void;
}

export function TagChip({ name, count, onRemove, onClick }: TagChipProps) {
  const { t } = useI18n();
  // E8: a chip with onClick behaves as a button — give it a button role, make it
  // focusable and trigger onClick from Enter/Space so it is keyboard accessible.
  const interactive = Boolean(onClick);
  const handleKeyDown = (event: React.KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onClick?.();
    }
  };
  return (
    <span
      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors"
      style={{
        backgroundColor: 'var(--color-accent-subtle)',
        color: 'var(--color-accent)',
        border: '1px solid var(--color-accent-border)',
      }}
    >
      {/* E8: a chip with onClick behaves as a button — role + focus + Enter/Space.
          Kept as a SIBLING of the remove button: nesting a button inside a
          role="button" span is an invalid interactive control (nested-interactive). */}
      <span
        role={interactive ? 'button' : undefined}
        tabIndex={interactive ? 0 : undefined}
        onKeyDown={interactive ? handleKeyDown : undefined}
        className={`inline-flex items-center gap-1 ${onClick ? 'cursor-pointer' : ''}`}
        onClick={onClick}
      >
        {name}
        {count != null && <span style={{ opacity: 0.7 }}>({count})</span>}
      </span>
      {onRemove && (
        <button
          type="button"
          aria-label={t('info.remove_tag', name)}
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="ml-0.5 hover:opacity-70 transition-opacity"
          style={{ color: 'var(--color-accent)' }}
        >
          <X size={12} />
        </button>
      )}
    </span>
  );
}
