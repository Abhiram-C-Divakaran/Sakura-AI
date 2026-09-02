import React from 'react';

export interface SakuraLogoProps {
  /** Dimension in pixels (width and height for square icon) */
  size?: number;
  /** 'icon' for the official transparent cherry blossom flower (default) */
  variant?: 'icon' | 'full' | 'wordmark';
  className?: string;
  alt?: string;
  ariaLabel?: string;
  style?: React.CSSProperties;
}

/**
 * Official Sakura AI Logo Component
 * Renders the transparent Sakura AI flower asset without any enclosing box or background container.
 */
export const SakuraLogo: React.FC<SakuraLogoProps> = ({
  size = 36,
  variant = 'icon',
  className = '',
  alt = 'Sakura AI',
  ariaLabel,
  style = {}
}) => {
  const src = variant === 'wordmark'
    ? '/branding/sakura-wordmark-transparent.png'
    : '/branding/sakura-flower-transparent.png';

  const width = size;
  const height = variant === 'wordmark' ? Math.round(size * (88 / 382)) : size;

  return (
    <img
      src={src}
      alt={alt}
      aria-label={ariaLabel || (alt ? undefined : 'Sakura AI')}
      width={width}
      height={height}
      className={`inline-block object-contain select-none flex-shrink-0 bg-transparent ${className}`}
      style={{
        width: `${width}px`,
        height: `${height}px`,
        background: 'transparent',
        ...style
      }}
      draggable={false}
      loading="eager"
    />
  );
};

export interface SakuraWordmarkProps {
  height?: number;
  className?: string;
  alt?: string;
  style?: React.CSSProperties;
}

/**
 * Official SAKURA AI Wordmark Component
 * Renders the geometric futuristic SAKURA lettering with triangular pink accents
 * and centered pink AI with circular-node flanking lines on a transparent background.
 */
export const SakuraWordmark: React.FC<SakuraWordmarkProps> = ({
  height = 30,
  className = '',
  alt = 'SAKURA AI',
  style = {}
}) => {
  // Original aspect ratio from media_1788270121878: 382w x 88h (~4.34:1)
  const width = Math.round(height * (382 / 88));

  return (
    <img
      src="/branding/sakura-wordmark-transparent.png"
      alt={alt}
      width={width}
      height={height}
      className={`inline-block object-contain select-none flex-shrink-0 bg-transparent ${className}`}
      style={{
        width: `${width}px`,
        height: `${height}px`,
        background: 'transparent',
        ...style
      }}
      draggable={false}
      loading="eager"
    />
  );
};

/**
 * Official Top-Left Application Brand Lockup
 * Transparent Sakura Flower + Official SAKURA AI Wordmark
 */
export const SakuraBrandHeader: React.FC<{
  logoSize?: number;
  wordmarkHeight?: number;
  className?: string;
}> = ({
  logoSize = 36,
  wordmarkHeight = 28,
  className = ''
}) => {
  return (
    <div className={`flex items-center gap-3 select-none bg-transparent ${className}`}>
      <SakuraLogo size={logoSize} alt="" className="bg-transparent" />
      <SakuraWordmark height={wordmarkHeight} alt="SAKURA AI" className="bg-transparent" />
    </div>
  );
};
