import Head from 'next/head';
import { LandingNavbar } from '../components/landing/LandingNavbar';
import { LandingFooter } from '../components/landing/LandingFooter';
export default function ContactPage() {
  const supportEmail=process.env.NEXT_PUBLIC_SUPPORT_EMAIL;
  return <div className="sakura-landing"><Head><title>Contact & Support — Sakura AI</title><meta name="description" content="Contact Sakura AI support or report issues." /></Head><LandingNavbar /><main className="landing-container" style={{paddingTop:150,paddingBottom:120,maxWidth:900}}><p className="landing-eyebrow">HELP & SUPPORT</p><h1 className="text-4xl font-bold mb-6">Contact Sakura AI</h1><p className="landing-body">For a bug report or product question, use the project issue tracker. Include the steps to reproduce the problem, but leave out passwords, access tokens, and private files.</p><a className="landing-primary mt-8" href="https://github.com/Abhiram-C-Divakaran/Sakura-AI/issues" target="_blank" rel="noopener noreferrer">Open project issues ↗</a>{supportEmail && <p className="mt-6"><a className="landing-text-link" href={`mailto:${supportEmail}`}>Email support</a></p>}</main><LandingFooter /></div>;
}
