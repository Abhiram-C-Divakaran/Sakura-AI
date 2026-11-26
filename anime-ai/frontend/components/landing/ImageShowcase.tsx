import Image from 'next/image';
import Link from 'next/link';
export const ImageShowcase = () => <section id="images" className="landing-section landing-container">
  <div className="landing-image-heading"><div><p className="landing-eyebrow">CREATE VISUALLY</p><h2>Turn ideas into visuals.</h2></div><p className="landing-body">Describe what you imagine. Create original images when an image provider is available in your workspace.</p></div>
  <div className="landing-image-examples">{[['pagoda','A quiet lakeside garden at dusk','Atmosphere'],['character','Sakura-inspired character illustration','Character'],['mountain','Mount Fuji beneath a rose evening sky','Landscape']].map(([name,alt,label]) => <figure key={name}><div><Image src={`/branding/example-${name}.webp`} alt={alt} fill sizes="(max-width: 640px) 90vw, 30vw" /></div><figcaption>{label}<span>Illustrative artwork</span></figcaption></figure>)}</div>
  <div className="landing-image-foot"><p className="landing-note">Generation depends on provider availability. These examples illustrate visual possibilities, not verified Sakura outputs.</p><Link className="landing-text-link" href="/chat">Open image workspace →</Link></div>
</section>;
