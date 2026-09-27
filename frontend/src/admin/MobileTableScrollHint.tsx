import Typography from '@mui/material/Typography';

/** 在窄屏提示宽表格可横向滚动，避免右侧字段和操作被误认为不存在。 */
export function MobileTableScrollHint() {
  return (
    <Typography
      variant="caption"
      sx={{ display: { xs: 'block', md: 'none' }, mb: 0.75, color: 'text.secondary', textAlign: 'right', fontSize: '0.6875rem' }}
    >
      左右滑动表格查看更多
    </Typography>
  );
}
