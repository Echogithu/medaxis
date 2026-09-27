import { useState, useMemo } from 'react';
import { Box, Typography, Paper, Chip, TextField, Button, Fade, Collapse, IconButton } from '@mui/material';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined';
import { carePalette } from '../theme';
import type { InterviewQuestion } from '../types/agent';
import type { ChatMessageItem } from '../types/agent';

interface Props {
  messages: ChatMessageItem[];
  answeredIds: Set<string>;
  onAnswer: (questionId: string, answer: string) => void;
}

/** Extract all still-pending interview questions across all agent messages */
function getPendingCards(messages: ChatMessageItem[], answeredIds: Set<string>): InterviewQuestion[] {
  const seen = new Set<string>();
  const pending: InterviewQuestion[] = [];
  // Walk messages in reverse (newest last) to preserve question order
  for (const msg of messages) {
    if (msg.role !== 'agent' || !msg.interviewQuestions?.length) continue;
    for (const q of msg.interviewQuestions) {
      if (!answeredIds.has(q.question_id) && !seen.has(q.question_id)) {
        seen.add(q.question_id);
        pending.push(q);
      }
    }
  }
  return pending;
}

function getPhaseColor(phase?: string): { bg: string; border: string } {
  return { bg: '#ffffff', border: phase === '过敏情况' ? '#e58a68' : '#b9dbd1' };
}

/** Single card */
function CardItem({
  q,
  onAnswer,
}: {
  q: InterviewQuestion;
  onAnswer: (questionId: string, answer: string) => void;
}) {
  const [textAnswer, setTextAnswer] = useState('');
  const [selectedOptions, setSelectedOptions] = useState<Set<string>>(new Set());
  const colors = getPhaseColor(q.colloquial_phase);

  const submitSingle = (option: string) => {
    onAnswer(q.question_id, option);
  };

  const toggleMulti = (option: string) => {
    setSelectedOptions((prev) => {
      const next = new Set(prev);
      if (next.has(option)) next.delete(option);
      else next.add(option);
      return next;
    });
  };

  const submitMulti = () => {
    if (selectedOptions.size === 0) return;
    onAnswer(q.question_id, Array.from(selectedOptions).join('、'));
  };

  const submitText = () => {
    const trimmed = textAnswer.trim();
    if (!trimmed) return;
    onAnswer(q.question_id, trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitText();
    }
  };

  return (
    <Fade in timeout={400}>
      <Paper
        elevation={1}
        sx={{
          p: 1.5,
          mb: 1,
          border: '1px solid #e2eae6',
          borderLeft: `3px solid ${colors.border}`,
          bgcolor: colors.bg,
          borderRadius: 2,
          transition: 'all 0.3s ease',
        }}
      >
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1, gap: 0.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, letterSpacing: '0.04em' }}>
            {q.colloquial_phase || q.hint || '问诊'}
          </Typography>
        </Box>

        {/* Question */}
        <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>
          {q.question}
        </Typography>

        {/* Choices */}
        {q.type === 'choice' && q.options?.length ? (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.8 }}>
            {q.options.map((opt, i) => (
              <Chip
                key={i}
                label={opt}
                size="small"
                onClick={() => submitSingle(opt)}
                sx={{
                  cursor: 'pointer',
                  bgcolor: '#fff',
                  border: `1px solid ${colors.border}`,
                  '&:hover': { bgcolor: colors.border, color: '#fff' },
                }}
              />
            ))}
          </Box>
        ) : null}

        {/* Multi-choice */}
        {q.type === 'multi_choice' && q.options?.length ? (
          <Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.8, mb: 1 }}>
              {q.options.map((opt, i) => (
                <Chip
                  key={i}
                  label={opt}
                  size="small"
                  variant={selectedOptions.has(opt) ? 'filled' : 'outlined'}
                  color={selectedOptions.has(opt) ? 'primary' : 'default'}
                  onClick={() => toggleMulti(opt)}
                  sx={{ cursor: 'pointer' }}
                />
              ))}
            </Box>
            <Button
              size="small"
              variant="contained"
              disabled={selectedOptions.size === 0}
              onClick={submitMulti}
              sx={{ textTransform: 'none', borderRadius: 2 }}
            >
              确认选择 ({selectedOptions.size})
            </Button>
          </Box>
        ) : null}

        {/* Text input */}
        {(q.type === 'text' || !q.options?.length) && (
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <TextField
              size="small"
              fullWidth
              placeholder={q.hint || '请输入...'}
              value={textAnswer}
              onChange={(e) => setTextAnswer(e.target.value)}
              onKeyDown={handleKeyDown}
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2, bgcolor: '#fff' } }}
            />
            {q.allow_skip !== false && (
              <Button
                size="small"
                variant="text"
                onClick={() => submitSingle('跳过')}
                sx={{ textTransform: 'none', whiteSpace: 'nowrap', minWidth: 'auto' }}
              >
                跳过
              </Button>
            )}
            <Button
              size="small"
              variant="contained"
              disabled={!textAnswer.trim()}
              onClick={submitText}
              sx={{ textTransform: 'none', borderRadius: 2, whiteSpace: 'nowrap' }}
            >
              发送
            </Button>
          </Box>
        )}

        {q.hint && q.type !== 'text' && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            {q.hint}
          </Typography>
        )}
      </Paper>
    </Fade>
  );
}

export default function PendingCardsPanel({ messages, answeredIds, onAnswer }: Props) {
  const pending = useMemo(() => getPendingCards(messages, answeredIds), [messages, answeredIds]);
  const [collapsed, setCollapsed] = useState(false);

  if (pending.length === 0) return null;

  return (
    <Box
      sx={{
        borderTop: '1px solid',
        borderColor: 'divider',
        bgcolor: '#fbfcfb',
        px: 1.5,
        pt: collapsed ? 0.5 : 1,
        pb: collapsed ? 0.5 : 1,
        maxHeight: collapsed ? 44 : 420,
        overflowY: 'auto',
        transition: 'all 0.3s ease',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          mb: collapsed ? 0 : 0.5, cursor: 'pointer',
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.7, color: carePalette.muted }}>
          <AssignmentOutlinedIcon sx={{ fontSize: 16, color: carePalette.primary }} />
          <Typography variant="caption" sx={{ fontWeight: 700, color: carePalette.ink }}>
            待回答（{pending.length}）
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <IconButton size="small" sx={{ transform: collapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.3s' }}>
            <KeyboardArrowUpIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>

      {/* Cards */}
      <Collapse in={!collapsed}>
        <Box>
          {pending.map((q) => (
            <CardItem key={q.question_id} q={q} onAnswer={onAnswer} />
          ))}
        </Box>
      </Collapse>
    </Box>
  );
}
