import { createTheme } from '@mui/material/styles';

// Shared non-Admin product palette, aligned with the patient chat workspace.
export const carePalette = {
  primary: '#178f82',
  primaryDark: '#0c756b',
  primarySoft: '#dff1ec',
  mint: '#eef6f2',
  page: '#f0f2ef',
  paper: '#fbfbf9',
  paperStrong: '#ffffff',
  ink: '#173238',
  muted: '#71898a',
  line: '#e2eae6',
  coral: '#e58a68',
  coralSoft: '#f8e0d2',
  amber: '#d99a43',
  amberSoft: '#f6ecd9',
  danger: '#d85c58',
  dangerSoft: '#fde8e6',
} as const;

export const careFonts = {
  sans: '"Plus Jakarta Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  serif: '"Noto Serif SC", "Source Han Serif SC", "Songti SC", serif',
} as const;

export const careShadows = {
  card: '0 8px 24px rgba(34,61,55,0.045)',
  paper: '0 18px 50px rgba(38,52,52,0.08)',
  brand: '0 8px 20px rgba(23,143,130,0.18)',
} as const;

export const patientTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: carePalette.primary,
      light: '#54b5a6',
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
    error: { main: '#d85c58' },
    warning: { main: '#d99a43' },
    success: { main: '#198d77' },
    info: { main: '#5289a8' },
  },
  typography: {
    fontFamily: careFonts.sans,
    h4: { fontFamily: careFonts.serif, fontWeight: 700, letterSpacing: '-0.03em', color: carePalette.ink },
    h5: { fontFamily: careFonts.serif, fontWeight: 700, letterSpacing: '-0.03em', color: carePalette.ink },
    h6: { fontFamily: careFonts.serif, fontWeight: 700, fontSize: '1.15rem', letterSpacing: '-0.02em' },
    subtitle1: { fontWeight: 650, fontSize: '0.95rem' },
    body1: { fontSize: '0.9375rem', lineHeight: 1.7 },
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
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          textTransform: 'none',
          fontWeight: 700,
          boxShadow: 'none',
          minHeight: 40,
        },
        contained: {
          '&:hover': { boxShadow: '0 6px 16px rgba(23,143,130,0.16)' },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          '& fieldset': { borderColor: carePalette.line },
          '&:hover fieldset': { borderColor: '#8dbab0' },
          '&.Mui-focused fieldset': { borderColor: carePalette.primary },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 20,
          boxShadow: careShadows.card,
          border: `1px solid ${carePalette.line}`,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        rounded: { borderRadius: 20 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 999, fontWeight: 650 },
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
