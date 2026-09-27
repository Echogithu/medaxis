import { createTheme, type PaletteMode } from '@mui/material/styles';

export type AdminThemeMode = PaletteMode;

const lightPalette = {
  primary: {
    main: '#2264E5',
    light: '#E8F0FF',
    dark: '#174FCB',
    contrastText: '#FFFFFF',
  },
  secondary: {
    main: '#64748B',
    light: '#E8EDF4',
    dark: '#334155',
    contrastText: '#FFFFFF',
  },
  background: {
    default: '#F6F8FB',
    paper: '#FFFFFF',
  },
  text: {
    primary: '#172033',
    secondary: '#526078',
    disabled: '#A4ADBC',
  },
  divider: '#DDE4EE',
  success: { main: '#17875F', light: '#E8F7F0', dark: '#0F6447' },
  warning: { main: '#B86A12', light: '#FFF4E4', dark: '#8A4D0C' },
  error: { main: '#C83C45', light: '#FEEEEF', dark: '#A72B2B' },
  info: { main: '#3478F6', light: '#E8F0FF', dark: '#174FCB' },
};
const darkPalette = {
  primary: {
    main: '#70A2FF',
    light: '#1C3A68',
    dark: '#A9C7FF',
    contrastText: '#0B1220',
  },
  secondary: {
    main: '#AAB7CC',
    light: '#2B3A52',
    dark: '#728098',
    contrastText: '#0B1220',
  },
  background: {
    default: '#0B1220',
    paper: '#111B2C',
  },
  text: {
    primary: '#EDF3FF',
    secondary: '#AAB7CC',
    disabled: '#66758D',
  },
  divider: '#22314A',
  success: { main: '#55D6A2', light: '#15392F', dark: '#8FE7C4' },
  warning: { main: '#F3B560', light: '#3B2D19', dark: '#FFD494' },
  error: { main: '#FF8383', light: '#422126', dark: '#FFB2B2' },
  info: { main: '#70A2FF', light: '#1C3A68', dark: '#A9C7FF' },
};


export function createAdminTheme(mode: AdminThemeMode) {
  const isDark = mode === 'dark';
  const palette = isDark ? darkPalette : lightPalette;

  return createTheme({
    palette: { mode, ...palette },
    shape: { borderRadius: 8 },
    typography: {
      fontFamily: '"MiSans", "HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
      h1: { fontWeight: 780, letterSpacing: '-0.04em' },
      h2: { fontWeight: 760, letterSpacing: '-0.03em' },
      h5: { fontWeight: 760, letterSpacing: '-0.02em' },
      h6: { fontWeight: 720, letterSpacing: '-0.015em' },
      body1: { lineHeight: 1.6 },
      body2: { lineHeight: 1.55 },
      caption: { lineHeight: 1.45 },
      button: { fontWeight: 680, textTransform: 'none' },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          ':root': { colorScheme: mode },
          body: {
            backgroundColor: palette.background.default,
            color: palette.text.primary,
            transition: 'background-color 180ms ease, color 180ms ease',
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            boxShadow: '0 1px 2px rgba(15, 23, 42, 0.08)',
            minHeight: 38,
            fontWeight: 650,
            transition: 'background-color 150ms ease, border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease',
            '&:hover': { transform: 'translateY(-1px)', boxShadow: '0 3px 8px rgba(15, 23, 42, 0.12)' },
            '&:active': { transform: 'translateY(0) scale(0.98)', boxShadow: '0 1px 2px rgba(15, 23, 42, 0.08)' },
            '&:focus-visible': { outline: '2px solid', outlineColor: palette.primary.main, outlineOffset: 2 },
          },
          contained: { boxShadow: '0 1px 2px rgba(15, 23, 42, 0.12)' },
        },
      },
      MuiIconButton: {
        styleOverrides: { root: { borderRadius: 6 } },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            '&.MuiInputBase-sizeSmall': { minHeight: 36 },
            '& fieldset': { borderColor: palette.divider },
            '&:hover fieldset': { borderColor: palette.primary.main },
            '&.Mui-focused fieldset': { borderColor: palette.primary.main },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            border: `1px solid ${palette.divider}`,
            boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
            backgroundImage: 'none',
            transition: 'box-shadow 150ms ease, border-color 150ms ease, transform 150ms ease',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            '&.MuiPaper-elevation1': {
              boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
              border: `1px solid ${palette.divider}`,
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: { root: { borderRadius: 6, fontWeight: 600 } },
      },
      MuiTableCell: {
        styleOverrides: {
          root: { borderColor: palette.divider, padding: '12px 16px' },
          head: {
            color: palette.text.secondary,
            backgroundColor: isDark ? '#152238' : '#F8FAFC',
            fontWeight: 680,
            whiteSpace: 'nowrap',
            borderBottom: `1px solid ${palette.divider}`,
          },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            '&.MuiTableRow-hover:hover': { backgroundColor: isDark ? '#17243A' : '#F6F9FD' },
            transition: 'background-color 120ms ease',
          },
        },
      },
      MuiAlert: {
        styleOverrides: { root: { borderRadius: 8 } },
      },
      MuiTabs: {
        styleOverrides: {
          root: {
            minHeight: 48,
            '& .MuiTabs-flexContainer': { gap: 4 },
          },
          indicator: { height: 3, borderRadius: 3, bottom: 3 },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            minHeight: 48,
            paddingInline: 16,
            borderRadius: 1.5,
            fontSize: '0.8125rem',
            fontWeight: 560,
            textTransform: 'none',
            color: palette.text.secondary,
            transition: 'color 160ms ease, background-color 160ms ease',
            '&:hover': { color: palette.text.primary, backgroundColor: isDark ? '#182943' : '#F3F6FA' },
            '&.Mui-selected': { color: palette.primary.main, fontWeight: 700 },
            '& .MuiTab-iconWrapper': { marginBottom: 0, marginRight: 0.75 },
          },
        },
      },
    },
  });
}
