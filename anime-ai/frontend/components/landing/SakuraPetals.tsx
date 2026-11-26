import React, { useEffect, useRef } from 'react';

// Petals are strictly constrained to the artwork area on the right half.
// They never drift into the clean black negative space on the left.
export const SakuraPetals: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Respect reduced motion preference
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }

    const container = containerRef.current;
    if (!container) return;

    const petalCount = 7;
    const petals: HTMLDivElement[] = [];

    const petalSvgs = [
      `<svg viewBox="0 0 20 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 2C10 2 3 7 3 13a7 7 0 0014 0c0-6-7-11-7-11z" fill="currentColor" opacity="0.8"/></svg>`,
      `<svg viewBox="0 0 22 26" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="11" cy="13" rx="6" ry="10" fill="currentColor" opacity="0.7" transform="rotate(-15 11 13)"/></svg>`,
    ];

    for (let i = 0; i < petalCount; i++) {
      const petal = document.createElement('div');
      const svg = petalSvgs[i % petalSvgs.length];

      petal.innerHTML = svg;
      petal.style.position = 'absolute';
      petal.style.pointerEvents = 'none';
      petal.style.color = `rgba(255, ${95 + Math.random() * 40}, ${143 + Math.random() * 30}, ${0.25 + Math.random() * 0.25})`;
      petal.style.width = `${10 + Math.random() * 12}px`;
      petal.style.height = `${10 + Math.random() * 12}px`;
      // Strictly right half (65% - 95%)
      petal.style.left = `${65 + Math.random() * 30}%`;
      petal.style.top = `-8%`;
      petal.style.willChange = 'transform, opacity';
      petal.style.zIndex = '5';

      const duration = 7000 + Math.random() * 6000;
      const delay = Math.random() * 4000;
      const startLeft = parseFloat(petal.style.left);
      const endLeft = Math.min(98, Math.max(60, startLeft + (Math.random() - 0.5) * 15));
      const rotation = Math.random() * 360 - 180;

      container.appendChild(petal);
      petals.push(petal);

      const animate = () => {
        petal.animate(
          [
            { transform: `translateX(0) translateY(0) rotate(0deg)`, opacity: 0 },
            { opacity: 0.7, offset: 0.15 },
            { transform: `translateX(${(endLeft - startLeft) * 0.5}%) translateY(55vh) rotate(${rotation / 2}deg)`, opacity: 0.6, offset: 0.6 },
            { transform: `translateX(${endLeft - startLeft}%) translateY(115vh) rotate(${rotation}deg)`, opacity: 0 },
          ],
          { duration, delay, easing: 'ease-in-out', fill: 'forwards' }
        ).addEventListener('finish', () => {
          petal.style.left = `${65 + Math.random() * 30}%`;
          petal.style.top = '-8%';
          setTimeout(animate, Math.random() * 2000);
        });
      };

      setTimeout(animate, delay);
    }

    return () => {
      petals.forEach(p => p.remove());
    };
  }, []);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="absolute inset-0 overflow-hidden pointer-events-none z-[5]"
    />
  );
};
