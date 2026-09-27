import { Box, Button, Stack, Typography } from '@mui/material';
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import HealingOutlinedIcon from '@mui/icons-material/HealingOutlined';
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined';
import { careFonts, carePalette } from '../theme';

const starters = [
  {
    title: '描述症状',
    detail: '头疼、咳嗽、腹痛等不适，用日常语言说即可',
    prompt: '头疼还发烧',
    icon: <HealingOutlinedIcon sx={{ fontSize: 20 }} />,
  },
  {
    title: '解读报告',
    detail: '先上传体检或检验单，再一起看异常项',
    prompt: '近期体检报告解读',
    icon: <DescriptionOutlinedIcon sx={{ fontSize: 20 }} />,
  },
  {
    title: '补充情况',
    detail: '病程超过几天时，说明开始时间和变化',
    prompt: '咳嗽一周了',
    icon: <ChatBubbleOutlineRoundedIcon sx={{ fontSize: 20 }} />,
  },
];

export default function ChatWelcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <Box sx={{ width: '100%', maxWidth: 720, mx: 'auto', px: { xs: 1, sm: 2 }, py: { xs: 3, sm: 6 } }}>
      <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 700, fontSize: { xs: 26, sm: 32 }, letterSpacing: '-0.035em', color: carePalette.ink, lineHeight: 1.2 }}>
        你好，我是医枢问诊助手
      </Typography>
      <Typography sx={{ mt: 1.25, maxWidth: 520, color: carePalette.muted, fontSize: 14, lineHeight: 1.75 }}>
        用日常语言说说哪里不舒服。我会先收集情况，再整理一份可与医生讨论的参考总结。
      </Typography>

      <Stack spacing={1.1} sx={{ mt: 3.5 }}>
        {starters.map((item) => (
          <Button
            key={item.title}
            onClick={() => onPick(item.prompt)}
            sx={{
              justifyContent: 'flex-start',
              gap: 1.4,
              px: 1.6,
              py: 1.4,
              minHeight: 64,
              borderRadius: '16px',
              border: '1px solid #e2eae6',
              bgcolor: '#fff',
              color: carePalette.ink,
              textAlign: 'left',
              '&:hover': { bgcolor: '#f4faf7', borderColor: '#b9dbd1' },
            }}
          >
            <Box sx={{
              width: 38, height: 38, flex: '0 0 auto', display: 'grid', placeItems: 'center',
              borderRadius: '12px', color: carePalette.primaryDark, bgcolor: carePalette.primarySoft,
            }}>
              {item.icon}
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{item.title}</Typography>
              <Typography variant="caption" sx={{ color: carePalette.muted, display: 'block' }}>{item.detail}</Typography>
            </Box>
          </Button>
        ))}
      </Stack>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, mt: 3, color: '#66878f', fontSize: 12, fontWeight: 650 }}>
        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.6 }}>
          <VerifiedUserOutlinedIcon sx={{ fontSize: 15, color: carePalette.primary }} />
          对话内容仅用于本次问诊
        </Box>
        <Box>紧急或持续加重时，请立即就医</Box>
      </Box>
    </Box>
  );
}
