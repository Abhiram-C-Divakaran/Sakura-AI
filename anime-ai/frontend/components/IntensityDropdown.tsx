import React, { useState, useEffect, useRef } from 'react';

export type IntensityLevel = 'low' | 'medium' | 'high';

interface IntensityOption {
  id: IntensityLevel;
  label: string;
  sublabel: string;
  tooltip: string;
}

const INTENSITY_OPTIONS: IntensityOption[] = [
  {
    id: 'low',
    label: 'Low',
    sublabel: 'Fast',
    tooltip: 'Fast responses for everyday tasks. Minimal reasoning overhead.'
  },
  {
    id: 'medium',
    label: 'Medium',
    sublabel: 'Balanced',
    tooltip: 'Balanced speed and reasoning. Recommended for everyday queries and coding.'
  },
  {
    id: 'high',
    label: 'High',
    sublabel: 'Deep reasoning',
    tooltip: 'Deeper reasoning, multi-step verification, and thorough analysis.'
  }
];

interface IntensityDropdownProps {
  value: IntensityLevel;
  onChange: (level: IntensityLevel) => void;
  disabled?: boolean;
}

export const IntensityDropdown: React.FC<IntensityDropdownProps> = ({
  value,
  onChange,
  disabled = false
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const currentOption = INTENSITY_OPTIONS.find((o) => o.id === value) || INTENSITY_OPTIONS[1];

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleSelect = (level: IntensityLevel) => {
    onChange(level);
    setIsOpen(false);
  };

  return (
    <div className="relative inline-block" ref={dropdownRef}>
      {/* Trigger Button - Clean text + chevron matching reference */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={`Response intensity: ${currentOption.label} (${currentOption.sublabel})`}
        title={currentOption.tooltip}
        className={`flex items-center gap-1.5 px-2.5 py-1 text-[14px] font-normal transition-colors rounded-lg ${
          isOpen
            ? 'bg-white/[0.12] text-white'
            : 'text-[#E0E0E0] hover:text-white hover:bg-white/[0.08]'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer select-none'}`}
      >
        <span>{currentOption.label}</span>
        <svg
          className={`w-3.5 h-3.5 text-[#B0B0B0] transition-transform duration-150 ${
            isOpen ? 'rotate-180 text-white' : ''
          }`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Compact Dropdown Popup */}
      {isOpen && (
        <div
          role="menu"
          aria-label="Select response intensity"
          className="absolute bottom-full right-0 mb-2 w-52 bg-[#262626] border border-[#3A3A3A] rounded-xl shadow-2xl p-1.5 z-50 animate-in fade-in slide-in-from-bottom-1 duration-100"
          style={{
            boxShadow: '0 12px 32px -4px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.07)',
          }}
        >
          <div className="px-2.5 py-1 border-b border-[#333333] mb-1">
            <span className="text-[11px] font-medium tracking-wide text-[#888888]">
              Reasoning Depth
            </span>
          </div>

          <div className="space-y-0.5">
            {INTENSITY_OPTIONS.map((option) => {
              const isSelected = option.id === value;
              return (
                <button
                  key={option.id}
                  role="menuitem"
                  onClick={() => handleSelect(option.id)}
                  title={option.tooltip}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-left transition-colors cursor-pointer group ${
                    isSelected ? 'bg-[#333333] text-white' : 'text-[#CCCCCC] hover:bg-[#2F2F2F] hover:text-white'
                  }`}
                >
                  <div className="flex flex-col">
                    <span className="text-[13.5px] font-medium leading-tight">
                      {option.label}
                    </span>
                    <span className="text-[11px] text-[#888888] group-hover:text-[#AAAAAA] mt-0.5">
                      {option.sublabel}
                    </span>
                  </div>

                  {isSelected && (
                    <svg
                      className="w-4 h-4 text-white flex-shrink-0"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
