import { useState } from 'react';
import { Copy, Check, Search } from 'lucide-react';

export interface DominantPalette {
  colors: string[];
  dominant?: string;
}

interface DominantPaletteStripProps {
  palette: DominantPalette | string[];
  onSearchByTone?: (hex: string) => void;
  className?: string;
}

/**
 * Compute relative luminance according to WCAG 2.1 formula
 */
function getLuminance(hex: string): number {
  const cleanHex = hex.replace('#', '');
  if (cleanHex.length !== 6) return 0.5;
  const r = parseInt(cleanHex.slice(0, 2), 16) / 255;
  const g = parseInt(cleanHex.slice(2, 4), 16) / 255;
  const b = parseInt(cleanHex.slice(4, 6), 16) / 255;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function DominantPaletteStrip({
  palette,
  onSearchByTone,
  className = '',
}: DominantPaletteStripProps) {
  const [copiedHex, setCopiedHex] = useState<string | null>(null);

  const colors = Array.isArray(palette) ? palette : palette.colors;
  if (!colors || colors.length === 0) return null;

  const displayColors = colors.slice(0, 5);

  const handleCopy = async (hex: string) => {
    try {
      await navigator.clipboard.writeText(hex.toUpperCase());
      setCopiedHex(hex);
      setTimeout(() => setCopiedHex(null), 1800);
    } catch {
      // Ignore clipboard write failure
    }
  };

  return (
    <div
      data-testid="dominant-palette-strip"
      className={`flex items-center gap-2 p-2 rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] shadow-sm ${className}`}
    >
      <span className="text-[11px] font-mono uppercase tracking-wider text-[var(--color-text-muted)] pl-1.5 select-none">
        Palette
      </span>
      <div className="flex items-center gap-1.5 flex-1 min-w-0">
        {displayColors.map(hex => {
          const isLight = getLuminance(hex) > 0.52;
          const isCopied = copiedHex === hex;
          const textColor = isLight ? '#0f172a' : '#ffffff';

          return (
            <div
              key={hex}
              role="button"
              tabIndex={0}
              aria-label={`色值 ${hex}，点击复制`}
              onClick={() => void handleCopy(hex)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  void handleCopy(hex);
                }
              }}
              className="group relative flex-1 h-7 rounded-full cursor-pointer transition-all hover:scale-105 active:scale-95 flex items-center justify-center shadow-inner select-none"
              style={{
                backgroundColor: hex,
                boxShadow: 'inset 0 0 0 1px rgba(255, 255, 255, 0.15)',
              }}
            >
              <span
                className="text-[10px] font-mono font-semibold tracking-tight opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity flex items-center gap-1"
                style={{ color: textColor }}
              >
                {isCopied ? (
                  <>
                    <Check size={11} strokeWidth={2.5} />
                    <span>COPIED</span>
                  </>
                ) : (
                  <>
                    <Copy size={9} />
                    <span>{hex.toUpperCase()}</span>
                  </>
                )}
              </span>

              {onSearchByTone && (
                <button
                  type="button"
                  aria-label={`按色调检索 ${hex}`}
                  title="按相似色调检索"
                  onClick={e => {
                    e.stopPropagation();
                    onSearchByTone(hex);
                  }}
                  className="absolute -top-1.5 -right-1.5 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 p-1 rounded-full bg-[var(--color-surface)] border border-[var(--color-border)] shadow text-[var(--color-text)] hover:text-[var(--color-accent)] transition-opacity"
                >
                  <Search size={10} />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
