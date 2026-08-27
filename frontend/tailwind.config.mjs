/**
 * Tailwind is the layout tool; the language lives in the design system.
 *
 * Every colour, font, size and easing below resolves to a custom property from
 * `src/design-system/tokens.css` — nothing here holds a value of its own. That
 * is what makes the token layer the seam: redefining a token re-skins the whole
 * platform, and no page has to be rewritten to inherit a change.
 *
 * @type {import('tailwindcss').Config}
 */

/** Wrap a token so Tailwind can apply an opacity modifier to it. */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        canvas: token('canvas'),

        surface: {
          DEFAULT: token('surface'),
          sunken: token('surface-sunken'),
          raised: token('surface-raised'),
          ink: token('surface-ink'),
        },

        ink: {
          DEFAULT: token('ink'),
          secondary: token('ink-secondary'),
          muted: token('ink-muted'),
          'on-ink': token('ink-on-ink'),
        },

        // The charcoal objects: primary pills, the bulk bar, toasts, tooltips.
        chrome: {
          DEFAULT: token('chrome'),
          raised: token('chrome-raised'),
          rule: token('chrome-rule'),
          ink: token('chrome-ink'),
          'ink-muted': token('chrome-ink-muted'),
        },

        rule: {
          DEFAULT: token('rule'),
          hairline: token('rule-hairline'),
          strong: token('rule-strong'),
        },

        accent: {
          DEFAULT: token('accent'),
          pressed: token('accent-pressed'),
          ink: token('accent-ink'),
          wash: token('accent-wash'),
          hairline: token('accent-hairline'),
          'on-chrome': token('accent-on-chrome'),
        },

        signal: {
          locked: token('signal-locked'),
          drift: token('signal-drift'),
          fault: token('signal-fault'),
          'locked-on-chrome': token('signal-locked-on-chrome'),
          'drift-on-chrome': token('signal-drift-on-chrome'),
          'fault-on-chrome': token('signal-fault-on-chrome'),
        },

        gold: {
          DEFAULT: token('gold'),
          deep: token('gold-deep'),
          'on-chrome': token('gold-on-chrome'),
        },
      },

      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },

      fontSize: {
        micro:   ['var(--text-micro)',   { lineHeight: 'var(--leading-normal)' }],
        caption: ['var(--text-caption)', { lineHeight: 'var(--leading-normal)' }],
        small:   ['var(--text-small)',   { lineHeight: 'var(--leading-normal)' }],
        body:    ['var(--text-body)',    { lineHeight: 'var(--leading-normal)' }],
        lead:    ['var(--text-lead)',    { lineHeight: 'var(--leading-relaxed)' }],
        title:   ['var(--text-title)',   { lineHeight: 'var(--leading-snug)' }],
        heading: ['var(--text-heading)', { lineHeight: 'var(--leading-tight)' }],
        display: ['var(--text-display)', { lineHeight: 'var(--leading-tight)', letterSpacing: 'var(--tracking-display)' }],
        // Legacy scale names used across the existing pages.
        xs:    ['var(--text-caption)', { lineHeight: 'var(--leading-normal)' }],
        sm:    ['var(--text-small)',   { lineHeight: 'var(--leading-normal)' }],
        base:  ['var(--text-body)',    { lineHeight: 'var(--leading-normal)' }],
        lg:    ['var(--text-lead)',    { lineHeight: 'var(--leading-relaxed)' }],
        xl:    ['var(--text-title)',   { lineHeight: 'var(--leading-snug)' }],
        '2xl': ['var(--text-heading)', { lineHeight: 'var(--leading-tight)' }],
        '3xl': ['var(--text-display)', { lineHeight: 'var(--leading-tight)' }],
      },

      fontWeight: {
        thin: 'var(--weight-thin)',
        light: 'var(--weight-light)',
        normal: 'var(--weight-regular)',
        medium: 'var(--weight-medium)',
        bold: 'var(--weight-bold)',
      },

      lineHeight: {
        tight: 'var(--leading-tight)',
        snug: 'var(--leading-snug)',
        normal: 'var(--leading-normal)',
        relaxed: 'var(--leading-relaxed)',
      },

      letterSpacing: {
        display: 'var(--tracking-display)',
        title: 'var(--tracking-title)',
        body: 'var(--tracking-body)',
        mono: 'var(--tracking-mono)',
        label: 'var(--tracking-label)',
      },

      maxWidth: {
        read: 'var(--measure-read)',
        form: 'var(--measure-form)',
        page: 'var(--measure-page)',
      },

      borderRadius: {
        none: '0',
        xs: 'var(--radius-xs)',
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        // Nothing in this system is more rounded than --radius-lg except the
        // deliberately circular, so xl resolves to the same ceiling.
        xl: 'var(--radius-lg)',
        full: 'var(--radius-full)',
      },

      boxShadow: {
        flat: 'var(--shadow-flat)',
        raised: 'var(--shadow-raised)',
        lifted: 'var(--shadow-lifted)',
        overlay: 'var(--shadow-overlay)',
      },

      transitionTimingFunction: {
        settle: 'var(--ease-settle)',
        depart: 'var(--ease-depart)',
        phase: 'var(--ease-phase)',
      },

      transitionDuration: {
        tick: 'var(--dur-tick)',
        tap: 'var(--dur-tap)',
        shift: 'var(--dur-shift)',
        reveal: 'var(--dur-reveal)',
        stage: 'var(--dur-stage)',
      },

      zIndex: {
        sticky: 'var(--z-sticky)',
        drawer: 'var(--z-drawer)',
        overlay: 'var(--z-overlay)',
        dialog: 'var(--z-dialog)',
        toast: 'var(--z-toast)',
      },

      keyframes: {
        // The beat — the system's one piece of ambient motion.
        beat: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.45', transform: 'scale(0.82)' },
        },
      },

      animation: {
        beat: 'beat var(--dur-beat) var(--ease-phase) infinite',
      },
    },
  },
  plugins: [],
};
