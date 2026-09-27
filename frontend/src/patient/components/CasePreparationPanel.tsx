import { useEffect, useMemo, useState } from 'react';
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
import type { CasePreparationPackage } from '../../api/patient';
import { patientText } from '../../state/patientText';

function displayValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  return JSON.stringify(value, null, 2);
}

function previewText(
  item: CasePreparationPackage,
  confirmedIds: string[],
  corrections: Record<string, string>,
  checklist: Record<string, 'pending' | 'ready'>,
  questionsText: string,
): string {
  const lines = [
    item.summary.case_title,
    '',
    '患者陈述（待本人核对）',
    ...item.known_facts.map((fact) => `- ${fact.label}：${displayValue(fact.value)}${fact.active === false ? '（原始陈述，已被患者更正但仍保留）' : confirmedIds.includes(fact.id) ? '（患者已核对）' : '（待核对）'}`),
    '',
    '未知或待补充',
    ...item.unknown_facts.map((fact) => `- ${fact.label}：未知/待核对`),
    ...Object.entries(corrections).filter(([, value]) => value.trim()).map(([factId, value]) => `- 患者更正 ${[...item.known_facts, ...item.unknown_facts].find(fact => fact.id === factId)?.label || '补充信息'}：${value}（患者自述，未覆盖原始记录）`),
    '',
    'AI 推断（未经医生确认）',
    ...(item.summary.ai_inference.length ? item.summary.ai_inference.map((value) => `- ${value}`) : ['- 暂无']),
    '',
    `科室建议：${item.department.recommendation || '依据不足，暂不能明确推荐'}`,
    item.department.reason,
    '',
    '准备事项',
    ...item.preparation_items.map((entry) => `- [${(checklist[entry.id] || entry.status) === 'ready' ? '已整理' : '待整理'}] ${entry.title}`),
    '',
    '患者希望询问的问题',
    ...(questionsText.split(/\r?\n/).map((question) => question.trim()).filter(Boolean).map((question) => `- ${question}`)),
    '',
    item.summary.disclaimer,
  ];
  return patientText(lines.join('\n'));
}

export default function CasePreparationPanel({ caseId }: { caseId: string }) {
  const [item, setItem] = useState<CasePreparationPackage | null>(null);
  const [history, setHistory] = useState<CasePreparationPackage[]>([]);
  const [confirmedIds, setConfirmedIds] = useState<string[]>([]);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [checklist, setChecklist] = useState<Record<string, 'pending' | 'ready'>>({});
  const [questionsText, setQuestionsText] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const hydrate = (value: CasePreparationPackage | null, older: CasePreparationPackage[]) => {
    setItem(value);
    setHistory(older);
    setConfirmedIds(value?.known_facts.filter((fact) => fact.confirmed).map((fact) => fact.id) || []);
    setCorrections(Object.fromEntries((value?.patient_corrections || []).map((entry) => [entry.fact_id, entry.value])));
    setChecklist(Object.fromEntries((value?.preparation_items || []).map((entry) => [entry.id, entry.status])));
    setQuestionsText((value?.patient_questions || []).join('\n'));
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    getCasePreparation(caseId)
      .then((response) => { if (!cancelled) hydrate(response.package, response.history); })
      .catch(() => { if (!cancelled) setError('就医准备暂时无法读取；已有诊断报告仍可查看。'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [caseId]);

  const preview = useMemo(
    () => item ? previewText(item, confirmedIds, corrections, checklist, questionsText) : '',
    [item, confirmedIds, corrections, checklist, questionsText],
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

  const save = async () => {
    if (!item) return;
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
        patient_questions: questionsText.split(/\r?\n/).map((question) => question.trim()).filter(Boolean),
        checklist_updates: item.preparation_items.map((entry) => ({
          item_id: entry.id,
          status: checklist[entry.id] || 'pending',
        })),
      });
      setItem(saved);
      setNotice(saved.is_stale ? '更正已保存，请更新就诊摘要。' : '已保存确认内容。');
    } catch (cause) {
      setError(cause instanceof Error ? `未保存：${cause.message}` : '未保存，请重试；您填写的内容仍保留在此页面。');
    } finally {
      setBusy(false);
    }
  };

  const copyPreview = async () => {
    try {
      await navigator.clipboard.writeText(preview);
      setNotice('已复制摘要内容到剪贴板。');
    } catch {
      setError('复制失败；预览仍可手动选择并复制。');
    }
  };

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 3 }}><CircularProgress size={24} /></Box>;

  return (
    <Paper variant="outlined" sx={{ mt: 3, p: { xs: 2, md: 3 }, borderRadius: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 750 }}>就医准备</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        确认你的情况，整理就诊时要带的资料和想问医生的问题。
      </Typography>
      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mt: 2 }}>{notice}</Alert>}

      {!item ? (
        <Button sx={{ mt: 2 }} variant="contained" onClick={() => void generate()} disabled={busy}>
          {busy ? '正在整理…' : '整理就诊摘要'}
        </Button>
      ) : (
        <Stack spacing={2} sx={{ mt: 2 }}>
          {item.is_stale && (
            <Alert severity="warning">
              你的资料已变化，请先更新就诊摘要再复制。
            </Alert>
          )}
          <Box>
            <Typography variant="subtitle1" sx={{ mt: 1, fontWeight: 700 }}>科室建议</Typography>
            <Typography sx={{ mt: 0.5 }}>{item.department.recommendation || '依据不足，暂不能明确推荐科室。'}</Typography>
            <Typography variant="body2" color="text.secondary">{patientText(item.department.reason)}</Typography>
          </Box>

          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>确认你的情况</Typography>
            {item.known_facts.map((fact) => (
              <Box key={fact.id} sx={{ mt: 0.5 }}>
                <Typography variant="body2"><b>{fact.label}：</b>{displayValue(fact.value)}</Typography>
                <FormControlLabel
                  control={<Checkbox
                    checked={confirmedIds.includes(fact.id)}
                    disabled={fact.active === false}
                    onChange={(event) => setConfirmedIds((current) => event.target.checked
                      ? [...new Set([...current, fact.id])]
                      : current.filter((id) => id !== fact.id))}
                  />}
                  label={fact.active === false ? '已由新的患者更正取代' : '我确认这项患者陈述准确'}
                />
                {fact.active !== false && <TextField
                  fullWidth
                  size="small"
                  label="如果不准确，请补充更正（保留原记录）"
                  value={corrections[fact.id] || ''}
                  onChange={(event) => setCorrections((current) => ({ ...current, [fact.id]: event.target.value }))}
                />}
              </Box>
            ))}
          </Box>

          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>需要补充的信息</Typography>
            {item.unknown_facts.map((fact) => (
              <TextField
                key={fact.id}
                fullWidth
                size="small"
                sx={{ mt: 1 }}
                label={`${fact.label}（未提供/待补充）`}
                value={corrections[fact.id] || ''}
                onChange={(event) => setCorrections((current) => ({ ...current, [fact.id]: event.target.value }))}
              />
            ))}
          </Box>

          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>准备清单</Typography>
            {item.preparation_items.map((entry) => (
              <FormControlLabel
                key={entry.id}
                sx={{ display: 'flex', alignItems: 'flex-start', mt: 0.5 }}
                control={<Checkbox
                  checked={(checklist[entry.id] || entry.status) === 'ready'}
                  onChange={(event) => setChecklist((current) => ({
                    ...current,
                    [entry.id]: event.target.checked ? 'ready' : 'pending',
                  }))}
                />}
                label={<Box><Typography variant="body2">{entry.title}</Typography><Typography variant="caption" color="text.secondary">{entry.reason}</Typography></Box>}
              />
            ))}
          </Box>

          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>AI 分析（未经医生确认）</Typography>
            {item.summary.ai_inference.length
              ? item.summary.ai_inference.map((finding, index) => <Typography key={index} variant="body2">• {patientText(finding)}</Typography>)
              : <Typography variant="body2" color="text.secondary">暂无结构化 AI 分析。</Typography>}
          </Box>

          <Accordion disableGutters elevation={0}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>资料来源与修改信息</AccordionSummary>
            <AccordionDetails>
              <Typography variant="caption" color="text.secondary">版本 {item.version} · 修订 {item.revision}</Typography>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>来源与资料</Typography>
            {item.source_index.length
              ? item.source_index.map((source) => (
                <Box key={source.id} sx={{ mt: 0.75 }}>
                  <Typography variant="body2"><b>{patientText(source.name)}</b>{source.parse_status ? ` · ${source.parse_status}` : ''}</Typography>
                  <Typography variant="caption" color="text.secondary">{patientText(source.note)}</Typography>
                </Box>
              ))
              : <Typography variant="body2" color="text.secondary">当前没有可列出的来源资料。</Typography>}
            {item.unverified_knowledge_sources.length > 0 && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>报告中的知识来源名称（尚不可核验）</Typography>
                {item.unverified_knowledge_sources.map((source, index) => (
                  <Typography key={`${patientText(source.name)}-${index}`} component="div" variant="caption" color="text.secondary">
                    {patientText(source.name)}：{patientText(source.note)}
                  </Typography>
                ))}
              </Box>
            )}
            </AccordionDetails>
          </Accordion>

          <TextField
            fullWidth
            multiline
            minRows={2}
            label="希望向医生询问的问题（每行一条）"
            value={questionsText}
            onChange={(event) => setQuestionsText(event.target.value)}
          />

          <TextField
            fullWidth
            multiline
            minRows={8}
            label="就诊摘要预览"
            value={preview}
            slotProps={{ htmlInput: { readOnly: true } }}
          />
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button variant="contained" onClick={() => void save()} disabled={busy}>
              {busy ? '保存中…' : '保存确认内容'}
            </Button>
            <Button
              variant="outlined"
              startIcon={<ContentCopyOutlinedIcon />}
              onClick={() => void copyPreview()}
              disabled={item.is_stale}
            >复制摘要</Button>
            {item.is_stale && <Button onClick={() => void generate()} disabled={busy}>更新就诊摘要</Button>}
          </Stack>
          {history.length > 0 && (
            <Accordion disableGutters>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography>修改历史（{history.length}）</Typography></AccordionSummary>
              <AccordionDetails>
                {history.map((previous) => (
                  <Box key={previous.package_id} sx={{ mb: 1.5 }}>
                    <Chip size="small" color={previous.is_stale ? 'warning' : 'default'} label={`版本 ${previous.version}${previous.is_stale ? ' · 待重评' : ''}`} />
                    <Typography variant="body2" sx={{ mt: 0.5 }}>{patientText(previous.summary.case_title)}</Typography>
                  </Box>
                ))}
              </AccordionDetails>
            </Accordion>
          )}
        </Stack>
      )}
    </Paper>
  );
}
