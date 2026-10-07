import { useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Card, Chip, Pagination, Skeleton, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { ArrowBackRounded, ArrowForwardRounded, DescriptionOutlined, UploadFileOutlined } from '@mui/icons-material';
import { editReport, getReport, listReports } from '../../api/reports';
import type { PatientReport, ReportCategory, ReportFields, ReportPage } from '../../api/reports';
import ReportFieldsForm from '../components/ReportFieldsForm';
import { fieldsOf, reportCategories } from '../../state/reportFields';
import ReportOriginal from '../components/ReportOriginal';
import ReportUploadDialog from '../components/ReportUploadDialog';
import ReportProcessingPanel from '../components/ReportProcessingPanel';
import ReportReviewPanel from '../components/ReportReviewPanel';
import ReportCaseLinksPanel from '../components/ReportCaseLinksPanel';
import ReportLifecycleControl from '../components/ReportLifecycleControl';
import { reviewLabels } from '../../state/reportReview';
import { carePalette } from '../../theme';

const panel = { p: { xs: 2.5, sm: 3 }, minWidth: 0 };
const timestamp = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
function processingLabel(report: PatientReport) {
  if (report.ai_status === 'completed') return 'AI已整理，待核对';
  if (['queued', 'processing'].includes(report.ai_status || '')) return 'AI整理中';
  if (report.ai_status === 'failed') return 'AI整理失败';
  if (report.extraction_status === 'completed') return '文字已识别';
  if (['queued', 'processing'].includes(report.extraction_status)) return '本地识别中';
  if (report.extraction_status === 'failed') return '本地识别失败';
  return '未整理';
}
function ReportDetail({ id }: { id: string }) {
  const navigate = useNavigate();
  const [report, setReport] = useState<PatientReport | null>(null);
  const [fields, setFields] = useState<ReportFields | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState('info');
  const [latest, setLatest] = useState<PatientReport | null>(null);
  useEffect(() => {
    let current = true;
    getReport(id).then(data => { if (current) { setReport(data); setFields(fieldsOf(data)); setError(''); } })
      .catch(failure => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [id, reload]);
  async function save() {
    if (!report || !fields) return;
    setBusy(true); setNotice(''); setError('');
    try {
      const updated = await editReport(id, fields, report.revision);
      setReport(updated); setFields(fieldsOf(updated)); setLatest(null); setNotice('报告信息已保存');
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function compareLatest() {
    try { setLatest(await getReport(id)); } catch (failure) { setError((failure as Error).message); }
  }
  return <>
    <Button component={RouterLink} to="/reports" startIcon={<ArrowBackRounded />} sx={{ mb: 2 }}>返回报告列表</Button>
    {!report || !fields ? error ? <><Alert severity="error" action={<Button onClick={() => setReload(value => value + 1)}>重试</Button>}>{error}</Alert><Button component={RouterLink} to="/reports?archive=trash" sx={{ mt: 1 }}>前往回收站</Button></> : <Skeleton height={350} /> : <>
      <Typography component="h1" variant="h5" sx={{ mb: 1, overflowWrap: 'anywhere' }}>{report.title}</Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap' }}><Chip label="已归档" size="small" /><Chip label={`原件版本 ${report.source_version}`} size="small" /><Chip label={reviewLabels[report.review_status] || '待本人核对'} size="small" /></Stack>
      <ReportLifecycleControl report={report} onRefresh={() => navigate('/reports')} onChanged={result => navigate(result.workspace?.report.archive_status === 'trash' || result.deleted ? '/reports?archive=trash' : '/reports')} />
      {notice && <Alert severity="success" sx={{ mb: 2 }}>{notice}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button onClick={compareLatest}>对照最新版本</Button>}>{error} 本页填写仍保留。</Alert>}
      {latest && <Card variant="outlined" sx={{ ...panel, mb: 2, boxShadow: 'none' }}>
        <Typography component="h2" variant="subtitle1">服务端最新信息（版本 {latest.revision}）</Typography>
        <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', my: 1 }}>{latest.title} · {reportCategories[latest.category]}{`\n机构：${latest.institution || '未填写'}\n检查日期：${latest.examination_date || '未填写'}\n报告日期：${latest.report_date || '未填写'}\n备注：${latest.notes || '未填写'}`}</Typography>
        <Button disabled={busy} onClick={() => { setReport(latest); setFields(fieldsOf(latest)); setLatest(null); setError(''); }}>放弃本页未保存填写，载入最新信息</Button>
      </Card>}
      <Tabs variant="scrollable" scrollButtons="auto" value={tab} onChange={(_, value) => setTab(value)} aria-label="报告详情内容" sx={{ display: { xs: 'flex', md: 'none' }, mb: 2 }}>
        <Tab label="报告信息" value="info" /><Tab label="查看原件" value="original" /><Tab label="整理报告" value="processing" /><Tab label="人工核对" value="review" />
      </Tabs>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1.2fr) minmax(0, 1fr)' }, gap: 2.5 }}>
        <Card sx={{ ...panel, display: { xs: tab === 'original' ? 'block' : 'none', md: 'block' }, alignSelf: 'start',
          position: { md: 'sticky' }, top: { md: 16 }, maxHeight: { md: 'calc(100dvh - 104px)' }, overflow: { md: 'auto' } }}><ReportOriginal report={report} /></Card>
        <Card component="section" sx={{ ...panel, display: { xs: tab !== 'original' ? 'block' : 'none', md: 'block' } }}>
          <Box sx={{ display: { xs: tab === 'info' ? 'block' : 'none', md: 'block' } }}>
          <Typography component="h2" variant="h6" sx={{ mb: 2 }}>报告信息</Typography>
          <ReportFieldsForm value={fields} onChange={setFields} disabled={busy} />
          <Button sx={{ mt: 2 }} variant="contained" disabled={busy || !fields.title.trim()} onClick={save}>{busy ? '保存中' : '保存报告信息'}</Button>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>来源：患者上传 · {report.file_count} 个文件 / {report.page_count} 页</Typography>
          <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>归档：{timestamp(report.created_at)} · 更新：{timestamp(report.updated_at)}（北京时间）</Typography>
          <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>信息版本 {report.revision} · 原件版本 {report.source_version} · 本人声明归属，不等于医生审核</Typography>
          <ReportCaseLinksPanel report={report} />
          </Box>
          <Box sx={{ display: { xs: tab === 'processing' ? 'block' : 'none', md: 'block' } }}><ReportProcessingPanel report={report} /></Box>
          <Box sx={{ display: { xs: tab === 'review' ? 'block' : 'none', md: 'block' } }}><ReportReviewPanel report={report} onSaved={() => {
            getReport(id).then(setReport).catch(failure => setError(failure.message));
          }} /></Box>
        </Card>
      </Box>
    </>}
  </>;
}

function ReportList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const isTrash = searchParams.get('archive') === 'trash';
  const [data, setData] = useState<ReportPage | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  useEffect(() => {
    let current = true;
    listReports({ page, search, archive: isTrash ? 'trash' : 'active', category: ['lab', 'imaging', 'other'].includes(category) ? category as ReportCategory : undefined, pending_only: !isTrash && category === 'pending' })
      .then(result => { if (current) { setData(result); setError(''); setLoading(false); } })
      .catch(failure => { if (current) { setError(failure.message); setLoading(false); } });
    return () => { current = false; };
  }, [page, search, category, reload, isTrash]);
  const refresh = () => { setLoading(true); setReload(value => value + 1); };
  return <>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 3, justifyContent: 'space-between' }}>
      <Box><Typography component="h1" variant="h5" sx={{ mb: 1 }}>{isTrash ? '检查报告回收站' : '检查报告'}</Typography><Typography color="text.secondary">{isTrash ? '可以恢复原件与核对历史；彻底删除需要单独确认。' : '保存本人的检查资料，随时查询与对照。'}</Typography></Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Button onClick={() => { setSearchParams(isTrash ? {} : { archive: 'trash' }); setPage(1); setCategory('all'); setSearch(''); setSearchInput(''); setLoading(true); }}>{isTrash ? '返回已归档报告' : `回收站（${data?.stats.trashed ?? 0}）`}</Button>
        {!isTrash && <Button variant="contained" startIcon={<UploadFileOutlined />} onClick={() => setUploadOpen(true)}>上传检查报告</Button>}
      </Stack>
    </Stack>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(3, minmax(0, 1fr))' }, gap: 2, mb: 3 }}>
      {[['已归档报告', data?.stats.archived, '份'], ['待本人核对', data?.stats.pending_review, '份'], ['最近检查日期', data?.stats.latest_examination_date || '未填写', '']].map(([label, value, unit]) => <Card key={label} sx={panel}>
        <Typography color="text.secondary" variant="body2">{label}</Typography>
        {loading ? <Skeleton height={55} /> : <Typography sx={{ fontSize: label === '最近检查日期' ? 24 : 32, my: 1, fontWeight: 600 }}>{error ? '—' : value} <Box component="span" sx={{ fontSize: 14, color: carePalette.muted }}>{error ? '' : unit}</Box></Typography>}
      </Card>)}
    </Box>
    {isTrash && <Alert severity="info" sx={{ mb: 2 }}>回收站不自动到期清理。这里的报告不会用于新的整理或病例引用；恢复不会重新发送文字或恢复关联。</Alert>}
    <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} sx={{ mb: 3, alignItems: { lg: 'center' } }}>
      <Tabs variant="scrollable" scrollButtons="auto" value={category} onChange={(_, value) => { setCategory(value); setPage(1); setLoading(true); }} aria-label="报告筛选" sx={{ minWidth: 0, flex: 1 }}>
        <Tab label="全部报告" value="all" /><Tab label="检验报告" value="lab" /><Tab label="影像报告" value="imaging" /><Tab label="其他" value="other" />{!isTrash && <Tab label="待本人核对" value="pending" />}
      </Tabs>
      <Box component="form" onSubmit={event => { event.preventDefault(); setSearch(searchInput.trim()); setPage(1); refresh(); }} sx={{ display: 'flex', gap: 1, minWidth: 0 }}>
        <TextField size="small" label="搜索名称、医院或日期" value={searchInput} onChange={event => setSearchInput(event.target.value)} slotProps={{ htmlInput: { maxLength: 200 } }} sx={{ flex: 1 }} />
        <Button type="submit">搜索</Button>
      </Box>
    </Stack>
    {error ? <Alert severity="error" action={<Button onClick={refresh}>重试</Button>}>{error}</Alert> : loading ? <Skeleton height={300} /> : data?.items.length ? <>
      <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>共找到 {data.total} 份报告</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2.5 }}>
        {data.items.map(report => <Card key={report.id} component="article" sx={panel}>
          <Stack direction="row" sx={{ mb: 2, justifyContent: 'space-between' }}><DescriptionOutlined sx={{ color: carePalette.primary }} /><Chip size="small" label={reviewLabels[report.review_status] || '待本人核对'} /></Stack>
          <Typography component="h2" variant="h6" sx={{ overflowWrap: 'anywhere', mb: 1 }}>{report.title}</Typography>
          <Typography color="text.secondary" variant="body2">检查日期：{report.examination_date || '未填写'} · {reportCategories[report.category]}</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 1, overflowWrap: 'anywhere' }}>{report.institution || '机构未填写'}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>{isTrash ? '已移入回收站' : `已归档 · ${processingLabel(report)}`} · {report.file_count} 个文件 / {report.page_count} 页</Typography>
          <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>更新：{timestamp(report.updated_at)}（北京时间）</Typography>
          {isTrash ? <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>移除：{report.trashed_at ? timestamp(report.trashed_at) : '未填写'}（北京时间）</Typography> : <Button component={RouterLink} to={`/reports/${report.id}`} endIcon={<ArrowForwardRounded />} sx={{ mt: 2 }}>查看报告</Button>}
          <ReportLifecycleControl report={report} onChanged={refresh} onRefresh={refresh} />
        </Card>)}
      </Box>
      {data.total > data.limit && <Pagination count={Math.ceil(data.total / data.limit)} page={page} onChange={(_, value) => { setPage(value); setLoading(true); }} sx={{ mt: 3 }} />}
    </> : <Card sx={{ ...panel, py: 6, textAlign: 'center' }}>
      <DescriptionOutlined sx={{ fontSize: 40, mb: 2, color: carePalette.muted }} />
      <Typography component="h2" variant="h6" sx={{ mb: 1 }}>{search || category !== 'all' ? '没有符合条件的报告' : isTrash ? '回收站为空' : '还没有检查报告'}</Typography>
      <Typography color="text.secondary">{search || category !== 'all' ? '可以调整筛选或搜索内容。' : isTrash ? '移除的报告会在这里显示。' : '上传图片或 PDF，无需先创建问诊记录。'}</Typography>
      {(search || category !== 'all') && <Button sx={{ mt: 2 }} onClick={() => { setSearchInput(''); setSearch(''); setCategory('all'); setPage(1); refresh(); }}>清除筛选</Button>}
    </Card>}
    <ReportUploadDialog open={uploadOpen} onClose={() => { setUploadOpen(false); refresh(); }} onResume={() => setUploadOpen(true)} onSaved={refresh} />
  </>;
}
export default function PatientReportsPage() {
  const { reportId } = useParams();
  return <Box sx={{ maxWidth: 1440, mx: 'auto', p: { xs: 2, sm: 3, lg: 4 } }}>{reportId ? <ReportDetail key={reportId} id={reportId} /> : <ReportList />}</Box>;
}
