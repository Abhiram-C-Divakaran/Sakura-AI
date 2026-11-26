import React, { useState, useEffect } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { Mail, Lock, Eye, EyeOff, User, Loader2, AlertCircle, Check, ArrowLeft } from 'lucide-react';
import { SakuraLogo, SakuraWordmark } from '../components/SakuraLogo';
import { getAccessToken, setAccessToken } from '../lib/auth';
import { apiUrl } from '../lib/api';

const GoogleIcon = () => (
  <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
  </svg>
);

const GitHubIcon = () => (
  <svg className="w-4 h-4 flex-shrink-0 fill-current text-[#F5F5F5]" viewBox="0 0 24 24" aria-hidden="true">
    <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
  </svg>
);

interface AuthConfig {
  password_reset_enabled: boolean;
  google_oauth_enabled: boolean;
  github_oauth_enabled: boolean;
}

function formatApiError(detail: any, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d: any) => (typeof d === 'string' ? d : d?.msg)).filter(Boolean);
    return msgs.length > 0 ? msgs.join('. ') : fallback;
  }
  return fallback;
}

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'signup' | 'forgot' | 'reset'>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    password_reset_enabled: false,
    google_oauth_enabled: false,
    github_oauth_enabled: false,
  });

  useEffect(() => {
    const token = getAccessToken();
    if (token) {
      router.push('/chat');
    }
  }, [router]);

  useEffect(() => {
    if (router.isReady && typeof router.query.reset_token === 'string' && router.query.reset_token) {
      setResetToken(router.query.reset_token);
      setMode('reset');
    }
  }, [router.isReady, router.query.reset_token]);

  useEffect(() => {
    let active = true;
    fetch(apiUrl('/api/v1/auth/config'))
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) {
          setAuthConfig({
            password_reset_enabled: Boolean(data.password_reset_enabled),
            google_oauth_enabled: Boolean(data.google_oauth_enabled),
            github_oauth_enabled: Boolean(data.github_oauth_enabled),
          });
        }
      })
      .catch(() => {
        // Leave unconfigured features honestly hidden/disabled on network error
      });
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    const cleanIdentifier = email.trim();

    try {
      if (mode === 'forgot') {
        if (!authConfig.password_reset_enabled) {
          throw new Error(
            'Password reset is currently disabled on this deployment because no email delivery provider is configured.'
          );
        }
        const resetRes = await fetch(apiUrl('/api/v1/auth/password-reset/request'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ identifier: cleanIdentifier }),
        });
        const resetData = await resetRes.json().catch(() => ({}));
        if (!resetRes.ok) {
          throw new Error(formatApiError(resetData.detail, 'Unable to process password reset request.'));
        }
        setSuccess(
          resetData.message || 'If an account exists for this email or username, a password reset link has been sent.'
        );
        return;
      }

      if (mode === 'reset') {
        if (password.length < 8) {
          throw new Error('New password must be at least 8 characters long.');
        }
        const confirmRes = await fetch(apiUrl('/api/v1/auth/password-reset/confirm'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: resetToken, new_password: password }),
        });
        const confirmData = await confirmRes.json().catch(() => ({}));
        if (!confirmRes.ok) {
          throw new Error(formatApiError(confirmData.detail, 'Reset token is invalid or expired.'));
        }
        setSuccess('Your password has been reset. You can now sign in with your new password.');
        setPassword('');
        setMode('login');
        return;
      }

      if (mode === 'signup') {
        if (password.length < 8) {
          throw new Error('Password must be at least 8 characters long.');
        }

        const regRes = await fetch(apiUrl('/api/v1/auth/register'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: cleanIdentifier,
            email: cleanIdentifier.includes('@') ? cleanIdentifier : undefined,
            password,
          }),
        });

        if (!regRes.ok) {
          const errData = await regRes.json().catch(() => ({}));
          throw new Error(formatApiError(errData.detail, 'Email or username already registered.'));
        }
      }

      const formData = new URLSearchParams();
      formData.append('username', cleanIdentifier);
      formData.append('password', password);

      const authRes = await fetch(apiUrl('/api/v1/auth/token'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString(),
      });

      if (!authRes.ok) {
        const errData = await authRes.json().catch(() => ({}));
        const fallback = authRes.status === 429
          ? 'Too many sign-in attempts. Please wait a moment and try again.'
          : 'Incorrect email or password.';
        throw new Error(formatApiError(errData.detail, fallback));
      }

      const authData = await authRes.json();
      setAccessToken(authData.access_token);
      router.push('/chat');
    } catch (err: any) {
      setError(err?.message || 'Authentication error.');
    } finally {
      setLoading(false);
    }
  };

  const showOAuthSection =
    mode !== 'forgot' &&
    mode !== 'reset' &&
    (authConfig.google_oauth_enabled || authConfig.github_oauth_enabled);

  return (
    <>
      <Head>
        <title>{mode === 'signup' ? 'Create account — Sakura AI' : 'Sign in — Sakura AI'}</title>
        <meta name="description" content="Sign in to your Sakura AI workspace." />
      </Head>
      <div
        className="min-h-screen w-full bg-[#000000] text-[#F5F5F5] flex flex-col items-center justify-center p-4 selection:bg-[#E9829B]/30 select-none relative"
        style={{ fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" }}
      >
        <Link
          href="/"
          className="fixed top-6 left-6 sm:top-8 sm:left-8 flex items-center gap-2 text-[13px] text-[#747474] hover:text-[#F5F5F5] transition-colors cursor-pointer group select-none z-20"
          title="Back to home"
        >
          <ArrowLeft className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" />
          <span className="font-medium">Back</span>
        </Link>

        <div className="w-full max-w-[390px] sm:max-w-[400px] flex flex-col items-center my-auto py-8">
          <div className="flex flex-col items-center select-none mb-8">
            <SakuraLogo size={46} className="mb-3 hover:scale-105 transition-transform duration-200" />
            <SakuraWordmark height={40} className="hover:opacity-95 transition-opacity" />
          </div>

          <div className="text-center mb-6 flex flex-col gap-1 w-full">
            <h1 className="text-[26px] sm:text-[28px] font-semibold text-[#F5F5F5] tracking-tight">
              {mode === 'signup'
                ? 'Create your account'
                : mode === 'forgot'
                ? 'Reset password'
                : mode === 'reset'
                ? 'Choose a new password'
                : 'Welcome back'}
            </h1>
            <p className="text-[14px] text-[#8D8D8D]">
              {mode === 'signup'
                ? 'Start using Sakura AI'
                : mode === 'forgot'
                ? authConfig.password_reset_enabled
                  ? "Enter your email address and we'll send you a single-use reset link."
                  : 'Password reset email delivery is not configured on this deployment.'
                : mode === 'reset'
                ? 'Enter a new password of at least 8 characters.'
                : 'Sign in to continue to Sakura AI'}
            </p>
          </div>

          {error && (
            <div role="alert" className="w-full mb-4 px-3.5 py-2.5 rounded-[10px] bg-red-950/20 border border-red-500/25 text-[#FF6B6B] text-[13px] flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 flex-shrink-0 text-[#FF6B6B]" />
              <span className="leading-snug">{error}</span>
            </div>
          )}

          {success && (
            <div role="status" className="w-full mb-4 px-3.5 py-2.5 rounded-[10px] bg-emerald-950/20 border border-emerald-500/25 text-[#35D0BA] text-[13px] flex items-center gap-2.5">
              <Check className="w-4 h-4 flex-shrink-0 text-[#35D0BA]" />
              <span className="leading-snug">{success}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
            {mode === 'signup' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[13.5px] font-medium text-[#D1D1D1]">Name</label>
                <div className="relative flex items-center">
                  <User className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Your name (optional)"
                    autoComplete="name"
                    className="w-full h-[50px] pl-11 pr-4 rounded-[11px] bg-[#141414] border border-[#2B2B2B] text-[15px] text-[#F5F5F5] placeholder-[#747474] focus:outline-none focus:border-[#555555] focus:ring-1 focus:ring-[#555555] transition-all"
                  />
                </div>
              </div>
            )}

            {mode !== 'reset' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[13.5px] font-medium text-[#D1D1D1]">Email or username</label>
                <div className="relative flex items-center">
                  <Mail className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
                  <input
                    type="text"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@example.com"
                    autoComplete="username"
                    className="w-full h-[50px] pl-11 pr-4 rounded-[11px] bg-[#141414] border border-[#2B2B2B] text-[15px] text-[#F5F5F5] placeholder-[#747474] focus:outline-none focus:border-[#555555] focus:ring-1 focus:ring-[#555555] transition-all"
                  />
                </div>
              </div>
            )}

            {mode !== 'forgot' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[13.5px] font-medium text-[#D1D1D1]">
                  {mode === 'reset' ? 'New password' : 'Password'}
                </label>
                <div className="relative flex items-center">
                  <Lock className="w-4 h-4 text-[#747474] absolute left-4 pointer-events-none" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    autoComplete={mode === 'signup' || mode === 'reset' ? 'new-password' : 'current-password'}
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
                {(mode === 'signup' || mode === 'reset') && (
                  <span className="text-[12px] text-[#747474] mt-0.5">At least 8 characters</span>
                )}
              </div>
            )}

            {mode === 'login' && authConfig.password_reset_enabled && (
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
              disabled={loading || (mode === 'forgot' && !authConfig.password_reset_enabled)}
              className="w-full h-[50px] rounded-[11px] bg-[#F5F5F5] hover:bg-white text-black font-semibold text-[15px] transition-all flex items-center justify-center cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed shadow-md active:scale-[0.99] mt-2"
            >
              {loading ? (
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-black" />
                  <span>
                    {mode === 'signup'
                      ? 'Creating account...'
                      : mode === 'forgot'
                      ? 'Sending reset link...'
                      : mode === 'reset'
                      ? 'Updating password...'
                      : 'Signing in...'}
                  </span>
                </div>
              ) : mode === 'signup' ? (
                'Create account'
              ) : mode === 'forgot' ? (
                authConfig.password_reset_enabled ? 'Send reset link' : 'Password reset unavailable'
              ) : mode === 'reset' ? (
                'Update password'
              ) : (
                'Continue'
              )}
            </button>

            {showOAuthSection && (
              <>
                <div className="flex items-center gap-3 my-3 w-full">
                  <div className="flex-1 h-[1px] bg-[#222222]" />
                  <span className="text-[12px] text-[#747474] lowercase font-medium select-none">or</span>
                  <div className="flex-1 h-[1px] bg-[#222222]" />
                </div>

                <div className="flex flex-col gap-2.5 w-full">
                  {authConfig.google_oauth_enabled && (
                    <a
                      href={apiUrl('/api/v1/auth/oauth/google')}
                      className="w-full h-[48px] px-4 rounded-[11px] bg-transparent hover:bg-[#111111] border border-[#2B2B2B] hover:border-[#444444] text-[14px] font-medium text-[#F5F5F5] flex items-center justify-center gap-3 transition-all"
                    >
                      <GoogleIcon />
                      <span>Continue with Google</span>
                    </a>
                  )}
                  {authConfig.github_oauth_enabled && (
                    <a
                      href={apiUrl('/api/v1/auth/oauth/github')}
                      className="w-full h-[48px] px-4 rounded-[11px] bg-transparent hover:bg-[#111111] border border-[#2B2B2B] hover:border-[#444444] text-[14px] font-medium text-[#F5F5F5] flex items-center justify-center gap-3 transition-all"
                    >
                      <GitHubIcon />
                      <span>Continue with GitHub</span>
                    </a>
                  )}
                </div>
              </>
            )}

            <div className="text-center text-[13.5px] text-[#8D8D8D] mt-6 select-none">
              {mode === 'login' ? (
                <span>
                  Don&apos;t have an account?{' '}
                  <button
                    type="button"
                    onClick={() => { setMode('signup'); setError(''); setSuccess(''); }}
                    className="text-[#E9829B] font-medium hover:underline cursor-pointer ml-1"
                  >
                    Sign up
                  </button>
                </span>
              ) : (
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
              )}
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
