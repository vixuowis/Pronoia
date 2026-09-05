#!/usr/bin/env python3
"""Build the reorganized document XML: comparison moved to front, unified metrics, merged improvement chapter."""
import re

SEC = '/tmp/nx8_sections'

def read(fn):
    return open(f'{SEC}/{fn}', encoding='utf-8').read()

def cell(content, colspan=None, rowspan=None):
    a = ''
    if colspan: a += f' colspan="{colspan}"'
    if rowspan: a += f' rowspan="{rowspan}"'
    return f'<td{a} vertical-align="top"><p>{content}</p></td>'

def tbl(headers, rows):
    ncol = len(headers)
    cols = '<colgroup>' + '<col/>' * ncol + '</colgroup>'
    thead = '<thead><tr>' + ''.join(f'<th vertical-align="top"><p>{h}</p></th>' for h in headers) + '</tr></thead>'
    tbody = '<tbody>' + ''.join('<tr>' + ''.join(r) + '</tr>' for r in rows) + '</tbody>'
    return f'<table>{cols}{thead}{tbody}</table>'

parts = []
A = parts.append

# ============================ 1. 总体结论 ============================
A('<h1>总体结论</h1>'
  '<p>本报告基于 CN 700 条 + US 300 条的完整事件池，使用 team_full trajectory runner 在 4 并发下完成全量推理，并通过 avgCAR 多 horizon 标签体系打标。主证据 horizon = <b>avg_all</b>，CAR epsilon = 0.5%。全文指标口径统一，定义见「数据集与实验设置 · 指标口径统一定义」。</p>'
  '<callout emoji="🎯"><p><b>三条核心结论</b>：</p>'
  '<p>1. <b>出手即准，但出手过少</b>。T+3 Lenient ACC = 70.9%（249/351，双方都出手时命中），Non-Neutral ACC = 62.7%（249/397）。但 pred=neutral 高达 60.3%（603/1000），导致 Strict ACC 被稀释至 T+3=39.3% / avg_all=31.4%。</p>'
  '<p>2. <b>公司事件可用，宏观事件明显偏弱</b>。公司类三类（指引/并购/财报，合计 580 条）T+3 Strict ACC = 46.4%（269/580）、avg_all = 37.8%；宏观三类（政策利率/就业/通胀，合计 420 条）T+3 Strict = 29.5%（124/420）、avg_all = 22.6%，且模型对宏观事件 89%~94% 判 neutral、几乎不出手（非中性预测每类仅 8~16 条）。</p>'
  '<p>3. <b>判别力随 horizon 快速衰减，校准不足</b>。AUC（双方非中性样本口径）从 T+1=0.773、T+3=0.730 衰减至 T+60=0.489（≈随机），avg_all=0.590；conf≥0.75 时 Non-Neutral ACC 升至 84.6%（T+3），高分样本确实更可信，可做运营级 gate trade-off。Spearman ρ（conf↔|CAR|）= 0.287，距 ρ≥0.5 的生产目标仍有差距。</p></callout>'
  '<h2>关键指标速览（主证据 avg_all）</h2>')
A(tbl(['指标', 'T+3', 'avg_all（主）', 'T+60'], [
    [cell('Strict ACC'), cell('<b>39.3%</b>（393/1000）'), cell('<b>31.4%</b>（314/1000）'), cell('24.2%（239/989*）')],
    [cell('Lenient ACC（双方出手）'), cell('<b>70.9%</b>（249/351）'), cell('<b>60.6%</b>（220/363）'), cell('49.5%（191/386）')],
    [cell('Non-Neutral Pred ACC'), cell('<b>62.7%</b>（249/397）'), cell('<b>55.4%</b>（220/397）'), cell('48.1%（191/397）')],
    [cell('AUC（up vs down 二分类）'), cell('<b>0.730</b>（n=351）'), cell('<b>0.590</b>（n=363）'), cell('0.489（n=386）')],
    [cell('F1 macro（3-class）'), cell('0.391'), cell('0.312'), cell('—')],
    [cell('Spearman ρ（conf ↔ |CAR|）'), cell('0.308'), cell('0.287'), cell('0.283')],
    [cell('pred=neutral 占比'), cell('60.3%（603/1000，所有 horizon 一致）', colspan=3)],
]))
A('<p>*注：11 条事件 car_t60 为空（均为 CN，长期窗口数据不足），T+60 各指标按有效样本 989 计。AUC 口径为「pred 与 GT 均非中性」的样本（up vs down，score = 带方向符号的 confidence）。</p>')

# ============================ 2. 与上一版对比（前置） ============================
A('<h1>与上一版报告（终期 v1）的多维度对比</h1>'
  '<p>对比对象：<b>上一版报告</b>「FEVER 事件方向预测系统 · 1000 条回测终期报告（含 Case Study + Trajectory 分析）」（<a href="https://icnyn86gi2iw.feishu.cn/docx/NQMldIKQ8on4VDx2IN5cbH6knsh">NQMldIKQ8</a>，后文简称<b>旧版</b>）vs <b>本版报告</b>（team_full runner · 1000 条 TF CN/US，后文简称<b>新版</b>）。</p>'
  '<callout emoji="💡"><p><b>重要前提差异（必看）</b>：</p><ol>'
  '<li seq="1"><b>样本量 &amp; 构成：</b>旧版 n=952，场景为「A 股并购 471 / A 股财报 181 / 美股并购 265 / 美股宏观 35」四类；新版 n=1000，覆盖<b>6 个事件类型 × 2 个市场</b>（A 股 700 / 美股 300），<b>新增政策利率 / 通胀 / 增长就业 3 类宏观样本共 420 条</b>（旧版宏观仅 35 条）。宏观类 Strict ACC 显著低于公司类，是新版整体 ACC 的最大结构性拖累。</li>'
  '<li><b>运行配置：</b>旧版有 conf Gate 前置拦截（0.50 / 0.60 两档对比）；新版 team_full runner 默认无 Gate，neutral 由模型经三重规则自决。</li>'
  '<li><b>Horizon 主口径：</b>旧版主汇报口径 = <b>Strict T+3 ACC</b>；新版主汇报口径 = <b>avg_all Strict ACC</b>，同时完整保留 T+1/3/5/7/15/30/60 七档。本章按<b>同口径 Strict T+3 ACC</b>对齐。</li>'
  '<li><b>Strict 定义一致：</b>两版 Strict ACC 均为 pred == GT（含 neutral==neutral 判对），数字可直接对比。</li>'
  '</ol></callout>')
A('<h2>一、核心指标对比（对齐 Strict T+3 ACC）</h2>')
A(tbl(['指标', '旧版 · Gate 0.60（拦截档）', '旧版 · Gate 0.50（推荐档）', '新版 · team_full（无 Gate）', '新版 − 旧版推荐档'], [
    [cell('总样本量 n'), cell('952'), cell('952'), cell('1000'), cell('样本构成差异大')],
    [cell('Strict T+3 ACC'), cell('384/952 = 40.3%'), cell('475/952 = <b>49.9%</b>'), cell('393/1000 = <b>39.3%</b>'), cell('<b>−10.6pp</b>')],
    [cell('Wilson 95% CI 下界'), cell('37.26%'), cell('46.73%'), cell('36.3%'), cell('−10.4pp')],
    [cell('Non-Neutral（NN）T+3 ACC'), cell('316/511 = 61.8%'), cell('444/746 = 59.5%'), cell('249/397 = <b>62.7%</b>'), cell('<b>+3.2pp</b>')],
    [cell('pred=neutral 占比'), cell('46.3%'), cell('21.6%'), cell('<b>60.3%</b>'), cell('+38.7pp')],
    [cell('avg_all Strict ACC'), cell('未披露'), cell('未披露'), cell('<b>31.4%</b>（314/1000）'), cell('新口径，无可比')],
]))
A('<callout emoji="📊"><p><b>结论：表面 −10.6pp ≠ 算法变差，拆开是「一升一降」：</b></p><ol>'
  '<li seq="1"><b>敢出手时更准：</b>Non-Neutral T+3 ACC 新版 62.7%，高于旧版 Gate 0.50 的 59.5%（+3.2pp），也高于 Gate 0.60 的 61.8%（+0.9pp）——新版真正给 up/down 方向时，单条精度为两版最高；</li>'
  '<li><b>无 Gate 已达到旧版强拦截档的整体水平：</b>新版 Strict T+3 = 39.3%，与旧版 Gate 0.60 的 40.3% 基本持平（−1.0pp），而旧版该档是靠拦截 274 条换来的（其中 86% 为误拦、128 条本可判对）；</li>'
  '<li><b>与旧版推荐档的 10.6pp 差距来自两处结构性原因：</b>① 新增 420 条宏观样本（T+3 Strict 29.5%，比公司类低 16.9pp）；② 模型自决 neutral 占比 60.3%，远高于旧版 Gate 0.50 的 21.6%，大量「本可判对」的中间幅度样本被判中性（详见三、|CAR| 分桶对比）。</li>'
  '</ol></callout>')
A('<h2>二、分场景对比（对齐市场 × 事件类型，T+3 Strict）</h2>'
  '<p>在<b>双方都有的重叠场景</b>下对比（A 股并购 / A 股财报 / 美股并购），并对新版独有场景单列。</p>')
A(tbl(['场景', '旧版 n', '旧版 Strict ACC', '新版 n', '新版 Strict T+3 ACC', 'Δ / 备注'], [
    [cell('A 股并购'), cell('471'), cell('39.9%'), cell('154'), cell('43.5%（67/154）'), cell('<b>+3.6pp</b>（新版反超）')],
    [cell('A 股财报'), cell('181'), cell('48.6%'), cell('154'), cell('50.6%（78/154）'), cell('<b>+2.0pp</b>（新版反超）')],
    [cell('美股并购'), cell('265'), cell('66.4%'), cell('66'), cell('51.5%（34/66）'), cell('<b>−14.9pp</b>（n 缩小 4×、样本构成变化 + 新版更保守）')],
    [cell('美股宏观（旧版聚合）'), cell('35'), cell('65.7%'), cell('42×3 = 126'), cell('利率 31.0% / 通胀 54.8% / 就业 35.7%'), cell('样本构成完全不同，不可直接比；通胀小样本波动大')],
    [cell('A 股公司指引'), cell('未单独披露'), cell('—'), cell('98'), cell('<b>53.1%</b>（52/98）'), cell('新版独有亮点（12 个市场×类型组合中最高）')],
    [cell('A 股政策利率'), cell('未覆盖'), cell('—'), cell('98'), cell('34.7%（34/98）'), cell('新版新增')],
    [cell('A 股通胀数据'), cell('未覆盖'), cell('—'), cell('98'), cell('23.5%（23/98）'), cell('新版新增（宏观短板区）')],
    [cell('A 股增长/就业'), cell('未覆盖'), cell('—'), cell('98'), cell('16.3%（16/98）'), cell('新版新增（宏观短板区）')],
    [cell('美股公司指引'), cell('未单独披露'), cell('—'), cell('42'), cell('33.3%（14/42）'), cell('新版独有')],
    [cell('美股财报'), cell('未单独披露'), cell('—'), cell('66'), cell('36.4%（24/66）'), cell('新版独有')],
]))
A('<p><b>重叠的 3 个场景中 2 个反超</b>（A 股并购 +3.6pp、A 股财报 +2.0pp）；美股并购 −14.9pp 主要因新版该场景样本从 265 条缩至 66 条、事件构成变化（再融资/分拆类占比升高），叠加新版整体更保守的 neutral 策略。</p>')
A('<h2>三、|CAR| 幅度分桶对比（T+3 Strict）</h2>')
A(tbl(['|CAR| T+3 幅度档', '旧版 n', '旧版 Strict ACC', '新版 n', '新版 Strict T+3 ACC', 'Δ &amp; 备注'], [
    [cell('&lt;0.5%（XSMALL / 噪声）'), cell('142'), cell('22%'), cell('190'), cell('<b>75.8%</b>（144/190）'), cell('<b>+53.8pp</b>（新版「该中性时中性」，噪声区白捡正确）')],
    [cell('0.5~1%（SMALL）'), cell('75'), cell('40%'), cell('147'), cell('17.7%（26/147）'), cell('−22.3pp')],
    [cell('1~3%（MED / 黄金区）'), cell('347'), cell('62%'), cell('331'), cell('24.2%（80/331）'), cell('<b>−37.8pp</b>（差距最大区）')],
    [cell('3~5%（LARGE）'), cell('191'), cell('49%'), cell('150'), cell('30.7%（46/150）'), cell('−18.3pp')],
    [cell('5~10%（XL）'), cell('135'), cell('55%'), cell('118'), cell('47.5%（56/118）'), cell('−7.5pp（差距收窄）')],
    [cell('≥10%（XXL / 极端）'), cell('62'), cell('55%'), cell('64'), cell('<b>64.1%</b>（41/64）'), cell('<b>+9.1pp</b>（新版反超；大极端区两版能力一致偏强）')],
]))
A('<p><b>关键曲线观察：</b>新版呈「<b>U 型</b>」——噪声区（&lt;0.5%）和极端大波动区（≥10%）优于旧版，中间幅度区（0.5%~5%）明显弱于旧版。原因：旧版 Gate 0.50 强制出手，在 GT 大多非中性的中间区拿到高 Strict；新版模型对中间幅度事件大量判 neutral（GT 却非中性）而被计错。<b>中间区的正确策略既不是全出手也不是全中性</b>，这正是 L1-3「幅度自适应阈值路由」的直接收益区。</p>')
A('<h2>四、T+N 全景对比（新版披露更完整）</h2>'
  '<p>旧版仅披露 T+3 主口径；新版披露 T+1/3/5/7/15/30/60 七档 + avg_short/avg_mid/avg_long/avg_all 四档共 11 个 horizon 的 Strict ACC（旧版 T+3 取 Gate 0.50 推荐档）：</p>')
A(tbl(['Horizon', '旧版（仅披露 T+3）', '新版 Strict ACC（k/n）', '新版趋势解读'], [
    [cell('T+1'), cell('—'), cell('<b>47.9%</b>（479/1000）'), cell('短期冲击最准')],
    [cell('<b>T+3</b>（双方主口径）'), cell('<b>49.9%</b>（475/952）'), cell('<b>39.3%</b>（393/1000）'), cell('差距 = 宏观新增 420 条 + 中性化过度，见上')],
    [cell('T+5'), cell('—'), cell('37.5%（375/1000）'), cell('单调衰减')],
    [cell('T+7'), cell('—'), cell('33.5%（335/1000）'), cell('—')],
    [cell('T+15'), cell('—'), cell('28.3%（283/1000）'), cell('—')],
    [cell('T+30'), cell('—'), cell('25.8%（258/1000）'), cell('—')],
    [cell('T+60'), cell('—'), cell('24.2%（239/989*）'), cell('*11 条 car_t60 为空；T+1→T+60 衰减约 24pp，符合事件 alpha 衰减先验')],
    [cell('avg_short（T+1/3/5）'), cell('—'), cell('36.6%（366/1000）'), cell('新口径')],
    [cell('<b>avg_all</b>（新版主口径）'), cell('—'), cell('<b>31.4%</b>（314/1000）'), cell('新口径，旧版无可比')],
]))
A('<h2>五、Confidence 阈值 &amp; 校准对比</h2><ul>'
  '<li><b>旧版机制：</b>Gate ∈ {0.50, 0.60} 两档 conf 前置拦截。Gate 从 0.60 降到 0.50：Strict ACC 40.3% → 49.9%（+9.6pp），Non-Neutral ACC 61.8% → 59.5%（−2.3pp）。Gate 0.60 严重过拦：274 条被拦截中 86% 为误拦、128 条本可判对。</li>'
  '<li><b>新版机制：</b>conf 由模型自报（集中在 0.50~0.80），无前置 Gate。Non-Neutral ACC = 62.7%，超过旧版两档；但模型自决 neutral 60.3% 远高于旧版 Gate 0.50 的 21.6%，是 Strict 偏低的核心。运营档 conf≥0.65 时 NN-ACC = 70.4%（覆盖 16.2%）、conf≥0.75 时 84.6%（覆盖 2.6%）。</li>'
  '<li><b>校准：</b>新版 Spearman(conf, |CAR|) = 0.287（avg_all），低于 ρ≥0.5 的生产目标；高置信错误仍存在（如 B01 conf=0.74 / B04 conf=0.72 判错），对应 L1-6 查表校准。</li>'
  '</ul>')
A('<h2>六、对比总结 &amp; 下一步优先项</h2>')
A(tbl(['维度', '新版优势（保留 &amp; 发扬）', '新版问题（L1 层即可修复）'], [
    [cell('单条判断质量'), cell('<b>NN T+3 ACC = 62.7%</b>，超旧版 Gate 0.60 的 61.8% 和 Gate 0.50 的 59.5%'), cell('neutral 过度保守（60.3% vs 旧版 21.6%），放弃大量可出手机会 → L1-3 幅度自适应阈值路由')],
    [cell('重叠场景'), cell('A 股并购 +3.6pp、A 股财报 +2.0pp 反超；≥10% 极端档 64.1% 反超'), cell('美股并购 −14.9pp；中间幅度区（0.5%~5%）差 18~38pp → L1-1 先验分桶 + L1-3')],
    [cell('覆盖广度'), cell('4 类场景 → <b>6 类 × 2 市场 12 组合</b>；11 档 horizon 全披露；A 股指引 53.1% 亮点'), cell('宏观三类 420 条 T+3 Strict 22~34%（公司类 46.4%），系统性拖低总体 → L1-5 Schema Guard + L1-1 宏观专属先验')],
    [cell('数据与系统'), cell('preds/labels/events 三 JSONL 完整落盘 + 847 个 trajectory 断点 + metrics 结构化，每次回测可<b>自动产 priors / thresholds / calibration 查表</b>，可自进化'), cell('脏数据（symbol 串扰 / 类型误标 / 占位文本）未被 Guard，是 B01/B05/B06/B07/B08 共性根因 → L1-5')],
    [cell('运营建议'), cell('conf≥0.65 运营档 T+3 NN-ACC 70.4%，高于旧版 Gate 0.60 的 61.8%'), cell('高置信错误 2/10（B01/B04），需校准 → L1-6')],
]))
A('<callout emoji="🎯"><p><b>结论一句话：</b>新版「<b>出手即更准</b>」（NN-ACC 62.7% &gt; 旧版两档）且「<b>该中性时中性</b>」（噪声区 +53.8pp、极端区 +9.1pp），但「<b>中间幅度区过度放弃出手</b>」（1~3% 档 −37.8pp）+「<b>新增宏观 420 条是结构性拖累</b>」（T+3 29.5%）。三者叠加使表面 Strict T+3 从 49.9% → 39.3%（−10.6pp）。按 L1 层 7 项 Quick Wins（不动模型）预计 3~5 天把 neutral 从 60.3% 压回 40~45%、Strict T+3 回到 45%+，同时保持 NN-ACC 62%+ 优势。</p></callout>')

# ============================ 3. 数据集与实验设置 ============================
sec01 = read('01.xml')
sec01 = sec01.replace('_trajectory_ckpt_tf_cn_us_1000_v1/（1000 个完整 JSON）',
                      '_trajectory_ckpt_tf_cn_us_1000_v1/（847 个 JSON，回测过程增量落盘）')
A(sec01)
A('<h2>指标口径统一定义（全文唯一口径）</h2>'
  '<p>为避免歧义，全文所有表格统一使用以下口径（T+N 指事件后第 N 个交易日）：</p><ol>'
  '<li seq="1"><b>Strict ACC</b>：pred_direction == label_tN 即判对（<b>含 neutral==neutral 判对</b>）；分母 = 该 horizon 有效标签样本数（T+60 为 989，其余 horizon 为 1000）。</li>'
  '<li><b>Non-Neutral ACC（NN-ACC）</b>：pred ≠ neutral 的样本中 pred == GT 的比例；分母 = 397（全部非中性预测，与 horizon 无关）。</li>'
  '<li><b>Lenient ACC</b>：pred ≠ neutral 且 GT ≠ neutral 的样本中 pred == GT 的比例；分母随 horizon 变化（338~386）。</li>'
  '<li><b>AUC</b>：up vs down 二分类，score = 带方向符号的 confidence（up 为 +conf，down 为 −conf）；<b>仅统计 pred 与 GT 均非中性的样本</b>（n=338~386）。子集样本不足（&lt;4 对）时标 n/a。</li>'
  '<li><b>F1</b>：3-class（up/neutral/down），与 Strict 同口径；macro = 三类算术平均。</li>'
  '<li><b>Spearman ρ</b>：confidence 与 |CAR| 的等级相关，全样本 1000 条。</li>'
  '<li><b>consensus66</b>：以 66% 分析师共识方向作为预测的对照基准（仅在多 horizon 总表出现）。</li>'
  '</ol>'
  '<callout emoji="📌"><p>中性判定：CAR epsilon = 0.5%，即 |CAR| &lt; 0.5% 时 Oracle 标签为 neutral。当前模型三重 neutral gate（结构化 |net| &lt; 0.5、conf &lt; 0.60、矛盾证据 ≥ 2）叠加后输出 60.3% neutral。</p></callout>')

# ============================ 4. 多时间窗口 ============================
A('<h1>多时间窗口 Strict + Lenient ACC 对比</h1>')
A(tbl(['Horizon', 'Strict ACC', 'Strict k/n', 'Lenient ACC', 'Lenient k/n', '趋势'], [
    [cell('T+1'), cell('<b>47.9%</b>'), cell('479 / 1000'), cell('<b>75.7%</b>'), cell('256 / 338'), cell('短期最强 ✅')],
    [cell('T+3'), cell('39.3%'), cell('393 / 1000'), cell('70.9%'), cell('249 / 351'), cell('较强')],
    [cell('T+5'), cell('37.5%'), cell('375 / 1000'), cell('67.6%'), cell('238 / 352'), cell('下行')],
    [cell('T+7'), cell('33.5%'), cell('335 / 1000'), cell('62.8%'), cell('226 / 360'), cell('下行')],
    [cell('T+15'), cell('28.3%'), cell('283 / 1000'), cell('57.2%'), cell('215 / 376'), cell('下行')],
    [cell('T+30'), cell('25.8%'), cell('258 / 1000'), cell('56.1%'), cell('212 / 378'), cell('下行')],
    [cell('T+60'), cell('24.2%'), cell('239 / 989*'), cell('49.5%'), cell('191 / 386'), cell('最弱')],
    [cell('avg_short（T+1/3/5）'), cell('36.6%'), cell('366 / 1000'), cell('68.3%'), cell('239 / 350'), cell('—')],
    [cell('avg_mid（T+7/15）'), cell('33.9%'), cell('339 / 1000'), cell('61.9%'), cell('229 / 370'), cell('—')],
    [cell('avg_long（T+30/60）'), cell('25.7%'), cell('257 / 1000'), cell('54.8%'), cell('207 / 378'), cell('—')],
    [cell('<b>avg_all（主证据）</b>'), cell('<b>31.4%</b>'), cell('314 / 1000'), cell('<b>60.6%</b>'), cell('220 / 363'), cell('主口径')],
    [cell('consensus66（对照）'), cell('30.0%'), cell('300 / 1000'), cell('61.3%'), cell('187 / 305'), cell('—')],
]))
A('<p>*T+60 有 11 条 car_t60 为空（均为 CN），按有效样本 989 计。</p>'
  '<callout emoji="📉"><p><b>Horizon 衰减模式</b>：Strict ACC 从 T+1=47.9% 单调递减到 T+60=24.2%（平均每 10 个交易日约 −4pp）。短期（T+1/T+3）方向判别力最强，长期（T+30/T+60）因噪声与多因素叠加趋于随机。avg_all 综合多 horizon 将方差拉低至 31.4%，作为生产主口径合理；模型（31.4%）略优于 consensus66 对照（30.0%）。</p></callout>')

# ============================ 5. F1 / AUC / 校准 ============================
A('<h1>F1 / AUC / 校准 综合指标</h1><h2>3-class F1（Strict 口径）</h2>')
A(tbl(['Horizon', 'F1 macro', 'F1 micro', 'F1 weighted', 'F1 up', 'F1 neutral', 'F1 down'], [
    [cell('T+3'), cell('<b>0.391</b>'), cell('0.393'), cell('0.402'), cell('0.357'), cell('0.363'), cell('0.453')],
    [cell('<b>avg_all</b>'), cell('<b>0.312</b>'), cell('0.314'), cell('0.333'), cell('0.279'), cell('0.257'), cell('0.398')],
]))
A('<h3>T+3 每类 Precision / Recall</h3>')
A(tbl(['类别', 'TP', 'FP', 'FN', 'Precision', 'Recall', 'F1'], [
    [cell('up'), cell('91'), cell('62'), cell('266'), cell('59.5%'), cell('25.5%'), cell('0.357')],
    [cell('neutral'), cell('144'), cell('459'), cell('46'), cell('23.9%'), cell('75.8%'), cell('0.363')],
    [cell('<b>down</b>'), cell('158'), cell('86'), cell('295'), cell('<b>64.8%</b>'), cell('34.9%'), cell('<b>0.453</b>')],
]))
A('<h2>全 Horizon AUC（up vs down 二分类，双方非中性样本）</h2>')
A(tbl(['Horizon', 'AUC', 'n（双方非中性）', 'Horizon', 'AUC', 'n（双方非中性）'], [
    [cell('T+1'), cell('<b>0.773</b>'), cell('338'), cell('T+15'), cell('0.587'), cell('376')],
    [cell('T+3'), cell('<b>0.730</b>'), cell('351'), cell('T+30'), cell('0.554'), cell('378')],
    [cell('T+5'), cell('0.689'), cell('352'), cell('T+60'), cell('0.489'), cell('386')],
    [cell('T+7'), cell('0.646'), cell('360'), cell('avg_short'), cell('0.695'), cell('350')],
    [cell('avg_mid'), cell('0.632'), cell('370'), cell('avg_long'), cell('0.526'), cell('378')],
    [cell('<b>avg_all（主）</b>'), cell('<b>0.590</b>'), cell('363'), cell('consensus66（对照）'), cell('—'), cell('—')],
]))
A('<callout emoji="📉"><p><b>AUC 随 horizon 单调衰减</b>：T+1/T+3 具备较强方向排序能力（0.773 / 0.730），T+15 起降到 0.6 以下，T+60 = 0.489 已低于随机线，avg_all = 0.590 仅弱判别力。短期置信度排序可用、长期失效，是「置信度校准」改进（L1-6 / L2-3）的核心靶点。</p></callout>')
A('<h2>校准：Spearman 等级相关（conf vs |CAR|）</h2>')
A(tbl(['Horizon', 'Spearman ρ', 'Horizon', 'Spearman ρ'], [
    [cell('T+1'), cell('<b>0.386</b>'), cell('T+15'), cell('0.284')],
    [cell('T+3'), cell('<b>0.308</b>'), cell('T+30'), cell('0.289')],
    [cell('T+7'), cell('0.277'), cell('T+60'), cell('0.283')],
    [cell('<b>avg_all（主）</b>'), cell('<b>0.287</b>'), cell('（全样本 n=1000，T+60 n=989）'), cell('—')],
]))
A('<h2>混淆矩阵：Pred × Oracle（T+3 &amp; avg_all）</h2><h3>T+3 混淆矩阵</h3>')
A(tbl(['Pred \\ Oracle', 'up（357）', 'neutral（190）', 'down（453）'], [
    [cell('up（153）'), cell('<b>91 ✅</b>'), cell('16'), cell('46')],
    [cell('neutral（603）'), cell('210'), cell('<b>144 ✅</b>'), cell('249')],
    [cell('down（244）'), cell('56'), cell('30'), cell('<b>158 ✅</b>')],
]))
A('<h3>avg_all 混淆矩阵</h3>')
A(tbl(['Pred \\ Oracle', 'up（398）', 'neutral（128）', 'down（474）'], [
    [cell('up（153）'), cell('<b>77 ✅</b>'), cell('16'), cell('60')],
    [cell('neutral（603）'), cell('238'), cell('<b>94 ✅</b>'), cell('271')],
    [cell('down（244）'), cell('83'), cell('18'), cell('<b>143 ✅</b>')],
]))
A('<callout emoji="🔍"><p><b>混淆矩阵解读</b>：① 603 条 neutral 预测中有 459 条（76%）实际 GT 非 neutral——「放弃出手」是 Strict ACC 的最大失分来源；② down 方向预测较准（T+3 精确率 64.8%），up 方向偏保守（召回率仅 25.5%）；③ pred=down 但 GT=up 的反向大错 56 条（T+3），对应 Case B01/B03/B09 的「先验反向套用」模式。</p></callout>')

# ============================ 6. 阈值 sweep ============================
A('<h1>不同置信度阈值下的 ACC 与覆盖率 trade-off</h1>'
  '<p>说明：阈值 sweep 不改变 pred_direction，仅在 397 条非中性预测内按 conf 过滤，因此「覆盖内 ACC」即非中性预测正确率（NN-ACC）；覆盖率为通过阈值样本占全量 1000 条的比例。</p>'
  '<h2>T+3 阈值 sweep</h2>')
A(tbl(['Conf ≥', '覆盖样本', '覆盖率', 'Lenient ACC', '覆盖内 ACC（NN-ACC）'], [
    [cell('0.50（默认全量）'), cell('397'), cell('39.7%'), cell('70.9%（249/351）'), cell('62.7%（249/397）')],
    [cell('0.55'), cell('397'), cell('39.7%'), cell('70.9%'), cell('62.7%')],
    [cell('0.60'), cell('397'), cell('39.7%'), cell('70.9%'), cell('62.7%')],
    [cell('<b>0.65（运营推荐）</b>'), cell('162'), cell('16.2%'), cell('<b>76.5%</b>（114/149）'), cell('<b>70.4%</b>（114/162）')],
    [cell('0.70'), cell('97'), cell('9.7%'), cell('83.5%（76/91）'), cell('78.4%（76/97）')],
    [cell('0.75（高精度模式）'), cell('26'), cell('2.6%'), cell('91.7%（22/24）'), cell('84.6%（22/26）')],
    [cell('0.80'), cell('6'), cell('0.6%'), cell('83.3%（5/6）'), cell('83.3%（5/6）')],
]))
A('<h2>avg_all 阈值 sweep</h2>')
A(tbl(['Conf ≥', '覆盖样本', '覆盖率', 'Lenient ACC', '覆盖内 ACC（NN-ACC）'], [
    [cell('0.50'), cell('397'), cell('39.7%'), cell('60.6%（220/363）'), cell('55.4%（220/397）')],
    [cell('0.65'), cell('162'), cell('16.2%'), cell('59.5%（88/148）'), cell('54.3%（88/162）')],
    [cell('0.70'), cell('97'), cell('9.7%'), cell('65.5%（57/87）'), cell('58.8%（57/97）')],
    [cell('0.75'), cell('26'), cell('2.6%'), cell('66.7%（16/24）'), cell('61.5%（16/26）')],
]))
A('<callout emoji="🔧"><p><b>运营建议</b>：若以 T+3 覆盖内 ACC ≥ 70% 为目标，conf ≥ 0.65 档可达标（70.4%），对应 16.2% 覆盖率（相比默认档覆盖降 59%、ACC +7.7pp）。avg_all 口径下高分档提升有限（55.4% → 61.5%），说明 conf 与长期正确率的关联弱于短期——与 AUC 随 horizon 衰减的结论一致，长期校准需依赖 L1-6 / L2-3 而非简单提阈值。</p></callout>')

# ============================ 7. 分市场对比 ============================
A('<h1>分市场对比（CN vs US）</h1><h2>全 horizon 维度</h2>')
A(tbl(['市场', 'n', 'Horizon', 'AUC（up vs down）', 'Strict ACC', 'Strict k/n', 'Lenient ACC'], [
    [cell('<b>CN</b>', rowspan=6), cell('700', rowspan=6), cell('T+3'), cell('0.704'), cell('38.6%'), cell('270 / 700'), cell('68.0%（181/266）')],
    [cell('T+7'), cell('0.647'), cell('34.0%'), cell('238 / 700'), cell('63.2%（172/272）')],
    [cell('T+15'), cell('0.590'), cell('28.9%'), cell('202 / 700'), cell('58.3%（162/278）')],
    [cell('T+30'), cell('0.571'), cell('27.1%'), cell('190 / 700'), cell('59.6%（167/280）')],
    [cell('T+60'), cell('0.515'), cell('24.8%'), cell('171 / 689*'), cell('53.6%（149/278）')],
    [cell('<b>avg_all</b>'), cell('0.597'), cell('<b>33.0%</b>'), cell('231 / 700'), cell('61.8%（168/272）')],
    [cell('<b>US</b>', rowspan=6), cell('300', rowspan=6), cell('T+3'), cell('<b>0.814</b>'), cell('41.0%'), cell('123 / 300'), cell('<b>80.0%</b>（68/85）')],
    [cell('T+7'), cell('0.622'), cell('32.3%'), cell('97 / 300'), cell('61.4%（54/88）')],
    [cell('T+15'), cell('0.560'), cell('27.0%'), cell('81 / 300'), cell('54.1%（53/98）')],
    [cell('T+30'), cell('0.473'), cell('22.7%'), cell('68 / 300'), cell('45.9%（45/98）')],
    [cell('T+60'), cell('0.368'), cell('22.7%'), cell('68 / 300'), cell('42.0%（42/100）')],
    [cell('<b>avg_all</b>'), cell('0.545'), cell('<b>27.7%</b>'), cell('83 / 300'), cell('57.1%（52/91）')],
]))
A('<p>*CN T+60 按 989 条有效样本中的 689 条计（11 条空标签均在 CN）。AUC 为双方非中性口径，分市场样本数见括号内 n 值。</p>'
  '<callout emoji="💡"><p><b>CN vs US 对比</b>：</p>'
  '<p>• Strict ACC：CN 33.0% vs US 27.7%（avg_all 主口径）。CN 出手率更高（41.9% vs 34.7%），中性化对 US 的伤害更大。</p>'
  '<p>• AUC（排序能力）：US 短期显著更强（T+3 0.814 vs CN 0.704），但衰减更快，长期被 CN 反超（T+60 0.368 vs 0.515；avg_all 0.545 vs 0.597）。US 短期事件驱动特征强，长期置信度排序失效更严重。</p>'
  '<p>• Lenient ACC：US T+3 高达 80.0%（68/85），远超 CN 的 68.0%——<b>US 出手即极准但出手极少</b>，导致 Strict 偏低；长期 US Lenient 跌至 42.0%（T+60），与 AUC 衰减一致。</p></callout>')

# ============================ 8. 分事件类型 ============================
A('<h1>分事件类型对比</h1><h2>主证据 avg_all 维度</h2>')
A(tbl(['事件类型', 'n', 'avg_all AUC', 'avg_all Strict ACC', 'avg_all Strict k/n', 'avg_all Lenient ACC'], [
    [cell('<b>公司指引上调/下调</b>'), cell('140'), cell('<b>0.704</b>（n=82）'), cell('<b>43.6%</b>'), cell('61 / 140'), cell('69.5%（57/82）')],
    [cell('<b>并购/分拆/再融资</b>'), cell('220'), cell('0.583（n=137）'), cell('<b>39.1%</b>'), cell('86 / 220'), cell('56.9%（78/137）')],
    [cell('<b>财报超预期/不及预期</b>'), cell('220'), cell('0.535（n=112）'), cell('<b>32.7%</b>'), cell('72 / 220'), cell('58.9%（66/112）')],
    [cell('政策利率调整'), cell('140'), cell('0.583（n=12）'), cell('28.6%'), cell('40 / 140'), cell('66.7%（8/12）')],
    [cell('增长/就业数据意外'), cell('140'), cell('0.583（n=14）'), cell('16.4%'), cell('23 / 140'), cell('64.3%（9/14）')],
    [cell('通胀数据意外'), cell('140'), cell('0.400（n=6）'), cell('22.9%'), cell('32 / 140'), cell('33.3%（2/6）')],
]))
A('<h2>T+3 维度（短期信号最强）</h2>')
A(tbl(['事件类型', 'n', 'T+3 AUC', 'T+3 Strict ACC', 'T+3 Strict k/n', 'T+3 Lenient ACC'], [
    [cell('<b>公司指引上调/下调</b>'), cell('140'), cell('0.745（n=82）'), cell('<b>47.1%</b>'), cell('66 / 140'), cell('70.7%（58/82）')],
    [cell('<b>并购/分拆/再融资</b>'), cell('220'), cell('0.684（n=134）'), cell('<b>45.9%</b>'), cell('101 / 220'), cell('64.2%（86/134）')],
    [cell('<b>财报超预期/不及预期</b>'), cell('220'), cell('<b>0.792</b>（n=110）'), cell('<b>46.4%</b>'), cell('102 / 220'), cell('79.1%（87/110）')],
    [cell('政策利率调整'), cell('140'), cell('0.600（n=10）'), cell('33.6%'), cell('47 / 140'), cell('80.0%（8/10）')],
    [cell('增长/就业数据意外'), cell('140'), cell('0.671（n=12）'), cell('22.1%'), cell('31 / 140'), cell('66.7%（8/12）')],
    [cell('通胀数据意外'), cell('140'), cell('n/a（n=3，样本不足）'), cell('32.9%'), cell('46 / 140'), cell('66.7%（2/3）')],
]))
A('<h2>公司类 vs 宏观类聚合</h2>')
A(tbl(['聚合', 'n', 'T+3 Strict', 'T+3 NN-ACC', 'T+3 Lenient', 'avg_all Strict', 'avg_all AUC'], [
    [cell('<b>公司类（指引/并购/财报）</b>'), cell('580'), cell('<b>46.4%</b>（269/580）'), cell('64.7%（231/357）'), cell('70.9%（231/326）'), cell('<b>37.8%</b>（219/580）'), cell('0.591（n=331）')],
    [cell('宏观类（利率/就业/通胀）'), cell('420'), cell('29.5%（124/420）'), cell('45.0%（18/40）'), cell('72.0%（18/25）'), cell('22.6%（95/420）'), cell('0.533（n=32）')],
]))
A('<callout emoji="✅"><p><b>三类公司事件（合计 580 条、占 58%）T+3 Strict ACC 均达 45.9~47.1%、Lenient 64~79%</b>，是当前算法的主力可用区；其中财报类 T+3 AUC = 0.792 为最高。宏观三类 T+3 Strict 仅 22.1~33.6%，且模型几乎不出手（非中性预测每类仅 8~16 条，宏观类合计仅 40 条），AUC 样本量不足（通胀 T+3 仅 3 对无法计算），不具备生产可用性——但出手时 Lenient 72.0% 并不差，问题在于「不敢出手 + 上游数据脏」而非方向判断本身。</p></callout>')

# ============================ 9. 市场×类型矩阵 ============================
A('<h1>市场 × 事件类型 × 多指标完整矩阵</h1>'
  '<p>AUC 为双方非中性口径（括号内 n 为参与计算的样本数，n &lt; 4 标 n/a）；Strict/Lenient 与全文口径一致。</p>')
A(tbl(['市场', '事件类型', 'n', 'T+3 AUC', 'T+3 Strict', 'T+3 Lenient', 'avg_all AUC', 'avg_all Strict'], [
    [cell('CN'), cell('公司指引上调/下调'), cell('98'), cell('0.745（n=70）'), cell('53.1%（52/98）'), cell('70.0%（49/70）'), cell('0.758（n=68）'), cell('53.1%（52/98）')],
    [cell('CN'), cell('并购/分拆/再融资'), cell('154'), cell('0.605（n=105）'), cell('43.5%（67/154）'), cell('58.1%（61/105）'), cell('0.572（n=109）'), cell('43.5%（67/154）')],
    [cell('CN'), cell('财报超预期/不及预期'), cell('154'), cell('<b>0.801</b>（n=89）'), cell('50.6%（78/154）'), cell('77.5%（69/89）'), cell('0.544（n=91）'), cell('37.0%（57/154）')],
    [cell('CN'), cell('政策利率调整'), cell('98'), cell('n/a（n=0）'), cell('34.7%（34/98）'), cell('—（0/0）'), cell('n/a（n=2）'), cell('29.6%（29/98）')],
    [cell('CN'), cell('增长/就业数据意外'), cell('98'), cell('n/a（n=2）'), cell('16.3%（16/98）'), cell('100%（2/2）'), cell('n/a（n=2）'), cell('11.2%（11/98）')],
    [cell('CN'), cell('通胀数据意外'), cell('98'), cell('n/a（n=0）'), cell('23.5%（23/98）'), cell('—（0/0）'), cell('n/a（n=0）'), cell('15.3%（15/98）')],
    [cell('US'), cell('公司指引上调/下调'), cell('42'), cell('0.757（n=12）'), cell('33.3%（14/42）'), cell('75.0%（9/12）'), cell('0.388（n=14）'), cell('21.4%（9/42）')],
    [cell('US'), cell('并购/分拆/再融资'), cell('66'), cell('<b>0.940</b>（n=29）'), cell('51.5%（34/66）'), cell('86.2%（25/29）'), cell('0.617（n=28）'), cell('28.8%（19/66）')],
    [cell('US'), cell('财报超预期/不及预期'), cell('66'), cell('0.839（n=21）'), cell('36.4%（24/66）'), cell('85.7%（18/21）'), cell('0.480（n=21）'), cell('22.7%（15/66）')],
    [cell('US'), cell('政策利率调整'), cell('42'), cell('0.600（n=10）'), cell('31.0%（13/42）'), cell('80.0%（8/10）'), cell('0.620（n=10）'), cell('26.2%（11/42）')],
    [cell('US'), cell('增长/就业数据意外'), cell('42'), cell('0.548（n=10）'), cell('35.7%（15/42）'), cell('60.0%（6/10）'), cell('0.528（n=12）'), cell('28.6%（12/42）')],
    [cell('US'), cell('通胀数据意外'), cell('42'), cell('n/a（n=3）'), cell('54.8%（23/42）'), cell('66.7%（2/3）'), cell('0.400（n=6）'), cell('40.5%（17/42）')],
]))
A('<callout emoji="💡"><p><b>矩阵要点</b>：① 12 个组合中 <b>CN·公司指引 53.1%</b> 最高、CN·增长就业 16.3% 最低；② US·并购 T+3 AUC = 0.940、Lenient 86.2% 为全场最强组合，但 n=66 样本偏小需谨慎外推；③ 宏观类 6 个组合中 4 个 AUC 无法计算（出手样本不足），印证「宏观不敢出手」是跨市场共性问题。</p></callout>')

# ============================ 10. |CAR| 分桶（原样） ============================
A(read('07.xml'))

# ============================ 11. Case Study（原样） ============================
A(read('10.xml'))

# ============================ 12. 改进建议（合并 L1/L2） ============================
sec12 = read('12.xml')
# L1 正文：从 L1-1 h3 起到 L2 h2 之前（旧 h1/引言 ul/L1 h2/核心原则段由本脚本重写；
# 旧 L2 全部条目与旧路线图表亦由本脚本重写版替代，全部丢弃，避免重复）
m = re.search(r'<h2[^>]*>\s*L2 · 动模型', sec12)
l1_part = sec12[:m.start()] if m else sec12
m2 = re.search(r'<h3[^>]*>\s*L1-1', l1_part)
l1_items = l1_part[m2.start():] if m2 else l1_part
# 修正 L1 汇总中的 AUC 基线错误（旧文按 0.477 口径，统一为重算后的 0.590）
l1_items = l1_items.replace(
    'avg_all AUC ↑ 0.05~0.07（从 0.477 → 0.53~0.55）',
    'avg_all AUC ↑ 0.03~0.05（从 0.590 → 0.62~0.64）')
# L1 汇总中的其他表述统一
l1_items = l1_items.replace('Strict ACC ↑ 10~14pp（从 31.4% → 41~45%）', 'Strict ACC ↑ 10~14pp（avg_all 从 31.4% → 41~45%）')
l1_items = l1_items.replace('运营档 conf≥0.65 ACC 从 70.4% → 76~79%', '运营档 conf≥0.65 覆盖内 ACC 从 70.4% → 76~79%')

A('<h1>改进建议：L1（不动模型）与 L2（动模型）分层路线</h1>'
  '<p>评估方式（AUC / ACC / threshold sweep 等口径）与数据集（1000 条 × 2 市场 × 6 类型）<b>保持不变</b>。改进按「是否动模型」严格分两层，避免「一上来就重训模型 / 改流式架构」的不可操作问题：</p><ul>'
  '<li><b>L1 · 不动模型（Agent Harness / Prompt / Skill 编排 / 数据来源）：</b>完全沿用当前 team_full 的模型权重、Skill 列表与 API 入参出参格式，只改 Harness 层规则 / 模板 / 编排与数据清洗映射。<b>零训练、零基建重构</b>，1~3 天可上线拿收益。</li>'
  '<li><b>L2 · 动模型（SFT / RLVR / 在线学习）：</b>需要专项训练，2~6 周量级；L1 验证可行后再切入，避免在脏基座上浪费训练预算。</li></ul>')
A('<h2>L1 · 不动模型：只改 Agent Harness / Prompt / 数据（可自进化 Quick Wins）</h2>'
  '<p><b>核心原则：</b>不改模型权重、不改 Skill 定义、不改 API 入参出参、不做流式、不做 DAG 调度重构。所有改动都落在 Harness 可热替换的规则 / 模板 / 编排层。</p>')
# L1-1 ~ L1-7 逐条（新 h2 与核心原则段已在上方重写）
A(l1_items)

A('<hr/><h2>L2 · 动模型：SFT / RLVR / 自进化层</h2>'
  '<p>L1 拿到确定收益、且三路由模板的错误分布稳定后，再切入 L2。所有 L2 项目都<b>假设 L1 已在线上跑</b>（脏数据已过滤、先验/阈值已最优、错误模式已 in-context 注入）。</p>'
  '<h3>L2-1 多 Horizon 联合预测 Head + Evidence Mixer（SFT 小模型，冻结基座只训 adapter）</h3><ul>'
  '<li><b>问题：</b>当前模型对每个事件仅输出单方向 + 单置信度，与 T+1~T+60 多 horizon 目标不对齐；负例中大量呈现「T+3 与 T+30/T+60 方向翻转」（B01/B02/B04/B08/B10），模型被迫在短期/长期间取平均，是 neutral 膨胀与 AUC 偏低的根因之一。同时决策链由 event_study_skill（T0 AR / pre20 drift / sell_the_news）、公告分类器、结构化净分以<b>手工规则加权</b>组合，先验僵化（B03 要约收购与普通重组套同一先验、B09 STN 误触发）。</li>'
  '<li><b>方案：</b>把 L1-7 三模板（Short/Mid/Long）验证有效的「权重配比」直接学进 <b>1 个 small adapter / LoRA</b>：输出 7 个 horizon 方向 head + 1 个 conf head；证据侧引入 <b>3~4 层轻量 Cross-Attention Evidence Mixer</b>，将 T0 AR、pre5/pre20 drift、STN 系数、info_tier、event_type 先验、consensus_net、结构化净分等编码为独立 token，与事件文本 CLS 做 cross-attention；CN / US 走独立 Mixture-of-Experts，避免 US 宏观被 CN 并购先验反向污染。基座主模型完全冻结，单卡 2~3 天可完成。</li>'
  '<li><b>预期收益：</b>修复「短期反转长期」类错误，Strict ACC ↑ 4~6pp；分市场 AUC 偏差（T+3：CN 0.704 vs US 0.814）收敛至 0.03 以内。</li></ul>'
  '<h3>L2-2 RLVR 训练：用「真实 pred→GT 收益 + 校准惩罚」作奖励函数</h3><ul>'
  '<li><b>为什么要 RLVR：</b>L1 的 Prompt 规则再精细也是离散的，学不到「证据冲突微妙时如何连续加权」。</li>'
  '<li><b>设置：</b>沿用当前证据链输入不变，Agent 只学两件事：① <b>evidence weighting</b>——给 8 条证据各学一个 0~1 权重（Market×EventType 条件下）；② <b>threshold 选择</b>——neutral 窗口连续收窄/放宽（可训练的 beta 分布采样）。输入特征可增加 pre[-60, 0] 相对收益序列经 1D-CNN + LSTM 编码的 <b>Momentum Embedding</b>（当前仅用 pre5/pre20 两个标量，丢弃了分布形状与极值信息），并加辅助任务预测「持续 / 反转 / 震荡」三态（监督信号从真实 CAR 曲线聚类得到）。</li>'
  '<li><b>Reward 函数：</b><code>R = 1.0×strict_correct − 0.3×strict_wrong − 0.1×neutral_penalty×(1−|CAR_avg|/5%) + 0.4×spearman(conf, |CAR|) − 0.5×ECE</code>。加权 Strict ACC 为主，同时惩罚「|CAR| 大时还 neutral」「conf 与真实幅度不校准」「ECE 过高」三件事（对应 L1 之后的剩余残差）。</li>'
  '<li><b>预期收益：</b>在 L1 基础上 Strict ACC 再 +4~6pp，AUC +0.03~0.05，ECE ↓ 40%。</li></ul>'
  '<h3>L2-3 置信度校准头 + 事件类型 OOD 检测头</h3><ul>'
  '<li><b>问题：</b>conf 为 LLM 自报（0.5~0.8 近似线性分布），B01（conf=0.74）/ B04（conf=0.72）高置信判错；B05 的 event_type_l2 被上游误标（重组程序文标为指引），模型按错误类型触发「文本无数值 → down」先验，这类误标估计占数据集 5~10%。</li>'
  '<li><b>方案：</b>① <b>Calibration Head</b>：二分类（High-Conf Correct vs not），标签由 (pred, GT, |CAR|) 联合计算（strict correct ∧ |CAR|≥1% → positive），推理时与 LLM 原始 conf 做 Platt 融合；② <b>OOD Head</b>：独立 Multi-label 事件分类器（6 类 + OTHER，输出 Shannon Entropy），entropy 超阈值时把「类型不确定度」注入 Mixer 并降低对应 event_type 先验权重。</li>'
  '<li><b>预期收益：</b>高置信错误（conf≥0.70 strict wrong）↓ 30%+，ECE ↓ 50%+，证据链断裂型误判（B05/B06 类）↓ 20~30%。注：轻量版（分桶查表）已在 L1-6 先行，此处是模型化完整版。</li></ul>'
  '<h3>L2-4 DebateRunnerV2 + 裁决器 PPO 自博弈与 Online RLVR</h3><ul>'
  '<li><b>方案：</b>① 升级 team_runner → <b>DebateRunnerV2</b>：Team A（Bear）只看 down 侧证据、Team B（Bull）只看 up 侧证据、Team C（Neutral）只看 info_tier / |AR| / consensus_entropy，Adjudicator 用小 LLM 或 Mixer 的 Cross-Attention 裁决——可先在 L1 层用 Prompt 实现三辩验证有效，再用 PPO 训裁决器（奖励 = 裁决 strict_correct_rate − 延迟成本）；② <b>Online RLVR</b>：L1 落地的 Prediction Warehouse（可先用 MySQL upsert + 每日 ETL 计算最新 T+N CAR，<b>不需要流式基建</b>）成熟后，每天把 matured label 回流做一次 online 小步 update（KL penalty ≤ 0.001，防灾难性遗忘）。</li>'
  '<li><b>预期收益：</b>高置信错误 ↓ 30~40%；自博弈不断吃 L1 新产生的 mistake_memory，每轮回测产出新辩论样本，实现「越跑越强」的自进化闭环。</li></ul>'
  '<h3>L2-5 工程前置（可与 L1 并行，不改变预测结果）：异步推理 + Batch Runner V2</h3><ul>'
  '<li>仅提升吞吐与可恢复性：将行情 / 公告分类 / 基本面 / 结构化净分拆为独立 Skill Node，DAG 调度单事件内三路并行，在证据汇合节点合并；LLM 调用走 batching（每批 32~128 条，KV cache 共享）；trajectory 断点改为 DAG 节点级持久化，中断恢复时间 ↓ 90%。<b>系统收益：</b>单事件 P50 延迟 ↓ 50~70%，1000 条在 4 并发下从约 28 小时缩至 1 小时内。</li></ul>')
A('<h2>两层路线图 &amp; 前置依赖（清晰不跳步）</h2>')
A(tbl(['阶段', '分层', '时间', '关键动作', '前置依赖 &amp; 成功指标'], [
    [cell('Phase 1 · Harness Quick Wins'), cell('<b>L1 不动模型</b>'), cell('T+0 ~ T+5 天'),
     cell('L1-5 数据 Guard → L1-2 STN 门控 + L1-6 Conf 校准 → L1-1 先验分桶 + L1-3 阈值路由 → L1-4 错误 RAG + L1-7 三模板'),
     cell('无前置。成功：avg_all Strict ACC ≥ 41%，运营档 conf≥0.65 覆盖内 ACC ≥ 76%，中性 ≤ 45%')],
    [cell('Phase 2 · 决策层微调'), cell('L2'), cell('T+2 ~ T+3 周'),
     cell('L2-2 RLVR 训证据权重 + 阈值（LR ≈ 1e-6，训 1~2 天）+ L2-3 校准/OOD 头'),
     cell('前置：Phase 1 全部上线 + 1000 条新回测。成功：Strict ACC 45%+，avg_all AUC ≥ 0.62')],
    [cell('Phase 3 · 自进化闭环'), cell('L2'), cell('T+4 ~ T+8 周'),
     cell('L2-1 多 Horizon Head + Evidence Mixer adapter、L2-4 Debate PPO + Online RLVR（每日批处理回灌）、L2-5 Batch Runner V2'),
     cell('前置：Phase 2 线上指标稳定（连续 7 天 shadow ≥ 主模型）。成功：Strict ACC 50%+，ECE ≤ 8%，1000 条回测延迟 ≤ 1 小时')],
]))
A('<callout emoji="✅"><p><b>结论：</b>「不动模型、不改交互、只改 Harness + 数据」的 L1 层一共 7 项，3~5 天可全量上，独立能拿到 Strict ACC +10~14pp / avg_all AUC +0.03~0.05 的收益；其中 5 项（priors / thresholds / calibration / mistake_memory / 路由表）<b>每次回测跑完自动查表更新</b>，天然可自进化，不需要人手动改 Prompt。L2 的 SFT / RLVR / Debate / Online 则是在 L1 基座已干净、收益已证明之后的 2 个月级持续提升。</p></callout>')

# ============================ 13. 总结 ============================
A('<h1>总结</h1>'
  '<callout><p><b>一句话版本</b>：1000 条 team_full 全量回测验证了算法<b>出手即准（Non-Neutral T+3 ACC 62.7%、Lenient 70.9%）</b>但<b>出手过度保守（60.3% neutral）</b>的特征；叠加新增宏观 420 条的结构性拖累，全量 avg_all Strict ACC = 31.4%。按 L1 层（不动模型）修复后，Strict T+3 预期回到 45%+。</p></callout>'
  '<h2>关键发现（按影响排序）</h2><ol>'
  '<li seq="1"><b>中性化过度是第一瓶颈</b>：60.3% 样本被判 neutral（旧版 Gate 0.50 仅 21.6%）。三重 neutral gate（|net|&lt;0.5、conf&lt;0.60、矛盾证据≥2）叠加 + 单一阈值窗口不分场景，使中间幅度区（|CAR| 0.5%~5%）被大量放弃出手（该区 Strict 比旧版低 18~38pp）。</li>'
  '<li><b>宏观类事件是第二瓶颈</b>：政策利率/就业/通胀三类合计 420 条（42%），T+3 Strict 仅 22.1~33.6%（公司类 46.4%），模型对宏观 89~94% 判 neutral、几乎不出手（宏观类非中性预测合计仅 40 条）；上游数据脏（占位正文、类型误标）进一步恶化（B05/B07/B08）。</li>'
  '<li><b>判别力随 horizon 衰减、校准不足</b>：AUC 从 T+1 0.773 / T+3 0.730 衰减至 T+60 0.489（≈随机），avg_all 0.590；Spearman ρ ≈ 0.29，远低于 ρ≥0.5 的生产目标。</li>'
  '<li><b>大波动样本（|CAR|≥10%）性能优秀</b>：T+3 Strict 64.1% / Lenient 83.7%，信号强烈时判向能力可靠（且反超旧版同档的 55%）。</li>'
  '<li><b>down 类精确率优于 up 类</b>：down P=64.8% vs up P=59.5%（T+3），负向事件识别更准。</li>'
  '</ol>')
A('<h2>分阶段目标预期</h2>')
A(tbl(['阶段', 'avg_all Strict ACC', 'T+3 Lenient ACC', 'avg_all AUC'], [
    [cell('当前（1000 条全量）'), cell('31.4%'), cell('70.9%'), cell('0.590')],
    [cell('仅公司类 580 条（实测子集，供参照）'), cell('37.8%'), cell('70.9%'), cell('0.591')],
    [cell('+ L1 全量上线（3~5 天）'), cell('41~45%'), cell('~75%'), cell('0.62~0.64')],
    [cell('+ L2 Phase 2（RLVR + 校准/OOD 头）'), cell('45%+'), cell('~78%'), cell('≥ 0.65')],
    [cell('+ L2 Phase 3（多 Horizon Head + Debate + Online）'), cell('50%+'), cell('~80%'), cell('≥ 0.68')],
]))
A('<hr/><p><b>输出文件清单</b>：</p><ul>'
  '<li>Predictions：/workspace/backtesting/preds_cn_us_1000_v1.jsonl（1000 行）</li>'
  '<li>Labels / Events：labels_cn_us_1000_v1.jsonl / events_cn_us_1000_v1.jsonl（各 1000 行）</li>'
  '<li>Metrics JSON：/workspace/backtesting/metrics_tf_cn_us_1000_v1.json</li>'
  '<li>Trajectory 断点：/workspace/backtesting/_trajectory_ckpt_tf_cn_us_1000_v1/（847 个 JSON）</li>'
  '<li>参考报告：<a href="https://alghub-docs.feishu.cn/docx/QBnbdKyHOoSTq9xhHc7cZ3nPnOb">648 条阶段性回测报告</a> ｜ <a href="https://icnyn86gi2iw.feishu.cn/docx/NQMldIKQ8on4VDx2IN5cbH6knsh">上一版 1000 条终期报告</a></li>'
  '</ul>')

# ============================ 组装 ============================
title = 'FEVER 事件方向预测系统 · 1000 条回测报告（v2 · team_full · 含 Case Study 与分层改进建议）'
doc = f'<title>{title}</title>' + ''.join(parts)

out = '/workspace/tmp_work/new_doc.xml'
open(out, 'w', encoding='utf-8').write(doc)
print(f'written: {out}, {len(doc)} chars')

# 校验 XML 良构
import xml.etree.ElementTree as ET
try:
    ET.fromstring(f'<root>{doc[len(f"<title>{title}</title>"):]}'.replace('<title>' + title + '</title>', '') + '</root>')
    print('XML well-formed check: need wrapper without title')
except Exception as e:
    print('parse issue:', e)
body = doc.replace(f'<title>{title}</title>', '')
try:
    ET.fromstring(f'<root>{body}</root>')
    print('XML well-formed: OK')
except Exception as e:
    print('XML ERROR:', e)
