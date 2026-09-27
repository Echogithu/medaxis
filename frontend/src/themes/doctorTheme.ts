import { createTheme } from '@mui/material/styles';
import { careFonts, carePalette } from '../theme';

/** Doctor workspace uses the same calm teal surfaces as the patient experience. */
export const doctorTheme = createTheme({
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
    background: { default: carePalette.page, paper: carePalette.paper },
    text: { primary: carePalette.ink, secondary: carePalette.muted },
    error: { main: '#d85c58' },
    warning: { main: '#d99a43' },
    success: { main: '#198d77' },
    info: { main: '#5289a8' },
  },
  typography: {
    fontFamily: careFonts.sans,
    h6: { fontWeight: 650, fontSize: '1.1rem' },
    subtitle1: { fontWeight: 550, fontSize: '0.95rem' },
    body1: { fontSize: '0.9375rem', lineHeight: 1.6 },
    body2: { fontSize: '0.875rem', lineHeight: 1.6 },
    caption: { fontSize: '0.75rem', color: carePalette.muted },
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 12, textTransform: 'none', fontWeight: 600, boxShadow: 'none' },
        contained: { '&:hover': { boxShadow: '0 6px 16px rgba(23,143,130,0.16)' } },
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
        root: { borderRadius: 18, boxShadow: '0 8px 24px rgba(34,61,55,0.045)' },
      },
    },
    MuiPaper: { styleOverrides: { rounded: { borderRadius: 18 } } },
    MuiChip: { styleOverrides: { root: { borderRadius: 9, fontWeight: 550 } } },
  },
});

export default doctorTheme;
