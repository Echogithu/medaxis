import { useState, useRef } from 'react';
import { Alert, Box, TextField, IconButton, Chip, Paper, Typography } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import ImageIcon from '@mui/icons-material/Image';
import MicIcon from '@mui/icons-material/Mic';
import StopIcon from '@mui/icons-material/Stop';
import { carePalette } from '../theme';

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
  quickReplies?: string[];
  onQuickReply?: (text: string) => void;
  onFileUpload?: (file: File) => void;
  placeholder?: string;
}

export default function ChatInput({ onSend, disabled = false, quickReplies, onQuickReply, onFileUpload, placeholder }: Props) {
  const [text, setText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [fileError, setFileError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    const rejected: string[] = [];
    setFileError('');
    if (files && onFileUpload) {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (file.size <= 10 * 1024 * 1024) {
          onFileUpload(file);
        } else {
          rejected.push(file.name);
        }
      }
    }
    if (rejected.length) setFileError(`文件太大：${rejected.join('、')}。请选择 10MB 以内的文件，再重新上传。`);
    if (e.target) e.target.value = '';
  };

  return (
    <Box>
      {fileError && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setFileError('')}>{fileError}</Alert>}
      {quickReplies && quickReplies.length > 0 && (
        <Box sx={{ display: 'flex', gap: 0.8, flexWrap: 'wrap', mb: 1.25, px: { xs: 0.25, sm: 0.5 } }}>
          {quickReplies.map((reply) => (
            <Chip key={reply} label={reply} size="small" clickable onClick={() => onQuickReply?.(reply)}
              sx={{ bgcolor: '#f2f7f4', border: '1px solid #e2ebe6', color: '#4d696c', '&:hover': { bgcolor: '#e7f3ed', borderColor: '#8ac5b2' }, fontSize: 11.5, height: 29, borderRadius: '999px' }} />
          ))}
        </Box>
      )}

      <Paper role="group" aria-label="问诊输入栏" elevation={0} sx={{ display: 'flex', alignItems: 'center', gap: { xs: 0.25, sm: 0.5 }, p: { xs: 0.5, sm: 0.75 }, borderRadius: '16px', border: `1px solid ${carePalette.line}`, bgcolor: '#fff', boxShadow: '0 5px 16px rgba(15,23,42,.04)', '&:focus-within': { borderColor: carePalette.primary, boxShadow: '0 0 0 3px rgba(13,148,136,.08)' } }}>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.txt"
          onChange={handleFileSelect}
        />
        <IconButton size="small" aria-label="添加文件" title="添加文件" sx={{ width: 44, height: 44, flexShrink: 0, color: carePalette.muted }} disabled={disabled} onClick={() => fileInputRef.current?.click()}>
          <AttachFileIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" aria-label="添加图片" title="添加图片" sx={{ display: { xs: 'none', sm: 'inline-flex' }, width: 44, height: 44, flexShrink: 0, color: carePalette.muted }} disabled={disabled} onClick={() => fileInputRef.current?.click()}>
          <ImageIcon fontSize="small" />
        </IconButton>

        <TextField
          inputRef={inputRef}
          fullWidth
          multiline
          maxRows={4}
          placeholder={disabled ? '请稍候…' : (placeholder || '描述您的症状，或补充检查报告…')}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          variant="standard"
          slotProps={{
            input: {
              disableUnderline: true,
              sx: { minHeight: 44, p: 0, fontSize: { xs: 13, sm: 14 }, color: carePalette.ink, '& textarea': { p: 0, lineHeight: 1.6, '&::placeholder': { color: '#94a3b8', opacity: 1 } } },
            },
          }}
        />

        <IconButton size="small" aria-label={isRecording ? '停止语音输入' : '语音输入'} title={isRecording ? '停止语音输入' : '语音输入'} onClick={() => setIsRecording(!isRecording)} disabled={disabled}
          sx={{ display: { xs: 'none', sm: 'inline-flex' }, width: 44, height: 44, flexShrink: 0, color: isRecording ? 'error.main' : carePalette.muted }}>
          {isRecording ? <StopIcon fontSize="small" /> : <MicIcon fontSize="small" />}
        </IconButton>

        <IconButton aria-label="发送消息" title="发送消息" onClick={handleSend} disabled={disabled || !text.trim()}
          sx={{ width: 44, height: 44, flexShrink: 0, p: 0, color: '#fff', '&:hover': { bgcolor: 'transparent', '& .send-face': { bgcolor: '#115e59' } }, '&.Mui-disabled .send-face': { bgcolor: '#e2e8f0', color: '#94a3b8' } }}>
          <Box component="span" className="send-face" sx={{ width: 32, height: 32, display: 'grid', placeItems: 'center', borderRadius: '10px', bgcolor: carePalette.primaryDark, transition: 'background-color 160ms ease' }}><SendIcon sx={{ fontSize: 16 }} /></Box>
        </IconButton>
      </Paper>
      <Typography variant="caption" sx={{ display: 'block', mt: .5, color: carePalette.muted }}>每个文件不超过 10MB</Typography>
    </Box>
  );
}
