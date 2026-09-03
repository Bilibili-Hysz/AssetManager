import { memo } from 'react';

interface AmbientBackdropProps {
  primaryAccent?: string;
  secondaryAccent?: string;
}

export const AmbientBackdrop = memo(function AmbientBackdrop({
  primaryAccent = 'var(--color-accent, #6366f1)',
  secondaryAccent = '#a78bfa',
}: AmbientBackdropProps) {
  return (
    <div
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden select-none motion-reduce:hidden"
      aria-hidden="true"
    >
      {/* 顶部中央微弱弥散光晕 */}
      <div
        className="absolute -top-[180px] left-1/2 h-[380px] w-[800px] -translate-x-1/2 rounded-[50%] blur-[120px] will-change-transform"
        style={{
          background: `radial-gradient(ellipse at center, ${primaryAccent} 0%, transparent 70%)`,
          opacity: 0.12,
        }}
      />
      {/* 右下侧次级微弱能量晕点 */}
      <div
        className="absolute -bottom-[200px] right-[5%] h-[500px] w-[500px] rounded-full blur-[140px] will-change-transform"
        style={{
          background: `radial-gradient(circle, ${secondaryAccent} 0%, transparent 65%)`,
          opacity: 0.08,
        }}
      />
      {/* 极细微噪点纹理层消除色阶断层 */}
      <div
        className="absolute inset-0 opacity-[0.02] dark:opacity-[0.035]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
        }}
      />
    </div>
  );
});
