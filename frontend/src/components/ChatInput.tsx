import { useState, useRef } from 'react';
import { Box, TextField, IconButton, Button, Chip, Paper } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import ImageIcon from '@mui/icons-material/Image';
import MicIcon from '@mui/icons-material/Mic';
import StopIcon from '@mui/icons-material/Stop';

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
    if (files && onFileUpload) {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (file.size <= 10 * 1024 * 1024) {
          onFileUpload(file);
        }
      }
    }
    if (e.target) e.target.value = '';
  };

  return (
    <Box>
      {quickReplies && quickReplies.length > 0 && (
        <Box sx={{ display: 'flex', gap: 0.8, flexWrap: 'wrap', mb: 1.25, px: { xs: 0.25, sm: 0.5 } }}>
          {quickReplies.map((reply) => (
            <Chip key={reply} label={reply} size="small" clickable onClick={() => onQuickReply?.(reply)}
              sx={{ bgcolor: '#f2f7f4', border: '1px solid #e2ebe6', color: '#4d696c', '&:hover': { bgcolor: '#e7f3ed', borderColor: '#8ac5b2' }, fontSize: 11.5, height: 29, borderRadius: '999px' }} />
          ))}
        </Box>
      )}

      <Paper elevation={0} sx={{ display: 'flex', alignItems: 'flex-end', gap: { xs: 0.35, sm: 0.75 }, p: { xs: 0.75, sm: 1 }, borderRadius: '16px', border: '1px solid #dce8e2', bgcolor: '#fff', boxShadow: '0 5px 16px rgba(34,61,55,.055)', '&:focus-within': { borderColor: '#78b9a7', boxShadow: '0 0 0 3px rgba(23,143,130,.08)' } }}>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.txt"
          onChange={handleFileSelect}
        />
        <IconButton size="small" aria-label="添加文件" title="添加文件" sx={{ color: '#71898a' }} disabled={disabled} onClick={() => fileInputRef.current?.click()}>
          <AttachFileIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" aria-label="添加图片" title="添加图片" sx={{ display: { xs: 'none', sm: 'inline-flex' }, color: '#71898a' }} disabled={disabled} onClick={() => fileInputRef.current?.click()}>
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
              sx: { fontSize: { xs: 13, sm: 14 }, color: '#173238', '&::placeholder': { color: '#9aa8a6', opacity: 1 } },
            },
          }}
        />

        <IconButton size="small" aria-label={isRecording ? '停止语音输入' : '语音输入'} title={isRecording ? '停止语音输入' : '语音输入'} onClick={() => setIsRecording(!isRecording)} disabled={disabled}
          sx={{ display: { xs: 'none', sm: 'inline-flex' }, color: isRecording ? 'error.main' : '#71898a' }}>
          {isRecording ? <StopIcon fontSize="small" /> : <MicIcon fontSize="small" />}
        </IconButton>

        <Button variant="contained" size="small" onClick={handleSend} disabled={disabled || !text.trim()}
          sx={{ minWidth: 39, width: 39, height: 39, borderRadius: '12px', p: 0, bgcolor: '#178f82', '&:hover': { bgcolor: '#0c756b' }, '&.Mui-disabled': { bgcolor: '#e4eeea', color: '#91a19d' } }}>
          <SendIcon sx={{ fontSize: 18 }} />
        </Button>
      </Paper>
    </Box>
  );
}
