import Image from 'next/image';

export const HeroSection = () => (
  <section id="hero" className="landing-hero" aria-label="Sakura AI introduction">
    <div className="landing-hero-art">
      <Image
        src="/branding/sakura-hero.webp"
        alt="Sakura blossoms and a thoughtful woman beneath a glowing pink moon. Ideas. Create. Belong. A brighter creative tomorrow."
        fill
        priority
        sizes="100vw"
      />
    </div>
    <div className="landing-container landing-hero-copy">
      <p className="landing-eyebrow">YOUR AI WORKSPACE</p>
      <h1>
        Where imagination
        <br />
        <span>Blooms</span> with AI
      </h1>
      <p className="landing-hero-description">
        Chat, create, research, code, and organize your ideas —
        <br className="hidden lg:block" /> all in one intelligent workspace.
      </p>
    </div>
  </section>
);
