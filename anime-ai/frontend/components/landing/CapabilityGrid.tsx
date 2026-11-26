import React from 'react';

interface CapabilityCard {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}

export const CapabilityGrid: React.FC = () => {
  const capabilities: CapabilityCard[] = [
    {
      id: 'chat',
      title: 'AI Chat',
      description: 'Thoughtful conversations across leading AI models.',
      icon: (
        <svg className="w-5 h-5 text-[#FF6F98]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      ),
    },
    {
      id: 'code',
      title: 'Sakura Code',
      description: 'Plan, inspect, edit, test, and verify real software projects.',
      icon: (
        <svg className="w-5 h-5 text-[#FF6F98]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
      ),
    },
    {
      id: 'images',
      title: 'Image Generation',
      description: 'Turn ideas into polished visuals with Sakura\u2019s creative tools.',
      icon: (
        <svg className="w-5 h-5 text-[#FF6F98]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      id: 'library',
      title: 'Your Library',
      description: 'Keep files, images, documents, and knowledge organized.',
      icon: (
        <svg className="w-5 h-5 text-[#FF6F98]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
      ),
    },
    {
      id: 'integrations',
      title: 'Integrations',
      description: 'Connect Sakura to the tools and services you already use.',
      icon: (
        <svg className="w-5 h-5 text-[#FF6F98]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
        </svg>
      ),
    },
  ];

  return (
    <section id="features" className="relative w-full py-20 sm:py-28 z-10">
      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12">

        {/* Section Header */}
        <div className="mb-12 sm:mb-14">
          <h2 className="text-[32px] sm:text-[40px] lg:text-[46px] font-bold font-display text-[#F7F7F8] tracking-[-0.02em] leading-[1.1]">
            Everything you need.<br />
            <span className="text-[#A3A3AA] font-medium">One intelligent workspace.</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 sm:gap-5">
          {capabilities.map((cap) => (
            <div
              key={cap.id}
              className="group relative bg-[#101014] rounded-[18px] p-6 border border-white/[0.08] hover:border-[#FF6F98]/35 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_12px_36px_rgba(255,79,131,0.08)] flex flex-col justify-between"
            >
              {/* Icon */}
              <div className="w-10 h-10 rounded-xl bg-[#16161D] border border-white/[0.06] flex items-center justify-center mb-5 group-hover:bg-[#FF4F83]/10 group-hover:border-[#FF4F83]/20 transition-colors">
                {cap.icon}
              </div>

              {/* Text */}
              <div>
                <h3 className="text-[17px] font-semibold text-[#F7F7F8] font-display mb-2">
                  {cap.title}
                </h3>
                <p className="text-[13px] text-[#A5A5AD] leading-relaxed">
                  {cap.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
