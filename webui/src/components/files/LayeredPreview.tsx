import { useEffect, useState } from 'react';
import { File, Folder } from 'lucide-react';

interface LayeredPreviewProps {
  src?: string;
  alt: string;
  isDir: boolean;
  size: 'grid' | 'list';
}

export function LayeredPreview({ src, alt, isDir, size }: LayeredPreviewProps) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const hasImage = Boolean(src) && !failed;
  const iconSize = size === 'grid' ? 36 : 16;

  useEffect(() => {
    setFailed(false);
    setLoaded(false);
  }, [src]);

  return (
    <div
      data-testid="layered-preview"
      data-size={size}
      className={size === 'grid' ? 'relative h-full w-full' : 'relative h-6 w-6'}
    >
      {hasImage ? (
        <>
          <div data-testid="layered-preview-back" className="absolute inset-0 translate-x-1 translate-y-1 rounded bg-slate-700/70" aria-hidden="true" />
          <div data-testid="layered-preview-back" className="absolute inset-0 translate-x-0.5 translate-y-0.5 rounded bg-slate-600/70" aria-hidden="true" />
          {!loaded && (
            <div
              className="absolute inset-0 rounded bg-slate-800/40 animate-pulse"
              aria-hidden="true"
            />
          )}
          <img
            src={src}
            alt={alt}
            loading="lazy"
            draggable={false}
            className={`relative h-full w-full rounded object-cover transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'}`}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          />
        </>
      ) : isDir ? (
        <Folder data-testid="layered-preview-folder" size={iconSize} className="text-amber-400/70" aria-hidden="true" />
      ) : (
        <File data-testid="layered-preview-file" size={iconSize} className="text-slate-500" aria-hidden="true" />
      )}
    </div>
  );
}
