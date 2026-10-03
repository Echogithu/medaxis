import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Button, Stack } from '@mui/material';
import { pendingPostVisitActions } from '../../api/patient';

export default function PendingPostVisitActions() {
  const [items, setItems] = useState<Array<{ case_id: string; revision: number }>>([]);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    pendingPostVisitActions().then(data => { if (alive) { setItems(data.items); setError(false); } })
      .catch(() => { if (alive) setError(true); });
    const timer = window.setInterval(() => setReload(key => key + 1), 60000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [reload]);
  if (error) return <Alert severity="warning" sx={{ mb: 2 }} action={<Button onClick={() => setReload(key => key + 1)}>重试</Button>}>待确认建议暂时无法读取</Alert>;
  if (!items.length) return null;
  return <Alert severity="info" sx={{ mb: 2 }}>
    你有 {items.length} 份就诊后建议待确认，尚未创建安排。
    <Stack>{items.map((item, index) => <Button key={item.case_id} component={RouterLink} to={`/cases?case_id=${encodeURIComponent(item.case_id)}&stage=visit`}>查看待确认建议 {index + 1}</Button>)}</Stack>
  </Alert>;
}
