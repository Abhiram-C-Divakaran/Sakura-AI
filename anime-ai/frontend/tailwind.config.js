/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Semantic dynamic theme colors
        theme: {
          app: "var(--bg-app)",
          sidebar: "var(--bg-sidebar)",
          chat: "var(--bg-chat)",
          panel: "var(--bg-panel)",
          surface: "var(--bg-surface)",
          card: "var(--bg-card)",
          "card-hover": "var(--bg-card-hover)",
          hover: "var(--bg-hover)",
          active: "var(--bg-active)",
          composer: "var(--bg-composer)",
          "composer-inner": "var(--bg-composer-inner)",
          "user-bubble": "var(--bg-user-bubble)",
          border: "var(--border-app)",
          "border-card": "var(--border-card)",
          "border-subtle": "var(--border-subtle)",
          text: "var(--text-main)",
          muted: "var(--text-muted)",
          dim: "var(--text-dim)",
          accent: "var(--accent)",
          "accent-blue": "var(--accent-blue)",
          "accent-cyan": "var(--accent-cyan)",
          popover: "var(--popover-bg)",
        },
        // Original retro configuration colors (restored to fix unstyled login/console)
        retro: {
          bg: "#090c15",
          glass: "rgba(16, 20, 35, 0.75)",
          border: "rgba(255, 255, 255, 0.08)",
          amber: "#ffb000",
          cyan: "#00f0ff",
          green: "#33ff33",
          magenta: "#ff007f",
          violet: "#9d4edd",
          text: "#f3f4f6",
          main: "#c8d8f0",
          muted: "#5a6a8a",
        },
        // Landing page specific theme colors
        navy:    "#060a14",
        "navy-2": "#0d1424",
        "navy-3": "#111928",
        cyan:    "#00f5ff",
        "cyan-dim": "#007a82",
        magenta: "#ff2d78",
        violet:  "#8b5cf6",
        amber:   "#ffb340",
        green:   "#39ff14",
        cream:   "#f0e6cc",
        muted:   "#5a6a8a",
        "text-main": "#c8d8f0",
        // Sakura AI Console Theme (Pitch Black – Minimal)
        sakura: {
          bg: "#000000",
          panel: "#050505",
          panel2: "#080808",
          border: "#202020",
          border2: "#2A2A2A",
          text: "#F5F5F2",
          muted: "#A0A0A0",
          faint: "#6E6E6E",
          "accent-teal": "#35D0BA",
          "accent-blue": "#4A8EFF",
          "accent-lavender": "#9880ED",
          "accent-pink": "#E98297",
          "chat-user": "#111116",
          "chat-select": "#131313",
        },
      },
      fontFamily: {
        mono:    ["'JetBrains Mono'", "monospace"],
        sans:    ["'Outfit'", "sans-serif"],
        display: ["'Outfit'", "sans-serif"],
        body:    ["'Inter'", "sans-serif"],
      },
      backgroundImage: {
        "crt-lines": "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.15) 2px, rgba(0,0,0,0.15) 4px)",
        "noise": "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E\")",
      },
      keyframes: {
        flicker: {
          "0%, 19.9%, 22%, 62.9%, 64%, 64.9%, 70%, 100%": { opacity: "0.99" },
          "20%, 21.9%, 63%, 63.9%, 65%, 69.9%":           { opacity: "0.4" },
        },
        scanroll: {
          "0%":   { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
        scanline: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" }
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%":      { transform: "translateY(-12px)" },
        },
        shimmer: {
          "0%":   { backgroundPosition: "-200% center" },
          "100%": { backgroundPosition: "200% center" },
        },
        glitch: {
          "0%, 100%": { clipPath: "inset(0 0 100% 0)", transform: "translate(0)" },
          "20%": { clipPath: "inset(30% 0 40% 0)", transform: "translate(-4px, 2px)" },
          "40%": { clipPath: "inset(60% 0 10% 0)", transform: "translate(4px, -2px)" },
          "60%": { clipPath: "inset(10% 0 70% 0)", transform: "translate(-2px, 4px)" },
          "80%": { clipPath: "inset(80% 0 5% 0)",  transform: "translate(2px, -4px)" },
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 8px rgba(0,245,255,0.3), 0 0 20px rgba(0,245,255,0.1)" },
          "50%":      { boxShadow: "0 0 20px rgba(0,245,255,0.7), 0 0 50px rgba(0,245,255,0.3)" },
        },
        glow: {
          "0%": { boxShadow: "0 0 5px rgba(157, 78, 221, 0.2), 0 0 10px rgba(157, 78, 221, 0.2)" },
          "100%": { boxShadow: "0 0 15px rgba(0, 240, 255, 0.4), 0 0 25px rgba(0, 240, 255, 0.2)" }
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0" },
        },
        typing: {
          "from": { width: "0" },
          "to":   { width: "100%" },
        },
      },
      animation: {
        flicker:    "flicker 5s linear infinite",
        scanroll:   "scanroll 8s linear infinite",
        scanline:   "scanline 6s linear infinite",
        float:      "float 6s ease-in-out infinite",
        shimmer:    "shimmer 3s linear infinite",
        glitch:     "glitch 0.4s steps(1) infinite",
        pulseGlow:  "pulseGlow 2s ease-in-out infinite",
        glow:       "glow 2s ease-in-out infinite alternate",
        blink:      "blink 1s step-end infinite",
        typing:     "typing 2s steps(20, end)",
      },
      boxShadow: {
        "glow-cyan":    "0 0 20px rgba(0,245,255,0.5), 0 0 60px rgba(0,245,255,0.2)",
        "glow-violet":  "0 0 20px rgba(139,92,246,0.5), 0 0 60px rgba(139,92,246,0.2)",
        "glow-magenta": "0 0 20px rgba(255,45,120,0.5), 0 0 60px rgba(255,45,120,0.2)",
        "inset-crt":    "inset 0 0 120px rgba(0,0,0,0.8), inset 0 0 40px rgba(0,245,255,0.05)",
      },
    },
  },
  plugins: [],
}
