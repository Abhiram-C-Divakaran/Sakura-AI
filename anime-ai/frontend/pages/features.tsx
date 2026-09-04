import { useEffect } from 'react';
import { useRouter } from 'next/router';

export default function FeaturesRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/#features');
  }, [router]);

  return null;
}
