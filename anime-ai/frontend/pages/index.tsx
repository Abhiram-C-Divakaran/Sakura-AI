import Head from 'next/head';
import { LandingNavbar } from '../components/landing/LandingNavbar';
import { HeroSection } from '../components/landing/HeroSection';
import { CapabilityOverview } from '../components/landing/CapabilityOverview';
import { ChatbotShowcase } from '../components/landing/ChatbotShowcase';
import { WorkspaceShowcase } from '../components/landing/WorkspaceShowcase';
import { SakuraCodeShowcase } from '../components/landing/SakuraCodeShowcase';
import { KnowledgeShowcase } from '../components/landing/KnowledgeShowcase';
import { ImageShowcase } from '../components/landing/ImageShowcase';
import { UseCases } from '../components/landing/UseCases';
import { HowItWorks } from '../components/landing/HowItWorks';
import { TrustSection } from '../components/landing/TrustSection';
import { FinalCTA } from '../components/landing/FinalCTA';
import { LandingFooter } from '../components/landing/LandingFooter';

const title = 'Sakura AI — Where Imagination Blooms with AI';
const description =
  'Chat, create, research, code, and organize your ideas — all in one intelligent workspace.';
const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL;
const canonical =
  configuredUrl && /^https?:\/\//.test(configuredUrl)
    ? configuredUrl.replace(/\/$/, '')
    : undefined;

export default function SakuraLandingPage() {
  return (
    <div className="sakura-landing">
      <Head>
        <title>{title}</title>
        <meta name="description" content={description} />
        <meta name="theme-color" content="#000000" />
        <meta property="og:title" content={title} />
        <meta property="og:description" content={description} />
        <meta property="og:type" content="website" />
        <meta property="og:image" content={`${canonical || ''}/branding/sakura-hero.webp`} />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={title} />
        <meta name="twitter:description" content={description} />
        <meta name="twitter:image" content={`${canonical || ''}/branding/sakura-hero.webp`} />
        <link rel="icon" href="/favicon.ico" />
        {canonical && <link rel="canonical" href={canonical} />}
        {canonical && <meta property="og:url" content={canonical} />}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              '@context': 'https://schema.org',
              '@type': 'SoftwareApplication',
              name: 'Sakura AI',
              operatingSystem: 'Web Browser',
              applicationCategory: 'ProductivityApplication',
              description,
            }),
          }}
        />
      </Head>

      <a className="landing-skip" href="#main-content">
        Skip to content
      </a>
      <LandingNavbar />

      <main id="main-content" tabIndex={-1}>
        <HeroSection />
        <CapabilityOverview />
        <ChatbotShowcase />
        <WorkspaceShowcase />
        <SakuraCodeShowcase />
        <KnowledgeShowcase />
        <ImageShowcase />
        <UseCases />
        <HowItWorks />
        <TrustSection />
        <FinalCTA />
      </main>

      <LandingFooter />
    </div>
  );
}
