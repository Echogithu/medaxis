import { useEffect, useId, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Container,
  Avatar, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControl, Grid, IconButton, InputLabel, MenuItem, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import SaveIcon from '@mui/icons-material/Save';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import HealthMeasurementsPanel from '../components/HealthMeasurementsPanel';
import { getProfile, ProfileSaveError, updateProfile } from '../../api/patient';
import type { DiseaseRecord, MedicationRecord, PatientProfile, ProfileSection, RecordMetadata, RecordState } from '../../api/patient';
import { pageHeader } from '../../styles/sxUtils';
import { useDemoMode } from '../../state/demoMode';
import { carePalette } from '../../theme';

const STATES: Record<RecordState, string> = { present: '有记录', none: '明确无', unknown: '未知', not_recorded: '未填写' };
const tagTones = {
  teal: { bgcolor: '#ccfbf1', color: '#115e59' },
  blue: { bgcolor: '#eff6ff', color: '#1d4ed8' },
  amber: { bgcolor: '#fff7ed', color: '#9a3412' },
  rose: { bgcolor: '#fff1f2', color: '#be123c' },
  slate: { bgcolor: '#f1f5f9', color: '#475569' },
};
const stateTones = { present: tagTones.teal, none: tagTones.blue, unknown: tagTones.amber, not_recorded: tagTones.slate };
const severityTones = { unknown: tagTones.slate, mild: tagTones.teal, moderate: tagTones.amber, severe: tagTones.rose };
const SEVERITIES: Record<NonNullable<DiseaseRecord['severity']>, string> = { unknown: '未知', mild: '轻度', moderate: '中度', severe: '重度' };
const COMMON_DISEASES = [
  { code: 'E11', name: '2型糖尿病' }, { code: 'I10', name: '原发性高血压' },
  { code: 'I25', name: '冠心病' }, { code: 'I50', name: '慢性心力衰竭' },
  { code: 'I48', name: '心房颤动' }, { code: 'I63', name: '脑梗死(中风)' },
  { code: 'E78', name: '高脂血症' }, { code: 'J44', name: '慢阻肺(COPD)' },
  { code: 'J45', name: '支气管哮喘' }, { code: 'N18', name: '慢性肾病(CKD)' },
  { code: 'K76.0', name: '脂肪肝' }, { code: 'B18.1', name: '慢性乙型肝炎' },
  { code: 'E05', name: '甲亢' }, { code: 'E03', name: '甲减' },
  { code: 'M81', name: '骨质疏松' }, { code: 'M06', name: '类风湿关节炎' },
  { code: 'M17', name: '膝骨关节炎' }, { code: 'G20', name: '帕金森病' },
  { code: 'F32', name: '抑郁症' }, { code: 'F41', name: '焦虑障碍' },
];
const buttonStyle = { borderRadius: 2, textTransform: 'none', color: carePalette.primary, borderColor: carePalette.primary };

function todayInProfileTimezone() {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' });
}

function sourceText(meta?: RecordMetadata) {
  const source = meta?.source === 'patient_reported' ? '患者自报' : meta?.source === 'legacy_record' ? '历史记录，来源未记录' : '来源未记录';
  const date = meta?.updated_at ? new Date(meta.updated_at) : null;
  const time = date && !Number.isNaN(date.getTime()) ? date.toLocaleString('zh-CN') : '未记录';
  return `${source} · 更新时间：${time}`;
}

function sectionState(profile: PatientProfile, section: ProfileSection): RecordState {
  const records = section === 'allergies' ? profile.allergies : section === 'conditions' ? profile.chronic_diseases : profile.medications;
  return profile.section_states?.[section] ?? (records?.length ? 'present' : 'not_recorded');
}

function SectionHeading({ title, section, profile, editing, onChange }: {
  title: string; section: ProfileSection; profile: PatientProfile; editing: boolean;
  onChange: (section: ProfileSection, state: RecordState) => void;
}) {
  const stateLabelId = useId();
  return <Box sx={{ mb: 2 }}>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ justifyContent: 'space-between', mb: 0.5 }}>
      <Typography variant="h6" sx={{ color: carePalette.ink, fontWeight: 600 }}>{title}</Typography>
      {editing ? <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel id={stateLabelId}>{title}记录状态</InputLabel>
        <Select labelId={stateLabelId} label={`${title}记录状态`} value={sectionState(profile, section)} onChange={event => onChange(section, event.target.value as RecordState)}>
          {Object.entries(STATES).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
        </Select>
      </FormControl> : <Chip size="small" label={STATES[sectionState(profile, section)]} sx={{ ...stateTones[sectionState(profile, section)], alignSelf: 'flex-start' }} />}
    </Stack>
    <Typography variant="caption" color="text.secondary">{sourceText(profile.section_metadata?.[section])}</Typography>
  </Box>;
}

export default function HealthProfilePage() {
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [draft, setDraft] = useState<PatientProfile | null>(null);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const demo = useDemoMode();
  const reportReady = !(demo?.enabled && !demo.report_center_ready);
  const reportPath = reportReady ? '/reports' : '/cases';
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [reload, setReload] = useState(0);
  const [newAllergy, setNewAllergy] = useState('');
  const [measurementOpen, setMeasurementOpen] = useState(false);

  useEffect(() => {
    let current = true;
    getProfile().then(data => {
      if (current) { setProfile(data); setDraft(data); setLoadError(''); }
    }).catch(() => {
      if (current) setLoadError('档案加载失败，请检查网络或重新登录后重试。');
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [reload]);

  function reloadProfile() {
    setEditing(false); setLoading(true); setLoadError(''); setSaveError(''); setConflict(false);
    setReload(value => value + 1);
  }

  function changeState(section: ProfileSection, state: RecordState) {
    setDraft(previous => previous ? { ...previous, section_states: { ...previous.section_states, [section]: state } } : previous);
  }

  function changeDisease(index: number, changes: Partial<DiseaseRecord>) {
    setDraft(previous => previous ? { ...previous, chronic_diseases: previous.chronic_diseases?.map((item, i) => i === index ? { ...item, ...changes } : item) } : previous);
  }

  function changeMedication(index: number, changes: Partial<MedicationRecord>) {
    setDraft(previous => previous ? { ...previous, medications: previous.medications?.map((item, i) => i === index ? { ...item, ...changes } : item) } : previous);
  }

  function addDisease() {
    setDraft(previous => previous ? { ...previous,
      chronic_diseases: [...(previous.chronic_diseases ?? []), { id: crypto.randomUUID(), name: '', code: '', category: 'chronic', severity: 'unknown', diagnosed_date: null, notes: '' }],
      section_states: { ...previous.section_states, conditions: 'present' },
    } : previous);
  }

  function removeRecord(section: ProfileSection, index: number) {
    setDraft(previous => {
      if (!previous) return previous;
      const key = section === 'allergies' ? 'allergies' : section === 'conditions' ? 'chronic_diseases' : 'medications';
      const records = (previous[key] ?? []).filter((_, i) => i !== index);
      return { ...previous, [key]: records, section_states: { ...previous.section_states, [section]: records.length ? 'present' : 'not_recorded' } };
    });
  }

  async function save() {
    if (!draft || !profile || saving) return;
    setSaveError(''); setConflict(false);
    const groups = [['allergies', draft.allergies], ['conditions', draft.chronic_diseases], ['medications', draft.medications]] as const;
    if (groups.some(([section, items]) => (sectionState(draft, section) === 'present') !== Boolean(items?.length))) {
      setSaveError('有条目时请选择“有记录”；无条目时请选择“明确无”“未知”或“未填写”。'); return;
    }
    if (draft.chronic_diseases?.some(item => !item.name.trim()) || draft.medications?.some(item => !item.name.trim())) {
      setSaveError('请填写疾病和药物名称，或删除空白条目；当前修改仍保留。'); return;
    }
    if (draft.chronic_diseases?.some(item => item.diagnosed_date && item.diagnosed_date > todayInProfileTimezone())) {
      setSaveError('确诊日期不能晚于今天；当前修改仍保留。'); return;
    }
    setSaving(true);
    try {
      const updated = await updateProfile({
        name: draft.name, phone: draft.phone, gender: draft.gender, height: draft.height, weight: draft.weight,
        allergies: draft.allergies ?? [], chronic_diseases: draft.chronic_diseases ?? [], medications: draft.medications ?? [],
        section_states: Object.fromEntries(groups.map(([section]) => [section, sectionState(draft, section)])),
        expected_revision: profile.revision ?? 0,
      });
      setProfile(updated); setDraft(updated); setEditing(false); setNewAllergy('');
    } catch (error) {
      const isConflict = error instanceof ProfileSaveError && [409, 428].includes(error.status);
      setConflict(isConflict);
      setSaveError(isConflict ? '档案已在其他位置更新。本次修改未保存且草稿仍保留，请先复制需要保留的内容，再重新加载并核对。' : '保存失败，请检查记录内容或网络后重试；当前修改仍保留。');
    } finally { setSaving(false); }
  }

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}><CircularProgress /></Box>;
  if (loadError || !profile || !draft) return <Box sx={{ textAlign: 'center', py: 8 }}>
    <Alert severity="error" sx={{ mb: 2 }}>{loadError || '未能读取档案'}</Alert>
    <Button onClick={reloadProfile}>重试</Button>
  </Box>;
  const display = editing ? draft : profile;

  const editor = <>
    {saveError && <Alert severity="error" sx={{ mb: 2 }} action={conflict ? <Button onClick={reloadProfile}>重新加载并退出编辑</Button> : undefined}>{saveError}</Alert>}
    <Box component="fieldset" disabled={saving} sx={{ p: 0, m: 0, border: 0, minWidth: 0, display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'repeat(2, minmax(0, 1fr))' }, gap: 2.5, alignItems: 'start', '& > .MuiCard-root': { mb: 0 }, '& > .MuiCard-root:first-of-type, & > .MuiCard-root:last-of-type': { gridColumn: '1 / -1' } }}>
      <Card sx={{ mb: 2, borderRadius: 3 }}><CardContent>
        <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>基础信息</Typography>
        <Grid container spacing={2}>
          {([{ field: 'name', label: '姓名' }, { field: 'phone', label: '手机' }] as const).map(({ field, label }) => <Grid key={field} size={{ xs: 12, sm: 6 }}>
            {editing ? <TextField fullWidth label={label} value={display[field] ?? ''} onChange={event => setDraft(previous => previous ? { ...previous, [field]: event.target.value } : previous)} /> : <><Typography variant="caption" color="text.secondary">{label}</Typography><Typography>{display[field] || '未填写'}</Typography></>}
          </Grid>)}
          <Grid size={{ xs: 12, sm: 6 }}><Typography variant="caption" color="text.secondary">邮箱</Typography><Typography>{display.email}</Typography></Grid>
          <Grid size={{ xs: 12, sm: 6 }}><Typography variant="caption" color="text.secondary">登记年龄</Typography><Typography>{display.age_years != null ? `${display.age_years}岁${display.age_months ? ` ${display.age_months}个月` : ''}` : '未填写'}</Typography></Grid>
          <Grid size={{ xs: 12, sm: 6 }}>{editing ? <FormControl fullWidth><InputLabel id="profile-gender-label">性别</InputLabel><Select labelId="profile-gender-label" label="性别" value={display.gender || ''} onChange={event => setDraft(previous => previous ? { ...previous, gender: event.target.value || null } : previous)}>
            <MenuItem value="">未知／未填写</MenuItem><MenuItem value="male">男</MenuItem><MenuItem value="female">女</MenuItem>
          </Select></FormControl> : <><Typography variant="caption" color="text.secondary">性别</Typography><Typography>{({ male: '男', female: '女' } as Record<string, string>)[display.gender ?? ''] || display.gender || '未知／未填写'}</Typography></>}</Grid>
          {([{ field: 'height', label: '身高 (cm)' }, { field: 'weight', label: '体重 (kg)' }] as const).map(({ field, label }) => <Grid key={field} size={{ xs: 12, sm: 6 }}>
            {editing ? <TextField fullWidth type="number" label={label} value={display[field] ?? ''} slotProps={{ htmlInput: { step: 1 } }} onChange={event => setDraft(previous => previous ? { ...previous, [field]: event.target.value === '' ? null : Number(event.target.value) } : previous)} /> : <><Typography variant="caption" color="text.secondary">{label}</Typography><Typography>{display[field] ?? '未填写'}</Typography></>}
          </Grid>)}
        </Grid>
      </CardContent></Card>
      <Card sx={{ mb: 2, borderRadius: 3 }}><CardContent>
        <SectionHeading title="过敏史" section="allergies" profile={display} editing={editing} onChange={changeState} />
        <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>{display.allergies?.map((item, index) => <Chip key={`${item}-${index}`} label={item} onDelete={editing ? () => removeRecord('allergies', index) : undefined}
          sx={{ ...tagTones.rose, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { py: 0.75, whiteSpace: 'normal', overflowWrap: 'anywhere' } }} />)}</Stack>
        {editing && <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
          <TextField size="small" label="过敏源" value={newAllergy} onChange={event => setNewAllergy(event.target.value)} sx={{ flex: 1 }} />
          <Button startIcon={<AddIcon />} onClick={() => {
            const value = newAllergy.trim(); if (!value) return;
            setDraft(previous => previous ? { ...previous, allergies: [...new Set([...(previous.allergies ?? []), value])], section_states: { ...previous.section_states, allergies: 'present' } } : previous);
            setNewAllergy('');
          }}>添加过敏源</Button>
        </Box>}
      </CardContent></Card>
      <Card sx={{ mb: 2, borderRadius: 3 }}><CardContent>
        <SectionHeading title="慢性病／特殊疾病" section="conditions" profile={display} editing={editing} onChange={changeState} />
        <Stack spacing={2}>{display.chronic_diseases?.map((item, index) => <Box key={item.id ?? index} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
          {editing ? <>
            <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 2 }}><Typography>疾病记录 {index + 1}</Typography><IconButton aria-label={`删除疾病记录 ${index + 1}`} onClick={() => removeRecord('conditions', index)}><DeleteIcon /></IconButton></Stack>
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="疾病名称" value={item.name} onChange={event => changeDisease(index, { name: event.target.value, code: '' })} /></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth><InputLabel id={`disease-common-${index}`}>常见疾病（可选）</InputLabel><Select labelId={`disease-common-${index}`} label="常见疾病（可选）" value={COMMON_DISEASES.some(option => option.code === item.code) ? item.code : ''} onChange={event => {
                const option = COMMON_DISEASES.find(value => value.code === event.target.value);
                changeDisease(index, option ? { code: option.code, name: option.name } : { code: '' });
              }}><MenuItem value="">自行填写</MenuItem>{COMMON_DISEASES.map(option => <MenuItem key={option.code} value={option.code}>{option.name}</MenuItem>)}</Select></FormControl></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth><InputLabel id={`disease-category-${index}`}>疾病分类</InputLabel><Select labelId={`disease-category-${index}`} label="疾病分类" value={item.category ?? 'chronic'} onChange={event => changeDisease(index, { category: event.target.value as DiseaseRecord['category'] })}><MenuItem value="chronic">慢性病</MenuItem><MenuItem value="special">特殊疾病</MenuItem></Select></FormControl></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth><InputLabel id={`disease-severity-${index}`}>严重程度</InputLabel><Select labelId={`disease-severity-${index}`} label="严重程度" value={item.severity ?? 'unknown'} onChange={event => changeDisease(index, { severity: event.target.value as DiseaseRecord['severity'] })}>{Object.entries(SEVERITIES).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}</Select></FormControl></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth type="date" label="确诊日期（可留空）" slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: todayInProfileTimezone() } }} value={item.diagnosed_date ?? ''} onChange={event => changeDisease(index, { diagnosed_date: event.target.value || null })} /></Grid>
              <Grid size={{ xs: 12 }}><TextField fullWidth multiline minRows={2} label="备注说明" value={item.notes ?? ''} slotProps={{ htmlInput: { maxLength: 1000 } }} onChange={event => changeDisease(index, { notes: event.target.value })} /></Grid>
            </Grid>
          </> : <>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5, mb: 1 }}><Typography sx={{ fontWeight: 600 }}>{item.name}</Typography><Chip size="small" label={item.category === 'special' ? '特殊疾病' : '慢性病'} sx={tagTones.blue} /><Chip size="small" label={`严重程度：${SEVERITIES[item.severity ?? 'unknown']}`} sx={severityTones[item.severity ?? 'unknown']} /></Stack>
            <Typography variant="body2">确诊日期：{item.diagnosed_date || '未知／未填写'}</Typography>
            {item.notes && <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.notes}</Typography>}
          </>}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>{sourceText(item)}</Typography>
        </Box>)}</Stack>
        {editing && <Button startIcon={<AddIcon />} onClick={addDisease} sx={{ mt: 2 }}>添加疾病</Button>}
      </CardContent></Card>
      <Card id="profile-medications-editor" sx={{ borderRadius: 3 }}><CardContent>
        <SectionHeading title="用药记录" section="medications" profile={display} editing={editing} onChange={changeState} />
        <Stack spacing={2}>{display.medications?.map((item, index) => <Box key={item.id ?? index} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
          {editing ? <>
            <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 2 }}><Typography>用药记录 {index + 1}</Typography><IconButton aria-label={`删除用药记录 ${index + 1}`} onClick={() => removeRecord('medications', index)}><DeleteIcon /></IconButton></Stack>
            <Grid container spacing={2}>
              {([{ field: 'name', label: '药物名称' }, { field: 'dosage', label: '剂量' }, { field: 'frequency', label: '频率' }] as const).map(({ field, label }) => <Grid key={field} size={{ xs: 12, sm: 6 }}><TextField fullWidth label={label} value={item[field]} onChange={event => changeMedication(index, { [field]: event.target.value })} /></Grid>)}
              <Grid size={{ xs: 12, sm: 6 }}><FormControl fullWidth><InputLabel id={`medication-status-${index}`}>用药状态</InputLabel><Select labelId={`medication-status-${index}`} label="用药状态" value={item.status ?? 'active'} onChange={event => changeMedication(index, { status: event.target.value as MedicationRecord['status'] })}><MenuItem value="active">有效（正在使用）</MenuItem><MenuItem value="stopped">已停用</MenuItem></Select></FormControl></Grid>
              <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth type="date" label="开始日期（可留空）" slotProps={{ inputLabel: { shrink: true } }} value={item.start_date ?? ''} onChange={event => changeMedication(index, { start_date: event.target.value || null })} /></Grid>
            </Grid>
          </> : <>
            <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap', gap: 0.5 }}><Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere', minWidth: 0 }}>{item.name}</Typography><Chip size="small" label={item.status === 'stopped' ? '已停用' : '有效（正在使用）'} sx={item.status === 'stopped' ? tagTones.slate : tagTones.teal} /></Stack>
            <Typography variant="body2">剂量：{item.dosage || '未填写'} · 频率：{item.frequency || '未填写'}</Typography>
            <Typography variant="body2">开始日期：{item.start_date || '未知／未填写'}</Typography>
          </>}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>{sourceText(item)}</Typography>
        </Box>)}</Stack>
        {editing && <Button startIcon={<AddIcon />} sx={{ mt: 2 }} onClick={() => setDraft(previous => previous ? { ...previous,
          medications: [...(previous.medications ?? []), { id: crypto.randomUUID(), name: '', dosage: '', frequency: '', status: 'active', start_date: null }],
          section_states: { ...previous.section_states, medications: 'present' },
        } : previous)}>添加药物</Button>}
      </CardContent></Card>
    </Box>
    {editing && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>请按原处方填写用药；标记停用仅记录事实。</Typography>}
  </>;
  const openEditor = (medications = false) => {
    setDraft(profile); setEditing(true); setSaveError(''); setConflict(false); setNewAllergy('');
    if (medications) setTimeout(() => document.getElementById('profile-medications-editor')?.scrollIntoView({ block: 'start' }), 250);
  };
  const age = profile.age_years != null ? `${profile.age_years}岁${profile.age_months ? ` ${profile.age_months}个月` : ''}` : '年龄未填写';
  const gender = ({ male: '男', female: '女' } as Record<string, string>)[profile.gender ?? ''] || '性别未填写';
  return <Box sx={{ pb: 6 }}><Container maxWidth="lg">
    <Box sx={{ ...pageHeader, flexWrap: 'wrap', gap: 2 }}>
      <Box sx={{ flex: 1, minWidth: 180 }}><Typography component="h1" variant="h5">健康档案</Typography><Typography variant="caption">{profile.updated_at ? `档案更新时间：${new Date(profile.updated_at).toLocaleString('zh-CN')}` : '档案更新时间未记录'}</Typography></Box>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}><Button variant="outlined" startIcon={<MonitorHeartOutlinedIcon />} sx={buttonStyle} onClick={() => setMeasurementOpen(true)}>记录健康指标</Button><Button variant="contained" startIcon={<EditIcon />} onClick={() => openEditor()}>编辑档案</Button></Stack>
    </Box>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0,1fr)', lg: 'minmax(0,1.7fr) minmax(300px,1fr)' }, gap: 3, alignItems: 'start', '& .MuiCard-root': { borderRadius: '24px', minWidth: 0 } }}>
      <Stack spacing={3} sx={{ minWidth: 0 }}>
        <Card><Box sx={{ p: 3, display: 'flex', alignItems: 'center', gap: 2.5, background: 'linear-gradient(110deg,#e3f4ee,#f5fbf9)' }}>
          <Avatar variant="rounded" sx={{ width: 72, height: 72, bgcolor: '#fff', color: carePalette.primary, fontSize: 30, borderRadius: '24px' }}>{profile.name?.slice(0, 1) || '我'}</Avatar>
          <Box sx={{ minWidth: 0 }}><Typography component="h2" variant="h5" sx={{ fontSize: 24, overflowWrap: 'anywhere' }}>{profile.name || '姓名未填写'}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{gender} · {age}</Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: .75, mt: 1.25 }}>{profile.chronic_diseases?.map((item, index) => <Chip size="small" key={item.id || index} label={item.name} sx={{ ...tagTones.teal, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { whiteSpace: 'normal', overflowWrap: 'anywhere', py: .5 } }} />)}</Stack>
          </Box>
        </Box><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}>
          <Typography component="h2" variant="h6" sx={{ mb: 2.5 }}>基础信息</Typography>
          <Grid container spacing={2.5}>
            {[['手机', profile.phone || '未填写'], ['邮箱', profile.email], ['登记年龄', age], ['身高', profile.height != null ? `${profile.height} cm` : '未填写'], ['体重', profile.weight != null ? `${profile.weight} kg` : '未填写'], ['性别', gender]].map(([label, value]) => <Grid key={label} size={{ xs: 6, sm: 4 }}><Typography variant="caption">{label}</Typography><Typography sx={{ mt: .5, overflowWrap: 'anywhere' }}>{value}</Typography></Grid>)}
          </Grid><Divider sx={{ my: 3 }} />
          <SectionHeading title="过敏史" section="allergies" profile={profile} editing={false} onChange={changeState} />
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>{profile.allergies?.map((item, index) => <Chip key={`${item}-${index}`} label={item} sx={{ ...tagTones.rose, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { py: .75, whiteSpace: 'normal', overflowWrap: 'anywhere' } }} />)}</Stack>
          <Divider sx={{ my: 3 }} />
          <SectionHeading title="慢性病／特殊疾病" section="conditions" profile={profile} editing={false} onChange={changeState} />
          <Stack spacing={2}>{profile.chronic_diseases?.map((item, index) => <Box key={item.id || index} sx={{ py: 1 }}>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1, alignItems: 'center' }}><Typography sx={{ fontWeight: 600 }}>{item.name}</Typography><Chip size="small" label={item.category === 'special' ? '特殊疾病' : '慢性病'} sx={tagTones.blue} /><Chip size="small" label={`严重程度：${SEVERITIES[item.severity ?? 'unknown']}`} sx={severityTones[item.severity ?? 'unknown']} /></Stack>
            <Typography variant="body2" sx={{ mt: 1 }}>确诊日期：{item.diagnosed_date || '未知／未填写'}</Typography>{item.notes && <Typography variant="body2" sx={{ mt: .5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.notes}</Typography>}
            <Typography variant="caption" sx={{ display: 'block', mt: .75 }}>{sourceText(item)}</Typography>
          </Box>)}</Stack>
        </CardContent></Card>
        <Card><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}>
          <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 1 }}><Box sx={{ flex: 1 }}><SectionHeading title="当前用药清单" section="medications" profile={profile} editing={false} onChange={changeState} /></Box><Button size="small" sx={{ flexShrink: 0 }} onClick={() => openEditor(true)}>编辑清单 →</Button></Stack>
          <Box sx={{ overflowX: 'auto' }}><Table size="small" aria-label="用药清单" sx={{ minWidth: 500, '& td, & th': { py: 1.75, px: 1.25 } }}>
            <TableHead sx={{ bgcolor: '#f6f8f7' }}><TableRow>{['药物名称', '剂量', '频率', '开始日期'].map(label => <TableCell key={label} sx={{ color: carePalette.muted }}>{label}</TableCell>)}</TableRow></TableHead>
            <TableBody>{profile.medications?.map((item, index) => <TableRow key={item.id || index}><TableCell><Typography sx={{ fontWeight: 600 }}>{item.name}</Typography><Chip size="small" label={item.status === 'stopped' ? '已停用' : '有效（正在使用）'} sx={{ mt: .5, ...(item.status === 'stopped' ? tagTones.slate : tagTones.teal) }} /><Typography variant="caption" sx={{ display: 'block', mt: .5 }}>{sourceText(item)}</Typography></TableCell><TableCell>{item.dosage || '未填写'}</TableCell><TableCell>{item.frequency || '未填写'}</TableCell><TableCell>{item.start_date || '未知／未填写'}</TableCell></TableRow>)}</TableBody>
          </Table></Box>
          <Typography variant="caption" sx={{ display: 'block', mt: 2 }}>清单与用药提醒分别管理，请按原处方核对。</Typography>
        </CardContent></Card>
      </Stack>
      <Stack component="aside" spacing={3} sx={{ minWidth: 0 }}>
        <HealthMeasurementsPanel open={measurementOpen} onClose={() => setMeasurementOpen(false)} onOpen={() => setMeasurementOpen(true)} />
        <Card><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}><Typography component="h2" variant="h6" sx={{ mb: 1.5 }}>就诊资料</Typography><Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}><Button component={RouterLink} to={reportPath}>{reportReady ? '检查报告' : '病例附件'} →</Button><Button component={RouterLink} to="/followups">随访记录 →</Button></Stack></CardContent></Card>
      </Stack>
    </Box>
    <Dialog open={editing} onClose={saving ? undefined : () => setEditing(false)} fullWidth maxWidth="md" aria-labelledby="profile-edit-title"><DialogTitle id="profile-edit-title">编辑健康档案</DialogTitle><DialogContent dividers>{editor}</DialogContent><DialogActions sx={{ p: 2.5 }}><Button disabled={saving} onClick={() => setEditing(false)}>取消</Button><Button disabled={saving} variant="contained" startIcon={<SaveIcon />} onClick={() => void save()}>{saving ? '保存中…' : '保存'}</Button></DialogActions></Dialog>
  </Container></Box>;
}
