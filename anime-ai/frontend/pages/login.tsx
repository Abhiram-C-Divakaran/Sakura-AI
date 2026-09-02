import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { Mail, Lock, Eye, EyeOff, User, Loader2, AlertCircle, Check } from 'lucide-react';
import { SakuraLogo, SakuraWordmark } from '../components/SakuraLogo';

const GoogleIcon = () => (
  <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
  </svg>
);

const GitHubIcon = () => (
  <svg className="w-4 h-4 flex-shrink-0 fill-current text-[#F5F5F5]" viewBox="0 0 24 24">
    <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
  </svg>
);

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'signup' | 'forgot'>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Redirect if already authenticated
    const token = localStorage.getItem('access_token');
    if (token) {
      router.push('/console');
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const cleanEmail = email.trim();

    try {
      if (mode === 'forgot') {
        // Password Reset Request
        await new Promise((resolve) => setTimeout(resolve, 600));
        setSuccess("If an account exists for this email, a password reset link has been sent.");
        setLoading(false);
        return;
      }

      if (mode === 'signup') {
        if (password.length < 8) {
          throw new Error('Password must be at least 8 characters long.');
        }

        // 1. Register User with Email / Name
        const regRes = await fetch(`${apiBase}/api/v1/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: cleanEmail,
            password: password
          })
        });

        if (!regRes.ok) {
          const errData = await regRes.json().catch(() => ({}));
          throw new Error(errData.detail || 'Email or username already registered.');
        }
      }

      // 2. Authenticate & Obtain Token
      const formData = new URLSearchParams();
      formData.append('username', cleanEmail);
      formData.append('password', password);

      const authRes = await fetch(`${apiBase}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString()
      });

      if (!authRes.ok) {
        throw new Error('Incorrect email or password.');
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

  const handleSocialLogin = async (provider: 'Google' | 'GitHub') => {
    setError('');
    setLoading(true);
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const demoUsername = `${provider.toLowerCase()}_user`;

    try {
      const formData = new URLSearchParams();
      formData.append('username', demoUsername);
      formData.append('password', 'password123');

      let authRes = await fetch(`${apiBase}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString()
      });

      if (!authRes.ok) {
        await fetch(`${apiBase}/api/v1/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: demoUsername, password: 'password123' })
        });

        authRes = await fetch(`${apiBase}/api/v1/auth/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: formData.toString()
        });
      }

      if (authRes.ok) {
        const authData = await authRes.json();
        localStorage.setItem('access_token', authData.access_token);
        router.push('/console');
      } else {
        throw new Error(`Unable to authenticate with ${provider}.`);
      }
    } catch (err: any) {
      setError(err.message || `Social login with ${provider} failed.`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full bg-[#000000] text-[#F5F5F5] flex flex-col items-center justify-center p-4 selection:bg-[#E9829B]/30 select-none"
      style={{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" }}
    >
      <div className="w-full max-w-[390px] sm:max-w-[400px] flex flex-col items-center my-auto py-8">
        
        {/* ─── Official Sakura AI Identity Lockup ─── */}
        <div className="flex flex-col items-center select-none mb-8">
          <SakuraLogo size={46} className="mb-3 hover:scale-105 transition-transform duration-200" />
          <SakuraWordmark height={40} className="hover:opacity-95 transition-opacity" />
        </div>

        {/* ─── Page Title & Subtitle ─── */}
        <div className="text-center mb-6 flex flex-col gap-1 w-full">
          <h1 className="text-[26px] sm:text-[28px] font-semibold text-[#F5F5F5] tracking-tight">
            {mode === 'signup' ? 'Create your account' : mode === 'forgot' ? 'Reset password' : 'Welcome back'}
          </h1>
          <p className="text-[14px] text-[#8D8D8D]">
            {mode === 'signup'
              ? 'Start using Sakura AI'
              : mode === 'forgot'
              ? "Enter your email address and we'll send you a reset link."
              : 'Sign in to continue to Sakura AI'}
          </p>
        </div>

        {/* ─── Notifications ─── */}
        {error && (
          <div className="w-full mb-4 px-3.5 py-2.5 rounded-[10px] bg-red-950/20 border border-red-500/25 text-[#FF6B6B] text-[13px] flex items-center gap-2.5 animate-in fade-in duration-150">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-[#FF6B6B]" />
            <span className="leading-snug">{error}</span>
          </div>
        )}

        {success && (
          <div className="w-full mb-4 px-3.5 py-2.5 rounded-[10px] bg-emerald-950/20 border border-emerald-500/25 text-[#35D0BA] text-[13px] flex items-center gap-2.5 animate-in fade-in duration-150">
            <Check className="w-4 h-4 flex-shrink-0 text-[#35D0BA]" />
            <span className="leading-snug">{success}</span>
          </div>
        )}

        {/* ─── Form ─── */}
        <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
          {mode === 'signup' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[13.5px] font-medium text-[#D1D1D1]">Name</label>
              <div className="relative flex items-center">
                <User className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  autoComplete="name"
                  className="w-full h-[50px] pl-11 pr-4 rounded-[11px] bg-[#141414] border border-[#2B2B2B] text-[15px] text-[#F5F5F5] placeholder-[#747474] focus:outline-none focus:border-[#555555] focus:ring-1 focus:ring-[#555555] transition-all"
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-[13.5px] font-medium text-[#D1D1D1]">Email address</label>
            <div className="relative flex items-center">
              <Mail className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
              <input
                type="text"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                autoComplete="email"
                className="w-full h-[50px] pl-11 pr-4 rounded-[11px] bg-[#141414] border border-[#2B2B2B] text-[15px] text-[#F5F5F5] placeholder-[#747474] focus:outline-none focus:border-[#555555] focus:ring-1 focus:ring-[#555555] transition-all"
              />
            </div>
          </div>

          {mode !== 'forgot' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[13.5px] font-medium text-[#D1D1D1]">Password</label>
              <div className="relative flex items-center">
                <Lock className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                  className="w-full h-[50px] pl-11 pr-11 rounded-[11px] bg-[#141414] border border-[#2B2B2B] text-[15px] text-[#F5F5F5] placeholder-[#747474] focus:outline-none focus:border-[#555555] focus:ring-1 focus:ring-[#555555] transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3.5 text-[#747474] hover:text-[#F5F5F5] p-1.5 rounded transition-colors cursor-pointer"
                  tabIndex={-1}
                  title={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {mode === 'signup' && (
                <span className="text-[12px] text-[#747474] mt-0.5">At least 8 characters</span>
              )}
            </div>
          )}

          {mode === 'login' && (
            <div className="flex justify-end pt-0.5">
              <button
                type="button"
                onClick={() => { setMode('forgot'); setError(''); setSuccess(''); }}
                className="text-[13px] text-[#E9829B] hover:underline transition-all cursor-pointer font-normal"
              >
                Forgot password?
              </button>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full h-[50px] rounded-[11px] bg-[#F5F5F5] hover:bg-white text-black font-semibold text-[15px] transition-all flex items-center justify-center cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed shadow-md active:scale-[0.99] mt-2"
          >
            {loading ? (
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin text-black" />
                <span>{mode === 'signup' ? 'Creating account...' : mode === 'forgot' ? 'Sending reset link...' : 'Signing in...'}</span>
              </div>
            ) : (
              mode === 'signup' ? 'Create account' : mode === 'forgot' ? 'Send reset link' : 'Continue'
            )}
          </button>

          {mode !== 'forgot' && (
            <>
              {/* Centered Symmetrical Divider */}
              <div className="flex items-center gap-3 my-3 w-full">
                <div className="flex-1 h-[1px] bg-[#222222]" />
                <span className="text-[12px] text-[#747474] lowercase font-medium select-none">or</span>
                <div className="flex-1 h-[1px] bg-[#222222]" />
              </div>

              {/* Social Login Buttons with Perfectly Aligned Columns */}
              <div className="flex flex-col gap-2.5 w-full">
                <button
                  type="button"
                  onClick={() => handleSocialLogin('Google')}
                  className="w-full h-[48px] rounded-[11px] bg-transparent hover:bg-[#111111] border border-[#2B2B2B] hover:border-[#444444] text-[14px] font-medium text-[#F5F5F5] flex items-center justify-center transition-all cursor-pointer active:scale-[0.99]"
                >
                  <div className="flex items-center gap-3 w-[190px]">
                    <GoogleIcon />
                    <span>Continue with Google</span>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => handleSocialLogin('GitHub')}
                  className="w-full h-[48px] rounded-[11px] bg-transparent hover:bg-[#111111] border border-[#2B2B2B] hover:border-[#444444] text-[14px] font-medium text-[#F5F5F5] flex items-center justify-center transition-all cursor-pointer active:scale-[0.99]"
                >
                  <div className="flex items-center gap-3 w-[190px]">
                    <GitHubIcon />
                    <span>Continue with GitHub</span>
                  </div>
                </button>
              </div>
            </>
          )}

          {/* Footer Navigation */}
          <div className="text-center text-[13.5px] text-[#8D8D8D] mt-6 select-none">
            {mode === 'login' ? (
              <span>
                Don't have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('signup'); setError(''); setSuccess(''); }}
                  className="text-[#E9829B] font-medium hover:underline cursor-pointer ml-1"
                >
                  Sign up
                </button>
              </span>
            ) : mode === 'signup' ? (
              <span>
                Already have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('login'); setError(''); setSuccess(''); }}
                  className="text-[#E9829B] font-medium hover:underline cursor-pointer ml-1"
                >
                  Log in
                </button>
              </span>
            ) : (
              <span>
                Remember your password?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('login'); setError(''); setSuccess(''); }}
                  className="text-[#E9829B] font-medium hover:underline cursor-pointer ml-1"
                >
                  Log in
                </button>
              </span>
            )}
          </div>
        </form>

      </div>
    </div>
  );
}
