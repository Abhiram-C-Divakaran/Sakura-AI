import React, { useEffect, useState } from 'react';
import { authFetch } from '../lib/auth';

export async function downloadAuthenticatedFile(url: string, filename: string): Promise<void> {
  const res = await authFetch(url);
  if (!res.ok) {
    throw new Error(`Download failed with status ${res.status}`);
  }
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename || 'download';
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }
}

interface AuthenticatedImageProps {
  src: string;
  alt: string;
  className?: string;
}

export const AuthenticatedImage: React.FC<AuthenticatedImageProps> = ({
  src,
  alt,
  className,
}) => {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;
    const controller = new AbortController();

    setFailed(false);
    setObjectUrl(null);

    authFetch(src, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const blob = await res.blob();
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch(() => {
        if (active && !controller.signal.aborted) {
          setFailed(true);
        }
      });

    return () => {
      active = false;
      controller.abort();
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl);
      }
    };
  }, [src]);

  if (failed || !objectUrl) {
    return (
      <div
        aria-label={alt || 'Image preview'}
        className="w-full h-full flex items-center justify-center bg-[#141414] text-[#555555] text-[11px]"
      >
        {failed ? 'Preview unavailable' : ''}
      </div>
    );
  }

  /* eslint-disable-next-line @next/next/no-img-element */
  return <img src={objectUrl} alt={alt} className={className} loading="lazy" />;
};
