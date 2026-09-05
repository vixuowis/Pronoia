# v0 与 claim-v2 共同误判案例集（最终 1000 条）

- 普通三分类口径下，两版本共同误判 **720** 条。
- 下列30条为按五类启发式规则挑选的代表案例；分类可复核但不是人工金标。
- strict 口径还会把 oracle-neutral 样本统一计错；本集锦排除了“两版均预测 neutral 且真实 neutral”的普通三分类正确样本。

## 方向映射错误：文本已有方向但两版仍 neutral

分析或事件语义包含方向线索，但图中没有显式 signed claim，裁决净分仍被归零。

### 1. `seed_cn_300620_event_a918e358b6`

- 事件：300620 2025-11-21 光库科技:北京德恒律师事务所关于不存在《上市公司监管指引第7号——上市公司重大资产重组相关股票异常交易监管》第十二条不得参与上市公司重大资产重组情形的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**up**；CAR=33.15%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/1；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：净分依据：证据图中三条已连接 claim 均未形成有效 up/down 方向信号。C1 为程序性法律核查披露、增量信息低、方向信号弱且倾向中性区间，未指向 up 或 down；C2 依赖事前漂移数值且两分支均未证实，维持 needs_more；C3 指出 event_type_l2 标签“公司指引上调/下调”与标题“法律意见书/核查说明”不符，属分类标签噪音，故不能按指引上调先验赋予 up 信号。MISSING 包括正文截断、事前漂移与
- claim-v2 裁决摘要：该事件为重大资产重组进程中的程序性合规披露，本身不含新增经营或财务信息，信息增量较低。证据图中无明确 supports/contradicts 连接形成的方向性信号，也未显示事件前漂移或 T0 相对基准的具体数值，无法确认重组预期是否已提前定价。程序性文件可能被市场解读为重组推进信号而带来短期正向超额，但缺少实质证据支持，方向不确定。净分为零，按评分卡规则判定 neutral。

### 2. `seed_cn_688051_event_02945cb0ae`

- 事件：688051 2025-12-06 佳华科技:董事会关于本次交易相关主体不存在《上市公司监管指引第7号——上市公司重大资产重组相关股票异常交易监管》第十二条及《上海证券交易所上市公司自律监管指引第6号——重大资产重组》第三十条规定情形的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**down**；CAR=-29.61%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/2；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为重大资产重组中的程序性合规说明，标题及正文均为流程性披露，无交易对价、标的、盈利预测等实质信息，亦无支撑股价方向的数据。虽然元数据标注为“公司指引上调/下调”，但与正文冲突，无法作为方向性先验。正向信号仅为低置信度备择解读，缺乏实质证据支持，不构成有效方向 claim。净分=0，无明确 up/down 信号，故判 neutral。
- claim-v2 裁决摘要：事件为重大资产重组流程中的程序性合规说明（即相关主体不存在异常交易监管情形），公告不含标的、对价、业绩承诺等基本面信息，也无盈利/营收等可形成超预期锚点的数据。证据图中两个主要claim均未提供明确利多或利空信号：一个判定方向指引弱，一个基于无基本面锚点预判中性；同时缺失重组实质内容及T0/pre5行情数值，无法校准方向。方向信号净分为0，按评分卡应判中性。

### 3. `seed_cn_301486_event_2fa2301f3c`

- 事件：301486 2025-04-22 致尚科技:董事会关于本次交易是否构成关联交易、重大资产重组及重组上市的说明
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=28.07%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：净分依据：事件公告为“是否构成关联交易、重大资产重组及重组上市”的程序性说明，正文不含交易标的、金额、定价等实质条款，无法提取有效的up/down方向信号；图中主要claim为“方向中性/不明确”及“数据缺失不可验证”，均未构成支持up或down的实质证据。up分数=0，down分数=0，净分=0，且无方向信号，故按评分卡判为neutral。虽然数据不完整，但没有可支撑方向判断的证据，不能强给方向；同时程序性披露的增量信息本身偏弱，符合
- claim-v2 裁决摘要：事件为董事会关于交易定性（是否构成关联交易/重大资产重组/重组上市）的程序性说明公告，无实质财务与定价细节；且事件研究所需行情、基本面数据全部超时缺失，无法提取任何具有实质证据支持的方向性信号。按评分卡计算，up 与 down 方向信号均为 0，净分=0，因此判定为 neutral，置信度取 0.50。

### 4. `seed_cn_000670_event_fbb988ec1d`

- 事件：000670 2026-01-20 盈方微:董事会关于本次交易符合《上市公司重大资产重组管理办法》第十一条、第四十三条及第四十四条有关规定的说明
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=25.43%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=2/1；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：该公告为程序性合规说明，无新增财务/方案细节，信息含量低；分类器default_prior=down被明确否定，不可作为方向依据；as-of事件前行情缺失，无实证up/down信号。净分=0，无方向信号，故判中性。
- claim-v2 裁决摘要：事件仅为重组合规程序性说明，无盈利、定价或对价等增量实质信息，且前视漂移与T0信号缺失；证据图中无支持正向或负向超额收益的明确方向claim，净分=0，故按规则判定neutral。

### 5. `seed_cn_300331_event_689613deba`

- 事件：300331 2025-09-01 苏大维格:关于签署股权收购意向协议的公告
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=17.28%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件仅为股权收购意向协议，正文无对价、标的、业绩承诺等实质条款，证据图C1定性为低信号程序性文件，否定仅凭标题判偏多的先验；C2进一步预判T+3超额收益大概率中性。T0/T+3行情与事件研究获取失败，缺少可计算的CAR信号。无有效up/down方向claim，净分为0，故判neutral。
- claim-v2 裁决摘要：事件仅为签署股权收购意向协议，公告未披露交易对手、标的、对价及进度条款，信息含量低；E1 事件原文无实质利好或利空细节。行情链路（event_study/market_research）全部失败或超时，无法获得 T0 及事件前漂移信号；基本面与新闻明细被截断，无可用方向锚点。所有 evidence claims 均未形成可计分的 up/down 信号，净分=0，故判定 neutral。

### 6. `seed_us_nvda__a903158bab`

- 事件：NVDA 2025-04-01 US Unemployment Rate
- 市场/类型：US / 增长/就业数据意外
- T3 真实标签：**up**；CAR=14.45%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：净分依据：证据图中无任何已被supports/contradicts连接、且给出明确up/down方向信号的claim。事件正文为ISM PMI占位文本且与标题不一致，实际数值缺失；market_research与stock_overview均超时，缺少NVDA相对涨跌与基本面输入。第三个claim仅为条件式假设（偏强则down、偏弱则up），未取得实际数据前无法激活方向信号。因此up与down信号均为0，净分=0，满足“完全没有方向信
- claim-v2 裁决摘要：（空）

## 证据缺失/图谱未闭合

关键 actual-vs-consensus、公告正文或 T0/pre-drift 数据缺失，两个图谱均未闭合。

### 1. `seed_cn_603259__9603b4d460`

- 事件：603259 2024-01-10 中国一季度业绩预告指引
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**up**；CAR=6.83%；avg_all=down；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=5/4；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件 packet 仅有模板摘要，无指引方向或幅度数值；E2/E3 专家结论与 E4-E11 数值均未展开，无任何被 supports 连接的有效方向 claim 可比分。MISSING 覆盖公告原文、T0 超额、pre5/pre20 漂移及基本面数据，无法形成 up/down 净分；净分=0，按评分卡应选 neutral。
- claim-v2 裁决摘要：事件文本为占位格式，无营收/净利/同比等量化指引，无法判断上调或下调；T0虽有个股+0.33%表现，但主动超额<0.5%阈值且主要来自基准下跌的被动贡献，signal_valid=false，不构成有效方向信号；预载专家摘要亦无实质结论。方向净分=0，缺乏实质证据支持的方向claim，故判中性。

### 2. `seed_us_bmy__8ab38ffcee`

- 事件：BMY 2025-04-01 US Index Constituents Guidance Update
- 市场/类型：US / 公司指引上调/下调
- T3 真实标签：**down**；CAR=-11.13%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/4；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：证据图中核心的指引增量数值（更新后指引 vs press consensus / street prev 的偏离方向）缺失，无法判断指引上调或下调；事件正文仅为模板字段，未披露具体数值。基本面与市场面佐证技能超时失败，辅助信号源虽存在但数值未复现，无法量化方向信号。方向打分：无有效 up 或 down 信号，净分=0，按评分卡选择 neutral。
- claim-v2 裁决摘要：证据图中无任何可提取的 up/down 方向信号；所有 claims 均为 needs_more 且未给出明确多空。事件正文仅为占位文本，标题与 event_type 存在歧义，且缺失财务数值、市场预期及指数成分调整方向。第一条 claim 直接认为 T+3 基准相对 CAR 大概率中性。因此净分=0，无方向信号，符合 neutral 条件，置信度设为 0.50。

### 3. `seed_cn_sh516160__12022cb205`

- 事件：SH516160 2025-01-22 中国PPI工业生产者价格指数月度公告
- 市场/类型：CN / 通胀数据意外
- T3 真实标签：**down**；CAR=-9.62%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/4；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件正文为占位符，缺乏PPI实际值与机构预期的预期差；事件研究工具对SH516160解析失败，无T0及事前漂移数据；两条claim均为证据不足状态，未形成任何有效方向信号。净分=0，按规则判定中性。
- claim-v2 裁决摘要：证据图中无任何 supports/contradicts 连接的有效方向 claim；PPI 实际值、机构预期与前值均缺失，意外方向不明；event_study 行情获取失败，事件日与事前漂移信号缺失；仅有的条件式推断（PPI 意外下行→up）不构成实际方向信号。因此 up/down 均无证据得分，净分为 0，按评分卡判定为 neutral。

### 4. `seed_us_aapl__710f8a7d03`

- 事件：AAPL 2025-04-01 US Advance GDP
- 市场/类型：US / 增长/就业数据意外
- T3 真实标签：**down**；CAR=-9.23%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/4；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件正文为占位符，无实际数值；技能调用超时或未展示有效数据，无法获取事件实际/预期/前值、T0相对强弱及事前漂移。图中唯一被支持的 claim 明确认为方向不可判定；另一个方向性推断未被证据连接且自认无数据支撑，不计入信号。净分=0，按评分卡应选 neutral。
- claim-v2 裁决摘要：事件 packet 仅含 ISM PMI 标签，无实际值 vs consensus 的预期差，无法判断宏观数据利好或利空；AAPL 与 XLK 的 T0/pre5 收益、基本面数据均缺失或技能超时，无任何被 supports/contradicts 连接的有效方向信号。按评分卡净分=0，无方向信号，故选 neutral。

### 5. `seed_cn_sh513050__f6ab2b0f7a`

- 事件：SH513050 2025-04-01 中国CPI居民消费价格指数月度公告
- 市场/类型：CN / 通胀数据意外
- T3 真实标签：**down**；CAR=-6.14%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/4；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件原文只有占位符，未提供CPI/PPI实际值、预期值与前值；T0当日行情、事件前漂移均缺失且技能调用失败，无任何可比较的方向信号。唯一的verified claim支持“不可判定”，needs_more claim仅为可证伪条件假设且无数据支撑，不能提取实质净分。净分=0，故判neutral。
- claim-v2 裁决摘要：事件正文仅含“PPI月度 | 统计局 预期:机构 前值:上月”，无实际读数与预期偏离幅度，无法判断“通胀数据意外”的方向；图内也无 SH513050 与沪深300基准的窗口行情，无法构造 benchmark-relative CAR。已连接的 claims 主要指向信息缺失与不可判断，没有提取出有效 up/down 方向信号，净分=0，故判定 neutral。

### 6. `seed_cn_sh516160__7ee13dfb0c`

- 事件：SH516160 2024-01-08 中国CPI/PPI月度经济数据
- 市场/类型：CN / 通胀数据意外
- T3 真实标签：**up**；CAR=5.63%；avg_all=up；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/5；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件正文仅含“PPI月度”字段标签，未提供实际公布值与机构预期的偏离方向，无法判断通胀数据“意外”是上偏还是下偏；行情数据获取失败，无T0及pre5漂移信号；证据图中无任何支持上行或下行的方向性claim，专家方向亦为neutral且置信度仅0.50。净分=0，无方向信号，故判定中性。
- claim-v2 裁决摘要：证据图中仅有的两条 claim 均为数据不足/无法判定，未提供任何 up/down 方向信号；事件原文仅为模板占位，无 CPI/PPI 实际值与预期差，T0 行情、事前漂移及标的识别均缺失。方向净分=0，且完全没有方向 claim 支撑，符合 neutral 条件，置信度维持 0.50。

## 时窗或因果链错配

T3 与更长窗口/共识标签不一致，或程序事件到 T+3 的传导链没有明确建模。

### 1. `seed_cn_920675_event_7c83103ede`

- 事件：688066 2026-06-22 秉扬科技:关于本次交易预计构成重大资产重组和关联交易但不构成重组上市的说明
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**down**；CAR=-25.60%；avg_all=down；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/2；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为程序性重组/关联交易定性公告，不构成重组上市；但公告正文截断、无交易规模与财务数据，事件研究及行情获取失败，缺失T0/T+3价格信号。现有证据仅确认合规定性，未形成可验证的up/down方向信号，净分为0，故判neutral。
- claim-v2 裁决摘要：事件仅为程序性重大资产重组与关联交易说明，未披露标的、对价及盈利预测等量化信息；证据图内无任何 up/down 方向 claim，多个 claims 明确指出方向信号弱或呈多空分歧，净分=0。虽然先验对普通并购略偏 down，但无具体资产质量/稀释证据支持，故不适用。按评分卡，无方向信号且净分=0时选择 neutral，置信度设为0.50。

### 2. `seed_cn_001331_event_06ea6568c3`

- 事件：001331 2026-06-04 胜通能源:关于七腾机器人有限公司要约收购结果暨股票继续停牌的公告
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=22.88%；avg_all=up；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：证据图中无任何被supports/contradicts连接的方向性claim，未给出要约价格、接受率、复牌时间及复牌后行情等关键定价信息；行情链路失败使T+3 CAR无可度量锚点。up/down信号均缺失，净分=0，按评分卡应选neutral。
- claim-v2 裁决摘要：证据图中无任何被 supports 支持且未被反驳的 up/down 方向 claim。标的继续停牌属已核实事实，T+3 窗口无该股收盘价序列，常规 benchmark-relative CAR 口径无法测算；要约收购结果、要约价及复牌时间均缺失，无法据此锚定方向。方向信号净分=0，故判定 neutral。

### 3. `seed_cn_300990_event_bdaf29e760`

- 事件：300990 2025-09-10 同飞股份:关于参加2025年河北辖区上市公司投资者网上集体接待日暨2025年半年报集体业绩说明会的公告
- 市场/类型：CN / 财报超预期/不及预期
- T3 真实标签：**up**；CAR=18.83%；avg_all=up；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=2/0；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为程序性投资者网上集体接待日暨半年报集体业绩说明会参与公告，未披露新增业绩数值；且行情与财务数据均缺失（T0涨跌、pre5漂移、完整正文），无法提取方向信号。event_type_l2标注存在张力但不足以作为证据。净分=0，无有效方向信号，故判neutral。
- claim-v2 裁决摘要：事件仅为参加河北辖区集体业绩说明会的流程性公告，text未披露任何财务数据；证据图中两条claim均为exploring，无supports/contradicts连接，无实质方向信号可提取，净分为0。虽event_type_l2标注为财报类，但缺乏业绩数值与可比基准，不能据此形成有效先验，故按规则判定为neutral。

### 4. `seed_cn_300792_event_102c2b88c8`

- 事件：300792 2026-02-07 壹网壹创:董事会关于本次交易符合《上市公司监管指引第9号—上市公司筹划和实施重大资产重组的监管要求》第四条规定的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**up**；CAR=14.13%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/1；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为壹网壹创重大资产重组的程序性合规说明，无交易定价、业绩承诺等实质条款；event_type_l2标签与正文性质不符，不触发方向先验。证据图中无任何 supports/contradicts 形成有效多空信号，净分为0，故判neutral。
- claim-v2 裁决摘要：净分=0。事件实为重大资产重组流程中的合规程序性说明（专项说明/独立意见），并非业绩指引；公告无新增财务条款、对价、业绩承诺或稀释信息，不构成实质性方向信号。证据图中三条核心claim均为非方向性：程序性披露信号弱、事前行情定价无法校准、标的财务细节未披露无法预判重组方向。无实质up/down claim可提取，故选择neutral。

### 5. `seed_cn_603268_event_a476dc67d2`

- 事件：603268 2025-04-22 松发股份:北京华亚正信资产评估有限公司关于上海证券交易所《关于广东松发陶瓷股份有限公司重大资产置换及发行股份购买资产并募集配套资金暨关联交易申请的并购重组委会议意见落实函》之核查意见
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**down**；CAR=-11.81%；avg_all=down；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/2；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为重组委意见落实函的评估机构核查意见，属程序性披露，公告本身无新增业绩、估值等硬数据。图内两条方向性推断均为需验证的潜在渠道，缺乏实质证据支持：正面渠道依赖市场对重组过会确定性的解读，但其强度无法量化；另有明确推断认为该程序性公告大概率落在±50bps中性区间。综合方向信号净分为0，无实质证据支撑的明确多空方向，故判neutral。
- claim-v2 裁决摘要：事件为并购重组委意见落实函的核查意见，属流程性文件；证据图中各 claim 均未提供方向性信号，且事件日行情、交易方案细节等关键信息缺失，无法形成 up/down 净分。净分=0，按评分卡应判 neutral。

### 6. `seed_cn_600186_event_156d2b22c9`

- 事件：600186 2025-04-07 莲花控股:莲花控股股份有限公司2025年第一季度业绩预告
- 市场/类型：CN / 财报超预期/不及预期
- T3 真实标签：**up**；CAR=11.56%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=False/False；v2 contradicts=0
- v0 裁决摘要：事件为2025Q1业绩预告，但正文未披露净利润/营收同比等财务数值；行情技能超时，无T0及pre5信号；新闻内容未展开。两位专家均给neutral@0.50，净方向分数为0，无实质方向信号，按评分卡判neutral，confidence=0.50。
- claim-v2 裁决摘要：事件文本仅为“2025年第一季度业绩预告”标题，未披露净利润、营收或同比增速等任何量化信息；event_scout与fundamentals_analyst均因取数技能超时未能补充有效财务数据，图中也无实质性方向信号。按评分卡，未提取到up/down方向信号，净分=0，且不存在有实质证据支持的方向claim，故判neutral。先验依赖业绩改善或miss证据，当前无证据支持，不可启用。

## 冲突证据处理错误

claim-v2 图中存在 contradicts，但裁决没有形成可复核的冲突净分或仍直接弃权。

### 1. `seed_cn_sh513050__e6279c3fe6`

- 事件：SH513050 2025-11-15 中国PPI工业生产者价格指数月度公告
- 市场/类型：CN / 通胀数据意外
- T3 真实标签：**down**；CAR=-2.80%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/4；sufficient v0/v2=True/False；v2 contradicts=4
- v0 裁决摘要：事件原文为占位文本，缺少实际PPI数值与预期值，无法计算意外幅度；SH513050行情链路失败，T0及pre5信号缺失；相关专家摘要未展开。已有claim均未形成有效方向证据，净分为0，符合neutral条件。PPI对中概互联网ETF传导偏弱，进一步支持不强行判定方向。
- claim-v2 裁决摘要：事件原文为模板占位，PPI实际值、前值、预期值全部缺失，无法计算预期差；事件研究接口两次失败，T0行情与事前漂移均不可得，也无中概板块基本面或宏观传导证据。所有claims均为insufficient且无任何up/down方向信号，净分=0，故判定neutral。

### 2. `seed_cn_920030_event_f7092d0cfc`

- 事件：603132 2025-02-21 德众汽车:2024年年度业绩快报公告
- 市场/类型：CN / 财报超预期/不及预期
- T3 真实标签：**up**；CAR=1.02%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=True/False；v2 contradicts=4
- v0 裁决摘要：事件公告仅为标题性文本，未披露营收、净利润、同比等关键财务数值，缺乏可提取的基本面方向信号；同时 event_study 两次失败导致 T0 行情与事前漂移均不可用，无法计算 benchmark-relative CAR 的方向。supports/contradicts 中不存在有实质证据支持且未被反驳的方向性 claim，净分为 0，按评分卡应判 neutral。
- claim-v2 裁决摘要：证据图中无任何被实质支持的 up/down 方向 claim；业绩快报正文未披露营收/净利润等数值，无法判断是否超预期；个股与沪深300行情均获取失败，缺少T+3 CAR计算基础。按评分卡净分=0，无方向信号，故选 neutral。

### 3. `seed_cn_300620_event_e2cfab102a`

- 事件：300620 2025-11-21 光库科技:关于披露重组报告书暨一般风险提示性公告
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=33.15%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/1；sufficient v0/v2=True/False；v2 contradicts=3
- v0 裁决摘要：证据图中无任何被 supports/contradicts 连接的多空方向 claim；事件仅为流程性“披露重组报告书暨一般风险提示性公告”，未提供标的资产、交易对价或业绩承诺等基本面数值，原始行情信号（pre5 漂移、T0 相对收益）亦缺失。按评分卡规则，无有效方向信号，净分=0，故判定为 neutral。
- claim-v2 裁决摘要：净分=0：证据图中C1（verified）认定本次公告为流程性风险提示，无盈利/估值等增量信息，不构成方向信号；C2（needs_more）指出方向信号弱、T+3 CAR落于中性区间概率偏高；C3（verified）表明关键数据缺失。无任何支持up或down的实质方向claim，不适用并购先验，故判定neutral。

### 4. `seed_cn_002222_event_d52c493619`

- 事件：002222 2026-03-06 福晶科技:2025年度业绩快报
- 市场/类型：CN / 财报超预期/不及预期
- T3 真实标签：**down**；CAR=-9.44%；avg_all=down；consensus66=neutral
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=3/2；sufficient v0/v2=True/False；v2 contradicts=3
- v0 裁决摘要：事件原文仅含业绩快报标题，无净利润/营收/同比等财务数值，无法判断超预期或不及预期方向；证据图中所有 claims 均为 insufficient/needs_more，无任何可计分的 up/down 方向信号，净分=0，且无实质证据支持的方向 claim，故按规则判定 neutral。
- claim-v2 裁决摘要：事件原文仅含标题，未披露净利润/营收/同比增速，无法锚定超预期或不及预期；事件类别标签为‘财报超预期/不及预期’但无数值支撑。event_scout 研究摘要因包含 2026Q1 等事件日后信息，违反严格 as-of 约束，不能用于方向判断。图中无已被 supports 连接且未被反驳的具体方向 claim，净分=0，故判 neutral。

### 5. `seed_us_msft_event_f6f1e4d8cc`

- 事件：MSFT 2024-02-13 Tender Offer/Acquisition Reports
- 市场/类型：US / 并购/分拆/再融资
- T3 真实标签：**down**；CAR=-2.74%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=2/2；sufficient v0/v2=False/False；v2 contradicts=3
- v0 裁决摘要：事件仅为SC 13G/A被动持股合规披露，无实质基本面或交易条款信息；图中无支持up/down的实质方向信号，market_analyst的up判断置信度仅0.52且缺乏数据支撑，可证伪性弱。净分=0，按规则选择neutral。
- claim-v2 裁决摘要：（空）

### 6. `seed_us_pep__0f097b111b`

- 事件：PEP 2025-07-01 US Take-private / Spin-off Filings Summary
- 市场/类型：US / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=2.21%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=4/3；sufficient v0/v2=False/False；v2 contradicts=3
- v0 裁决摘要：事件为程序性/汇总性质的M&A filing roundup，未含PEP个体基本面或具体交易条款；T0及事前漂移数值缺失，无法确认take-private/spin-off实质方向。信号净分为0，按规则选neutral。
- claim-v2 裁决摘要：事件为程序性并购/分拆文件汇总，正文无交易条款或财务数字，缺乏基本面锚点；market_research与stock_overview四次调用超时，event_study/ar_decomposer/drift_context虽有返回但未展开具体漂移数值，无法确认方向信号。综合supports/contradicts：程序性文本支持中性预判，漂移类线索仅提示方向置信度下调，均未形成有效up/down信号。方向分up=0、down=0，净

## 信息较充分但推理/符号错误

至少一版自报 sufficient 或给出明确方向，但方向先验、漂移或因果符号映射错误。

### 1. `seed_cn_300889_event_260376c5a3`

- 事件：300889 2025-12-03 爱克股份:董事会关于本次交易符合《上市公司监管指引第9号—上市公司筹划和实施重大资产重组的监管要求》第四条规定的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**down**；CAR=-11.16%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`up`
- 图谱状态：missing v0/v2=3/2；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：净分=0：证据图内无支持 up 或 down 的实质性方向 claim。C1 基于事件为程序性重组合规性说明、正文无业绩/交易细节，判定 T+3 benchmark-relative CAR 大概率落在 ±50bps 中性区间；C2 仅指出 event_type_l2 分类与正文语义不符，不构成收益方向信号；C3 因缺少标的财务与交易细节维持 needs_more。MISSING 项（T0 漂移数值、交易核心条款、首次披露时点）均无法提
- claim-v2 裁决摘要：事件为重组合规性程序说明，但严格as-of行情证据显示事件日T0主动收益+7.91%、AR+8.72%，事前pre5/+15.90%和pre20/+33.47%漂移一致向上，drift_score=4，形成实质未反驳的up方向信号。不过公告信息增量有限，重组标的条款缺失，且公司当期基本面亏损，事件前已大幅上涨可能部分定价上行空间，因此降低置信度。净分：up有强信号（+3），无有效down信号，故方向为up。

### 2. `seed_cn_301309_event_89c56bf4e3`

- 事件：301309 2026-04-08 万得凯:董事会关于本次交易符合《上市公司监管指引第9号—上市公司筹划和实施重大资产重组的监管要求》第四条规定的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**down**；CAR=-11.12%；avg_all=down；consensus66=down
- 预测：v0=`neutral`；claim-v2=`up`
- 图谱状态：missing v0/v2=2/2；sufficient v0/v2=False/True；v2 contradicts=0
- v0 裁决摘要：事件公告为重大资产重组配套的程序性合规专项说明，标题与披露品类均指向流程性文件，不包含新增业绩指引或交易条款信息。event_type_l2字段为“公司指引上调/下调”，但该字段与标题语义冲突，已被判定为分类噪音，不宜施加方向先验。证据图中无任何支持up或down方向的有效信号，且T0/pre5等行情数值缺失，无法量化重组预期漂移。净分为0，按裁决规则应输出中性。
- claim-v2 裁决摘要：按评分卡：公告为重大资产重组程序性合规说明，未含对价、标的资产或盈利预测等实质增量信息，事件标签“指引上调/下调”与正文不符，不计为强信号；但公告确认本次交易符合监管第四条要求、重组仍在推进，属于中性偏正面的流程信号，弱正向计1分；无终止、监管否定或摊薄利空等向下证据，down计0分；净分=+1，故方向为up。因信息含量低且缺乏交易实质条款，置信度取弱区间0.62。

### 3. `seed_cn_000612_event_a396bc2195`

- 事件：000612 2025-08-23 焦作万方:焦作万方铝业股份有限公司董事会关于本次交易相关主体不存在《上市公司监管指引第7号——上市公司重大资产重组相关股票异常交易监管》第十二条和《深圳证券交易所上市公司自律监管指引第8号——重大资产重组》第三十条规定情形的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**down**；CAR=-8.93%；avg_all=down；consensus66=down
- 预测：v0=`up`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=2/2；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件为重大资产重组推进中的程序性合规说明，声明相关主体不存在监管指引所列规定情形，属边际正面但信息增量很小。证据图中无新增盈利/对价等基本面数据，也无被反驳的实质方向信号；仅有一条弱正面 claim，净分约 up 1 分，故弱看多。由于事件本身为流程性披露，预期 T+3 超额收益接近中性，但方向略偏多，置信度取弱方向区间。事件类型标签与公告实际性质不符，不触发额外先验。
- claim-v2 裁决摘要：事件为重大资产重组的程序性合规核查说明，公告仅确认相关主体不存在异常交易监管规定情形，不含净利润、营收等基本面数值，也无交易方案细节。证据图中三条claim均指向该事件为流程性披露，不改变已有重组预期，未形成明确向上或向下信号；无可读行情数值校准。按评分卡无方向性实质证据，净分=0，故判neutral。

### 4. `seed_cn_601198_event_7edeb29dba`

- 事件：601198 2025-12-18 东兴证券:东兴证券董事会关于本次交易信息公布前股票价格波动是否达到《上海证券交易所上市公司自律监管指引第6号——重大资产重组》相关标准的说明
- 市场/类型：CN / 公司指引上调/下调
- T3 真实标签：**up**；CAR=6.40%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`down`
- 图谱状态：missing v0/v2=3/2；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：证据图中 C1 仅认定为程序性波动核查说明，方向信号弱且不确定，C1 状态 needs_more；C2 verified 指出 event_text 截断、E4/E6 数值缺失、E7 失败，无法支撑任何 up/down 定量判断。无被支持且未反驳的方向 claim，up 分与 down 分均为 0，净分=0，因此选 neutral。缺失 T0/pre5 漂移与重组细节，不补充事件日后信息。
- claim-v2 裁决摘要：净分依据：仅有方向性 claim 支持下行，按弱信号计 1 分；无 up 方向信号，up 0 分，净分 -1，故选 down。事件标题为重组前股价波动核查公告，提示事件前已有股价异动、预期可能部分消化，存在 buy-the-rumor/sell-the-news 风险；A股普通并购/资产重组若无优质资产注入证据先验偏 down。event_type_l2 虽标为指引调整，但正文未提供具体上/下调数值，不能构成 up 信号。缺全文及 pr

### 5. `seed_cn_601888__e2c9b782a8`

- 事件：601888 2024-07-01 中国上市公司发行股份购买资产公告
- 市场/类型：CN / 并购/分拆/再融资
- T3 真实标签：**up**；CAR=5.93%；avg_all=up；consensus66=up
- 预测：v0=`neutral`；claim-v2=`down`
- 图谱状态：missing v0/v2=3/3；sufficient v0/v2=True/False；v2 contradicts=0
- v0 裁决摘要：事件图中无任何被 supports/contradicts 连接的方向性 claim；三个 claim 均指出事件正文缺少交易对价/标的盈利等量化条款，且 T0/pre5 等行情数值未展开，无法构成 up 或 down 信号。净分=0 且完全无方向信号，依评分卡判 neutral；软先验因缺少稀释或优质资产注入的实质证据不可启用。
- claim-v2 裁决摘要：净分依据：down方向信号共3分——(1) event_study/ar_decomposer 信息显示 T0 个股+0.02% vs 基准+0.48%（AR=-0.46%），且 pre5/pre20 漂移分别为-3.35%/-13.29%，向下趋势一致，该事件研究证据给 down 中等信号2分；(2) 基本面分析师显示 2024Q1 营收同比-9.45%、净利同比-1.25%，盈利动能弱化，给 down 弱信号1分。up方向无有效证据

### 6. `seed_cn_001288_event_05816fbd3d`

- 事件：001288 2025-01-10 运机集团:2024年度业绩预告
- 市场/类型：CN / 财报超预期/不及预期
- T3 真实标签：**down**；CAR=-5.54%；avg_all=down；consensus66=down
- 预测：v0=`up`；claim-v2=`neutral`
- 图谱状态：missing v0/v2=2/3；sufficient v0/v2=True/False；v2 contradicts=1
- v0 裁决摘要：证据图中有 market_analyst 方向预判为 up（置信 0.52）及 event_study_skill 返回支持信号，形成弱正向净分；同时无 contradicts 证据。但 as_of 事件原文仅含业绩预告标题，无净利润/同比增速等财务数值，且 T0 行情与漂移数据缺失，方向上偏 up 但证据强度弱。按弱方向规则，给 up 且置信度取下限 0.60。
- claim-v2 裁决摘要：事件正文仅含业绩预告标题，无净利润/营收/同比等量化数据；stock_overview 与 event_study_skill 均超时或未找到标的，无法获得 T0 行情及 pre5/pre20 漂移。市场中唯一 up 方向来自专家，但置信度仅 0.52，且被判定为接近中性、不可作为方向先验。按评分卡，无实质证据支持或反驳的方向 claim，净分=0，故判中性。
