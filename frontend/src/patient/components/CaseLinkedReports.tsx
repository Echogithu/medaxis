import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Pagination, Stack, Typography } from '@mui/material';
import { listCaseReports } from '../../api/reports';
import type { CaseReportsPage } from '../../api/reports';
import { reportLinkLabels } from '../../state/reportLinks';

export default function CaseLinkedReports({ caseId }: { caseId: string }) {
  const [data, setData] = useState<CaseReportsPage | null>(null);
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    listCaseReports(caseId,page).then(value => { if (live) { setData(value); setError(''); } })
      .catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [caseId,page,reload]);
  return <Box component="section" aria-label="病例关联报告" sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
    <Typography component="h3" variant="subtitle1">关联的独立报告（本人可见）</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>这里是资料引用；不自动授权医生或进入诊断。删除病例后，独立报告仍保留。</Typography>
    {error ? <Alert severity="error" action={<Button onClick={() => setReload(value=>value+1)}>重试</Button>}>{error}</Alert> : !data ? <Typography>加载关联报告中…</Typography> : <>
      {!data.items.length && <Typography color="text.secondary">还没有关联的独立报告。</Typography>}
      <Stack spacing={1}>{data.items.map(item => <Box key={item.id} sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{item.title}</Typography>
        <Typography variant="body2">关联原件版本 {item.link.source_version} · {item.link.review_revision ? `本人核对版本 ${item.link.review_revision}` : '未关联核对内容'}</Typography>
        <Typography variant="body2" color="text.secondary">{reportLinkLabels[item.link.status]}</Typography>
        <Button component={RouterLink} to={`/reports/${encodeURIComponent(item.id)}`}>查看独立报告</Button>
      </Box>)}</Stack>
      {data.total > data.limit && <Pagination page={page} count={Math.ceil(data.total/data.limit)} onChange={(_,value)=>{setPage(value);setData(null);}} />}
    </>}
    <Button component={RouterLink} to="/reports">去报告中心选择关联</Button>
  </Box>;
}
