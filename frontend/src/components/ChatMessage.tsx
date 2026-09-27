import { Box, Typography, Avatar, Paper } from '@mui/material';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import PersonIcon from '@mui/icons-material/Person';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessageItem } from '../types/agent';
import DiagnosisCard from './DiagnosisCard';
import { patientText } from '../state/patientText';
import AgentWorkflow from './AgentWorkflow';
import LabReportCard from './LabReportCard';
import UploadReportCard from './UploadReportCard';

interface Props { message: ChatMessageItem; onInterviewAnswer?: (questionId: string, answer: string) => void; }

const warmPrimary = '#178f82';
const warmText = '#173238';

export default function ChatMessage({ message, onOpenReport }: Props & { onOpenReport?: () => void }) {
  const isAgent = message.role === 'agent';
  const isSystem = message.role === 'system';
  const isInterviewQ = !!(isAgent && (message.interviewQuestion || message.interviewQuestions?.length));

  if (isSystem) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', my: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>{message.content}</Typography>
      </Box>
    );
  }

  if (isAgent && message.uploadStatus) {
    return (
      <UploadReportCard
        fileName={message.uploadFileName || '文件'}
        status={message.uploadStatus === 'processing' ? 'parsing' : message.uploadStatus}
        report={message.labReport}
        error={message.uploadError}
      />
    );
  }

  return (
    <Box sx={{
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: isAgent ? 'flex-start' : 'flex-end',
      gap: { xs: 0.8, sm: 1.1 },
      width: '100%',
      maxWidth: 1080,
      mx: 'auto',
      mb: isInterviewQ ? 1 : 2,
      px: { xs: 0.5, sm: 1 },
    }}>
      {isAgent && (
        <Avatar variant="rounded" sx={{ width: { xs: 29, sm: 33 }, height: { xs: 29, sm: 33 }, flex: '0 0 auto', mt: 0.15, borderRadius: '10px', bgcolor: '#178f82', color: '#fff' }}>
          <SmartToyIcon sx={{ fontSize: { xs: 17, sm: 19 } }} />
        </Avatar>
      )}
      <Box sx={{
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
        maxWidth: { xs: 'calc(100% - 40px)', sm: isInterviewQ ? 'calc(100% - 48px)' : '78%' },
        width: isInterviewQ ? '100%' : 'fit-content',
      }}>
        {isAgent && message.workflowSteps && message.workflowSteps.length > 0 && (
          <AgentWorkflow steps={message.workflowSteps} isStreaming={!!message.isStreaming} />
        )}
        {!isInterviewQ && !message.structured && (
          <Paper elevation={0} sx={{
            p: { xs: 1.35, sm: 1.7 },
            borderRadius: isAgent ? '5px 16px 16px 16px' : '16px 5px 16px 16px',
            background: isAgent ? '#fff' : '#e8f4f0',
            border: isAgent ? '1px solid #e5ece8' : '1px solid #d8ebe4',
            boxShadow: isAgent ? '0 3px 10px rgba(34,61,55,.035)' : 'none',
          }}>
            <Box sx={{ color: '#173238', wordBreak: 'break-word', lineHeight: 1.6, whiteSpace: 'pre-wrap', '& > *:first-of-type': { mt: 0 }, '& > *:last-of-type': { mb: 0 } }}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <Typography component="p" variant="body2" sx={{ m: 0, mb: 0.75, lineHeight: 1.6 }}>{children}</Typography>,
                  h1: ({ children }) => <Typography variant="h6" sx={{ fontWeight: 700, color: warmText, mt: 1.5, mb: 0.75 }}>{children}</Typography>,
                  h2: ({ children }) => <Typography variant="subtitle1" sx={{ fontWeight: 700, color: warmText, mt: 1.25, mb: 0.5 }}>{children}</Typography>,
                  h3: ({ children }) => <Typography variant="subtitle2" sx={{ fontWeight: 700, color: warmText, mt: 1, mb: 0.5 }}>{children}</Typography>,
                  strong: ({ children }) => <Box component="strong" sx={{ fontWeight: 700, color: warmPrimary }}>{children}</Box>,
                  em: ({ children }) => <Box component="em" sx={{ fontStyle: 'italic', color: '#71898a' }}>{children}</Box>,
                  ul: ({ children }) => <Box component="ul" sx={{ pl: 2.5, mb: 1, '& li': { mb: 0.5, lineHeight: 1.6 } }}>{children}</Box>,
                  ol: ({ children }) => <Box component="ol" sx={{ pl: 2.5, mb: 1, '& li': { mb: 0.5, lineHeight: 1.6 } }}>{children}</Box>,
                  li: ({ children }) => <Box component="li">{children}</Box>,
                  code: ({ children, className }) => {
                    const isInline = !className;
                    return (
                      <Box component="code" sx={{
                        fontFamily: 'monospace', fontSize: '0.85em',
                        bgcolor: isInline ? 'rgba(23,143,130,0.10)' : '#203438',
                        color: isInline ? warmText : '#f3f6f4',
                        px: isInline ? 0.5 : 1.5, py: isInline ? 0.25 : 1,
                        borderRadius: 1, display: isInline ? 'inline' : 'block',
                        overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      }}>{children}</Box>
                    );
                  },
                  pre: ({ children }) => (
                    <Box component="pre" sx={{ bgcolor: '#2D2D2D', p: 1.5, borderRadius: 1.5, overflowX: 'auto', mb: 1 }}>{children}</Box>
                  ),
                  blockquote: ({ children }) => (
                    <Box component="blockquote" sx={{ borderLeft: `3px solid ${warmPrimary}`, pl: 1.5, ml: 0, color: '#71898a', fontStyle: 'italic', mb: 1 }}>{children}</Box>
                  ),
                  a: ({ children, href }) => (
                    <Box component="a" href={href} target="_blank" rel="noopener noreferrer" sx={{ color: warmPrimary, textDecoration: 'underline', '&:hover': { color: '#0c756b' } }}>{children}</Box>
                  ),
                  hr: () => <Box component="hr" sx={{ border: 'none', borderTop: '1px solid #e2eae6', my: 1.5 }} />,
                  table: ({ children }) => (
                    <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', mb: 1, fontSize: '0.875rem' }}>{children}</Box>
                  ),
                  thead: ({ children }) => <Box component="thead" sx={{ bgcolor: '#eef6f2' }}>{children}</Box>,
                  th: ({ children }) => (
                    <Box component="th" sx={{ border: '1px solid #e2eae6', p: 0.75, textAlign: 'left', fontWeight: 700, color: warmText }}>{children}</Box>
                  ),
                  td: ({ children }) => (
                    <Box component="td" sx={{ border: '1px solid #e2eae6', p: 0.75, color: 'text.primary' }}>{children}</Box>
                  ),
                }}
              >
                {(isAgent ? patientText(message.content) : message.content) || (message.isStreaming ? '思考中...' : '')}
              </ReactMarkdown>
            </Box>
          </Paper>
        )}

        {isInterviewQ && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, fontStyle: 'italic' }}>
            问诊卡已移至下方待答面板
          </Typography>
        )}

        {isAgent && message.structured && <DiagnosisCard report={message.structured} onOpen={onOpenReport} />}

        {isAgent && message.labReport && message.uploadStatus !== 'completed' && (
          <LabReportCard report={message.labReport} />
        )}

        {isAgent && message.toolCalls && message.toolCalls.length > 0 && (
          <Box sx={{ mt: 1 }}>
            {message.toolCalls.map((tc, i) => (
              <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1, bgcolor: '#f2f7f4', border: '1px dashed #dce8e2', borderRadius: 2, px: 1.5, py: 0.75, mb: 0.5 }}>
                <Typography variant="caption" color="text.secondary">🔧 {tc.tool}</Typography>
                {tc.result !== undefined && <Typography variant="caption" color="success.main">✅ 已完成</Typography>}
              </Box>
            ))}
          </Box>
        )}

        <Typography variant="caption" sx={{ mt: 0.5, display: 'block', color: '#8a9998', textAlign: isAgent ? 'left' : 'right' }}>
          {message.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </Typography>
      </Box>
      {!isAgent && (
        <Avatar sx={{ width: { xs: 29, sm: 33 }, height: { xs: 29, sm: 33 }, flex: '0 0 auto', mt: 0.15, bgcolor: '#e9efec', color: '#557073' }}>
          <PersonIcon sx={{ fontSize: { xs: 17, sm: 19 } }} />
        </Avatar>
      )}
    </Box>
  );
}
