MedAxis - 高级 UI 设计规范 (Design System Guidelines)
1. 色彩心理学与品牌色系 (Color Palette)
摒弃传统医疗系统冰冷、严肃的“医院蓝”，采用具有生命力、疗愈感与专业性的青绿色（Teal / Emerald）为主轴，辅以极低饱和度的石板灰，打造“无压力”视觉。

品牌主色 (Primary):

Teal-500 (#14b8a6): 核心交互、主按钮、图标背景。

Teal-600 (#0d9488): 悬停状态、强调文本。

Teal-50 (#f0fdfa): 极浅背景底色，用于高亮选中块或成功提示区。

中性灰度 (Neutral - Slate 系):

Slate-800 (#1e293b): 主标题、核心正文文字（替代纯黑，降低视觉锐利度）。

Slate-500 (#64748b): 次要信息、时间戳、说明文本。

Slate-50 (#f8fafc): 全局应用背景色，与纯白卡片形成微妙的层级区分。

语义强调色 (Semantic):

心脏/血压/警告: Rose-500 (#f43f5e) 配合浅红背景 Rose-50 (#fff1f2)。

睡眠/静谧数据: Indigo-500 (#6366f1)。

提醒/待办: Orange-500 (#f97316)。

2. 排版与字体体系 (Typography)
字体族: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif（确保多端原生渲染最优）。

层级定义:

超大标题 (Hero): 36px/30px, SemiBold，用于欢迎语、核心指标（如健康分）。

模块标题 (Section): 18px/20px, SemiBold，用于卡片头部（如“今日照护”）。

正文阅读 (Body): 14px, Regular/Medium，行高 1.6-1.8，确保问诊记录等长文本的舒适阅读。

辅助说明 (Caption): 12px, Regular，用于标签、日期、免责声明。

3. 空间、圆角与层级 (Shape & Elevation)
大圆角美学: 彻底抛弃尖锐边角。主卡片采用 24px 或 32px (rounded-3xl) 圆角；按钮与图标容器采用 12px 或 16px (rounded-xl/rounded-2xl)，形塑极具包容感的硬件级流线外形。

柔和阴影 (Soft Shadows): 抛弃生硬的实线边框（Border）。依靠超轻量的弥散阴影 box-shadow: 0 10px 40px -10px rgba(0,0,0,0.03)，以及白底 (#ffffff) 对抗浅灰底 (#f8fafc) 来拉开空间纵深（Z-Axis）。

留白 (Whitespace): 增加内部 Padding。卡片内部边距最小设为 24px (p-6)，保持绝对的“呼吸感”。

4. 微交互与组件细节 (Micro-interactions)
悬浮抬升: 桌面端下，卡片悬停时触发轻微的向上平移（-translate-y-1）与阴影范围扩散，反馈轻盈灵动。

毛玻璃效应 (Glassmorphism): 顶部导航栏和底部输入框背景采用 rgba(255,255,255,0.85) + backdrop-filter: blur(16px)，让底层内容滚动时若隐若现，增加界面的通透度。

💻 完整功能重构版 HTML 代码 (响应式 SPA)
这份代码引入了 Tailwind CSS 和 Phosphor Icons。它包含了一个完整的响应式应用外壳（App Shell）：

宽屏设备 (PC/Pad)：显示左侧优雅导航栏，右侧为宽大舒适的卡片工作区。

移动端 (Phone)：自动转为底部毛玻璃导航栏，全屏沉浸体验。
