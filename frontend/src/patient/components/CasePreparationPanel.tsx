import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Link,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyOutlinedIcon from '@mui/icons-material/ContentCopyOutlined';
import {
  createCasePreparation,
  getCasePreparation,
  updateCasePreparation,
} from '../../api/patient';
import type { CasePreparationPackage, PreparationFact } from '../../api/patient';
import { patientText } from '../../state/patientText';
import { getPreparationDraft, preparationFactId, preparationHasChanges, preparationContext, preparationResponse as patientResponseText, preparationSummary, preparationValue as displayValue, setPreparationDraft } from '../../state/casePreparation';

function assertionLabel(status?: PreparationFact['assertion_status']): string {
  if (status === 'denied') return '（患者明确否认）';
  if (status === 'affirmed') return '（患者明确表示有）';
  return '';
}

export default function CasePreparationPanel({ caseId }: { caseId: string }) {
  const [item, setItem] = useState<CasePreparationPackage | null>(null);
  const [history, setHistory] = useState<CasePreparationPackage[]>([]);
  const [confirmedIds, setConfirmedIds] = useState<string[]>([]);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [checklist, setChecklist] = useState<Record<string, 'pending' | 'ready'>>({});
  const [questionsText, setQuestionsText] = useState('');
  const [loadedCaseId, setLoadedCaseId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editingFacts, setEditingFacts] = useState(false);
  const [editingIds, setEditingIds] = useState<string[]>([]);
  const [previousDraftText, setPreviousDraftText] = useState('');

  const hydrate = useCallback((value: CasePreparationPackage | null, older: CasePreparationPackage[], restoreDraft = false) => {
    setItem(value);
    setHistory(older);
    setConfirmedIds(value?.known_facts.filter((fact) => fact.confirmed).map((fact) => fact.id) || []);
    setCorrections(Object.fromEntries((value?.patient_corrections || []).map((entry) => [entry.fact_id, entry.value])));
    setChecklist(Object.fromEntries((value?.preparation_items || []).map((entry) => [entry.id, entry.status])));
    setQuestionsText((value?.patient_questions || []).join('\n'));
    if (value && restoreDraft) {
      const draft = getPreparationDraft(caseId);
      if (draft && draft.version === value.version && draft.revision === value.revision) {
        setConfirmedIds(draft.confirmedIds);
        setCorrections(draft.corrections);
        setChecklist(draft.checklist);
        setQuestionsText(draft.questionsText);
        setNotice('已恢复本次浏览中未保存的修改。');
      } else if (draft) {
        const checklistText = Object.entries(draft.checklist).map(([id, status]) =>
          `${value.preparation_items.find(entry => entry.id === id)?.title || id}：${status === 'ready' ? '已准备' : '待准备'}`).join('\n');
        setPreviousDraftText(`${draft.summaryText}\n\n先前准备清单\n${checklistText}`);
      }
    }
  }, [caseId]);

  useEffect(() => {
    let cancelled = false;
    getCasePreparation(caseId)
      .then((response) => {
        if (cancelled) return;
        hydrate(response.package, response.history, true);
        setError('');
      })
      .catch(() => {
        if (cancelled) return;
        hydrate(null, []);
        setError('就医准备暂时无法读取；已有诊断报告仍可查看。');
      })
      .finally(() => { if (!cancelled) setLoadedCaseId(caseId); });
    return () => { cancelled = true; };
  }, [caseId, hydrate]);

  const loading = loadedCaseId !== caseId;

  const preview = useMemo(
    () => item ? preparationSummary(item, confirmedIds, corrections, questionsText) : '',
    [item, confirmedIds, corrections, questionsText],
  );

  const generate = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await createCasePreparation(caseId);
      const response = await getCasePreparation(caseId);
      hydrate(response.package, response.history);
      setNotice('就诊摘要已保存。');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成失败；原诊断报告未受影响。');
    } finally {
      setBusy(false);
    }
  };

  const dirty = item ? preparationHasChanges(item, confirmedIds, corrections, checklist, questionsText) : false;

  useEffect(() => {
    if (loading || !item || previousDraftText) return;
    setPreparationDraft(caseId, dirty ? {
      version: item.version, revision: item.revision, confirmedIds, corrections, checklist, questionsText, summaryText: preview,
    } : null);
  }, [caseId, loading, item, dirty, confirmedIds, corrections, checklist, questionsText, preview, previousDraftText]);

  useEffect(() => {
    if (!dirty && !previousDraftText) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, previousDraftText]);

  const reloadSaved = async () => {
    setBusy(true);
    setNotice('');
    try {
      const response = await getCasePreparation(caseId);
      hydrate(response.package, response.history, true);
      setError('');
    } catch {
      setError('重新读取失败；填写内容仍保留，请稍后重试。');
    } finally {
      setBusy(false);
    }
  };

  const save = async (): Promise<CasePreparationPackage | null> => {
    if (!item || busy) return null;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const saved = await updateCasePreparation(caseId, item.package_id, {
        expected_revision: item.revision,
        confirmed_fact_ids: confirmedIds,
        patient_corrections: Object.entries(corrections)
          .filter(([, value]) => value.trim())
          .map(([fact_id, value]) => ({ fact_id, value: value.trim() })),
        patient_questions: questionsText.split(/\r?\n/).map(question => question.trim()).filter(Boolean),
        checklist_updates: item.preparation_items.map(entry => ({
          item_id: entry.id, status: checklist[entry.id] || entry.status,
        })),
      });
      hydrate(saved, history);
      if (saved.is_stale) {
        await createCasePreparation(caseId);
        const response = await getCasePreparation(caseId);
        hydrate(response.package, response.history);
        if (!response.package || response.package.is_stale) throw new Error('请更新就诊摘要后再试。');
        setNotice('已保存并更新就诊摘要。');
        return response.package;
      }
      setNotice('已保存确认内容。');
      return saved;
    } catch (cause) {
      setError(cause instanceof Error ? `保存或更新未完成：${cause.message}` : '未保存，请重试；填写内容仍保留在此页面。');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const copyPreview = async () => {
    if (!item || item.is_stale || busy) return;
    const saved = dirty ? await save() : item;
    if (!saved || saved.is_stale) return;
    const text = preparationSummary(saved, saved.known_facts.filter(fact => fact.confirmed).map(fact => fact.id),
      Object.fromEntries(saved.patient_corrections.map(entry => [entry.fact_id, entry.value])),
      saved.patient_questions.join('\n'));
    try {
      await navigator.clipboard.writeText(text);
      setNotice('已复制已保存的摘要到剪贴板。');
    } catch {
      setError('复制失败；可展开完整摘要，手动选择并复制。');
    }
  };

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 3 }}><CircularProgress size={24} /></Box>;

  return (
    <Paper variant="outlined" sx={{ p: { xs: 1.5, md: 2.5 }, borderRadius: 3 }}>
      {error && <Alert severity="error" sx={{ mb: 2 }} action={item &&
        <Button disabled={busy} onClick={() => void reloadSaved()}>重新读取已保存版本</Button>
      }>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }}>{notice}</Alert>}
      {previousDraftText && <Box sx={{ mb: 2 }}>
        <Alert severity="warning">资料已更新。先前未保存的草稿仍保留在这里，请核对后重新填写。</Alert>
        <Accordion disableGutters elevation={0}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>查看先前未保存的草稿</AccordionSummary>
          <AccordionDetails><TextField fullWidth multiline minRows={4} value={previousDraftText}
            label="先前未保存的草稿" slotProps={{ htmlInput: { readOnly: true } }} /></AccordionDetails>
        </Accordion>
        <Button onClick={() => { setPreviousDraftText(''); setPreparationDraft(caseId, null); }}>已核对，继续编辑当前摘要</Button>
      </Box>}
      {!item ? (
        <Stack spacing={1.5}>
          <Typography color="text.secondary">整理本次病情、要带的资料和想问医生的问题。</Typography>
          <Button variant="contained" onClick={() => void generate()} disabled={busy}>
            {busy ? '正在整理…' : '整理就诊摘要'}
          </Button>
        </Stack>
      ) : (
        <Box component="fieldset" disabled={busy || !!previousDraftText} sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}>
          <Stack spacing={3}>
            {item.is_stale && <Alert severity="warning" action={
              <Button onClick={() => void (dirty ? save() : generate())} disabled={busy}>更新就诊摘要</Button>
            }>资料已变化，请先更新摘要再查看建议或复制。</Alert>}

            <Box component="section" aria-label="下一步建议">
              <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>下一步建议</Typography>
              {item.is_stale ? <Typography>更新后查看本次咨询方向。</Typography> : (
                <>
                  <Typography sx={{ fontWeight: 650 }}>
                    {item.department.recommendation ? `可考虑咨询：${item.department.recommendation}`
                      : item.department.status === 'urgent' ? '请优先处理紧急就医'
                        : item.department.status === 'risk_review' ? '先确认就医紧急程度' : '先确认本次咨询方向'}
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{patientText(item.department.reason)}</Typography>
                  {(item.department.risk_notes?.length ?? 0) > 0 && <Alert severity="warning" sx={{ mt: 1 }}>
                    {item.department.risk_notes?.map((note, index) => <Typography key={index} variant="body2">{patientText(note)}</Typography>)}
                  </Alert>}
                  {item.unknown_facts.some(fact => fact.id === 'unknown.department_focus') && (item.department.options?.length ?? 0) > 0 && (
                    <TextField select fullWidth size="small" sx={{ mt: 1.5 }}
                      label="这次主要想咨询哪类问题？"
                      value={corrections['unknown.department_focus'] || ''}
                      onChange={event => setCorrections(current => ({ ...current, 'unknown.department_focus': event.target.value }))}
                      helperText="选择后保存，更新咨询方向。">
                      <MenuItem value="" disabled={item.patient_corrections.some(entry => entry.fact_id === 'unknown.department_focus')}>暂不选择</MenuItem>
                      {item.department.options?.map(option => <MenuItem key={option.id} value={option.label}>{option.label}</MenuItem>)}
                    </TextField>
                  )}
                  {!item.department.guidance_version && <Button sx={{ mt: 1 }} onClick={() => void (dirty ? save() : generate())}>更新科室参考</Button>}
                  <Accordion disableGutters elevation={0} sx={{ mt: 1, '&::before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>查看科室参考依据与适用范围</AccordionSummary>
                    <AccordionDetails>
                      <Typography variant="body2" color="text.secondary">{item.department.scope_note || '当前摘要尚未包含通用科室参考，请更新摘要。'}</Typography>
                      {item.department.references?.map(reference => <Box key={reference.id} sx={{ mt: 1 }}>
                        <Link href={reference.url} target="_blank" rel="noopener noreferrer">{reference.title}</Link>
                        <Typography variant="caption" sx={{ display: 'block' }} color="text.secondary">{reference.published_at ? `发布：${reference.published_at} · ` : ''}核对：{reference.checked_at}</Typography>
                      </Box>)}
                      {(item.department.options?.length ?? 0) > 0 && <Accordion disableGutters elevation={0} sx={{ mt: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>浏览常见科室</AccordionSummary>
                        <AccordionDetails>
                          <Stack spacing={1}>{item.department.options?.map(option => <Typography key={option.id} variant="body2">
                            <b>{option.department}</b>：{option.label}
                          </Typography>)}</Stack>
                        </AccordionDetails>
                      </Accordion>}
                    </AccordionDetails>
                  </Accordion>
                </>
              )}
            </Box>

            <Box component="section" aria-label="出发前准备">
              <Typography variant="h6" sx={{ fontWeight: 700 }}>出发前准备</Typography>
              {item.preparation_items.map(entry => <FormControlLabel key={entry.id}
                sx={{ display: 'flex', alignItems: 'flex-start', mt: 0.5 }}
                control={<Checkbox checked={(checklist[entry.id] || entry.status) === 'ready'}
                  onChange={event => setChecklist(current => ({ ...current, [entry.id]: event.target.checked ? 'ready' : 'pending' }))} />}
                label={<Typography variant="body2">{patientText(entry.title)}</Typography>} />)}
              <TextField fullWidth multiline minRows={2} sx={{ mt: 1.5 }}
                label="希望向医生询问的问题（每行一条）" value={questionsText}
                onChange={event => setQuestionsText(event.target.value)} />
            </Box>

            <Box component="section" aria-label="给医生看的摘要">
              <Typography variant="h6" sx={{ fontWeight: 700 }}>给医生看的摘要</Typography>
              <Typography variant="caption" color="text.secondary">患者自述，供医生核对 · 版本 {item.version}</Typography>
              <Box sx={{ mt: 1, p: 1.5, bgcolor: '#f4f8f6', borderRadius: 2, overflowWrap: 'anywhere' }}>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>{preview.split('\n\n')[1]?.split('\n').slice(0, 6).join('\n')}</Typography>
                <Typography variant="caption" color="text.secondary">摘要节选，完整内容见下方。</Typography>
              </Box>
              {item.unresolved_facts.length > 0 && <Alert severity="warning" sx={{ mt: 1.5 }}>
                有 {item.unresolved_facts.length} 项前后回答待核对，摘要会保留这些差异。
              </Alert>}
              <Button sx={{ mt: 1 }} onClick={() => setEditingFacts(current => !current)} aria-expanded={editingFacts}>
                {editingFacts ? '收起病情核对' : '核对或修改病情'}
              </Button>
              {editingFacts && <Stack spacing={2} sx={{ mt: 1.5 }}>
                <Typography variant="body2" color="text.secondary">只核对你本人的陈述；不确定的信息可保留未知。</Typography>
                {item.known_facts.map(fact => <Box key={fact.id}>
                  <Typography variant="body2"><b>{patientText(fact.label)}：</b>{displayValue(fact.display_value ?? fact.value)}{assertionLabel(fact.assertion_status)}</Typography>
                  {preparationContext(fact).map((context, index) => <Typography key={index} variant="caption" component="div" color="text.secondary">原话语境：{context}</Typography>)}
                  {fact.active === false ? <Typography variant="caption" color="text.secondary">先前原话，已保留并由患者更正取代。</Typography> : <>
                    <FormControlLabel control={<Checkbox checked={confirmedIds.includes(fact.id)}
                      onChange={event => setConfirmedIds(current => event.target.checked ? [...new Set([...current, fact.id])] : current.filter(id => id !== fact.id))} />}
                      label="我确认这项患者陈述准确" />
                    <Button size="small" aria-label={`修改${fact.label}`} onClick={() => setEditingIds(current => current.includes(fact.id) ? current.filter(id => id !== fact.id) : [...current, fact.id])}>有误，修改</Button>
                    {editingIds.includes(fact.id) && (preparationFactId(fact) === 'unknown.department_focus' ? (
                      <TextField select fullWidth size="small" label="修改本次咨询主题"
                        value={corrections['unknown.department_focus'] || ''}
                        onChange={event => setCorrections(current => ({ ...current, 'unknown.department_focus': event.target.value }))}
                        helperText="改为其他、多个问题或不确定，可撤回专科方向。">
                        {item.department.options?.map(option => <MenuItem key={option.id} value={option.label}>{option.label}</MenuItem>)}
                      </TextField>
                    ) : <TextField fullWidth size="small" label="补充更正（保留原记录）"
                      value={corrections[preparationFactId(fact)] || ''}
                      helperText={item.patient_corrections.some(entry => entry.fact_id === preparationFactId(fact)) ? '不确定时填写“不清楚”；空白不删除已保存的更正。' : undefined}
                      onChange={event => setCorrections(current => ({ ...current, [preparationFactId(fact)]: event.target.value }))} />)}
                  </>}
                </Box>)}
                {item.unknown_facts.filter(fact => fact.id !== 'unknown.department_focus').map(fact => <Box key={fact.id}>
                  {patientResponseText(fact) && <Typography variant="caption">{patientText(patientResponseText(fact))}</Typography>}
                  {preparationContext(fact).map((context, index) => <Typography key={index} variant="caption" component="div" color="text.secondary">原话语境：{context}</Typography>)}
                  <TextField fullWidth size="small" label={`${patientText(fact.label)}（${fact.record_state === 'not_recorded' ? '未填写，可补充' : '可保留未知'}）`}
                    value={corrections[fact.id] || ''} onChange={event => setCorrections(current => ({ ...current, [fact.id]: event.target.value }))} />
                </Box>)}
                {item.unresolved_facts.map(fact => <Box key={fact.id}>
                  <Typography variant="body2" sx={{ fontWeight: 650 }}>{patientText(fact.label)} · 前后回答待核对</Typography>
                  {fact.statements.map((statement, index) => <Typography key={statement.source_id} variant="body2" color="text.secondary">
                    第{index + 1}次原话：{patientText(statement.value)}
                    {preparationContext(statement).map((context, contextIndex) => <Typography key={contextIndex} component="span" sx={{ display: 'block' }} variant="caption">原话语境：{context}</Typography>)}
                  </Typography>)}
                  <TextField fullWidth size="small" sx={{ mt: 1 }} label="补充当前说法（保留先前原话）"
                    value={corrections[fact.id] || ''} onChange={event => setCorrections(current => ({ ...current, [fact.id]: event.target.value }))} />
                </Box>)}
              </Stack>}
              <Accordion disableGutters elevation={0} sx={{ mt: 1 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>查看完整摘要</AccordionSummary>
                <AccordionDetails><TextField fullWidth multiline minRows={8} maxRows={20}
                  label="就诊摘要预览" value={preview} slotProps={{ htmlInput: { readOnly: true } }} /></AccordionDetails>
              </Accordion>
              {dirty && <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>有未保存的修改；复制时会先保存。</Typography>}
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 1.5 }}>
                <Button variant="contained" startIcon={<ContentCopyOutlinedIcon />} onClick={() => void copyPreview()}
                  disabled={busy || item.is_stale}>{busy ? '处理中…' : dirty ? '保存并复制摘要' : '复制摘要'}</Button>
                <Button variant="outlined" onClick={() => void save()} disabled={busy || !dirty}>保存准备内容</Button>
              </Stack>
            </Box>

            <Accordion disableGutters elevation={0}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>查看 AI 分析、资料来源与修改历史</AccordionSummary>
              <AccordionDetails>
                <Typography variant="subtitle2">AI 分析（未经医生确认）</Typography>
                {item.summary.ai_inference.map((finding, index) => <Typography key={index} variant="body2">{patientText(finding)}</Typography>)}
                <Typography variant="subtitle2" sx={{ mt: 2 }}>资料来源 · 版本 {item.version} · 修订 {item.revision}</Typography>
                {item.source_index.map(source => <Box key={source.id} sx={{ mt: 1 }}>
                  <Typography variant="body2">{patientText(source.name)}{source.parse_status ? ` · ${source.parse_status}` : ''}</Typography>
                  <Typography variant="caption" color="text.secondary">{patientText(source.note)}</Typography>
                </Box>)}
                {item.unverified_knowledge_sources.map((source, index) => <Typography key={index} variant="body2" sx={{ mt: 1 }}>
                  {patientText(source.name)}：{patientText(source.note)}
                </Typography>)}
                {history.length > 0 && <Box sx={{ mt: 2 }}>
                  <Typography variant="subtitle2">修改历史</Typography>
                  {history.map(previous => <Chip key={previous.package_id} size="small" sx={{ mt: 1, mr: 1 }}
                    label={`版本 ${previous.version}${previous.is_stale ? ' · 已过期' : ''}`} />)}
                </Box>}
              </AccordionDetails>
            </Accordion>
          </Stack>
        </Box>
      )}
    </Paper>
  );
}
