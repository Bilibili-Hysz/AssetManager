import { ArrowUpRight, Image as ImageIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { SearchResult } from '../../types/api';

interface LegacyAssetCardProps {
  asset: SearchResult;
}

export default function LegacyAssetCard({ asset }: LegacyAssetCardProps) {
  const href = `/store/${asset.path.split('/').map(encodeURIComponent).join('/')}`;
  const thumbnail = asset.thumbnail_url;
  return (
    <article style={{ border: '1px solid var(--color-border)', borderRadius: 16, overflow: 'hidden', background: 'var(--color-surface)' }}>
      <Link to={href} style={{ display: 'block', position: 'relative', aspectRatio: '4 / 3', background: 'var(--color-surface-hover)' }}>
        {thumbnail ? <img src={thumbnail} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} /> : <span style={{ display: 'grid', height: '100%', placeItems: 'center', color: 'var(--color-text-muted)' }}><ImageIcon size={28} /></span>}
        <span style={{ position: 'absolute', right: 12, bottom: 12, display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 999, color: '#fff', background: 'rgb(15 23 42 / 72%)' }}><ArrowUpRight size={16} /></span>
      </Link>
      <div style={{ padding: 16 }}>
        <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: 12 }}>{asset.category || asset.type}</p>
        <Link to={href} style={{ display: 'block', marginTop: 6, color: 'var(--color-text)', fontSize: 16, fontWeight: 650, textDecoration: 'none' }}>{asset.name}</Link>
        <p style={{ margin: '8px 0 0', color: 'var(--color-text-secondary)', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{asset.path}</p>
      </div>
    </article>
  );
}
