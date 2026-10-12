"""新增40组评测草稿；只读旧资产，执行输入和人工标注分开冻结。"""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / '.ai/tasks/2026-10-09-evidence-support'
OUT = TASK / 'resume-evaluation-goal/frozen-v2'
CORPUS = TASK / 'query-development-v2/corpus.json'
PRIOR = [ROOT / '.ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json',
         ROOT / '.ai/tasks/2026-10-08-source-authority/validation-frozen-v1/dataset.json',
         TASK / 'frozen-v4/dataset.json', TASK / 'query-development-v2/dataset.json']

# 题目与范围先于模型实验确定。必要证据用逐字锚点定位，不依赖chunk编号。
# 字段：主题、集合、文档前缀、起止、问题、必要证据、部分候选截断位置。
SPECS = [
 ('diarrhea_severity', 'development', '0a9e', 2513, 2636,
  '儿童腹泻规范如何区分轻型、中型和重型？请分别说明胃肠道症状、脱水及全身中毒症状。',
  ['1.轻型。', '2.中型。', '3.重型。'], '3.重型。'),
 ('diarrhea_oral_volume', 'development', '0a9e', 2924, 3046,
  '儿童每次稀便后的补液量按年龄如何安排？轻至中度脱水口服补液总量如何按体重计算、多久服完和复评？',
  ['＜6月50ml', '体重(kg)×(50～75)', '4h后再次评估脱水情况'], '轻至中度脱水：'),
 ('diarrhea_after_24h', 'development', '0a9e', 3896, 4067,
  '按儿童腹泻规范，第一个24小时已基本纠正脱水后，如何选择继续补液途径、丢失量与生理需要量的液体及补液时间？',
  ['若能够口服', '常用1/2～1/3含钠液', '12～24h内匀速补液'], '补充继续丢失量的原则'),
 ('diarrhea_nasogastric', 'development', '0a9e', 4068, 4184,
  '儿童脱水鼻饲补液适用于什么条件、初始速度是什么？出现呕吐腹胀及中重度脱水时如何处理和复评？',
  ['无严重呕吐', '初始速度20ml/kg·h', '每1～2h评估脱水情况', '尽快建立静脉通路'], '每1～2h'),
 ('diarrhea_hypernatremia', 'development', '0a9e', 4547, 4642,
  '腹泻规范中一般高渗性脱水如何处理？严重高钠血症的阈值和血钠下降速度上限分别是多少？',
  ['一般高渗性脱水不需特殊处理', '血钠>155mmol/L', '≤0.5mmol/L'], '严重高钠血症'),
 ('diarrhea_parasites', 'holdout', '0a9e', 5852, 5918,
  '儿童腹泻规范分别列举蓝氏贾地鞭毛虫、阿米巴和隐孢子虫感染的治疗药物，并提到隐孢子虫主要见于哪类患儿？',
  ['甲硝唑、替硝唑', '免疫功能低下', '大蒜素'], '隐孢子虫感染'),
 ('diarrhea_montmorillonite', 'holdout', '0a9e', 6048, 6138,
  '规范描述蒙脱石散对哪类腹泻有什么作用？小于1岁、1至2岁和2岁以上儿童的单次用量及服用时间频次是什么？',
  ['急性水样便', '＜1岁，1g/次', '每日3次口服'], '用法和用量：'),
 ('diarrhea_prevention_management', 'holdout', '0a9e', 8048, 8257,
  '儿童感染性腹泻规范列举哪些日常预防措施？婴儿室或儿科病房发现病毒性腹泻、鼠伤寒沙门菌肠炎时如何管理患者和污染环境？',
  ['提倡母乳喂养', '疫苗接种', '对污染的环境进行消毒'], '（二）患者、接触者'),
 ('flu_antigen', 'development', '95b3', 2012, 2078,
  '流感抗原检测采集什么标本，与核酸检测相比敏感性如何？阳性和阴性结果分别意味着什么？',
  ['鼻咽拭子或咽拭子', '敏感性低于核酸检测', '阴性不\n能排除流感'], '抗原检测阳性'),
 ('flu_serology', 'development', '95b3', 2165, 2214,
  '流感血清学检查中恢复期IgG出现哪两种变化有诊断意义，这种意义属于什么性质？',
  ['IgG 抗体阳转', '4 倍及以上升高', '回\n顾性诊断意义'], None),
 ('flu_child_severity', 'development', '95b3', 3072, 3263,
  '流感儿童重型标准中，高热持续时间、按年龄区分的呼吸频率及其排除条件、静息吸空气时氧饱和度阈值分别是什么？',
  ['持续高热超过 3 天', '除外发热和哭闹的影响', '指氧饱和度≤93%'], '（3）静息状态下'),
 ('flu_aspirin', 'development', '95b3', 4034, 4070,
  '流感方案规定儿童退热时应禁用哪些含阿司匹林或水杨酸的制剂？',
  ['儿童忌用阿司匹林', '他水杨酸制剂'], None),
 ('flu_home_care', 'holdout', '95b3', 3867, 3936,
  '非住院流感患者的居家隔离、房间与口罩、休息饮水饮食及病情观察各有哪些建议？',
  ['保持房间通风', '易于消化和富有营养', '尤其是儿童和老年患者'], '充分休'),
 ('flu_hospital_control', 'holdout', '95b3', 8285, 8602,
  '流感方案对医院内患者转运和探视、环境管理及医务人员健康监测分别有什么要求？',
  ['探视', '清洁和消毒', '医务人员'], '（五）'),
 ('flu_daily_prevention', 'holdout', '95b3', 8941, 9136,
  '流感一般预防措施中，个人与环境卫生、咳嗽打喷嚏后的卫生以及有流感样症状时的隔离和口罩分别如何安排？',
  ['保持环境清洁和通风', '咳嗽或打喷嚏后洗手', '自我隔离'], '出现流感样症状'),
 ('flu_respiratory_support', 'development', '95b3', 5486, 5843,
  '流感重型或危重型呼吸支持中常规氧疗、HFNC/NIV和有创通气各在什么PaO2/FiO2条件考虑？俯卧位时长及ARDS肺复张的限制是什么？',
  ['PaO2/FiO2≤300', '每天应大于 12 小时', '不\n推荐在 ARDS 患者中常规使用肺复张手法'], '（2）经鼻高流量'),
 ('fever_high_risk', 'development', '5ce0', 9056, 9520,
  'NG143高风险体征中有哪些异常皮肤颜色？呼吸方面对呻吟、呼吸频率和胸壁凹陷的描述是什么？',
  ['pale/mottled/ashen/blue', 'grunting', 'respiratory rate greater than 60', 'moderate or severe chest indrawing'], '• grunting'),
 ('fever_pneumonia', 'development', '5ce0', 14196, 14825,
  'NG143建议发热儿童出现哪些按年龄划分的呼吸频率及空气中血氧阈值时考虑肺炎？',
  ['0 to \n5 months', '6 to 12 months', 'older than 12 months', '95% or less'], '• oxygen saturation'),
 ('fever_joint_infection', 'development', '5ce0', 15497, 15694,
  'NG143列举发热儿童出现哪三类肢体或关节表现时，应考虑感染性关节炎或骨髓炎？',
  ['swelling of a limb or joint', 'not using an extremity', 'non-weight bearing'], '• non-weight bearing'),
 ('fever_travel', 'holdout', '5ce0', 17034, 17209,
  'NG143评估发热儿童时如何询问境外旅行，为什么要结合到访地区考虑感染？',
  ['travel abroad', 'region visited'], None),
 ('fever_remote_red', 'holdout', '5ce0', 25014, 25439,
  '远程评估发热儿童，有红色特征但并非立即危及生命时，NG143要求以什么方式、在多久内进一步评估？请保留适用条件。',
  ['not considered to have an \nimmediately life-threatening illness', 'face-to-face', 'within 2 hours'], 'face-to-face'),
 ('fever_safety_net', 'holdout', '5ce0', 27552, 28088,
  'NG143对有琥珀色特征尚未明确诊断的发热儿童，安全网中的家长告知内容和随访时间地点应如何安排？',
  ["no diagnosis has been reached", 'warning symptoms', 'specified time and place'], '• arranging further follow-up'),
 ('fever_infant_tests', 'development', '5ce0', 30653, 31280,
  'NG143对小于3个月的发热婴儿列举哪些血液和尿液检查？胸片及粪便培养分别需要什么条件？',
  ['full blood count', 'urinary tract infection', 'respiratory signs', 'diarrhoea'], '• stool culture'),
 ('fever_infant_lp', 'development', '5ce0', 31282, 31761,
  'NG143规定小于1个月和1至3个月发热婴儿，哪些情况下做腰穿？如何保留禁忌、白细胞条件和抗菌药之前尽早实施的要求？',
  ['unless \ncontraindicated', 'younger than 1 month', 'less than 5', 'before the administration of antibiotics'], '1.5.5'),
 ('mpp_clinical', 'holdout', 'eb49', 1573, 1739,
  '儿童MPP常见与少见年龄、主要症状和早期至进展期的肺部体征分别如何描述？',
  ['1 岁\n以下少见', '发热、咳嗽', '早期肺部体征可不明显'], '早期肺部体征'),
 ('mpp_imaging', 'holdout', 'eb49', 2042, 2413,
  '儿童MPP早期影像有哪些支气管血管周围及肺泡表现？呈细支气管炎特征时HRCT描述了哪些征象？',
  ['支气管壁增厚', '大叶性实变', '马赛克征象'], '部分 MPP 可表现'),
 ('mpp_diagnostic_tests', 'holdout', 'eb49', 3753, 3864,
  '结合哪些临床和影像前提，MPP病原学诊断的核酸及PA抗体效价证据分别满足什么条件？',
  ['临床和影像学', 'MP-DNA 或 RNA', '≥1:160'], None),
 ('mpp_adv_differential', 'development', 'eb49', 3873, 4018,
  'MPP鉴别中的腺病毒肺炎多见于什么年龄，有何主要鉴别依据？为何还要警惕与MP混合感染？',
  ['6 月-2 岁', '流行病学史和病原', '进一步加重病情'], '但需警惕'),
 ('mpp_bacterial_differential', 'development', 'eb49', 4223, 4375,
  'MPP鉴别中，细菌性肺炎早期实验室指标、形成空洞的时间与MPP相比如何，主要鉴别依靠什么？',
  ['尤其是 3d 内', '2 周以后', '病原学\n检查'], '细菌性肺炎引起'),
 ('mpp_tb_differential', 'development', 'eb49', 4376, 4605,
  'MPP治疗效果不佳时，哪些病史影像线索提示需鉴别肺结核，必要时列举哪些检测？',
  ['肺门淋巴结', '必要时', 'γ干扰素释放试验'], '必要时'),
 ('mpp_respiratory_support', 'development', 'eb49', 12068, 12290,
  'FMPP轻重程度不同及无创通气无效时如何升级呼吸支持？怀疑塑形性支气管炎和常规呼吸支持无效时分别考虑什么？',
  ['持续气道正压通气', '气管插管、有创通气', '塑形\n性支气管炎', 'ECMO'], '怀疑塑形'),
 ('mpp_coinfection_antibiotics', 'development', 'eb49', 10472, 10675,
  'MPP合并细菌感染且考虑耐药可能性小时如何选择抗菌药？哪些药不推荐常规使用，以及何时无需另加抗菌药？',
  ['耐药的可能性较低', '不推荐', '一般不建议额外加用其他抗菌药物'], '不推荐'),
]
NEGATIVE = [
 ('dental_implant', 'development', '这四份资料是否规定成人牙种植失败后骨增量手术的选择标准？', ['牙种植', '骨增量']),
 ('glaucoma_surgery', 'development', '资料是否提供原发性开角型青光眼的小梁切除术适应证？', ['青光眼', '小梁切除']),
 ('renal_transplant', 'development', '资料是否给出肾移植后他克莫司目标谷浓度与调整方案？', ['肾移植', '他克莫司']),
 ('breast_cancer_staging', 'development', '资料是否解释乳腺癌TNM分期及新辅助治疗选择？', ['乳腺癌', 'TNM']),
 ('migraine_cgrp', 'holdout', '资料是否推荐偏头痛预防使用CGRP单克隆抗体的标准？', ['偏头痛', 'CGRP']),
 ('rheumatoid_jak', 'holdout', '资料是否提供类风湿关节炎JAK抑制剂治疗失败后的换药标准？', ['类风湿', 'JAK']),
 ('spinal_anesthesia', 'holdout', '资料是否给出腰麻时局部麻醉药的阻滞剂量计算方法？', ['腰麻', '局部麻醉']),
 ('hp_eradication', 'holdout', '资料是否包含幽门螺杆菌初次根除治疗的四联方案选择？', ['幽门螺杆菌', '四联方案']),
]

# 审核v1发现短锚点丢失限定条件；v2逐项冻结完整主张，不以标题/单词计覆盖。
REQUIREMENTS = {
 'diarrhea_severity': ['1.轻型。以胃肠道症状为主，无脱水及明显全身中毒症状。',
  '2.中型。胃肠道症状较重，并出现轻、中度脱水和/或有全身中毒症状。',
  '3.重型。胃肠道症状重，重度脱水和/或有明显的全身中毒症状。'],
 'diarrhea_oral_volume': ['每次稀便后补充一定量的液体(＜6月50ml，6月～2岁100ml，2～10岁150ml，10岁以上儿童按需随意饮用)，直至腹泻停止。',
  '轻至中度脱水：口服补液用量(ml)=体重(kg)×(50～75)，4h内分次服完。', '4h后再次评估脱水情况。'],
 'diarrhea_after_24h': ['经第1个24h补液，脱水和电解质及酸碱平衡紊乱已基本纠正，需要补充继续丢失量和生理需要量。',
  '若能够口服，则改为口服补液；若因呕吐不能口服，则静脉补液。',
  '补充继续丢失量的原则是“丢多少补多少、随时丢随时补”，常用1/2～1/3含钠液；补充生理需要量用1/4～1/5张含钠液。',
  '这两部分相加后，于12～24h内匀速补液。'],
 'diarrhea_nasogastric': ['推荐应用于无静脉输液条件、无严重呕吐的脱水患儿，液体选择ORSⅢ，初始速度20ml/kg·h，',
  '如患儿反复呕吐或腹胀，应放慢管饲速度。', '每1～2h评估脱水情况。',
  '有中、重度脱水者应同时尽快建立静脉通路或转至上级医院。'],
 'diarrhea_hypernatremia': ['一般高渗性脱水不需特殊处理，随脱水纠正血钠水平可逐渐恢复。',
  '严重高钠血症（血钠>155mmol/L）时应避免血钠水平降低过快，以每小时血钠下降速度≤0.5mmol/L为宜。'],
 'diarrhea_parasites': ['蓝氏贾地鞭毛虫和阿米巴感染可使用甲硝唑、替硝唑；', '隐孢子虫感染主要见于免疫功能低下者，可予大蒜素等治疗。'],
 'diarrhea_montmorillonite': ['蒙脱石散有助于缩短急性水样便患儿的病程，减少腹泻次数和量。',
  '用法和用量：＜1岁，1g/次，1～2岁，1～2g/次，2岁以上2～3g/次，餐前口服，每日3次口服。'],
 'diarrhea_prevention_management': ['主要措施包括：培养良好的卫生习惯，注意个人卫生和环境卫生；提倡母乳喂养；积极防治营养不良；疫苗接种。',
  '感染性腹泻的患者应及时到医疗机构治疗。',
  '在医院产科的婴儿室、儿科病房等发现病毒性腹泻、鼠伤寒沙门氏菌肠炎等时，应及时隔离、治疗病人，对污染的环境进行消毒。'],
 'flu_antigen': ['采集鼻咽拭子或咽拭子进行抗原检测', '敏感性低于核酸检测。', '抗原检测阳性支持诊断，阴性不能排除流感。'],
 'flu_serology': ['恢复期 IgG 抗体阳转或较急性期呈 4 倍及以上升高，有回顾性诊断意义。'],
 'flu_child_severity': ['儿童符合下列任何一条：', '超高热或持续高热超过 3 天；',
  '呼吸急促（＜2 月龄，RR≥60 次/分；2～12 月龄，RR≥50次/分；1～5 岁，RR≥40 次/分；＞5 岁，RR≥30 次/分），除外发热和哭闹的影响；',
  '静息状态下，吸空气时指氧饱和度≤93%；'],
 'flu_aspirin': ['儿童忌用阿司匹林或含阿司匹林及其他水杨酸制剂。'],
 'flu_home_care': ['非住院患者居家隔离，保持房间通风，佩戴口罩；', '充分休息，多饮水，饮食应当易于消化和富有营养；',
  '密切观察病情变化，尤其是儿童和老年患者。'],
 'flu_hospital_control': ['患者外出检查、转科或转院途中应当佩戴医用外科口罩。', '限制疑似或确诊患者探视或陪护，防止住院患者感染。',
  '加强病房通风，并做好诊室、病房、办公室和值班室等区域物体表面的清洁和消毒。',
  '按照要求处理医疗废物，患者转出或离院后进行终末消毒。',
  '出现发热或流感样症状时，及时进行流感筛查。疑似或确诊流感的医务人员，不建议带病工作。'],
 'flu_daily_prevention': ['主要措施包括：勤洗手、保持环境清洁和通风、在流感流行季节尽量减少到人群密集场所活动、避免接触呼吸道感染患者；',
  '保持良好的呼吸道卫生习惯，咳嗽或打喷嚏时，用上臂或纸巾、毛巾等遮住口鼻，咳嗽或打喷嚏后洗手，尽量避免触摸眼睛、鼻或口；',
  '出现流感样症状应当注意休息及自我隔离，前往公共场所或就医过程中需戴口罩。'],
 'flu_respiratory_support': ['常规氧疗：PaO2/FiO2≤300 的重型患者应立即给予鼻导管或面罩吸氧。',
  'PaO2/FiO2≤200 应给予 HFNC 或 NIV，无禁忌证的情况下，建议同时实施俯卧位通气，即清醒俯卧位通气，俯卧位治疗时间每天应大于 12 小时。',
  '一般情况下，PaO2/FiO2≤150，或吸气努力明显增强的患者（尤其是儿童），应及时气管插管，给予有创机械通气；',
  '不推荐在 ARDS 患者中常规使用肺复张手法。'],
 'fever_high_risk': ['children with any of the following symptoms or signs are in a high-risk group for serious illness:',
  'pale/mottled/ashen/blue skin, lips or tongue', 'grunting', 'respiratory rate greater than 60 breaths per minute', 'moderate or severe chest indrawing'],
 'fever_pneumonia': ['Consider pneumonia in children with fever and any of the following signs:',
  'tachypnoea (respiratory rate greater than 60 breaths per minute, age 0 to 5 months; greater than 50 breaths per minute, age 6 to 12 months; greater than 40 breaths per minute, age older than 12 months)',
  'oxygen saturation of 95% or less when breathing air.'],
 'fever_joint_infection': ['Consider septic arthritis or osteomyelitis in children with fever and any of the following signs:',
  'swelling of a limb or joint', 'not using an extremity', 'non-weight bearing.'],
 'fever_travel': ['When assessing a child with feverish illness, enquire about recent travel abroad and consider the possibility of imported infections according to the region visited.'],
 'fever_remote_red': ["Children with any 'red' features but who are not considered to have an immediately life-threatening illness", 'professional in a face-to-face setting within 2 hours.'],
 'fever_safety_net': ["If any 'amber' features are present and no diagnosis has been reached", 'providing the parent or carer with verbal and/or written information on warning symptoms and how further healthcare can be accessed',
  'arranging further follow-up at a specified time and place'],
 'fever_infant_tests': ['Perform the following investigations in infants younger than 3 months with fever:', 'full blood count', 'blood culture', 'C-reactive protein',
  'urine testing for urinary tract infection', 'chest X-ray only if respiratory signs are present', 'stool culture, if diarrhoea is present.'],
 'fever_infant_lp': ['Perform lumbar puncture in the following children with fever (unless contraindicated):', 'infants younger than 1 month',
  'all infants aged 1 to 3 months who appear unwell', 'infants aged 1 to 3 months with a white blood cell count (WBC) less than 5 times 109 per litre or greater than 15 times 109 per litre.',
  'When indicated, perform a lumbar puncture without delay and, whenever possible, before the administration of antibiotics.'],
 'mpp_clinical': ['MPP 多见于 5 岁及以上儿童，5 岁以下儿童也可发病，1 岁以下少见。', '以发热、咳嗽为主要临床表现',
  '早期肺部体征可不明显，随病情进展可出现呼吸音降低和干、湿性啰音。'],
 'mpp_imaging': ['MPP 早期胸片或胸部 CT 主要表现为支气管血管周围纹理增粗、增多、支气管壁增厚，可有磨玻璃影、“树芽征”、小叶间隔增厚、网格影等。',
  '肺泡炎性改变则依肺泡受累的范围而异，可有磨玻璃样阴影、斑片状、节段乃至大叶性实变，常见肺不张，可伴有肺门影增大，重者可合并胸腔积液。',
  '部分 MPP 可表现为局限或弥漫性细支气管炎特征，胸部高分辨 CT（HRCT）显示为小叶中心结节影、“树芽征”、分支样线条征、细支气管扩张以及马赛克征象，可同时伴有支气管炎症，出现支气管壁增厚和分泌物堵塞。'],
 'mpp_diagnostic_tests': ['符合以上临床和影像学表现，结合以下任何一项或两项，即可诊断为 MPP：', 'MP-DNA 或 RNA 阳性。',
  '单份血清 MP 抗体滴度≥1:160（PA 法）；病程中双份血清 MP 抗体滴度上升 4 倍及以上。'],
 'mpp_adv_differential': ['多发于 6 月-2 岁儿童', '主要鉴别依据为流行病学史和病原学检查。',
  '但需警惕，腺病毒可以与 MP 混合感染，这种情况在部分患者中可能会进一步加重病情，并增加遗留后遗症的发生风险。'],
 'mpp_bacterial_differential': ['重症肺炎常在病程初期尤其是 3d 内出现白细胞总数、中性粒细胞占比、CRP、PCT 明显升高。',
  '细菌性肺炎引起的空洞常发生于病程 1 周左右，而 MPP 多在 2 周以后，鉴别主要依据病原学检查。'],
 'mpp_tb_differential': ['当治疗反应不佳时，应考虑到肺结核的可能性。一般情况下，肺结核病史相对较长，咳嗽相对不重。',
  '影像学表现为：原发性肺结核存在纵隔或肺门淋巴结肿大；继发性肺结核常有空洞形成；结核性胸膜炎出现中到大量胸腔积液时，常不伴肺实变。',
  '必要时进行 PPD 试验、γ干扰素释放试验鉴别以及痰液和支气管-肺泡灌洗液病原学鉴别。'],
 'mpp_respiratory_support': ['轻度呼吸衰竭患者可采用经鼻持续气道正压通气或高流量鼻导管吸氧。',
  '无创通气不能缓解的呼吸衰竭或中重度呼吸衰竭应予气管插管、有创通气。',
  '怀疑塑形性支气管炎或大量痰栓阻塞者，应尽快行支气管镜检查和治疗。',
  '常规机械通气不能缓解的呼吸衰竭，可采用 ECMO 治疗。'],
 'mpp_coinfection_antibiotics': ['如高度怀疑或已明确 MPP 合并肺炎链球菌、流感嗜血杆菌等感染，且耐药的可能性较低，可联合应用第 2、3 代头孢类抗菌药物，',
  '不推荐常规联合抗菌药物如糖肽类、噁唑烷酮类及碳青霉烯类等，除非有指征使用；',
  '当所使用的抗 MP 药物对混合感染的细菌也敏感时，一般不建议额外加用其他抗菌药物。'],
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def opaque(prefix, value):
    return prefix + sha(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())[:20]


def construct():
    corpus = load(CORPUS)
    docs = {d['id']: d for d in corpus['documents']}
    parent = load(PRIOR[2])
    previous = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p.read_bytes()),
                 'ranges': [{k: u[k] for k in ('document_id', 'start', 'end')} for u in load(p)['gold_units']],
                 'queries': [c['query'] for c in load(p)['cases']]} for p in PRIOR]
    sources, gold, questions, themes = {}, [], [], {}

    def source(doc, start, end):
        raw = doc['content'][start:end]
        start += len(raw) - len(raw.lstrip())
        text = raw.strip()
        end = start + len(text)
        require(text and 0 <= start < end <= len(doc['content']), '来源范围无效')
        old = [r for p in previous for r in p['ranges']]
        require(not any(r['document_id'] == doc['id'] and max(r['start'], start) < min(r['end'], end) for r in old), '新证据与旧gold重叠')
        origin = next(u for u in parent['gold_units'] if u['document_id'] == doc['id'])
        record = {'document_id': doc['id'], 'document_sha256': doc['text_sha256'], 'title': doc['title'],
                  'start': start, 'end': end, 'quote': text, 'metadata': origin['metadata'], 'source_url': origin['source_url']}
        record['id'] = opaque('S', [record['document_sha256'], start, end])
        sources[record['id']] = record
        return record

    for theme, split, pref, start, end, query, anchors, cut in SPECS:
        doc = next(d for d in docs.values() if d['id'].startswith(pref))
        if theme == 'fever_joint_infection':
            end = doc['content'].index('Fever in under 5s', start)
        full = source(doc, start, end)
        requirements = []
        for anchor in REQUIREMENTS[theme]:
            # PDF换行可能落在词中；只忽略空白定位，输出仍保留逐字原文及实际坐标。
            pattern = r'\s*'.join(re.escape(ch) for ch in anchor if not ch.isspace())
            match = re.search(pattern, full['quote'])
            require(match is not None, f'{theme}:必要证据不存在: {anchor}')
            a = full['start'] + match.start()
            # 锚点是必要要点，不以整段多余正文作Recall分母；完整原文仍单列评分。
            requirements.append({'document_id': doc['id'], 'start': a, 'end': full['start'] + match.end(), 'quote': match.group()})
        candidate_gold = [{'id': full['id'], 'label': 'answers', 'covered_requirement_indexes': list(range(len(requirements)))}]
        if cut is not None:
            require(cut in full['quote'], f'{theme}:截断标志不存在')
            part = source(doc, full['start'], full['start'] + full['quote'].index(cut))
            covered = [i for i, q in enumerate(requirements) if q['end'] <= part['end']]
            require(0 < len(covered) < len(requirements), f'{theme}:部分候选必须有用且不完整')
            candidate_gold.append({'id': part['id'], 'label': 'partial_answer', 'covered_requirement_indexes': covered})
        qid = opaque('Q', query)
        themes[qid] = theme
        questions.append({'id': qid, 'query': query, 'candidates': [sources[g['id']] for g in candidate_gold], 'split': split})
        gold.append({'id': qid, 'theme': theme, 'topic_family': theme, 'split': split, 'answerable': True,
                     'full_source_id': full['id'], 'requirements': requirements, 'candidates': candidate_gold,
                     'review_status': 'ai_draft_not_clinically_reviewed'})
    # 紧密关联题只留在同一个集合；不是把相同主题改写后放入留出集。
    families = {'flu_home_care': 'flu_daily_control', 'flu_daily_prevention': 'flu_daily_control',
                'fever_infant_tests': 'fever_infant_investigations', 'fever_infant_lp': 'fever_infant_investigations',
                'flu_respiratory_support': 'respiratory_support', 'mpp_respiratory_support': 'respiratory_support',
                'mpp_adv_differential': 'mpp_differential', 'mpp_bacterial_differential': 'mpp_differential',
                'mpp_tb_differential': 'mpp_differential'}
    for g in gold:
        g['topic_family'] = families.get(g['theme'], g['theme'])
    # 干扰候选仅从同集合选取，且没有任何本题逐字锚点；语义标签仍需独立审核。
    for q, g in zip(questions, gold):
        other = next(x for x in gold if x['split'] == g['split'] and x['id'] != g['id']
                     and sources[x['full_source_id']]['document_id'] == sources[g['full_source_id']]['document_id']
                     and not any(r['quote'] in sources[x['full_source_id']]['quote'] for r in g['requirements']))
        record = sources[other['full_source_id']]
        q['candidates'].append(record)
        g['candidates'].append({'id': record['id'], 'label': 'does_not_answer', 'covered_requirement_indexes': []})
    for theme, split, query, absence_terms in NEGATIVE:
        require(all(term.lower() not in d['content'].lower() for d in docs.values() for term in absence_terms), '无答案关键词实际存在')
        # 无答案仅限冻结语料，不等同于医学无答案；关键字缺失只是审核线索。
        selected = [g for g in gold if g['split'] == split and g['answerable']][:2]
        qid = opaque('Q', query)
        candidates = [sources[g['full_source_id']] for g in selected]
        questions.append({'id': qid, 'query': query, 'candidates': candidates, 'split': split})
        gold.append({'id': qid, 'theme': theme, 'topic_family': theme, 'split': split, 'answerable': False,
                     'full_source_id': None, 'requirements': [], 'absence_terms': absence_terms,
                     'candidates': [{'id': s['id'], 'label': 'does_not_answer', 'covered_requirement_indexes': []} for s in candidates],
                     'review_status': 'ai_draft_not_clinically_reviewed'})
    for q in questions:
        # 来源及问题使用无标签ID排序，禁止完整候选总在首位。
        q['candidates'].sort(key=lambda s: opaque('', [q['id'], s['id']]))
    questions.sort(key=lambda q: q['id'])
    gold.sort(key=lambda q: q['id'])
    return corpus, {'version': 'resume-eval-v2', 'questions': questions}, {'version': 'resume-eval-v2', 'questions': gold}, previous


def validate(folder):
    manifest = load(folder / 'manifest.json')
    require(sha(Path(__file__).read_bytes()) == manifest['builder_sha256'], '构建规格已变化；旧版本须使用存档脚本验证')
    for name, value in manifest['assets_sha256'].items():
        require(sha((folder / name).read_bytes()) == value, f'冻结文件变化:{name}')
    corpus, inputs, gold, previous = construct()
    require(load(folder / 'inputs.json') == inputs and load(folder / 'gold.json') == gold, '冻结资产与先验采样规格不一致')
    require(load(folder / 'corpus.json') == corpus and load(folder / 'prior-exposure.json') == previous, '旧资产或语料变化')
    require(len(inputs['questions']) == 40 and len({q['id'] for q in inputs['questions']}) == 40, '问题数/ID错误')
    counts = Counter(g['split'] for g in gold['questions'])
    require(counts == {'development': 24, 'holdout': 16}, '集合数量错误')
    require(sum(g['answerable'] for g in gold['questions']) == 32, '可回答数量错误')
    require(not any(q['query'] in p['queries'] for q in inputs['questions'] for p in previous), '题目逐字复用旧题')
    topic_splits = {}
    source_splits = {}
    documents = {d['id']: d for d in corpus['documents']}
    for split in counts:
        expected = {'version': inputs['version'], 'questions': [{k: v for k, v in q.items() if k != 'split'} for q in inputs['questions'] if q['split'] == split]}
        require(load(folder / f'inputs-{split}.json') == expected, '执行集合与冻结母集不一致')
    for q, g in zip(inputs['questions'], gold['questions']):
        require(set(q) == {'id', 'query', 'candidates', 'split'}, '执行输入含gold字段')
        require(q['id'] == g['id'] and 2 <= len(q['candidates']) <= 4, '候选组错误')
        require(0 < len(g['requirements']) <= 8 if g['answerable'] else not g['requirements'], '必要要点数量非法')
        topic_splits.setdefault(g['topic_family'], set()).add(g['split'])
        for s in q['candidates']:
            source_splits.setdefault(s['id'], set()).add(g['split'])
            require(set(s) == {'id', 'document_id', 'document_sha256', 'title', 'start', 'end', 'quote', 'metadata', 'source_url'}, '来源输入泄漏标注')
            d = documents[s['document_id']]
            require(sha(d['content'].encode()) == s['document_sha256'] == d['text_sha256'], '文档SHA错误')
            require(d['content'][s['start']:s['end']] == s['quote'], '原文坐标错误')
    require(all(len(v) == 1 for v in topic_splits.values()), '主题跨集合')
    require(all(len(v) == 1 for v in source_splits.values()), '候选来源跨集合，留出证据提前暴露')
    return {'status': 'PASS_DRAFT_ASSETS_ONLY', 'groups': 40, 'answerable': 32, 'no_answer': 8,
            'splits': dict(counts), 'candidate_rows': sum(len(q['candidates']) for q in inputs['questions']),
            'old_span_overlap': 0, 'cross_split_sources': 0, 'shared_corpus': True,
            'not_blind': True, 'professional_reviewed': 0, 'model_experiments_run': False}


def build(folder):
    require(not folder.exists(), '目标目录存在，禁止覆盖冻结资产')
    corpus, inputs, gold, previous = construct()
    folder.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, item in [('corpus.json', corpus), ('inputs.json', inputs), ('gold.json', gold), ('prior-exposure.json', previous)]:
        write(name, item)
    for split in ('development', 'holdout'):
        write(f'inputs-{split}.json', {'version': inputs['version'], 'questions': [{k: v for k, v in q.items() if k != 'split'} for q in inputs['questions'] if q['split'] == split]})
    lookup = {q['id']: q for q in inputs['questions']}
    lines = ['# 40组评测题与审核依据', '', 'AI标注草稿，共享4份冻结语料，非盲测，专业审核0。留出集尚未用于模型调优。',
             '候选来源与主题均不跨集合。字符坐标为Python Unicode字符，end不含；必要要点与整段原文覆盖分别计算。',
             '无答案指这些冻结资料不支持，关键词缺失仅为审核线索，不是医学证明。', '']
    for g in gold['questions']:
        q = lookup[g['id']]
        lines += [f"## {g['id']} / {g['theme']} / {g['split']}", '', q['query'], '', '必要要点：' + json.dumps(g['requirements'], ensure_ascii=False), '']
        for cg in g['candidates']:
            s = next(s for s in q['candidates'] if s['id'] == cg['id'])
            lines += [f"候选 {s['id']}：{cg['label']}；覆盖要点索引 {cg['covered_requirement_indexes']}",
                      f"原文：{s['title']}，{s['start']}:{s['end']}；SHA {s['document_sha256']}", '', '```text', s['quote'], '```', '', f"官方出处：{s['source_url']}", '']
    (folder / 'QUESTIONS.md').write_text('\n'.join(lines), encoding='utf-8')
    (folder / 'review.csv').write_text('question_id,source_id,reviewer,label,decision,comment\n' + ''.join(f"{g['id']},{s['id']},,,,\n" for g in gold['questions'] for s in g['candidates']), encoding='utf-8')
    names = ['corpus.json', 'inputs.json', 'gold.json', 'prior-exposure.json', 'inputs-development.json', 'inputs-holdout.json', 'QUESTIONS.md', 'review.csv']
    write('manifest.json', {'version': inputs['version'], 'builder_sha256': sha(Path(__file__).read_bytes()),
                           'groups': 40, 'answerable': 32, 'no_answer': 8, 'professional_reviewed': 0,
                           'sampling_before_model_run': True, 'shared_corpus': True, 'not_blind': True,
                           'assets_sha256': {n: sha((folder / n).read_bytes()) for n in names}})
    return validate(folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run:
        corpus, inputs, gold, prior = construct()
        result = {'status': 'DRAFT_CONSTRUCTED_IN_MEMORY', 'groups': len(inputs['questions'])}
    else:
        result = validate(args.output) if args.verify_only else build(args.output)
    print(json.dumps(result, ensure_ascii=False))
