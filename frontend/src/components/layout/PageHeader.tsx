/** 通用页面头部组件
 * 替换各页面中重复的标题行布局。
 * 支持图标、副标题、操作按钮、Badge 等多种组合。
 */

import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';

interface PageHeaderProps {
  title: string;
  /** 右侧操作区域（按钮、Chip 等） */
  actions?: ReactNode;
  /** 标题前的图标 */
  icon?: ReactNode;
  /** 标题后的附加元素（如 Badge） */
  titleSuffix?: ReactNode;
  /** 附加说明文本（显示在标题下方） */
  subtitle?: string;
}

export function PageHeader({ title, actions, icon, titleSuffix, subtitle }: PageHeaderProps) {
  return (
    <Box sx={{ display: 'flex', flexDirection: { xs: 'column', sm: 'row' }, alignItems: { xs: 'stretch', sm: 'center' }, justifyContent: 'space-between', gap: 2, mb: 3, pb: 1.5, borderBottom: 1, borderColor: 'divider' }}>
      <Box sx={{ minWidth: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', minWidth: 0 }}>
          {icon && <Box sx={{ display: 'flex', alignItems: 'center', color: 'primary.main', '& svg': { fontSize: 22 } }}>{icon}</Box>}
          <Typography variant="h5" sx={{ fontSize: { xs: '1.3rem', sm: '1.5rem' }, lineHeight: 1.3, fontWeight: 720, letterSpacing: '-0.025em' }}>
            {title}
          </Typography>
          {titleSuffix}
        </Box>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, fontSize: '0.8125rem' }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions && (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: { xs: 'flex-start', sm: 'flex-end' }, flexWrap: 'wrap', gap: 1, flexShrink: 0 }}>
          {actions}
        </Box>
      )}
    </Box>
  );
}
