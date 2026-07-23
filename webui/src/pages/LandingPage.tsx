import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, SlidersHorizontal, X } from 'lucide-react';
import { Link, Navigate } from 'react-router-dom';
import { createMetadataApi } from '../api/metadata';
import { useAuth } from '../hooks/useAuth';
import type { ProjectItem } from '../types/api';

interface BackgroundSettings {
  blur: number;
  brightness: number;
  saturation: number;
  opacity: number;
}

const defaultBackgroundSettings: BackgroundSettings = {
  blur: 4,
  brightness: 55,
  saturation: 75,
  opacity: 38,
};

function summaryText(count: number) {
  return `${count} ${count === 1 ? 'asset' : 'assets'}`;
}

function backgroundStorageKey(theme: string | undefined) {
  return `assets-manager.gate-background.${theme || 'default'}`;
}

function readBackgroundSettings(key: string): BackgroundSettings {
  try {
    const saved = window.localStorage.getItem(key);
    if (!saved) return defaultBackgroundSettings;
    const parsed = JSON.parse(saved) as Partial<BackgroundSettings>;
    if (typeof parsed.blur !== 'number' || typeof parsed.brightness !== 'number' || typeof parsed.saturation !== 'number' || typeof parsed.opacity !== 'number') {
      return defaultBackgroundSettings;
    }
    return parsed as BackgroundSettings;
  } catch {
    return defaultBackgroundSettings;
  }
}

type FeaturedStatus = 'loading' | 'online' | 'unavailable';

export default function LandingPage() {
  const { serverInfo, isLoading, isAuthenticated, role, api } = useAuth();
  const [featured, setFeatured] = useState<ProjectItem[]>([]);
  const [failedFeatured, setFailedFeatured] = useState<Set<string>>(() => new Set());
  const [featuredStatus, setFeaturedStatus] = useState<FeaturedStatus>('loading');
  const [tuningOpen, setTuningOpen] = useState(false);
  const [settings, setSettings] = useState(defaultBackgroundSettings);
  const [isPageVisible, setIsPageVisible] = useState(() => document.visibilityState !== 'hidden');

  const isProtected = serverInfo?.auth_enabled && (!isAuthenticated || role === 'guest');
  const metadataApi = useMemo(() => createMetadataApi(api), [api]);
  const storageKey = useMemo(() => backgroundStorageKey(serverInfo?.theme_color), [serverInfo?.theme_color]);
  const visibleFeatured = featured.filter(item => !failedFeatured.has(item.path));

  useEffect(() => {
    setSettings(readBackgroundSettings(storageKey));
  }, [storageKey]);

  useEffect(() => {
    if (isLoading || isProtected) return;

    const controller = new AbortController();
    let active = true;
    setFeaturedStatus('loading');
    metadataApi.getHome(controller.signal)
      .then(response => {
        if (!active) return;
        setFeatured(response.recent_projects.slice(0, 6));
        setFailedFeatured(new Set());
        setFeaturedStatus('online');
      })
      .catch(() => {
        if (active) setFeaturedStatus('unavailable');
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [isLoading, isProtected, metadataApi]);

  useEffect(() => {
    const preloaders = featured.flatMap(item => {
      if (!item.thumbnail_url || failedFeatured.has(item.path)) return [];
      const image = new Image();
      const onError = () => setFailedFeatured(current => new Set(current).add(item.path));
      image.addEventListener('error', onError);
      image.src = item.thumbnail_url;
      return [[image, onError] as const];
    });

    return () => preloaders.forEach(([image, onError]) => image.removeEventListener('error', onError));
  }, [featured, failedFeatured]);

  useEffect(() => {
    const updateVisibility = () => setIsPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', updateVisibility);
    return () => document.removeEventListener('visibilitychange', updateVisibility);
  }, []);

  useEffect(() => {
    if (!tuningOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTuningOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [tuningOpen]);

  if (isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#07070d] p-6" aria-label="Loading library">
        <div className="h-1 w-32 overflow-hidden rounded-full bg-slate-800"><div className="h-full w-1/2 bg-indigo-400" /></div>
      </main>
    );
  }

  if (isProtected) return <Navigate to="/login" replace />;

  const name = serverInfo?.share_name || 'AssetManager';
  const stats = serverInfo?.library_stats;
  const backgroundStyle = {
    '--gate-blur': `${settings.blur}px`,
    '--gate-brightness': `${settings.brightness}%`,
    '--gate-saturation': `${settings.saturation}%`,
    '--gate-opacity': `${settings.opacity}%`,
  } as React.CSSProperties;

  const updateSetting = (key: keyof BackgroundSettings, value: number) => {
    const next = { ...settings, [key]: value };
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // Visual tuning remains usable when storage is unavailable.
    }
    setSettings(next);
  };

  return (
    <main className="gate min-h-screen overflow-x-hidden bg-[#07070d] text-slate-100" style={backgroundStyle}>
      <style>{`
        .gate { --gate-blur: 4px; --gate-brightness: 55%; --gate-saturation: 75%; --gate-opacity: 38%; font-family: "Segoe UI", system-ui, sans-serif; }
        .gate-wall { filter: blur(var(--gate-blur)) brightness(var(--gate-brightness)) saturate(var(--gate-saturation)); opacity: calc(var(--gate-opacity) / 100); }
        @media (prefers-reduced-motion: no-preference) { .gate-wall { animation: gate-drift 24s ease-in-out infinite alternate; } .gate-wall-paused { animation-play-state: paused; } .gate-enter-icon { transition: transform 160ms ease; } .gate-enter:hover .gate-enter-icon { transform: translateX(3px); } }
        @keyframes gate-drift { from { transform: scale(1.04) translate3d(-0.5%, -0.5%, 0); } to { transform: scale(1.1) translate3d(0.5%, 0.5%, 0); } }
      `}</style>

      <div className={`gate-wall pointer-events-none fixed inset-0 grid grid-cols-2 gap-3 p-3 sm:grid-cols-3${isPageVisible ? '' : ' gate-wall-paused'}`} aria-hidden="true">
        {visibleFeatured.map(item => item.thumbnail_url && (
          <img key={item.path} src={item.thumbnail_url} alt="" className="h-full min-h-40 w-full object-cover" />
        ))}
          {!visibleFeatured.length && <div className="col-span-full bg-[#111122]" />}
      </div>
      <div className="pointer-events-none fixed inset-0 bg-[#07070d]/70" aria-hidden="true" />

      <section className="relative mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center px-5 py-16 text-center sm:px-8">
        <div className="mb-7 grid h-16 w-16 place-items-center rounded-full border border-indigo-300/60 bg-indigo-400/15 shadow-[0_0_42px_rgba(129,140,248,0.35)]" aria-hidden="true">
          <span className="font-mono text-xl font-semibold text-indigo-100">AM</span>
        </div>
        <p className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-indigo-200">Local asset library</p>
        <h1 className="max-w-full break-words text-4xl font-semibold tracking-normal text-slate-50 sm:text-5xl">{name}</h1>
        <p className="mt-4 max-w-xl text-base leading-7 text-slate-300">{serverInfo?.welcome_msg || 'Your local files are ready to browse.'}</p>

        <div className="mt-7 flex flex-wrap justify-center gap-x-5 gap-y-2 font-mono text-xs text-slate-300" aria-live="polite">
          <span>
            <span className={`mr-2 inline-block h-2 w-2 rounded-full ${featuredStatus === 'online' ? 'bg-emerald-400' : featuredStatus === 'unavailable' ? 'bg-rose-400' : 'bg-amber-300'}`} aria-hidden="true" />
            {featuredStatus === 'online' ? 'Library online' : featuredStatus === 'unavailable' ? 'Library unavailable' : 'Library loading'}
          </span>
          {stats && <span>{summaryText(stats.total_projects)}</span>}
          {stats?.total_size_fmt && <span>{stats.total_size_fmt}</span>}
        </div>

          {visibleFeatured.length > 0 && (
            <div className="mt-9 grid w-full grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Featured assets">
              {visibleFeatured.map(item => (
               <figure key={item.path} className="aspect-square overflow-hidden border border-white/10 bg-[#111122]">
                  {item.thumbnail_url ? (
                   <img
                    src={item.thumbnail_url}
                    alt={item.name}
                    className="h-full w-full object-cover"
                     onError={() => setFailedFeatured(current => new Set(current).add(item.path))}
                  />
                 ) : null}
              </figure>
            ))}
          </div>
        )}
        {featuredStatus === 'online' && featured.length === 0 && <p className="mt-7 text-sm text-slate-400">No featured assets are available yet.</p>}
        {featuredStatus === 'unavailable' && <p className="mt-7 text-sm text-slate-400" role="alert">Featured assets are unavailable. You can still enter the library.</p>}

        <Link to="/browse" className="gate-enter mt-10 inline-flex min-h-12 items-center gap-3 border border-indigo-300/70 bg-indigo-500 px-5 py-3 font-medium text-white shadow-lg shadow-indigo-950/40 outline-none hover:bg-indigo-400 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#07070d]">
          Enter Library <ArrowRight className="gate-enter-icon" size={18} aria-hidden="true" />
        </Link>
      </section>

      <button type="button" aria-label="Tune background" aria-expanded={tuningOpen} aria-controls="background-tuning" onClick={() => setTuningOpen(open => !open)} className="fixed bottom-4 right-4 grid h-11 w-11 place-items-center border border-slate-600 bg-[#111122]/90 text-slate-200 outline-none hover:border-indigo-300 hover:text-white focus-visible:ring-2 focus-visible:ring-white">
        <SlidersHorizontal size={18} aria-hidden="true" />
      </button>

      {tuningOpen && (
        <section id="background-tuning" role="dialog" aria-modal="false" aria-label="Background tuning" className="fixed bottom-4 right-4 max-h-[calc(100dvh-2rem)] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto border border-slate-600 bg-[#111122]/95 p-4 shadow-2xl backdrop-blur">
          <div className="mb-4 flex items-center justify-between"><h2 className="font-medium text-slate-100">Background</h2><button type="button" aria-label="Close background tuning" onClick={() => setTuningOpen(false)} className="grid h-9 w-9 place-items-center text-slate-300 outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-white"><X size={18} aria-hidden="true" /></button></div>
          {([
            ['blur', 'Blur', 0, 16, 'px'],
            ['brightness', 'Brightness', 25, 100, '%'],
            ['saturation', 'Saturation', 0, 150, '%'],
            ['opacity', 'Image opacity', 0, 100, '%'],
          ] as const).map(([key, label, min, max, suffix]) => (
            <label key={key} className="mb-3 block text-sm text-slate-300">{label} <output className="float-right font-mono text-xs text-slate-400">{settings[key]}{suffix}</output><input aria-label={label} className="mt-2 block w-full accent-indigo-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white" type="range" min={min} max={max} value={settings[key]} onChange={event => updateSetting(key, Number(event.target.value))} /></label>
          ))}
        </section>
      )}
    </main>
  );
}
