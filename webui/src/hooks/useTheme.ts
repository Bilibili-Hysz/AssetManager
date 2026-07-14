import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';

function getStoredTheme(): Theme {
  try {
    return (localStorage.getItem('am_theme') as Theme) || 'dark';
  } catch {
    return 'dark';
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.classList.toggle('light', theme === 'light');
    try { localStorage.setItem('am_theme', theme); } catch { /* ignore */ }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState(t => t === 'dark' ? 'light' : 'dark');
  }, []);

  return { theme, toggleTheme };
}