import { X } from 'lucide-react';

interface TagChipProps {
  name: string;
  count?: number;
  onRemove?: () => void;
  onClick?: () => void;
}

export function TagChip({ name, count, onRemove, onClick }: TagChipProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium
        bg-brand-500/10 text-brand-300 border border-brand-500/20
        ${onClick ? 'cursor-pointer hover:bg-brand-500/20' : ''}`}
      onClick={onClick}
    >
      {name}
      {count != null && <span className="text-brand-400">({count})</span>}
      {onRemove && (
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="ml-0.5 hover:text-white transition-colors"
        >
          <X size={12} />
        </button>
      )}
    </span>
  );
}