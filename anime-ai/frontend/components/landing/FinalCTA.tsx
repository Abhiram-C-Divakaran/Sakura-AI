import Link from 'next/link';
import Image from 'next/image';
import { ArrowRight } from 'lucide-react';
export const FinalCTA = () => <section className="landing-final landing-container">
  <div className="landing-scenic">
    <Image src="/branding/sakura-fuji.webp" alt="Mount Fuji beyond a quiet lake, framed by cherry blossoms at pink dusk" fill sizes="(max-width: 1440px) 100vw, 1440px" />
    <div className="landing-scenic-content">
      <p className="landing-eyebrow">MORE THAN A TOOL</p>
      <h2>A home for your imagination.</h2>
      <p>Think, create, build, and organize your work with one AI workspace designed to stay with your ideas from beginning to end.</p>
      <Link href="/chat" className="landing-primary">Get Started <ArrowRight size={18} /></Link>
      <small>Ideas today. A brighter tomorrow.</small>
    </div>
  </div>
</section>;

