import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { motion, AnimatePresence } from 'framer-motion';
import { Key, User, ArrowRight, Activity, Terminal } from 'lucide-react';

export default function Login() {
  const router = useRouter();
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Redirect if already logged in
    const token = localStorage.getItem('access_token');
    if (token) {
      router.push('/console');
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    try {
      if (isRegistering) {
        // 1. Register User
        const regRes = await fetch(`${apiBase}/api/v1/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        if (!regRes.ok) {
          const errData = await regRes.json();
          throw new Error(errData.detail || 'Registration failed');
        }
      }

      // 2. Authenticate & Obtain Token
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const authRes = await fetch(`${apiBase}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString()
      });

      if (!authRes.ok) {
        throw new Error('Incorrect credentials. Please verify details.');
      }

      const authData = await authRes.json();
      localStorage.setItem('access_token', authData.access_token);
      router.push('/console');
    } catch (err: any) {
      setError(err.message || 'Authentication error.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-height-screen min-h-screen w-full flex items-center justify-center bg-retro-bg p-4 select-none relative">
      {/* Neo-Tokyo Grid Background */}
      <div 
        className="absolute inset-0 opacity-10 pointer-events-none" 
        style={{
          backgroundImage: 'linear-gradient(rgba(0, 240, 255, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 240, 255, 0.1) 1px, transparent 1px)',
          backgroundSize: '24px 24px'
        }}
      />

      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-md bg-retro-glass border border-retro-violet/40 rounded-2xl overflow-hidden shadow-2xl crt-bezel z-10"
        style={{ backdropFilter: 'blur(12px)' }}
      >
        {/* Cassette Header Bar */}
        <div className="bg-gradient-to-r from-retro-violet/30 to-retro-cyan/20 border-b border-retro-border p-4 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <Terminal className="text-retro-cyan w-5 h-5 animate-pulse" />
            <span className="font-mono text-xs text-retro-cyan tracking-wider font-semibold">NEO-TOKYO SECURITY TERMINAL</span>
          </div>
          <div className="flex items-center gap-1.5 bg-black/40 px-2.5 py-1 rounded border border-retro-border">
            <div className={`w-1.5 h-1.5 rounded-full ${loading ? 'bg-retro-magenta animate-pulse' : 'bg-retro-green'}`} />
            <span className="font-mono text-[10px] text-retro-muted uppercase">{loading ? 'Accessing' : 'Ready'}</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-8 flex flex-col gap-6">
          {/* Cassette Visual Decor */}
          <div className="w-full bg-black/60 border border-retro-border rounded-xl p-4 flex flex-col items-center gap-3 relative">
            {/* Cassette Window */}
            <div className="w-3/4 h-16 bg-[#16161a] border border-[#2b2b35] rounded-md flex justify-between items-center px-8 relative overflow-hidden">
              {/* Tape spools animation */}
              <div className={`w-8 h-8 rounded-full border-4 border-dashed border-retro-cyan/40 flex items-center justify-center ${loading ? 'tape-reel-spin-fast' : 'tape-reel-spin'}`}>
                <div className="w-2.5 h-2.5 bg-black rounded-full" />
              </div>
              <div className="flex flex-col gap-1 w-1/3 border-x border-retro-border h-full justify-center">
                <div className="w-full h-1 bg-retro-magenta/30" />
                <div className="w-full h-1 bg-retro-cyan/30" />
              </div>
              <div className={`w-8 h-8 rounded-full border-4 border-dashed border-retro-cyan/40 flex items-center justify-center ${loading ? 'tape-reel-spin-fast' : 'tape-reel-spin'}`}>
                <div className="w-2.5 h-2.5 bg-black rounded-full" />
              </div>
            </div>
            <div className="text-[10px] font-mono text-retro-muted tracking-widest text-center select-none uppercase">DYNAMIC COGNITION CARTRIDGE TYPE II</div>
          </div>

          <div className="text-center flex flex-col gap-1.5">
            <h1 className="text-2xl font-bold font-sans text-transparent bg-clip-text bg-gradient-to-r from-retro-cyan to-retro-violet uppercase tracking-wide">
              {isRegistering ? 'Register Operator' : 'Operator Access'}
            </h1>
            <p className="text-xs text-retro-muted">
              {isRegistering ? 'Enroll in the neural network interface.' : 'Initialize credentials to login.'}
            </p>
          </div>

          {error && (
            <motion.div 
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-retro-magenta/10 border border-retro-magenta/30 text-retro-magenta text-xs p-3 rounded-lg font-mono text-center flex items-center justify-center gap-2"
            >
              <Activity className="w-4 h-4" />
              {error}
            </motion.div>
          )}

          {/* Form Inputs */}
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] font-mono text-retro-cyan uppercase font-semibold">Operator Username</label>
              <div className="relative flex items-center">
                <User className="absolute left-3.5 text-retro-muted w-4 h-4" />
                <input 
                  type="text" 
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-black/45 border border-retro-border focus:border-retro-cyan rounded-xl py-3 pl-11 pr-4 text-sm focus:outline-none transition-all font-mono"
                  placeholder="E.g. operator_zero"
                  required
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] font-mono text-retro-cyan uppercase font-semibold">Security Passkey</label>
              <div className="relative flex items-center">
                <Key className="absolute left-3.5 text-retro-muted w-4 h-4" />
                <input 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-black/45 border border-retro-border focus:border-retro-cyan rounded-xl py-3 pl-11 pr-4 text-sm focus:outline-none transition-all font-mono"
                  placeholder="••••••••"
                  required
                />
              </div>
            </div>
          </div>

          {/* Submit button */}
          <button 
            type="submit" 
            disabled={loading}
            className="w-full py-3.5 bg-gradient-to-r from-retro-cyan to-retro-violet hover:brightness-110 border border-retro-cyan/40 text-black font-semibold rounded-xl flex items-center justify-center gap-2 hover:scale-[1.01] active:scale-[0.99] transition-all cursor-pointer shadow-lg shadow-retro-cyan/15 hover:shadow-retro-cyan/25 text-sm uppercase tracking-wider"
          >
            {loading ? 'Initializing Interface...' : isRegistering ? 'Begin Registration' : 'Load Operator Session'}
            {!loading && <ArrowRight className="w-4 h-4" />}
          </button>

          {/* Toggle Register/Login */}
          <div className="text-center">
            <button 
              type="button"
              onClick={() => setIsRegistering(!isRegistering)}
              className="text-xs text-retro-muted hover:text-retro-cyan transition-colors hover:underline cursor-pointer font-mono"
            >
              {isRegistering 
                ? 'Already verified? Access terminal here' 
                : 'Need terminal registration? Enroll here'}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
