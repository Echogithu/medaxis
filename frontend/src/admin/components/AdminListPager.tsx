import { Box, Button, Typography } from '@mui/material';

/** 数组接口没有总数；多取一条判断下一页，不推算全库总页数。 */
export default function AdminListPager({ page, count, pageSize, hasMore, loading, onChange }: {
  page: number; count: number; pageSize: number; hasMore: boolean; loading: boolean;
  onChange: (page: number) => void;
}) {
  return <Box aria-label="列表翻页" sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 1, mt: 2 }}>
    <Typography variant="body2" color="text.secondary">第 {page} 页{count > 0 ? ` · 显示第 ${(page - 1) * pageSize + 1}–${(page - 1) * pageSize + count} 条` : ' · 本页暂无记录'}</Typography>
    <Box sx={{ display: 'flex', gap: 1 }}>
      <Button variant="outlined" disabled={loading || page <= 1} onClick={() => onChange(page - 1)}>上一页</Button>
      <Button variant="outlined" disabled={loading || !hasMore} onClick={() => onChange(page + 1)}>下一页</Button>
    </Box>
  </Box>;
}
