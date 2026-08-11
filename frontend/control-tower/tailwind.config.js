/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#030712',
        card: '#0A0F1A',
        'card-hover': '#0F1629',
        border: '#1A2235',
        'border-light': '#243049',
        foreground: '#F1F5F9',
        muted: '#64748B',
        'muted-light': '#94A3B8',
        primary: '#3B82F6',
        'primary-light': '#60A5FA',
        'primary-dim': '#1D4ED8',
        success: '#10B981',
        'success-light': '#34D399',
        warning: '#F59E0B',
        'warning-light': '#FBBF24',
        error: '#EF4444',
        'error-light': '#F87171',
        accent: '#8B5CF6',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'glow-strong': 'glow-strong 2s ease-in-out infinite alternate',
        'typing': 'typing 1.5s steps(20, end) forwards',
        'blink': 'blink 1s step-end infinite',
        'float': 'float 3s ease-in-out infinite',
        'progress': 'progress 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.5s ease-out',
        'fade-in': 'fade-in 0.6s ease-out',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(59, 130, 246, 0.2), 0 0 10px rgba(59, 130, 246, 0.1)' },
          '100%': { boxShadow: '0 0 15px rgba(59, 130, 246, 0.4), 0 0 30px rgba(59, 130, 246, 0.2)' },
        },
        'glow-strong': {
          '0%': { boxShadow: '0 0 10px rgba(59, 130, 246, 0.3), 0 0 20px rgba(59, 130, 246, 0.15)' },
          '100%': { boxShadow: '0 0 25px rgba(59, 130, 246, 0.5), 0 0 50px rgba(59, 130, 246, 0.25), 0 0 80px rgba(59, 130, 246, 0.1)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        progress: {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
        'slide-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'glow-sm': '0 0 10px rgba(59, 130, 246, 0.15)',
        'glow-md': '0 0 20px rgba(59, 130, 246, 0.25)',
        'glow-lg': '0 0 40px rgba(59, 130, 246, 0.3)',
        'card': '0 4px 24px rgba(0, 0, 0, 0.3)',
        'card-hover': '0 8px 40px rgba(0, 0, 0, 0.4)',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'),
  ],
}
