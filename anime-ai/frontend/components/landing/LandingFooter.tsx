import Link from 'next/link';
import { SakuraLogo } from '../SakuraLogo';
export const LandingFooter = () => <footer className="landing-footer">
  <div className="landing-container">
    <div className="landing-footer-grid">
      <div><Link href="/" className="landing-brand"><SakuraLogo size={28} /> Sakura AI</Link><p>One AI workspace for conversation, creation, and execution.</p></div>
      {[
        ['Product', [['Chat','/chat'],['Sakura Code','/#sakura-code'],['Images','/#images'],['Library','/#library'],['Projects','/chat']]],
        ['Company', [['About','/about'],['Contact','/contact']]],
        ['Legal', [['Privacy','/privacy'],['Terms','/terms']]],
        ['Account', [['Sign in','/login'],['Get Started','/chat']]],
      ].map(([heading, links]) => <div key={heading as string}><h3>{heading as string}</h3><ul>{(links as string[][]).map(([label,href]) => <li key={label}><Link href={href}>{label}</Link></li>)}</ul></div>)}
    </div>
    <div className="landing-footer-bottom"><span>© {new Date().getFullYear()} Sakura AI. All rights reserved.</span><span>Ideas today. A brighter tomorrow.</span></div>
  </div>
</footer>;

