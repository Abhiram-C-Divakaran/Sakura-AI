import React, { useRef, useEffect } from 'react';
import { LogOut, Sun, Moon, Sparkles, User, Settings, Check } from 'lucide-react';
import { useTheme, ThemeMode } from '../ThemeContext';

export interface AccountMenuProps {
  currentUser?: string | null;
  isOpen: boolean;
  onClose: () => void;
  onLogout: () => void;
  onOpenSettings?: () => void;
}

export const AccountMenu: React.FC<AccountMenuProps> = ({
  currentUser,
  isOpen,
  onClose,
  onLogout,
  onOpenSettings
}) => {
  const { theme, setTheme, themes } = useTheme();
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on outside click or Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Truthful identity: never display "Operator"
  const displayName = !currentUser || currentUser === 'Operator' ? 'Account' : currentUser;

  return (
    <div
      ref={menuRef}
      className="absolute right-0 top-12 w-64 rounded-2xl border border-white/10 bg-[#0d0d0d] shadow-2xl z-50 overflow-hidden text-xs text-neutral-200 divide-y divide-white/5 animate-in fade-in zoom-in-95 duration-100"
    >
      {/* User Header */}
      <div className="p-3.5 flex items-center gap-3 bg-[#111111]">
        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#ff7597] to-[#ff2d78] flex items-center justify-center text-white font-bold text-sm shadow-md">
          {displayName[0]?.toUpperCase() || 'A'}
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-semibold text-white truncate text-xs">{displayName}</span>
          <span className="text-[10px] text-neutral-400 truncate">Sakura AI Workspace</span>
        </div>
      </div>

      {/* Theme Selector */}
      <div className="p-2 space-y-1">
        <div className="px-2 py-1 text-[10px] uppercase font-semibold tracking-wider text-neutral-500">
          Theme Mode
        </div>
        {themes.map(t => (
          <button
            key={t.id}
            onClick={() => setTheme(t.id)}
            className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg transition-colors text-left ${
              theme === t.id
                ? 'bg-[#ff7597]/15 text-[#ff7597] font-medium'
                : 'text-neutral-300 hover:bg-white/5'
            }`}
          >
            <div className="flex items-center gap-2">
              {t.icon === 'sparkles' && <Sparkles className="w-3.5 h-3.5 text-[#ff7597]" />}
              {t.icon === 'moon' && <Moon className="w-3.5 h-3.5" />}
              {t.icon === 'sun' && <Sun className="w-3.5 h-3.5" />}
              <span>{t.name}</span>
            </div>
            {theme === t.id && <Check className="w-3.5 h-3.5 text-[#ff7597]" />}
          </button>
        ))}
      </div>

      {/* Actions */}
      <div className="p-1.5 space-y-0.5">
        {onOpenSettings && (
          <button
            onClick={() => {
              onClose();
              onOpenSettings();
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg hover:bg-white/5 text-neutral-300 hover:text-white transition-colors text-left"
          >
            <Settings className="w-4 h-4 text-neutral-400" />
            <span>Settings</span>
          </button>
        )}

        <button
          onClick={() => {
            onClose();
            onLogout();
          }}
          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg hover:bg-rose-950/30 text-rose-400 hover:text-rose-300 transition-colors text-left"
        >
          <LogOut className="w-4 h-4 text-rose-400" />
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  );
};
