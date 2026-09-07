import { useEffect } from 'react';
import { useRouter } from 'next/router';

/**
 * Sakura AI — Console Redirection
 * Seamlessly redirects legacy /console routes to the unified /chat workspace while preserving query parameters.
 */
export default function ConsoleRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace({
      pathname: '/chat',
      query: router.query
    });
  }, [router]);

  return (
    <div className="flex items-center justify-center h-screen w-screen bg-black text-neutral-400 font-mono text-xs">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-[#ff7597] animate-pulse" />
        <span>Redirecting to Sakura AI workspace...</span>
      </div>
    </div>
  );
}
