import React, { useId } from 'react';
import './EmptyState.css';

export type EmptyStateType = 'directory' | 'search' | 'offline';

export interface EmptyStateActionConfig {
  label: React.ReactNode;
  onClick?: (event: React.MouseEvent<HTMLElement>) => void;
  href?: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  variant?: 'primary' | 'secondary';
  'data-testid'?: string;
}

export type EmptyStateAction = React.ReactNode | EmptyStateActionConfig;

export interface EmptyStateProps {
  type?: EmptyStateType;
  title?: React.ReactNode;
  description?: React.ReactNode;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  children?: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  'data-testid'?: string;
}

/* ─────────────────────────────────────────────────────────────
   Illustration 1: Directory (3D Isometric Grid Archive & Cube)
   ───────────────────────────────────────────────────────────── */
function DirectoryIllustration() {
  const uid = useId().replace(/:/g, '_');

  return (
    <svg
      viewBox="0 0 240 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="dark-archive-svg dark-archive-directory-svg"
      role="img"
      aria-label="Empty directory archive"
      data-testid="empty-state-illustration-directory"
    >
      <defs>
        <radialGradient id={`${uid}-ground-glow`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.22" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${uid}-box-left`} x1="65" y1="115" x2="120" y2="190" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.12" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-ink-1)' }} stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id={`${uid}-box-right`} x1="175" y1="115" x2="120" y2="190" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.16" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-ink-1)' }} stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id={`${uid}-box-top`} x1="120" y1="85" x2="120" y2="145" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-accent-hi)' }} stopOpacity="0.18" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.08" />
        </linearGradient>
        <linearGradient id={`${uid}-cube-left`} x1="102" y1="42" x2="120" y2="70" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-sky)' }} stopOpacity="0.8" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-deep-1)' }} stopOpacity="0.4" />
        </linearGradient>
        <linearGradient id={`${uid}-cube-right`} x1="138" y1="42" x2="120" y2="70" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-accent-hi)' }} stopOpacity="0.85" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-deep-2)' }} stopOpacity="0.45" />
        </linearGradient>
        <linearGradient id={`${uid}-cube-top`} x1="120" y1="32" x2="120" y2="52" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-purple)' }} stopOpacity="0.9" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-accent-hi)' }} stopOpacity="0.75" />
        </linearGradient>
      </defs>

      {/* Ground ambient glow & isometric grid plane */}
      <ellipse cx="120" cy="155" rx="72" ry="26" fill={`url(#${uid}-ground-glow)`} />
      <path
        d="M 40 150 L 120 195 L 200 150 M 60 138 L 120 172 L 180 138 M 80 126 L 120 149 L 160 126"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.18"
        strokeWidth="1"
      />
      <path
        d="M 80 172 L 160 126 M 120 195 L 200 150 M 40 150 L 120 104"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.14"
        strokeWidth="1"
      />

      {/* 3D Isometric Transparent Archive Box */}
      {/* Interior wireframe back edges */}
      <path
        d="M 65 115 L 120 130 L 175 115 M 120 130 L 120 175"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.28"
        strokeWidth="1"
        strokeDasharray="3 3"
      />

      {/* Left Face */}
      <polygon
        points="65,115 120,145 120,190 65,160"
        fill={`url(#${uid}-box-left)`}
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.55"
        strokeWidth="1.2"
      />
      {/* Left Face Grid Lines */}
      <path
        d="M 83.3 125 L 83.3 170 M 101.6 135 L 101.6 180"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.28"
        strokeWidth="1"
      />
      <path
        d="M 65 130 L 120 160 M 65 145 L 120 175"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.22"
        strokeWidth="1"
      />

      {/* Right Face */}
      <polygon
        points="120,145 175,115 175,160 120,190"
        fill={`url(#${uid}-box-right)`}
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.6"
        strokeWidth="1.2"
      />
      {/* Right Face Grid Lines */}
      <path
        d="M 138.3 135 L 138.3 180 M 156.6 125 L 156.6 170"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.28"
        strokeWidth="1"
      />
      <path
        d="M 120 160 L 175 130 M 120 175 L 175 145"
        style={{ stroke: 'var(--illu-accent)' }}
        strokeOpacity="0.22"
        strokeWidth="1"
      />

      {/* Top Face */}
      <polygon
        points="120,85 175,115 120,145 65,115"
        fill={`url(#${uid}-box-top)`}
        style={{ stroke: 'var(--illu-accent-hi)' }}
        strokeOpacity="0.75"
        strokeWidth="1.2"
      />
      {/* Top Face Isometric Grid Lines */}
      <path
        d="M 83.3 105 L 138.3 135 M 101.6 95 L 156.6 125 M 101.6 135 L 156.6 105 M 83.3 125 L 138.3 95"
        style={{ stroke: 'var(--illu-accent-hi)' }}
        strokeOpacity="0.32"
        strokeWidth="1"
      />

      {/* Glowing Corner Accents */}
      <circle cx="120" cy="145" r="2.5" style={{ fill: 'var(--illu-sky)' }} />
      <circle cx="65" cy="115" r="2" style={{ fill: 'var(--illu-accent-hi)' }} opacity="0.8" />
      <circle cx="175" cy="115" r="2" style={{ fill: 'var(--illu-accent-hi)' }} opacity="0.8" />
      <circle cx="120" cy="85" r="2" style={{ fill: 'var(--illu-purple-soft)' }} opacity="0.8" />
      <circle cx="120" cy="190" r="2.5" style={{ fill: 'var(--illu-sky)' }} opacity="0.9" />

      {/* Tech Telemetry Markings */}
      <text x="70" y="156" style={{ fill: 'var(--illu-muted)' }} fontSize="6" fontFamily="monospace" letterSpacing="1" opacity="0.75">
        ARCHIVE // 01
      </text>

      {/* Floating Cube Shadow */}
      <ellipse
        cx="120"
        cy="115"
        rx="16"
        ry="8"
        style={{ fill: 'var(--illu-sky)' }}
        className="dark-archive-float-shadow"
      />

      {/* Micro-hovering Isometric Cube */}
      <g className="dark-archive-float">
        {/* Left Face */}
        <polygon
          points="102,42 120,52 120,70 102,60"
          fill={`url(#${uid}-cube-left)`}
          style={{ stroke: 'var(--illu-sky)' }}
          strokeWidth="1.2"
        />
        {/* Right Face */}
        <polygon
          points="120,52 138,42 138,60 120,70"
          fill={`url(#${uid}-cube-right)`}
          style={{ stroke: 'var(--illu-accent-hi)' }}
          strokeWidth="1.2"
        />
        {/* Top Face */}
        <polygon
          points="120,32 138,42 120,52 102,42"
          fill={`url(#${uid}-cube-top)`}
          style={{ stroke: 'var(--illu-purple)' }}
          strokeWidth="1.4"
        />

        {/* Center Glowing Core Node */}
        <circle cx="120" cy="42" r="2.5" style={{ fill: 'var(--illu-contrast)' }} opacity="0.95" />
        <circle cx="120" cy="42" r="5" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1" strokeOpacity="0.6" fill="none" />

        {/* Top Telemetry Tick */}
        <path d="M 120 28 L 120 22 M 116 25 L 124 25" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1" strokeOpacity="0.7" />
      </g>
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   Illustration 2: Search (Radar Beam & Coordinate Crosshair)
   ───────────────────────────────────────────────────────────── */
function SearchIllustration() {
  const uid = useId().replace(/:/g, '_');

  return (
    <svg
      viewBox="0 0 240 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="dark-archive-svg dark-archive-search-svg"
      role="img"
      aria-label="No search results"
      data-testid="empty-state-illustration-search"
    >
      <defs>
        <radialGradient id={`${uid}-radar-glow`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" style={{ stopColor: 'var(--illu-sky)' }} stopOpacity="0.15" />
          <stop offset="60%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.05" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${uid}-sweep-beam`} x1="120" y1="100" x2="185" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0%" style={{ stopColor: 'var(--illu-sky)' }} stopOpacity="0.4" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-accent)' }} stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {/* Radar Background Glow */}
      <circle cx="120" cy="100" r="75" fill={`url(#${uid}-radar-glow)`} />

      {/* Concentric Radar Rings */}
      <circle cx="120" cy="100" r="75" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.32" strokeWidth="1" />
      <circle cx="120" cy="100" r="55" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.38" strokeWidth="1" strokeDasharray="4 3" />
      <circle cx="120" cy="100" r="35" style={{ stroke: 'var(--illu-accent-hi)' }} strokeOpacity="0.48" strokeWidth="1" />
      <circle cx="120" cy="100" r="15" style={{ stroke: 'var(--illu-sky)' }} strokeOpacity="0.65" strokeWidth="1" />

      {/* Coordinate Reticle Axes */}
      <line x1="30" y1="100" x2="210" y2="100" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" strokeDasharray="3 3" />
      <line x1="120" y1="15" x2="120" y2="185" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" strokeDasharray="3 3" />

      {/* Coordinate Axis Tick Marks */}
      {/* r=35 */}
      <line x1="85" y1="97" x2="85" y2="103" style={{ stroke: 'var(--illu-accent-hi)' }} strokeWidth="1" strokeOpacity="0.7" />
      <line x1="155" y1="97" x2="155" y2="103" style={{ stroke: 'var(--illu-accent-hi)' }} strokeWidth="1" strokeOpacity="0.7" />
      <line x1="117" y1="65" x2="123" y2="65" style={{ stroke: 'var(--illu-accent-hi)' }} strokeWidth="1" strokeOpacity="0.7" />
      <line x1="117" y1="135" x2="123" y2="135" style={{ stroke: 'var(--illu-accent-hi)' }} strokeWidth="1" strokeOpacity="0.7" />
      {/* r=55 */}
      <line x1="65" y1="97" x2="65" y2="103" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1" strokeOpacity="0.6" />
      <line x1="175" y1="97" x2="175" y2="103" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1" strokeOpacity="0.6" />
      <line x1="117" y1="45" x2="123" y2="45" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1" strokeOpacity="0.6" />
      <line x1="117" y1="155" x2="123" y2="155" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1" strokeOpacity="0.6" />
      {/* r=75 */}
      <line x1="45" y1="96" x2="45" y2="104" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1.2" strokeOpacity="0.5" />
      <line x1="195" y1="96" x2="195" y2="104" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1.2" strokeOpacity="0.5" />
      <line x1="116" y1="25" x2="124" y2="25" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1.2" strokeOpacity="0.5" />
      <line x1="116" y1="175" x2="124" y2="175" style={{ stroke: 'var(--illu-accent)' }} strokeWidth="1.2" strokeOpacity="0.5" />

      {/* HUD Reticle Corner Targeting Brackets */}
      <path d="M 52 35 L 40 35 L 40 47" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeOpacity="0.85" fill="none" />
      <path d="M 188 35 L 200 35 L 200 47" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeOpacity="0.85" fill="none" />
      <path d="M 52 165 L 40 165 L 40 153" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeOpacity="0.85" fill="none" />
      <path d="M 188 165 L 200 165 L 200 153" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeOpacity="0.85" fill="none" />

      {/* Target Data Blips */}
      <circle cx="152" cy="72" r="2.5" style={{ fill: 'var(--illu-sky)' }} />
      <circle cx="152" cy="72" r="5" style={{ stroke: 'var(--illu-sky)' }} strokeOpacity="0.4" strokeWidth="1" fill="none" />
      <circle cx="88" cy="122" r="2" style={{ fill: 'var(--illu-accent-hi)' }} />
      <circle cx="140" cy="132" r="1.8" style={{ fill: 'var(--illu-accent)' }} />

      {/* HUD Telemetry Labels */}
      <text x="44" y="28" style={{ fill: 'var(--illu-muted)' }} fontSize="6.5" fontFamily="monospace" letterSpacing="1" opacity="0.8">
        RADAR // 360°
      </text>
      <text x="156" y="178" style={{ fill: 'var(--illu-muted)' }} fontSize="6.5" fontFamily="monospace" letterSpacing="1" opacity="0.8">
        SCAN // NULL
      </text>

      {/* Radar Scan Beam */}
      <g className="dark-archive-radar-sweep">
        {/* Sweep Wedge Path (45 degree beam) */}
        <path
          d="M 120 100 L 195 100 A 75 75 0 0 0 173 47 Z"
          fill={`url(#${uid}-sweep-beam)`}
        />
        {/* Leading edge laser line */}
        <line x1="120" y1="100" x2="195" y2="100" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeLinecap="round" />
      </g>

      {/* Solid Central Reticle Crosshair & Pivot Point */}
      <line x1="108" y1="100" x2="132" y2="100" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeLinecap="round" />
      <line x1="120" y1="88" x2="120" y2="112" style={{ stroke: 'var(--illu-sky)' }} strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="120" cy="100" r="3.5" style={{ fill: 'var(--illu-sky)' }} />
      <circle cx="120" cy="100" r="1.5" style={{ fill: 'var(--illu-contrast)' }} />
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   Illustration 3: Offline (Disconnected Node & Amber Pulse)
   ───────────────────────────────────────────────────────────── */
function OfflineIllustration() {
  const uid = useId().replace(/:/g, '_');

  return (
    <svg
      viewBox="0 0 240 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="dark-archive-svg dark-archive-offline-svg"
      role="img"
      aria-label="Service offline disconnected"
      data-testid="empty-state-illustration-offline"
    >
      <defs>
        <radialGradient id={`${uid}-amber-glow`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" style={{ stopColor: 'var(--illu-amber)' }} stopOpacity="0.22" />
          <stop offset="60%" style={{ stopColor: 'var(--illu-amber)' }} stopOpacity="0.06" />
          <stop offset="100%" style={{ stopColor: 'var(--illu-amber)' }} stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Ambient Amber Glow */}
      <circle cx="120" cy="100" r="60" fill={`url(#${uid}-amber-glow)`} />

      {/* Left Node Cluster */}
      <circle cx="36" cy="72" r="4" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-deep-3)' }} strokeOpacity="0.55"  />
      <line x1="39" y1="74" x2="56" y2="94" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" />
      <circle cx="36" cy="128" r="4" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-deep-3)' }} strokeOpacity="0.55"  />
      <line x1="39" y1="126" x2="56" y2="106" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" />

      {/* Main Left Node */}
      <circle cx="60" cy="100" r="14" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-ink-2)' }} strokeOpacity="0.65" strokeWidth="1.5"  />
      <circle cx="60" cy="100" r="8" style={{ stroke: 'var(--illu-accent-hi)' }} strokeOpacity="0.8" strokeWidth="1.2" fill="none" />
      <circle cx="60" cy="100" r="3" style={{ fill: 'var(--illu-accent-hi)' }} />

      {/* Right Node Cluster */}
      <circle cx="204" cy="72" r="4" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-deep-3)' }} strokeOpacity="0.55"  />
      <line x1="201" y1="74" x2="184" y2="94" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" />
      <circle cx="204" cy="128" r="4" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-deep-3)' }} strokeOpacity="0.55"  />
      <line x1="201" y1="126" x2="184" y2="106" style={{ stroke: 'var(--illu-accent)' }} strokeOpacity="0.35" strokeWidth="1" />

      {/* Main Right Node */}
      <circle cx="180" cy="100" r="14" style={{ stroke: 'var(--illu-accent)', fill: 'var(--illu-ink-2)' }} strokeOpacity="0.65" strokeWidth="1.5"  />
      <circle cx="180" cy="100" r="8" style={{ stroke: 'var(--illu-accent-hi)' }} strokeOpacity="0.8" strokeWidth="1.2" fill="none" />
      <circle cx="180" cy="100" r="3" style={{ fill: 'var(--illu-accent-hi)' }} />

      {/* Severed Transmission Link (dashed lines with break) */}
      <line x1="74" y1="100" x2="94" y2="100" style={{ stroke: 'var(--illu-accent-hi)' }} strokeOpacity="0.5" strokeWidth="1.5" strokeDasharray="3 2" />
      <line x1="146" y1="100" x2="166" y2="100" style={{ stroke: 'var(--illu-accent-hi)' }} strokeOpacity="0.5" strokeWidth="1.5" strokeDasharray="3 2" />

      {/* Severed Break Slashes */}
      <line x1="97" y1="94" x2="103" y2="106" style={{ stroke: 'var(--illu-amber)' }} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.85" />
      <line x1="137" y1="94" x2="143" y2="106" style={{ stroke: 'var(--illu-amber)' }} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.85" />

      {/* Amber Warning Ripples (Pulsing waves) */}
      <circle cx="120" cy="100" r="28" className="dark-archive-pulse dark-archive-pulse-1" style={{ stroke: 'var(--illu-amber)' }} strokeWidth="1.5" fill="none" />
      <circle cx="120" cy="100" r="42" className="dark-archive-pulse dark-archive-pulse-2" style={{ stroke: 'var(--illu-amber)' }} strokeWidth="1.2" fill="none" />
      <circle cx="120" cy="100" r="56" className="dark-archive-pulse dark-archive-pulse-3" style={{ stroke: 'var(--illu-amber-hi)' }} strokeWidth="1" fill="none" />

      {/* Central Amber Alert Hexagonal Badge */}
      <polygon
        points="120,78 139,89 139,111 120,122 101,111 101,89"
        style={{ stroke: 'var(--illu-amber)', fill: 'var(--illu-ink-3)' }}
        strokeWidth="1.8"
      />
      <polygon
        points="120,83 134,92 134,108 120,117 106,108 106,92"
        style={{ stroke: 'var(--illu-amber-hi)' }}
        strokeWidth="1"
        strokeDasharray="2 2"
        fill="none"
        opacity="0.6"
      />

      {/* Disconnected / Broken Link Icon inside Hexagon */}
      <path
        d="M 112 96 L 115 93 C 117.5 90.5 121.5 90.5 124 93 L 126 95"
        style={{ stroke: 'var(--illu-amber)' }}
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M 128 104 L 125 107 C 122.5 109.5 118.5 109.5 116 107 L 114 105"
        style={{ stroke: 'var(--illu-amber)' }}
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
      {/* Red disconnect diagonal slash */}
      <line x1="111" y1="108" x2="129" y2="92" style={{ stroke: 'var(--illu-danger)' }} strokeWidth="1.8" strokeLinecap="round" />

      {/* Telemetry Warning Label */}
      <text x="120" y="142" textAnchor="middle" style={{ fill: 'var(--illu-amber-hi)' }} fontSize="7" fontFamily="monospace" letterSpacing="1.2" opacity="0.9">
        OFFLINE // 503
      </text>
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   Default copy per type
   ───────────────────────────────────────────────────────────── */
const DEFAULT_CONTENT: Record<EmptyStateType, { title: string; description: string }> = {
  directory: {
    title: '档案库为空',
    description: '当前目录中没有可显示的内容或资源。',
  },
  search: {
    title: '未检索到匹配结果',
    description: '未找到符合检索条件的资源，请调整关键词或过滤条件。',
  },
  offline: {
    title: '连接已中断',
    description: '无法连接到资源库服务，请检查网络或服务状态。',
  },
};

/* ─────────────────────────────────────────────────────────────
   Helper: Render Action (Config Object or ReactNode)
   ───────────────────────────────────────────────────────────── */
function isActionConfig(action: unknown): action is EmptyStateActionConfig {
  return (
    typeof action === 'object' &&
    action !== null &&
    'label' in action &&
    !React.isValidElement(action)
  );
}

function renderAction(
  action: EmptyStateAction | undefined,
  defaultVariant: 'primary' | 'secondary',
  key: string
) {
  if (!action) return null;

  if (React.isValidElement(action)) {
    return <React.Fragment key={key}>{action}</React.Fragment>;
  }

  if (isActionConfig(action)) {
    const variant = action.variant || defaultVariant;
    const buttonClass = `empty-state-btn empty-state-btn-${variant} ${action.className || ''}`.trim();

    if (action.href) {
      return (
        <a
          key={key}
          href={action.href}
          className={buttonClass}
          onClick={action.onClick}
          data-testid={action['data-testid']}
        >
          {action.icon && <span className="empty-state-btn-icon">{action.icon}</span>}
          <span>{action.label}</span>
        </a>
      );
    }

    return (
      <button
        key={key}
        type="button"
        className={buttonClass}
        onClick={action.onClick}
        disabled={action.disabled}
        data-testid={action['data-testid']}
      >
        {action.icon && <span className="empty-state-btn-icon">{action.icon}</span>}
        <span>{action.label}</span>
      </button>
    );
  }

  return <span key={key}>{action}</span>;
}

/* ─────────────────────────────────────────────────────────────
   Main Component: EmptyState
   ───────────────────────────────────────────────────────────── */
export function EmptyState({
  type = 'directory',
  title,
  description,
  primaryAction,
  secondaryAction,
  children,
  className = '',
  style,
  'data-testid': testId = 'empty-state',
}: EmptyStateProps) {
  const defaults = DEFAULT_CONTENT[type] || DEFAULT_CONTENT.directory;
  const resolvedTitle = title !== undefined ? title : defaults.title;
  const resolvedDescription = description !== undefined ? description : defaults.description;

  return (
    <div
      className={`empty-state empty-state-${type} ${className}`.trim()}
      style={style}
      data-testid={testId}
    >
      <div className="empty-state-illustration">
        {type === 'directory' && <DirectoryIllustration />}
        {type === 'search' && <SearchIllustration />}
        {type === 'offline' && <OfflineIllustration />}
      </div>

      <div className="empty-state-content">
        {resolvedTitle && <h3 className="empty-state-title">{resolvedTitle}</h3>}
        {resolvedDescription && (
          <p className="empty-state-description">{resolvedDescription}</p>
        )}
      </div>

      {(primaryAction || secondaryAction) && (
        <div className="empty-state-actions">
          {renderAction(primaryAction, 'primary', 'primary')}
          {renderAction(secondaryAction, 'secondary', 'secondary')}
        </div>
      )}

      {children}
    </div>
  );
}
