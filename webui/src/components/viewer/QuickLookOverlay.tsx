import { useEffect, useState, useRef } from 'react';
import {
  X,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Download,
  FileCode,
  Folder,
  Play,
  Pause,
  Volume2,
  VolumeX,
} from 'lucide-react';
import type { BrowsableItem } from '../../types/api';

interface QuickLookOverlayProps {
  item: BrowsableItem | null;
  currentIndex: number;
  totalCount: number;
  thumbnailPlaceholder?: string;
  originalMediaUrl?: string;
  isOpen: boolean;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
  onOpenFullDetail: (item: BrowsableItem) => void;
  onDownload: (item: BrowsableItem) => void;
}

export function QuickLookOverlay({
  item,
  currentIndex,
  totalCount,
  thumbnailPlaceholder,
  originalMediaUrl,
  isOpen,
  onClose,
  onNext,
  onPrev,
  onOpenFullDetail,
  onDownload,
}: QuickLookOverlayProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [isPlaying, setIsPlaying] = useState(true);
  const [isMuted, setIsMuted] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    setImageLoaded(false);
  }, [item?.path]);

  if (!isOpen || !item) return null;

  const isVideo = item.category === 'video' || /\.(mp4|webm|mov|m4v)$/i.test(item.extension);
  const isImage = item.category === 'image' || /\.(jpg|jpeg|png|gif|webp|svg|avif)$/i.test(item.extension);
  const mediaSrc = originalMediaUrl || thumbnailPlaceholder || '';

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="quicklook-overlay"
      aria-label={`QuickLook: ${item.name}`}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8"
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* 极简深色半透毛玻璃背景 */}
      <div className="absolute inset-0 bg-black/75 backdrop-blur-xl -z-10" />

      {/* 主视窗浮动面板 */}
      <div className="relative flex flex-col max-h-[90vh] max-w-[92vw] w-auto h-auto rounded-2xl overflow-hidden bg-slate-900/95 border border-white/10 shadow-2xl">
        {/* 顶部极简浮动工具条 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-slate-950/60 text-xs text-slate-300">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="font-semibold text-slate-100 truncate max-w-[280px] md:max-w-md">
              {item.name}
            </span>
            <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
              {item.extension || item.type}
            </span>
            {item.size_fmt && (
              <span className="text-slate-400 font-mono text-[11px]">{item.size_fmt}</span>
            )}
          </div>

          <div className="flex items-center gap-1.5 ml-4">
            <span className="text-[11px] font-mono text-slate-500 mr-2">
              {currentIndex + 1} / {totalCount}
            </span>
            <button
              type="button"
              aria-label="打开完整详情页"
              onClick={() => onOpenFullDetail(item)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
              title="打开完整详情页 (Enter)"
            >
              <ExternalLink size={15} />
            </button>
            <button
              type="button"
              aria-label="下载资产"
              onClick={() => onDownload(item)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
              title="下载资产"
            >
              <Download size={15} />
            </button>
            <button
              type="button"
              aria-label="关闭即览"
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors ml-1"
              title="关闭 (ESC / Space)"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* 内容展示区 */}
        <div className="relative flex items-center justify-center min-w-[320px] min-h-[240px] max-w-[85vw] max-h-[75vh] p-2 bg-black/40 overflow-hidden select-none">
          {totalCount > 1 && (
            <>
              <button
                type="button"
                aria-label="上一张"
                onClick={e => {
                  e.stopPropagation();
                  onPrev();
                }}
                className="absolute left-3 top-1/2 -translate-y-1/2 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-slate-900/80 border border-white/10 text-white/70 hover:text-white hover:bg-slate-800 transition shadow-lg"
                title="上一张 (←)"
              >
                <ChevronLeft size={22} />
              </button>
              <button
                type="button"
                aria-label="下一张"
                onClick={e => {
                  e.stopPropagation();
                  onNext();
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-slate-900/80 border border-white/10 text-white/70 hover:text-white hover:bg-slate-800 transition shadow-lg"
                title="下一张 (→)"
              >
                <ChevronRight size={22} />
              </button>
            </>
          )}

          {isImage ? (
            <div className="relative flex items-center justify-center h-full w-full">
              {thumbnailPlaceholder && !imageLoaded && (
                <img
                  src={thumbnailPlaceholder}
                  alt=""
                  className="max-h-[72vh] max-w-full object-contain filter blur-md scale-95 opacity-60 transition-opacity"
                />
              )}
              <img
                src={mediaSrc}
                alt={item.name}
                onLoad={() => setImageLoaded(true)}
                className={`max-h-[72vh] max-w-full object-contain transition-all duration-200 ${
                  imageLoaded ? 'opacity-100 scale-100' : 'opacity-0 scale-98 absolute'
                }`}
              />
            </div>
          ) : isVideo ? (
            <div className="relative flex flex-col items-center justify-center h-full w-full">
              <video
                ref={videoRef}
                src={mediaSrc}
                autoPlay
                loop
                muted={isMuted}
                playsInline
                className="max-h-[70vh] max-w-full rounded-lg object-contain shadow-2xl"
              />
              <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-950/80 border border-white/10 backdrop-blur-md">
                <button
                  type="button"
                  aria-label={isPlaying ? '暂停' : '播放'}
                  onClick={() => {
                    if (!videoRef.current) return;
                    if (isPlaying) videoRef.current.pause();
                    else void videoRef.current.play();
                    setIsPlaying(!isPlaying);
                  }}
                  className="text-slate-300 hover:text-white"
                >
                  {isPlaying ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button
                  type="button"
                  aria-label={isMuted ? '取消静音' : '静音'}
                  onClick={() => setIsMuted(!isMuted)}
                  className="text-slate-300 hover:text-white"
                >
                  {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center p-12 text-slate-400 gap-3">
              {item.type === 'dir' ? (
                <Folder size={48} className="text-amber-400/80" />
              ) : (
                <FileCode size={48} className="text-indigo-400/80" />
              )}
              <span className="text-sm font-medium text-slate-200">{item.name}</span>
              <p className="text-xs text-slate-500">按 Enter 打开详情以检视此文件</p>
            </div>
          )}
        </div>

        {/* 底部快捷键提示条 */}
        <div className="flex items-center justify-center gap-4 py-2 bg-slate-950/80 border-t border-white/10 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-slate-300 text-[10px] font-mono">
              Space
            </kbd>
            退出
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-slate-300 text-[10px] font-mono">
              ←
            </kbd>
            <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-slate-300 text-[10px] font-mono">
              →
            </kbd>
            切片
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-slate-300 text-[10px] font-mono">
              Enter
            </kbd>
            详情
          </span>
        </div>
      </div>
    </div>
  );
}
