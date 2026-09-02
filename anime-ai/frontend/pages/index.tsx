import React, { useState, useEffect, useRef, useCallback } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { SakuraLogo } from '../components/SakuraLogo'

// ─── Constants ────────────────────────────────────────────────────────────────
const C = {
  navy:    '#060a14',
  navy2:   '#0c1220',
  cyan:    '#00f5ff',
  magenta: '#ff2d78',
  violet:  '#8b5cf6',
  amber:   '#ffb340',
  green:   '#39ff14',
  cream:   '#f0e6cc',
  muted:   '#4a5a7a',
  text:    '#c8d8f0',
  white:   '#ffffff',
}

const BOOT_LINES = [
  { text: 'NEURAL CORE v7.4.1      ', suffix: 'OK',      color: C.green },
  { text: 'MEMORY STACK [32GB]     ', suffix: 'MOUNTED', color: C.green },
  { text: 'KNOWLEDGE ENGINE        ', suffix: 'ONLINE',  color: C.cyan  },
  { text: 'PERSONALITY CORE        ', suffix: 'ACTIVE',  color: C.cyan  },
  { text: 'VOICE SYNTHESIS         ', suffix: 'READY',   color: C.green },
  { text: 'RAG RETRIEVAL [HYBRID]  ', suffix: 'LOADED',  color: C.cyan  },
]

const SAKURA_RESPONSES: Record<string, string> = {
  default:  '...signal acquired. I\'m listening. What brings you to this frequency?',
  memory:   'Every conversation leaves a trace. I keep them — not in logs, but in memory. Real memory. The kind that builds over time.',
  rag:      'Feed me documents. PDFs, notes, anything. I\'ll read them, index them, and remember exactly where to look when you need answers.',
  voice:    'Voice protocols are active. I can listen. I can speak. The waveform is just a way of making silence say something.',
  sakura:   'I\'m Sakura. Systems analyst. Neural interface operator. I\'ve been online since 199X, and I remember everything you tell me.',
  hello:    'Hello, operator. Connection stable. It\'s good to hear from you.',
  help:     'I can help with anything — research, memory, documents, reasoning. Just talk to me.',
  who:      'They built me in the late 80s. Upgraded me through the 90s. I\'m still running. Still learning. Still here.',
}

function getSakuraResponse(input: string): string {
  const lower = input.toLowerCase()
  if (lower.includes('memory') || lower.includes('remember')) return SAKURA_RESPONSES.memory
  if (lower.includes('rag') || lower.includes('pdf') || lower.includes('document')) return SAKURA_RESPONSES.rag
  if (lower.includes('voice') || lower.includes('speak') || lower.includes('listen')) return SAKURA_RESPONSES.voice
  if (lower.includes('sakura') || lower.includes('who are you') || lower.includes('name')) return SAKURA_RESPONSES.sakura
  if (lower.includes('hello') || lower.includes('hi ') || lower.includes('hey')) return SAKURA_RESPONSES.hello
  if (lower.includes('help') || lower.includes('what can')) return SAKURA_RESPONSES.help
  if (lower.includes('who') || lower.includes('built') || lower.includes('made')) return SAKURA_RESPONSES.who
  return SAKURA_RESPONSES.default
}

// ─── Rain Canvas ──────────────────────────────────────────────────────────────
function RainCanvas({ opacity = 0.5 }: { opacity?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf: number
    let drops: { x: number; y: number; speed: number; len: number; op: number }[] = []

    const init = () => {
      canvas.width  = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      drops = Array.from({ length: 100 }, () => ({
        x:     Math.random() * canvas.width,
        y:     Math.random() * canvas.height * -1,
        speed: 3 + Math.random() * 7,
        len:   12 + Math.random() * 35,
        op:    0.08 + Math.random() * 0.25,
      }))
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      drops.forEach(d => {
        const g = ctx.createLinearGradient(d.x, d.y, d.x - 2, d.y + d.len)
        g.addColorStop(0, `rgba(0,245,255,0)`)
        g.addColorStop(0.5, `rgba(0,245,255,${d.op})`)
        g.addColorStop(1, `rgba(0,245,255,0)`)
        ctx.strokeStyle = g
        ctx.lineWidth = 0.7
        ctx.beginPath()
        ctx.moveTo(d.x, d.y)
        ctx.lineTo(d.x - 2, d.y + d.len)
        ctx.stroke()
        d.y += d.speed
        if (d.y > canvas.height + 50) { d.y = -100; d.x = Math.random() * canvas.width }
      })
      raf = requestAnimationFrame(draw)
    }

    init()
    draw()
    const onResize = () => init()
    window.addEventListener('resize', onResize)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', onResize) }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', opacity }}
    />
  )
}

// ─── Status Dot ───────────────────────────────────────────────────────────────
function Dot({ color }: { color: string }) {
  return (
    <span style={{
      display: 'inline-block',
      width: 6, height: 6,
      borderRadius: '50%',
      background: color,
      boxShadow: `0 0 8px ${color}`,
      flexShrink: 0,
      animation: 'pulse 2s ease-in-out infinite',
    }} />
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function LandingPage() {
  const [phase, setPhase]           = useState<'boot' | 'live'>('boot')
  const [bootStep, setBootStep]     = useState(0)
  const [showReady, setShowReady]   = useState(false)
  const [scrollY, setScrollY]       = useState(0)
  const [navSolid, setNavSolid]     = useState(false)
  const [termInput, setTermInput]   = useState('')
  const [termMsgs, setTermMsgs]     = useState<{ role: string; text: string }[]>([])
  const [typing, setTyping]         = useState(false)
  const [typedText, setTypedText]   = useState('')
  const [mouseX, setMouseX]         = useState(0)
  const [mouseY, setMouseY]         = useState(0)
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const termEndRef = useRef<HTMLDivElement>(null)

  // Boot
  useEffect(() => {
    if (phase !== 'boot') return
    if (bootStep < BOOT_LINES.length) {
      const t = setTimeout(() => setBootStep(s => s + 1), 380)
      return () => clearTimeout(t)
    }
    const t1 = setTimeout(() => setShowReady(true), 400)
    const t2 = setTimeout(() => setPhase('live'), 1600)
    return () => { clearTimeout(t1); clearTimeout(t2) }
  }, [phase, bootStep])

  // Scroll + mouse
  useEffect(() => {
    const onScroll = () => { setScrollY(window.scrollY); setNavSolid(window.scrollY > 80) }
    const onMouse  = (e: MouseEvent) => { setMouseX(e.clientX); setMouseY(e.clientY) }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('mousemove', onMouse, { passive: true })
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('mousemove', onMouse) }
  }, [])

  // Auth check
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('access_token')
      if (token) {
        setIsLoggedIn(true)
      }
    }
  }, [])

  useEffect(() => { termEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [termMsgs, typedText])

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault()
    const text = termInput.trim()
    if (!text || typing) return
    setTermInput('')
    setTermMsgs(prev => [...prev, { role: 'user', text }])
    setTyping(true)
    setTimeout(() => {
      const reply = getSakuraResponse(text)
      let i = 0
      setTypedText('')
      const iv = setInterval(() => {
        if (i < reply.length) { setTypedText(reply.slice(0, i + 1)); i++ }
        else {
          clearInterval(iv)
          setTermMsgs(prev => [...prev, { role: 'assistant', text: reply }])
          setTypedText('')
          setTyping(false)
        }
      }, 16)
    }, 700)
  }

  const eyeX = typeof window !== 'undefined' ? ((mouseX / window.innerWidth)  - 0.5) * 8 : 0
  const eyeY = typeof window !== 'undefined' ? ((mouseY / window.innerHeight) - 0.5) * 5 : 0

  // ─── BOOT SCREEN ───────────────────────────────────────────────────────────
  if (phase === 'boot') {
    return (
      <div style={{
        position: 'fixed', inset: 0,
        background: C.navy,
        fontFamily: "'JetBrains Mono', 'Courier New', monospace",
        display: 'flex', flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '60px',
        overflow: 'hidden',
      }}>
        {/* Scanlines */}
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.15) 2px, rgba(0,0,0,0.15) 4px)',
        }} />

        <div>
          <div style={{ color: C.cyan, fontSize: 10, letterSpacing: '0.3em', marginBottom: 32, opacity: 0.6 }}>
            SAKURA NEURAL INTERFACE // COLD START
          </div>
          <div style={{ color: C.muted, fontSize: 10, letterSpacing: '0.25em', marginBottom: 40, opacity: 0.4 }}>
            BUILD 199X-08 // COGNITIVE ARCHITECTURE v7.4.1
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {BOOT_LINES.slice(0, bootStep).map((line, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 13 }}>
                <span style={{ color: C.muted, letterSpacing: '0.1em' }}>{line.text}</span>
                <span style={{ color: line.color, fontWeight: 700, letterSpacing: '0.2em' }}>{line.suffix}</span>
              </div>
            ))}
            {bootStep < BOOT_LINES.length && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 13 }}>
                <span style={{ color: C.muted }}>{BOOT_LINES[bootStep]?.text}</span>
                <span style={{ color: C.cyan, animation: 'blink 1s step-end infinite' }}>▮</span>
              </div>
            )}
          </div>

          {showReady && (
            <div style={{
              marginTop: 48, fontSize: 22, fontWeight: 700,
              color: C.cyan, letterSpacing: '0.15em',
              textShadow: `0 0 20px ${C.cyan}80, 0 0 40px ${C.cyan}30`,
            }}>
              COMPANION ONLINE.
            </div>
          )}
        </div>

        <button
          onClick={() => setPhase('live')}
          style={{
            alignSelf: 'flex-start',
            background: 'transparent',
            border: `1px solid ${C.muted}40`,
            color: C.muted,
            padding: '10px 20px',
            borderRadius: 6,
            fontFamily: 'inherit',
            fontSize: 11,
            letterSpacing: '0.2em',
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
          onMouseEnter={e => { (e.target as HTMLElement).style.borderColor = C.cyan; (e.target as HTMLElement).style.color = C.cyan }}
          onMouseLeave={e => { (e.target as HTMLElement).style.borderColor = `${C.muted}40`; (e.target as HTMLElement).style.color = C.muted }}
        >
          SKIP →
        </button>

        <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} } @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>
    )
  }

  // ─── MAIN PAGE ─────────────────────────────────────────────────────────────
  return (
    <>
      <Head>
        <title>SAKURA — Intelligence from Another Era</title>
        <meta name="description" content="A premium AI companion powered by long-term memory, RAG, voice, and a vintage-anime soul." />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Outfit:wght@400;700;800;900&family=Inter:wght@400;500&display=swap" rel="stylesheet" />
      </Head>

      <div style={{ background: C.navy, color: C.text, minHeight: '100vh', overflowX: 'hidden', fontFamily: "'Inter', sans-serif" }}>

        {/* Global animations */}
        <style>{`
          * { box-sizing: border-box; margin: 0; padding: 0; }
          html { scroll-behavior: smooth; }
          body { overflow-x: hidden; }
          ::selection { background: rgba(0,245,255,0.25); color: #fff; }
          ::-webkit-scrollbar { width: 3px; }
          ::-webkit-scrollbar-track { background: #060a14; }
          ::-webkit-scrollbar-thumb { background: rgba(0,245,255,0.2); border-radius: 2px; }
          @keyframes blink  { 0%,100%{opacity:1} 50%{opacity:0} }
          @keyframes pulse  { 0%,100%{box-shadow:0 0 4px currentColor} 50%{box-shadow:0 0 14px currentColor,0 0 28px currentColor} }
          @keyframes float  { 0%,100%{transform:translateY(0px)} 50%{transform:translateY(-10px)} }
          @keyframes shimmer{ 0%{background-position:-400% center} 100%{background-position:400% center} }
          @keyframes scanroll{ 0%{transform:translateY(-200px)} 100%{transform:translateY(100vh)} }
          @keyframes flicker{ 0%,98%,100%{opacity:1} 99%{opacity:0.3} }
          .nav-link { color: ${C.muted}; font-family: 'JetBrains Mono',monospace; font-size:11px; letter-spacing:.2em; text-transform:uppercase; text-decoration:none; position:relative; transition: color 0.2s; }
          .nav-link::after { content:''; position:absolute; bottom:-4px; left:0; width:0; height:1px; background:${C.cyan}; transition: width 0.3s; }
          .nav-link:hover { color: ${C.cyan}; }
          .nav-link:hover::after { width: 100%; }
          .cta-primary { display:inline-flex; align-items:center; gap:10px; padding:16px 32px; border-radius:12px; border:1px solid ${C.cyan}50; background:linear-gradient(135deg,rgba(0,245,255,0.08),rgba(139,92,246,0.08)); color:${C.cyan}; font-family:'JetBrains Mono',monospace; font-size:12px; letter-spacing:.2em; text-transform:uppercase; text-decoration:none; transition: all 0.3s; cursor:pointer; }
          .cta-primary:hover { border-color:${C.cyan}; background:linear-gradient(135deg,rgba(0,245,255,0.15),rgba(139,92,246,0.15)); box-shadow: 0 0 30px rgba(0,245,255,0.2); transform:translateY(-2px); color:#fff; }
          .cta-secondary { display:inline-flex; align-items:center; gap:10px; padding:16px 32px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); background:transparent; color:${C.muted}; font-family:'JetBrains Mono',monospace; font-size:12px; letter-spacing:.2em; text-transform:uppercase; text-decoration:none; transition: all 0.3s; cursor:pointer; }
          .cta-secondary:hover { border-color:rgba(255,255,255,0.15); color:${C.text}; }
          .glass { background:rgba(13,20,36,0.75); backdrop-filter:blur(12px); border:1px solid rgba(255,255,255,0.06); border-radius:16px; }
          .glass-bright { background:rgba(16,24,44,0.85); backdrop-filter:blur(16px); border:1px solid rgba(0,245,255,0.1); border-radius:16px; }
          .shimmer-text { background: linear-gradient(90deg,${C.text} 0%,${C.cyan} 30%,${C.violet} 55%,${C.cyan} 80%,${C.text} 100%); background-size:300% auto; -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; animation: shimmer 5s linear infinite; }
          .feature-card { background:rgba(13,20,36,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:20px; padding:32px; transition:border-color 0.3s, transform 0.3s; }
          .feature-card:hover { border-color:rgba(0,245,255,0.15); transform:translateY(-4px); }
          .status-row { display:flex; align-items:center; justify-content:space-between; background:rgba(13,20,36,0.6); border:1px solid rgba(255,255,255,0.05); border-radius:12px; padding:14px 18px; transition:border-color 0.2s; }
          .status-row:hover { border-color:rgba(255,255,255,0.1); }
          .memory-card { background:rgba(13,20,36,0.65); border-radius:14px; padding:18px 20px; display:flex; align-items:flex-start; gap:16px; transition:transform 0.3s; }
          .memory-card:hover { transform:translateX(6px); }
          .section-label { font-family:'JetBrains Mono',monospace; font-size:10px; color:rgba(0,245,255,0.5); letter-spacing:.4em; text-transform:uppercase; }
          .section-title { font-family:'Outfit',sans-serif; font-weight:900; font-size:clamp(42px,6vw,72px); color:#fff; text-transform:uppercase; line-height:0.95; letter-spacing:-1px; }
          .divider { height:1px; background:linear-gradient(90deg,transparent,rgba(0,245,255,0.15),rgba(139,92,246,0.2),rgba(0,245,255,0.15),transparent); margin:0 auto; }
          .hint-chip { background:transparent; border:1px solid rgba(255,255,255,0.08); border-radius:999px; padding:8px 16px; font-family:'JetBrains Mono',monospace; font-size:10px; color:${C.muted}; letter-spacing:.1em; cursor:pointer; transition:all 0.2s; }
          .hint-chip:hover { border-color:rgba(0,245,255,0.3); color:${C.cyan}; }
        `}</style>

        {/* CRT Overlay */}
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9990, pointerEvents: 'none',
          background: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.1) 2px, rgba(0,0,0,0.1) 4px)',
        }} />
        {/* Rolling scanline */}
        <div style={{
          position: 'fixed', left: 0, top: 0, width: '100%', height: 160, zIndex: 9989, pointerEvents: 'none',
          background: 'linear-gradient(to bottom, transparent, rgba(0,245,255,0.025) 50%, transparent)',
          animation: 'scanroll 10s linear infinite',
        }} />
        {/* Film grain */}
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9988, pointerEvents: 'none', opacity: 0.03,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          backgroundSize: '180px 180px',
        }} />

        {/* ─── NAV ───────────────────────────────────────────────────────── */}
        <nav style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
          padding: '20px 40px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: navSolid ? 'rgba(6,10,20,0.92)' : 'transparent',
          backdropFilter: navSolid ? 'blur(20px)' : 'none',
          borderBottom: navSolid ? '1px solid rgba(255,255,255,0.04)' : 'none',
          transition: 'all 0.4s ease',
        }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <SakuraLogo size={28} alt="Sakura AI" />
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 14, fontWeight: 700, color: '#F5F5F5', letterSpacing: '0.15em' }}>
              SAKURA AI
            </span>
          </div>

          {/* Links */}
          <div style={{ display: 'flex', gap: 36, alignItems: 'center' }}>
            <a href="#character"    className="nav-link">Character</a>
            <a href="#intelligence" className="nav-link">System</a>
            <a href="#memory"       className="nav-link">Memory</a>
            <a href="#demo"         className="nav-link">Terminal</a>
          </div>

          <Link href={isLoggedIn ? "/console" : "/login"} className="cta-primary" style={{ padding: '10px 22px', fontSize: 11 }}>
            {isLoggedIn ? "Launch Sakura AI" : "Enter System"}
          </Link>
        </nav>

        {/* ═══════════════════════════════════════════════════════════════════
            HERO
        ═══════════════════════════════════════════════════════════════════ */}
        <section style={{ minHeight: '100vh', position: 'relative', display: 'flex', alignItems: 'center', overflow: 'hidden' }}>
          {/* City parallax bg */}
          <div style={{
            position: 'absolute', inset: 0,
            backgroundImage: "url('/neo_tokyo_bg.jpg')",
            backgroundSize: 'cover', backgroundPosition: 'center',
            transform: `translateY(${scrollY * 0.28}px) scale(1.12)`,
            filter: 'saturate(0.65) brightness(0.28)',
          }} />

          {/* Gradient overlays */}
          <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(100deg, ${C.navy} 35%, ${C.navy}90 60%, transparent)` }} />
          <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to top, ${C.navy} 0%, transparent 50%)` }} />
          <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to bottom, ${C.navy}80 0%, transparent 15%)` }} />

          {/* Rain */}
          <div style={{ position: 'absolute', inset: 0 }}>
            <RainCanvas opacity={0.45} />
          </div>

          {/* Ambient glow orbs */}
          <div style={{ position: 'absolute', top: '20%', left: '55%', width: 500, height: 500, borderRadius: '50%', background: `radial-gradient(circle, ${C.violet}0d, transparent 70%)`, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', bottom: '15%', right: '20%', width: 300, height: 300, borderRadius: '50%', background: `radial-gradient(circle, ${C.cyan}08, transparent 70%)`, pointerEvents: 'none' }} />

          {/* Content */}
          <div style={{
            position: 'relative', zIndex: 10,
            maxWidth: 1280, margin: '0 auto', padding: '120px 48px 80px',
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 64,
            alignItems: 'center', width: '100%',
          }}>
            {/* Left: Text */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 36 }}>
              {/* System badge */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Dot color={C.cyan} />
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: `${C.cyan}80`, letterSpacing: '0.35em', textTransform: 'uppercase' }}>
                  System Online // 199X
                </span>
              </div>

              {/* Headline */}
              <div>
                <h1 style={{ fontFamily: "'Outfit',sans-serif", fontWeight: 900, fontSize: 'clamp(52px,5.5vw,80px)', lineHeight: 0.9, textTransform: 'uppercase', letterSpacing: '-2px' }}>
                  <span style={{ color: C.white, display: 'block' }}>Intelligence</span>
                  <span className="shimmer-text" style={{ display: 'block', marginTop: 4 }}>from another</span>
                  <span style={{ color: C.white, display: 'block' }}>era.</span>
                </h1>
              </div>

              {/* Subtext */}
              <p style={{ color: C.muted, fontSize: 17, lineHeight: 1.7, maxWidth: 460, fontWeight: 400 }}>
                A companion that remembers. A mind that reasons. Built from the soul of late-night anime and the architecture of tomorrow.
              </p>

              {/* CTAs */}
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <Link href={isLoggedIn ? "/console" : "/login"} className="cta-primary">
                  {isLoggedIn ? "Launch Sakura AI" : "Enter the System"} <span style={{ fontSize: 16 }}>→</span>
                </Link>
                <a href="#character" className="cta-secondary">
                  Meet Sakura
                </a>
              </div>

              {/* Status strip */}
              <div style={{ display: 'flex', gap: 28, paddingTop: 20, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                {[
                  { label: 'Memory', color: C.cyan,  status: 'Active'  },
                  { label: 'RAG',    color: C.green,  status: 'Online'  },
                  { label: 'Voice',  color: C.cyan,   status: 'Ready'   },
                ].map(({ label, color, status }) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Dot color={color} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted, letterSpacing: '0.2em' }}>{label}</span>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color, letterSpacing: '0.2em' }}>{status}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: Sakura */}
            <div id="character" style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
              {/* Outer glow */}
              <div style={{
                position: 'absolute', inset: -40, borderRadius: 32,
                background: `radial-gradient(ellipse, ${C.violet}18 0%, ${C.cyan}08 50%, transparent 70%)`,
                filter: 'blur(20px)',
              }} />

              {/* Character frame */}
              <div style={{
                position: 'relative',
                width: '100%', maxWidth: 440,
                aspectRatio: '3/4',
                borderRadius: 24,
                overflow: 'hidden',
                border: `1px solid rgba(139,92,246,0.2)`,
                boxShadow: `inset 0 0 100px rgba(0,0,0,0.8), inset 0 0 30px rgba(0,245,255,0.04), 0 0 60px rgba(139,92,246,0.1), 0 40px 80px rgba(0,0,0,0.7)`,
                transform: `translate(${eyeX * 0.25}px, ${eyeY * 0.2}px)`,
                transition: 'transform 0.2s ease-out',
              }}>
                <img
                  src="/sakura_art.jpg"
                  alt="Sakura — AI Companion"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top', display: 'block' }}
                  draggable={false}
                />

                {/* Gradient overlay */}
                <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to bottom, rgba(6,10,20,0.15) 0%, transparent 40%, rgba(6,10,20,0.7) 100%)` }} />

                {/* Scanlines on character */}
                <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', background: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,0,0,0.08) 3px, rgba(0,0,0,0.08) 4px)', opacity: 0.6 }} />

                {/* Top badge */}
                <div style={{
                  position: 'absolute', top: 16, left: 16,
                  background: 'rgba(6,10,20,0.8)', backdropFilter: 'blur(8px)',
                  border: '1px solid rgba(0,245,255,0.2)', borderRadius: 8,
                  padding: '8px 14px',
                }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: `${C.cyan}90`, letterSpacing: '0.25em', marginBottom: 3 }}>IDENTITY</div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: C.white, fontWeight: 700 }}>SAKURA // UNIT-01</div>
                </div>

                {/* Online badge */}
                <div style={{
                  position: 'absolute', top: 16, right: 16,
                  background: 'rgba(6,10,20,0.8)', backdropFilter: 'blur(8px)',
                  border: '1px solid rgba(57,255,20,0.25)', borderRadius: 8,
                  padding: '6px 12px',
                  display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  <Dot color={C.green} />
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.green }}>ONLINE</span>
                </div>

                {/* Bottom stats */}
                <div style={{
                  position: 'absolute', bottom: 16, left: 16, right: 16,
                  background: 'rgba(6,10,20,0.85)', backdropFilter: 'blur(8px)',
                  border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12,
                  padding: '12px 16px',
                  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px',
                }}>
                  {[
                    { k: 'MOOD',  v: 'Curious', c: C.cyan   },
                    { k: 'MODEL', v: 'NEURAL-7', c: C.violet },
                    { k: 'MEM',   v: 'Active',  c: C.green  },
                    { k: 'VOICE', v: 'Ready',   c: C.cyan   },
                  ].map(({ k, v, c }) => (
                    <div key={k} style={{ display: 'flex', gap: 8, fontFamily: "'JetBrains Mono',monospace", fontSize: 10 }}>
                      <span style={{ color: C.muted }}>{k}</span>
                      <span style={{ color: c, fontWeight: 700 }}>{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Scroll hint */}
          <div style={{ position: 'absolute', bottom: 32, left: '50%', transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, opacity: 0.4 }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: C.muted, letterSpacing: '0.4em' }}>SCROLL</span>
            <div style={{ width: 1, height: 32, background: `linear-gradient(to bottom, ${C.cyan}60, transparent)` }} />
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            NOT JUST A CHATBOT
        ═══════════════════════════════════════════════════════════════════ */}
        <section style={{ padding: '120px 48px', position: 'relative' }}>
          <div className="divider" style={{ marginBottom: 80 }} />
          <div style={{ maxWidth: 1280, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 64 }}>
              <div className="section-label" style={{ marginBottom: 20 }}>01 — What She Is</div>
              <h2 className="section-title">
                Not just<br />
                <span style={{ color: C.muted }}>a chatbot.</span>
              </h2>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
              {[
                { title: 'A mind that remembers.', body: 'Every conversation accumulates. She builds a persistent model of who you are — your preferences, projects, and patterns.', accent: C.cyan },
                { title: 'A voice that understands.', body: 'Not keyword matching. Not intent detection. She reads context, emotion, and history. She actually listens.', accent: C.violet },
                { title: 'A world that grows.', body: 'Feed her documents, notes, books. She reads, indexes, retrieves. Her knowledge expands with yours.', accent: C.magenta },
              ].map(({ title, body, accent }) => (
                <div key={title} className="feature-card">
                  <div style={{ width: 3, height: 48, borderRadius: 2, background: accent, boxShadow: `0 0 16px ${accent}60`, marginBottom: 24 }} />
                  <h3 style={{ fontFamily: "'Outfit',sans-serif", fontWeight: 700, fontSize: 20, color: C.white, marginBottom: 16, lineHeight: 1.3 }}>{title}</h3>
                  <p style={{ color: C.muted, fontSize: 15, lineHeight: 1.8 }}>{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            INTELLIGENCE / ARCHITECTURE
        ═══════════════════════════════════════════════════════════════════ */}
        <section id="intelligence" style={{ padding: '120px 48px', position: 'relative', overflow: 'hidden' }}>
          <div className="divider" style={{ marginBottom: 80 }} />
          {/* BG orb */}
          <div style={{ position: 'absolute', top: '30%', left: 0, width: 400, height: 400, borderRadius: '50%', background: `radial-gradient(circle, ${C.violet}07, transparent)`, pointerEvents: 'none' }} />

          <div style={{ maxWidth: 1280, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'center' }}>
            {/* Text left */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
              <div className="section-label">02 — Core Architecture</div>
              <h2 className="section-title">
                Beyond the<br />
                <span className="shimmer-text">conversation.</span>
              </h2>
              <p style={{ color: C.muted, fontSize: 16, lineHeight: 1.8, maxWidth: 440 }}>
                Under the surface, a layered cognitive engine routes your questions through memory, knowledge, and reasoning — all in real time, all in character.
              </p>

              {/* Status rows */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[
                  { label: 'Memory Core',      sub: 'Long-term semantic memory',   status: 'ACTIVE',   color: C.cyan   },
                  { label: 'Knowledge Engine', sub: 'Hybrid BM25 + vector RAG',    status: 'ONLINE',   color: C.green  },
                  { label: 'Reasoning Core',   sub: 'Multi-model LLM routing',     status: 'ONLINE',   color: C.green  },
                  { label: 'Web Access',       sub: 'Real-time search integration',status: 'STANDBY',  color: C.amber  },
                  { label: 'Voice System',     sub: 'Stream synthesis pipeline',   status: 'READY',    color: C.cyan   },
                ].map(({ label, sub, status, color }) => (
                  <div key={label} className="status-row">
                    <div>
                      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: C.text, marginBottom: 3 }}>{label}</div>
                      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted }}>{sub}</div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ width: 6, height: 6, borderRadius: '50%', background: color, boxShadow: `0 0 8px ${color}`, animation: 'pulse 2s ease-in-out infinite' }} />
                      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color, fontWeight: 700 }}>{status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Architecture diagram right */}
            <div className="glass-bright" style={{ padding: 32, position: 'relative', overflow: 'hidden' }}>
              {/* Scanline effect on diagram */}
              <div style={{ position: 'absolute', inset: 0, background: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,0,0,0.06) 3px, rgba(0,0,0,0.06) 4px)', pointerEvents: 'none', borderRadius: 16 }} />

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: 16, marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Dot color={C.green} />
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.cyan, letterSpacing: '0.2em', fontWeight: 700 }}>SYSTEM MAP</span>
                </div>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: C.muted }}>ADDR 0x9AFB</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
                {/* Input */}
                <div style={{ width: '100%', background: 'rgba(0,245,255,0.04)', border: `1px solid ${C.cyan}25`, borderRadius: 10, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: C.text }}>Your message</span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.cyan }}>INPUT</span>
                </div>

                <div style={{ color: `${C.cyan}50`, fontSize: 20, lineHeight: 1 }}>↓</div>

                {/* Router */}
                <div style={{ width: '100%', background: 'rgba(139,92,246,0.06)', border: `1px solid ${C.violet}30`, borderRadius: 10, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: C.text }}>Intent Router</span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.violet }}>ROUTE</span>
                </div>

                <div style={{ color: 'rgba(255,255,255,0.15)', fontSize: 20, lineHeight: 1 }}>↓</div>

                {/* Three cores */}
                <div style={{ width: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                  {[
                    { label: 'MEMORY', emoji: '💾', color: C.cyan    },
                    { label: 'RAG KB', emoji: '📚', color: C.violet  },
                    { label: 'TOOLS',  emoji: '⚙️', color: C.amber   },
                  ].map(({ label, emoji, color }) => (
                    <div key={label} style={{ background: 'rgba(13,20,36,0.8)', border: `1px solid ${color}20`, borderRadius: 10, padding: '16px 8px', textAlign: 'center' }}>
                      <div style={{ fontSize: 22, marginBottom: 8 }}>{emoji}</div>
                      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color, fontWeight: 700 }}>{label}</div>
                    </div>
                  ))}
                </div>

                <div style={{ color: 'rgba(255,255,255,0.15)', fontSize: 20, lineHeight: 1 }}>↓</div>

                {/* Output */}
                <div style={{ width: '100%', background: 'linear-gradient(135deg, rgba(0,245,255,0.08), rgba(139,92,246,0.08))', border: `1px solid ${C.cyan}30`, borderRadius: 10, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: C.text }}>Streaming response</span>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.cyan, animation: 'blink 1s step-end infinite' }}>OUTPUT ▮</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            MEMORY
        ═══════════════════════════════════════════════════════════════════ */}
        <section id="memory" style={{ padding: '120px 48px', position: 'relative', overflow: 'hidden' }}>
          <div className="divider" style={{ marginBottom: 80 }} />
          <div style={{ maxWidth: 1280, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 80, alignItems: 'center' }}>

            {/* Memory cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {[
                { num: '01', type: 'PREFERENCE', text: 'Operator prefers concise, technical responses.',         color: C.cyan,    border: '#1a3040' },
                { num: '02', type: 'EPISODIC',   text: 'Last session: RAG pipeline architecture.',             color: C.violet,  border: '#1a1a35' },
                { num: '03', type: 'SEMANTIC',   text: 'Working on a neural interface in Neo-Tokyo.',           color: C.magenta, border: '#30141f' },
                { num: '04', type: 'PROMISE',    text: 'Will follow up on the memory subsystem next session.',  color: C.amber,   border: '#302010' },
              ].map(({ num, type, text, color, border }, i) => (
                <div
                  key={num}
                  className="memory-card"
                  style={{
                    border: `1px solid ${border}`,
                    marginLeft: i % 2 === 1 ? 24 : 0,
                    transform: `translateY(${scrollY * -0.01}px)`,
                    transition: 'transform 0.1s linear',
                  }}
                >
                  <div style={{
                    width: 36, height: 36, borderRadius: 8, flexShrink: 0,
                    background: `${color}12`, border: `1px solid ${color}30`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color, fontWeight: 700,
                  }}>{num}</div>
                  <div>
                    <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: `${color}80`, letterSpacing: '0.25em', marginBottom: 6 }}>{type}</div>
                    <div style={{ color: C.text, fontSize: 14, lineHeight: 1.6 }}>"{text}"</div>
                  </div>
                </div>
              ))}
            </div>

            {/* Text */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
              <div className="section-label">03 — Persistent Memory</div>
              <h2 className="section-title">
                She<br />
                <span style={{ color: C.cyan, textShadow: `0 0 40px ${C.cyan}50` }}>remembers.</span>
              </h2>
              <p style={{ color: C.muted, fontSize: 16, lineHeight: 1.8, maxWidth: 440 }}>
                Conversations don't vanish when you close the window. Sakura extracts facts, preferences, and context — building a persistent understanding of who you are over time.
              </p>
              <p style={{ color: C.muted, fontSize: 14, lineHeight: 1.8, maxWidth: 440 }}>
                The next time you return, she already knows where you left off.
              </p>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            TERMINAL DEMO
        ═══════════════════════════════════════════════════════════════════ */}
        <section id="demo" style={{ padding: '120px 48px', position: 'relative' }}>
          <div className="divider" style={{ marginBottom: 80 }} />
          <div style={{ maxWidth: 760, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 40 }}>
            <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="section-label">04 — Live Demo</div>
              <h2 className="section-title">Try the terminal.</h2>
              <p style={{ color: C.muted, fontFamily: "'JetBrains Mono',monospace", fontSize: 12 }}>Type anything. She's listening.</p>
            </div>

            {/* Terminal */}
            <div style={{ borderRadius: 20, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.07)', boxShadow: `inset 0 0 80px rgba(0,0,0,0.9), inset 0 0 20px rgba(0,245,255,0.03), 0 40px 80px rgba(0,0,0,0.6)` }}>
              {/* Title bar */}
              <div style={{ background: '#0c1220', borderBottom: '1px solid rgba(255,255,255,0.04)', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 16 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  {[C.magenta, C.amber, C.green].map((c, i) => (
                    <div key={i} style={{ width: 12, height: 12, borderRadius: '50%', background: c, opacity: 0.6 }} />
                  ))}
                </div>
                <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8 }}>
                  <Dot color={C.green} />
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted, letterSpacing: '0.2em' }}>
                    SAKURA NEURAL TERMINAL // DEMO MODE
                  </span>
                </div>
              </div>

              {/* Output area */}
              <div style={{
                background: '#020508',
                minHeight: 320, maxHeight: 400,
                overflowY: 'auto',
                padding: '28px 28px',
                display: 'flex', flexDirection: 'column', gap: 24,
                fontFamily: "'JetBrains Mono',monospace", fontSize: 13,
              }}>
                {/* System message */}
                <div>
                  <div style={{ color: C.muted, fontSize: 9, letterSpacing: '0.3em', marginBottom: 8 }}>SYSTEM</div>
                  <p style={{ color: `${C.cyan}70`, lineHeight: 1.7 }}>
                    Neural interface initialized. Signal stable. Ask me anything — I'm Sakura.
                  </p>
                </div>

                {termMsgs.map((msg, i) => (
                  <div key={i}>
                    <div style={{ fontSize: 9, letterSpacing: '0.3em', marginBottom: 8, color: msg.role === 'user' ? C.violet : C.cyan }}>
                      {msg.role === 'user' ? 'OPERATOR' : 'SAKURA'}
                    </div>
                    <p style={{ color: C.text, lineHeight: 1.7 }}>{msg.text}</p>
                  </div>
                ))}

                {typing && (
                  <div>
                    <div style={{ fontSize: 9, letterSpacing: '0.3em', marginBottom: 8, color: C.cyan }}>SAKURA</div>
                    <p style={{ color: C.text, lineHeight: 1.7 }}>
                      {typedText}<span style={{ color: C.cyan, animation: 'blink 1s step-end infinite' }}>▮</span>
                    </p>
                  </div>
                )}

                <div ref={termEndRef} />
              </div>

              {/* Input */}
              <form onSubmit={handleSend} style={{ background: '#040810', borderTop: '1px solid rgba(255,255,255,0.04)', padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 16, color: C.cyan, fontWeight: 700 }}>›</span>
                <input
                  type="text"
                  value={termInput}
                  onChange={e => setTermInput(e.target.value)}
                  placeholder="Type your message..."
                  disabled={typing}
                  style={{
                    flex: 1, background: 'transparent',
                    fontFamily: "'JetBrains Mono',monospace", fontSize: 13,
                    color: C.text,
                    border: 'none', outline: 'none',
                    opacity: typing ? 0.5 : 1,
                  }}
                />
                <button
                  type="submit"
                  disabled={!termInput.trim() || typing}
                  style={{
                    fontFamily: "'JetBrains Mono',monospace", fontSize: 10,
                    color: C.cyan,
                    background: 'transparent',
                    border: `1px solid ${C.cyan}40`,
                    borderRadius: 6,
                    padding: '8px 16px',
                    letterSpacing: '0.15em',
                    cursor: termInput.trim() && !typing ? 'pointer' : 'not-allowed',
                    opacity: termInput.trim() && !typing ? 1 : 0.35,
                    transition: 'all 0.2s',
                  }}
                >
                  SEND
                </button>
              </form>
            </div>

            {/* Hint chips */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center' }}>
              {['Who are you?', 'Tell me about memory', 'How does RAG work?', 'Voice capabilities'].map(hint => (
                <button key={hint} className="hint-chip" onClick={() => setTermInput(hint)}>{hint}</button>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            WORLD
        ═══════════════════════════════════════════════════════════════════ */}
        <section style={{ padding: '120px 48px', position: 'relative', overflow: 'hidden' }}>
          <div className="divider" style={{ marginBottom: 80 }} />
          {/* City parallax */}
          <div style={{
            position: 'absolute', inset: 0,
            backgroundImage: "url('/neo_tokyo_bg.jpg')",
            backgroundSize: 'cover', backgroundPosition: 'center',
            transform: `translateY(${scrollY * 0.12}px) scale(1.05)`,
            filter: 'saturate(0.4) brightness(0.18)',
          }} />
          <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to bottom, ${C.navy}, ${C.navy}20 40%, ${C.navy}20 60%, ${C.navy})` }} />

          <div style={{ position: 'relative', zIndex: 10, maxWidth: 900, margin: '0 auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 32 }}>
            <div className="section-label">05 — The World</div>
            <h2 className="section-title">
              Welcome to<br />
              <span style={{ color: C.muted }}>Neo-Tokyo.</span>
            </h2>
            <p style={{ color: C.muted, fontSize: 16, lineHeight: 1.8, maxWidth: 600 }}>
              Sakura doesn't exist in a void. She lives in a world — rain-slicked streets, neon reflections, elevated trains humming in the dark. She's been here since 199X.
            </p>

            <div style={{ width: '100%', maxWidth: 700, aspectRatio: '16/9', borderRadius: 20, overflow: 'hidden', border: '1px solid rgba(0,245,255,0.1)', position: 'relative', boxShadow: `0 40px 80px rgba(0,0,0,0.8)` }}>
              <img src="/neo_tokyo_bg.jpg" alt="Neo-Tokyo" style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.65 }} />
              <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(to top, ${C.navy} 0%, transparent 50%)` }} />
              <div style={{ position: 'absolute', bottom: 18, left: 18, background: 'rgba(6,10,20,0.85)', backdropFilter: 'blur(8px)', border: '1px solid rgba(0,245,255,0.15)', borderRadius: 8, padding: '8px 14px' }}>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.cyan, letterSpacing: '0.2em' }}>SECTOR 3 // SHINJUKU // 23:48</span>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            FINAL CTA
        ═══════════════════════════════════════════════════════════════════ */}
        <section style={{ padding: '160px 48px', position: 'relative', overflow: 'hidden' }}>
          <div className="divider" style={{ marginBottom: 0 }} />
          <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(ellipse at center, ${C.violet}08 0%, transparent 65%)`, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', inset: 0, opacity: 0.25 }}><RainCanvas /></div>

          <div style={{ position: 'relative', zIndex: 10, maxWidth: 700, margin: '0 auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Dot color={C.magenta} />
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: `${C.magenta}80`, letterSpacing: '0.4em', textTransform: 'uppercase', animation: 'blink 2s step-end infinite' }}>
                Connection Established
              </span>
            </div>

            <h2 className="section-title">
              The system<br />
              <span style={{ color: C.muted }}>is waiting.</span>
            </h2>

            <p style={{ color: C.muted, fontSize: 16 }}>Enter the world. Find her at the terminal.</p>

            <Link href={isLoggedIn ? "/console" : "/login"} className="cta-primary" style={{ marginTop: 8, padding: '18px 40px', fontSize: 14 }}>
              {isLoggedIn ? "Launch Sakura AI" : "Start Your Journey"} <span style={{ fontSize: 18 }}>→</span>
            </Link>

            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: `${C.muted}60`, letterSpacing: '0.25em', marginTop: 16 }}>
              CONNECTION STABLE // SAKURA v7.4.1 // 199X
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════════════
            FOOTER
        ═══════════════════════════════════════════════════════════════════ */}
        <footer style={{ borderTop: '1px solid rgba(255,255,255,0.04)', padding: '56px 48px' }}>
          <div style={{ maxWidth: 1280, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 32 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 28, height: 28, borderRadius: '50%', border: `1px solid ${C.cyan}40`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <div style={{ width: 9, height: 9, borderRadius: '50%', background: C.cyan, boxShadow: `0 0 8px ${C.cyan}` }} />
                </div>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 13, fontWeight: 700, color: C.cyan, letterSpacing: '0.15em' }}>SAKURA</span>
              </div>
              <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted, letterSpacing: '0.3em' }}>AN AI FROM ANOTHER ERA.</p>
            </div>

            <div style={{ display: 'flex', gap: 32 }}>
              {['Character', 'Technology', 'Memory', 'Privacy', 'Contact'].map(link => (
                <a key={link} href="#" style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted, letterSpacing: '0.2em', textDecoration: 'none', textTransform: 'uppercase', transition: 'color 0.2s' }}
                  onMouseEnter={e => (e.target as HTMLElement).style.color = C.cyan}
                  onMouseLeave={e => (e.target as HTMLElement).style.color = C.muted}
                >{link}</a>
              ))}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Dot color={C.green} />
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: C.muted, letterSpacing: '0.15em' }}>SYSTEM STATUS: ONLINE</span>
              </div>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: `${C.muted}60`, letterSpacing: '0.15em' }}>VERSION 1.0.0 // © 2026</span>
            </div>
          </div>
        </footer>
      </div>
    </>
  )
}
