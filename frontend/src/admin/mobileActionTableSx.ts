/** 手机上固定对象与操作，横滑只查看中间属性。 */
export const mobileActionTableSx = {
  '@media (max-width: 899px)': {
    '& th:first-of-type, & td:first-of-type:not([colspan])': {
      position: 'sticky', left: 0, zIndex: 1, bgcolor: 'background.paper',
      width: 140, minWidth: 140, maxWidth: 140, overflowWrap: 'anywhere',
      boxShadow: '2px 0 4px rgba(0,0,0,.06)',
    },
    '& th:last-of-type, & td:last-of-type:not([colspan])': {
      position: 'sticky', right: 0, zIndex: 1, bgcolor: 'background.paper',
      width: 124, minWidth: 124, maxWidth: 124, whiteSpace: 'nowrap',
      boxShadow: '-2px 0 4px rgba(0,0,0,.06)',
    },
  },
} as const;
