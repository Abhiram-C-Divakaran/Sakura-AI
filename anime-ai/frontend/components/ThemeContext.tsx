import React, { createContext, useContext, useEffect, useState, useMemo } from 'react';

export type ThemeMode = 'pitch-black' | 'dark' | 'light' | 'blue';

export interface ThemeMeta {
  id: ThemeMode;
  name: string;
  description: string;
  previewBg: string;
  previewBorder: string;
  previewAccent: string;
  icon: 'moon' | 'sun' | 'sparkles' | 'droplet';
}

export const THEME_LIST: ThemeMeta[] = [
  {
    id: 'pitch-black',
    name: 'Pitch Black',
    description: 'Pure OLED black minimal aesthetic',
    previewBg: '#000000',
    previewBorder: '#282828',
    previewAccent: '#ff7597',
    icon: 'sparkles'
  },
  {
    id: 'dark',
    name: 'Dark Mode',
    description: 'Refined deep charcoal & slate tones',
    previewBg: '#121318',
    previewBorder: '#2b2e3c',
    previewAccent: '#ff6584',
    icon: 'moon'
  },
  {
    id: 'light',
    name: 'Light Mode',
    description: 'Crisp clean workspace with soft contrast',
    previewBg: '#f8fafc',
    previewBorder: '#cbd5e1',
    previewAccent: '#e11d48',
    icon: 'sun'
  },
  {
    id: 'blue',
    name: 'Cyber Blue',
    description: 'Deep midnight navy with electric blue glow',
    previewBg: '#060b17',
    previewBorder: '#1c2d56',
    previewAccent: '#00f0ff',
    icon: 'droplet'
  }
];

interface ThemeContextType {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  cycleTheme: () => void;
  themes: ThemeMeta[];
}

const ThemeContext = createContext<ThemeContextType>({
  theme: 'pitch-black',
  setTheme: () => {},
  cycleTheme: () => {},
  themes: THEME_LIST
});

const STORAGE_KEY = 'sakura_theme';

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeMode>('pitch-black');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
      if (saved && (saved === 'pitch-black' || saved === 'dark' || saved === 'light' || saved === 'blue')) {
        setThemeState(saved);
        applyThemeToDocument(saved);
      } else {
        applyThemeToDocument('pitch-black');
      }
    } catch {
      applyThemeToDocument('pitch-black');
    }
    setMounted(true);
  }, []);

  const applyThemeToDocument = (mode: ThemeMode) => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    root.setAttribute('data-theme', mode);
    
    // Update body class
    root.classList.remove('theme-pitch-black', 'theme-dark', 'theme-light', 'theme-blue');
    root.classList.add(`theme-${mode}`);

    // Update meta theme-color for mobile address bar
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
      const themeColors: Record<ThemeMode, string> = {
        'pitch-black': '#000000',
        'dark': '#121318',
        'light': '#f8fafc',
        'blue': '#060b17'
      };
      metaThemeColor.setAttribute('content', themeColors[mode]);
    }
  };

  const setTheme = (newTheme: ThemeMode) => {
    setThemeState(newTheme);
    applyThemeToDocument(newTheme);
    try {
      localStorage.setItem(STORAGE_KEY, newTheme);
    } catch {
      // localStorage may fail in restricted privacy modes
    }
  };

  const cycleTheme = () => {
    const order: ThemeMode[] = ['pitch-black', 'dark', 'light', 'blue'];
    const currentIndex = order.indexOf(theme);
    const nextTheme = order[(currentIndex + 1) % order.length];
    setTheme(nextTheme);
  };

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      cycleTheme,
      themes: THEME_LIST
    }),
    [theme]
  );

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
