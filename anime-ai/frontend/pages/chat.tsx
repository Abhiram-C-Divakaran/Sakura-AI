import React, { useState, useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { AppShell } from '../components/app/AppShell';
import { getAccessToken, clearAccessToken } from '../lib/auth';

export default function ChatPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace('/login');
      return;
    }

    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      const sub = payload.sub || payload.username || payload.email;
      setCurrentUser(sub && sub !== 'Operator' ? sub : 'Account');
    } catch {
      setCurrentUser('Account');
    }
    setReady(true);
  }, [router]);

  const handleLogout = () => {
    clearAccessToken();
    router.replace('/login');
  };

  if (!ready) {
    return (
      <div className="flex items-center justify-center h-screen w-screen bg-black text-neutral-400 font-mono text-xs">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#ff7597] animate-pulse" />
          <span>Authenticating workspace session...</span>
        </div>
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>Sakura AI — Workspace</title>
        <meta name="description" content="Sakura AI autonomous coding workspace with durable cloud storage and isolated Docker sandbox execution." />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <AppShell currentUser={currentUser} onLogout={handleLogout} />
    </>
  );
}
