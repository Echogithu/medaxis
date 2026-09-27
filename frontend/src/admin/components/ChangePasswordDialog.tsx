import { useState, type FormEvent } from 'react';
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
} from '@mui/material';
import { changePassword } from '../../api/admin';

interface ChangePasswordDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function ChangePasswordDialog({ open, onClose }: ChangePasswordDialogProps) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleClose = () => {
    if (loading) return;
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError('');
    setSuccess('');
    onClose();
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSuccess('');

    if (!oldPassword) {
      setError('请输入当前密码');
      return;
    }
    if (newPassword.length < 8) {
      setError('新密码至少 8 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次新密码不一致');
      return;
    }

    setLoading(true);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setSuccess('管理员密码修改成功，请使用新密码重新登录');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '密码修改失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>修改管理员密码</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}
        <form id="change-admin-password-form" onSubmit={handleSubmit}>
          <TextField
            autoFocus
            fullWidth
            required
            margin="dense"
            label="当前密码"
            type="password"
            autoComplete="current-password"
            value={oldPassword}
            onChange={(event) => setOldPassword(event.target.value)}
            disabled={Boolean(success) || loading}
          />
          <TextField
            fullWidth
            required
            margin="dense"
            label="新密码"
            type="password"
            autoComplete="new-password"
            helperText="至少 8 位字符"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={Boolean(success) || loading}
          />
          <TextField
            fullWidth
            required
            margin="dense"
            label="确认新密码"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            disabled={Boolean(success) || loading}
          />
        </form>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>{success ? '关闭' : '取消'}</Button>
        {!success && (
          <Button type="submit" form="change-admin-password-form" variant="contained" disabled={loading}>
            {loading ? <CircularProgress size={18} color="inherit" /> : '确认修改'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
