/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          0: 'rgb(var(--surface-0) / <alpha-value>)',
          1: 'rgb(var(--surface-1) / <alpha-value>)',
          2: 'rgb(var(--surface-2) / <alpha-value>)',
          ink: 'rgb(var(--surface-ink) / <alpha-value>)',
        },
        ink: {
          primary: 'rgb(var(--text-primary) / <alpha-value>)',
          secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          muted: 'rgb(var(--text-muted) / <alpha-value>)',
          inverse: 'rgb(var(--text-on-ink) / <alpha-value>)',
        },
        rule: {
          subtle: 'rgb(var(--border-subtle) / <alpha-value>)',
          strong: 'rgb(var(--border-strong) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
          soft: 'rgb(var(--accent-soft) / <alpha-value>)',
        },
        signal: {
          success: 'rgb(var(--signal-success) / <alpha-value>)',
          warning: 'rgb(var(--signal-warning) / <alpha-value>)',
          danger: 'rgb(var(--signal-danger) / <alpha-value>)',
        },
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
      fontFamily: {
        sans: ['"Instrument Sans Variable"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.9375rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.625rem' }],
        xl: ['1.375rem', { lineHeight: '1.875rem' }],
        '2xl': ['1.75rem', { lineHeight: '2.125rem' }],
        '3xl': ['2.25rem', { lineHeight: '2.625rem' }],
        display: ['3rem', { lineHeight: '3.25rem', letterSpacing: '-0.02em' }],
      },
      letterSpacing: {
        tightest: '-0.02em',
        tighter: '-0.01em',
        label: '0.08em',
      },
      borderRadius: {
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        hairline: 'inset 0 0 0 1px rgb(var(--border-subtle))',
        lift: '0 1px 2px rgb(0 0 0 / 0.04), 0 0 0 1px rgb(var(--border-subtle))',
      },
      transitionTimingFunction: {
        decelerate: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
      },
      keyframes: {
        'signal-pulse': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.55', transform: 'scale(0.88)' },
        },
      },
      animation: {
        'signal-pulse': 'signal-pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
