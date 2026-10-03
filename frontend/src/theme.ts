import { createTheme } from '@mui/material/styles';

// 患者工作台的颜色与原型统一，组件只引用这份品牌色。
export const carePalette = {
  primary: '#0d9488',
  primaryDark: '#0f766e',
  primarySoft: '#ccfbf1',
  mint: '#f0fdfa',
  page: '#f8fafc',
  paper: '#f8fafc',
  paperStrong: '#ffffff',
  ink: '#1e293b',
  muted: '#64748b',
  line: '#e2e8f0',
  coral: '#f97316',
  coralSoft: '#fff7ed',
  amber: '#ea580c',
  amberSoft: '#fff7ed',
  danger: '#e11d48',
  dangerSoft: '#fff1f2',
} as const;

export const careFonts = {
  sans: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
  serif: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
} as const;

export const careShadows = {
  card: '0 10px 40px -10px rgba(15,23,42,0.06)',
  paper: '0 22px 50px -14px rgba(15,23,42,0.12)',
  brand: '0 14px 34px -12px rgba(13,148,136,0.3)',
} as const;

export const patientTheme = createTheme({
  shape: { borderRadius: 8 },
  palette: {
    mode: 'light',
    primary: {
      main: carePalette.primary,
      light: '#14b8a6',
      dark: carePalette.primaryDark,
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: carePalette.ink,
      light: '#49666a',
      dark: '#10272b',
    },
    background: {
      default: carePalette.page,
      paper: carePalette.paperStrong,
    },
    text: {
      primary: carePalette.ink,
      secondary: carePalette.muted,
    },
    divider: carePalette.line,
    error: { main: carePalette.danger },
    warning: { main: carePalette.amber },
    success: { main: carePalette.primaryDark },
    info: { main: '#6366f1' },
  },
  typography: {
    fontFamily: careFonts.sans,
    h4: { fontWeight: 600, fontSize: '2.25rem', letterSpacing: '-0.03em', color: carePalette.ink },
    h5: { fontWeight: 600, fontSize: '1.875rem', letterSpacing: '-0.03em', color: carePalette.ink },
    h6: { fontWeight: 600, fontSize: '1.125rem', letterSpacing: '-0.02em' },
    subtitle1: { fontWeight: 650, fontSize: '0.95rem' },
    body1: { fontSize: '0.875rem', lineHeight: 1.7 },
    body2: { fontSize: '0.875rem', lineHeight: 1.7 },
    caption: { fontSize: '0.75rem', color: carePalette.muted, lineHeight: 1.55 },
    button: { fontWeight: 700 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: carePalette.page,
          color: carePalette.ink,
          WebkitFontSmoothing: 'antialiased',
        },
        ':focus-visible': { outline: '3px solid rgba(20,184,166,.4)', outlineOffset: 3 },
        '@media (prefers-reduced-motion: reduce)': {
          '*, *::before, *::after': { animation: 'none !important', transition: 'none !important', scrollBehavior: 'auto !important' },
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 16,
          textTransform: 'none',
          fontWeight: 600,
          boxShadow: 'none',
          minHeight: 44,
          transition: 'background-color 200ms ease, box-shadow 200ms ease, transform 200ms ease',
          '&:active': { transform: 'translateY(1px)' },
        },
        contained: {
          boxShadow: careShadows.brand,
          '&:hover': { boxShadow: careShadows.brand },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 16,
          '& fieldset': { borderColor: carePalette.line },
          '&:hover fieldset': { borderColor: '#8dbab0' },
          '&.Mui-focused fieldset': { borderColor: carePalette.primary },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 24,
          boxShadow: careShadows.card,
          border: 0,
        },
      },
    },
    MuiCardContent: { styleOverrides: { root: { padding: 24, '&:last-child': { paddingBottom: 24 } } } },
    MuiPaper: {
      styleOverrides: {
        rounded: { borderRadius: 24 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 10, fontWeight: 500 },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 14 },
      },
    },
  },
});

export default patientTheme;
