/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/features/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Spec §1.1 surfaces — map to the --nx-* tokens so new components can use
        // `bg-bg`, `bg-surface`, `border-border`, `text-secondary`, etc.
        bg: 'var(--nx-bg)',
        surface: {
          DEFAULT: 'var(--nx-surface)',
          2: 'var(--nx-surface-2)',
        },
        border: {
          DEFAULT: 'var(--nx-border)',
          strong: 'var(--nx-border-strong)',
        },
        ink: {
          DEFAULT: 'var(--nx-text)',
          secondary: 'var(--nx-text-secondary)',
          muted: 'var(--nx-text-muted)',
        },
        accent: {
          DEFAULT: 'var(--nx-accent)',
          hover: 'var(--nx-accent-hover)',
          subtle: 'var(--nx-accent-subtle)',
        },
        critical: {
          DEFAULT: 'var(--nx-critical)',
          subtle: 'var(--nx-critical-subtle)',
        },
        warning: {
          DEFAULT: 'var(--nx-warning)',
          subtle: 'var(--nx-warning-subtle)',
        },
        // Back-compat aliases for components/Header.tsx (marketing) — not for new product UI.
        canvas: 'var(--nx-bg)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // Spec §1.3: square/compact control geometry. Zero the card/control radii.
      // `full` is intentionally left default so status DOTS stay circular.
      borderRadius: {
        none: '0px',
        DEFAULT: '0px',
        sm: '0px',
        md: '0px',
        lg: '0px',
        xl: '0px',
        '2xl': '0px',
        '3xl': '0px',
      },
      maxWidth: {
        content: '1440px',
      },
    },
  },
  plugins: [],
};
