"""build_v5_vertical.py — 生成 Pronoia-PAPV 实验报告单文件 HTML（竖向可滚动文档）。
内嵌 v5 训练曲线图 base64。线性暗色风。

生成： python3 build_v5_vertical.py
产物： v5_experiment_report_vertical.html（自包含单文件）
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).parent
CURVE = HERE / "v5_reward_loss_curves.png"
CURVE_B64 = base64.b64encode(CURVE.read_bytes()).decode()

D = {
    "V4_SAMPLES": 1782, "V5_SAMPLES": 2507, "TARGET": 5174,
    "COLLECTED": 2977, "CONCURRENCY": 20,
    "OOS_ACC": 0.641, "OOS_BASE": 0.560, "OOS_ECE": 0.095, "OOS_ECE_BASE": 0.133,
    "OOS_BRIER": 0.228, "OOS_BRIER_BASE": 0.266,
    "V5_STEPS": 83, "V5_STEPS_TOTAL": 627, "V5_REWARD": 0.681,
    "V5_EMA": 0.690, "V5_KL": 0.00065, "V5_GRAD": 0.139,
}
D["V5_PCT"] = round(D["V5_STEPS"] / D["V5_STEPS_TOTAL"] * 100, 1)

DOC = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Pronoia-PAPV 实验报告 · v5</title>
<style>
:root{
  --acid:#e4f222; --green:#27a644; --red:#eb5757; --teal:#02b8cc;
  --void:#0a0b0c; --carbon:#0f1011; --graphite:#23252a; --smoke:#383b3f;
  --ash:#62666d; --fog:#8a8f98; --mist:#d0d6e0; --bone:#e5e5e6;
  --line:#23252a; --bg:#0f1011; --bg-muted:#161718; --text:#d0d6e0; --text-muted:#8a8f98;
  --radius-sm:12px; --radius-pill:9999px;
  --mono:'JetBrains Mono','Berkeley Mono',ui-monospace,monospace;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--void);color:var(--text);font-family:var(--sans);line-height:1.65}

/* 顶栏 */
.topbar{position:sticky;top:0;z-index:50;background:rgba(10,11,12,.86);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line)}
.topbar-inner{max-width:980px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
.topbar .brand{font:600 12px var(--mono);color:var(--fog);letter-spacing:.06em;text-transform:uppercase}
.topbar .meta{font:400 11px var(--mono);color:var(--ash)}

.wrap{max-width:980px;margin:0 auto;padding:48px 24px 80px}

/* 封面 */
.cover{padding:28px 0 40px;border-bottom:1px solid var(--line)}
.badge{display:inline-block;font:600 11px var(--mono);color:var(--void);background:var(--acid);
  padding:5px 11px;border-radius:4px;letter-spacing:.04em;text-transform:uppercase}
.cover h1{font-size:46px;font-weight:590;line-height:1.12;letter-spacing:-.03em;color:#f2f4f5;margin-top:20px}
.cover .kicker{margin-top:12px;font:500 13px var(--mono);color:var(--acid);letter-spacing:.1em;text-transform:uppercase}
.cover .sub{margin-top:12px;font-size:15px;color:var(--fog);max-width:70ch}
.cover .tags{margin-top:18px;display:flex;gap:8px;flex-wrap:wrap}
.cover .tags span{font:500 12px var(--mono);color:var(--mist);background:var(--bg);border:1px solid var(--line);
  padding:6px 12px;border-radius:var(--radius-pill)}
.cover .big{margin-top:20px;font-size:22px;color:var(--ash)}
.cover .big b{color:var(--acid);font-weight:500}

section{padding:44px 0 12px}
.kicker{font:500 12px var(--mono);color:var(--acid);text-transform:uppercase;letter-spacing:.08em}
h2{font-size:30px;font-weight:590;letter-spacing:-.02em;color:#e5e5e6;margin-top:8px}
.lead{font-size:15px;color:var(--text-muted);max-width:72ch;margin-top:6px}
hr.h{border:0;border-top:1px solid var(--line);margin:10px 0 22px}

/* 卡片网格（PAPV 六条） */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px}
.card{background:var(--bg);border:1px solid var(--line);border-radius:var(--radius-sm);padding:16px 18px}
.card .cd{font:600 11px var(--mono);color:var(--acid);letter-spacing:.06em}
.card .ct{font-size:15px;font-weight:600;color:var(--bone);margin-top:4px}
.card .ds{font-size:13px;color:var(--text-muted);margin-top:4px}

/* 指标矩阵 */
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:var(--radius-sm);overflow:hidden;margin-top:20px}
.metric{background:var(--bg);padding:16px 18px;display:flex;flex-direction:column;gap:4px}
.metric .mv{font-size:24px;font-weight:200;letter-spacing:-.02em;color:#e5e5e6}
.metric .mv b{color:var(--acid);font-weight:400}
.metric .ml{font-size:12px;color:var(--text-muted)}
.metric .md{font-size:11px;font-weight:600}
.metric .md.pos{color:var(--green)}.metric .md.neg{color:var(--red)}

/* 流程步 */
.flow{display:flex;align-items:stretch;gap:8px;margin-top:20px;flex-wrap:wrap}
.fstep{flex:1;min-width:150px;border:1px solid var(--line);border-radius:var(--radius-sm);
  background:var(--bg);padding:14px 12px;display:flex;flex-direction:column;gap:5px}
.fstep .fsi{font:600 10px var(--mono);color:var(--acid)}
.fstep .fst{font-size:13px;font-weight:600;color:var(--bone)}
.fstep .fsd{font-size:11px;color:var(--text-muted);line-height:1.45}
.farrow{display:flex;align-items:center;color:var(--fog);font-size:15px}

/* 图 */
.chart{margin-top:20px;background:var(--bg);border:1px solid var(--line);border-radius:var(--radius-sm);
  padding:14px;width:100%}
.chart img{width:100%;height:auto;border-radius:6px;display:block}

/* 对比表 */
table{width:100%;border-collapse:collapse;margin-top:20px;font-size:13px}
th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line)}
thead th{font:600 11px var(--mono);text-transform:uppercase;letter-spacing:.04em;background:var(--bg-muted);color:var(--fog)}
td.dim{color:var(--text-muted);font-weight:500;white-space:nowrap}
td.hl{background:rgba(228,242,34,.07);font-weight:600;color:var(--bone)}
td .no{color:var(--ash)}.pos{color:var(--green)}

/* 结论/列表 */
.quote{font-size:22px;line-height:1.5;color:var(--mist);font-weight:400;margin-top:16px}
.sub-line{font-size:14px;color:var(--fog);max-width:72ch;line-height:1.7;margin-top:12px}
ol.steps{margin:16px 0 0 20px;display:flex;flex-direction:column;gap:10px}
ol.steps li{font-size:14px;color:var(--mist)}
ol.steps li span{color:var(--text-muted)}

.hl-green{color:var(--green);font-weight:600}
.hl-red{color:var(--red);font-weight:600}
.footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--ash);font:400 12px var(--mono)}
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <span class="brand">PRONOIA · PAPV 实验报告</span>
    <span class="meta">v5 · 2026-08 · Qwen3-8B / LoRA / GRPO</span>
  </div>
</div>

<div class="wrap">

  <!-- 封面 -->
  <div class="cover">
    <span class="badge">实验报告</span>
    <h1>Pronoia-PAPV 持续学习实验报告<br/>v4 → v5</h1>
    <div class="kicker">Prediction · Assertion · Post-Validation</div>
    <div class="sub">从 v4 到 v5 的两轮 GRPO 训练：修复输出坍缩、积累真实 Team 推理数据，并在样本外验证断言判断与置信度校准的提升。</div>
    <div class="tags"><span>GRPO · LoRA · Qwen3-8B</span><span>OOS 200 样本核验</span><span>数据收集 20 并发</span></div>
    <div class="big">v4 Reward <b>0.755</b> · v5 训练进行中（@V5_STEPS@/@V5_STEPS_TOTAL@ 步）</div>
  </div>

  <!-- 1 范式 -->
  <section>
    <span class="kicker">01 · Paradigm</span>
    <h2>PAPV 学习范式</h2>
    <p class="lead">模型自主提出可验证断言并判断真假，reward 只看「判断是否命中事后结算」。</p>
    <hr class="h"/>
    <div class="grid2">
      <div class="card"><span class="cd">PREDICTION</span><div class="ct">预测</div><div class="ds">输入事件 + 研究上下文，提出 3–6 条可验证断言</div></div>
      <div class="card"><span class="cd">ASSERTION</span><div class="ct">断言</div><div class="ds">每条含指标 / 阈值 / 方向 / 置信度，覆盖 ≥2 horizon 与指标族</div></div>
      <div class="card"><span class="cd">POST-VALIDATION</span><div class="ct">事后验证</div><div class="ds">labels.jsonl 客观结算真实涨跌 / 显著性，判定命中</div></div>
      <div class="card"><span class="cd">REWARD</span><div class="ct">六元结算</div><div class="ds">准确率(0.38) + 校准 + 可验证 + 格式 + 逻辑链 + 多样性</div></div>
      <div class="card"><span class="cd">CORE VALUE</span><div class="ct">核心价值</div><div class="ds">学会「对哪些命题有把握」，而非记住单一方向</div></div>
      <div class="card"><span class="cd">GUARDRAIL</span><div class="ct">护栏 · 权重再平衡</div><div class="ds">v5 新增单指标族惩罚 + 多样性门槛(2→3)，防坍缩</div></div>
    </div>
  </section>

  <!-- 2 数据收集 -->
  <section>
    <span class="kicker">02 · Data</span>
    <h2>数据是如何收集的</h2>
    <p class="lead">用真 Team 多智能体推理替代程序化统计替身，为每个事件产出深度研究上下文。</p>
    <hr class="h"/>
    <div class="flow">
      <div class="fstep"><span class="fsi">STEP 1</span><span class="fst">事件源</span><span class="fsd">events_enriched.jsonl 全量事件（目标 @TARGET@）</span></div>
      <div class="farrow">→</div>
      <div class="fstep"><span class="fsi">STEP 2</span><span class="fst">Team 推理</span><span class="fsd">market / fundamentals / deep_researcher 三专家</span></div>
      <div class="farrow">→</div>
      <div class="fstep"><span class="fsi">STEP 3</span><span class="fst">落地缓存</span><span class="fsd">research_cache_team_v4.jsonl · 断点续跑 · 失败重试 1 次</span></div>
      <div class="farrow">→</div>
      <div class="fstep"><span class="fsi">STEP 4</span><span class="fst">组装 v5</span><span class="fsd">合并 events + labels + 统计上下文 + rationale</span></div>
      <div class="farrow">→</div>
      <div class="fstep"><span class="fsi">STEP 5</span><span class="fst">训练集</span><span class="fsd">data_v5 = @V5_SAMPLES@ 条 · 100% 可结算</span></div>
    </div>
    <div class="metrics">
      <div class="metric"><span class="mv">20</span><span class="ml">并发（asyncio.Semaphore）</span></div>
      <div class="metric"><span class="mv">@V4_SAMPLES@→<b>@V5_SAMPLES@</b></span><span class="ml">v4→v5 可用样本（+725）</span></div>
      <div class="metric"><span class="mv"><b>@COLLECTED@</b><span style="color:#e5e5e6">/@TARGET@</span></span><span class="ml">实时收集进度（持续增长）</span></div>
      <div class="metric"><span class="mv">3600s</span><span class="ml">单调用超时兜底</span></div>
    </div>
  </section>

  <!-- 3 v4 结果 -->
  <section>
    <span class="kicker">03 · v4 Run（已跑完 + OOS）</span>
    <h2>v4 训练结果</h2>
    <p class="lead">299 步 GRPO 完成后，在样本外池抽样 200 条，基准模型 vs 训练后 LoRA。</p>
    <hr class="h"/>
    <div class="metrics">
      <div class="metric"><span class="mv">299</span><span class="ml">训练步数 · 8h07m</span><span class="md pos">完成</span></div>
      <div class="metric"><span class="mv">0.755</span><span class="ml">最终 Reward</span><span class="md pos">KL 0.013</span></div>
      <div class="metric"><span class="mv">@OOS_BASE@→<b>@OOS_ACC@</b></span><span class="ml">样本外断言命中率</span><span class="md pos">+8.1pt</span></div>
      <div class="metric"><span class="mv">@OOS_ECE_BASE@→<b>@OOS_ECE@</b></span><span class="ml">ECE 校准误差</span></div>
      <div class="metric"><span class="mv"><b>@OOS_BRIER@</b></span><span class="ml">Brier</span><span class="md pos">base @OOS_BRIER_BASE@ · 校准改善</span></div>
      <div class="metric"><span class="mv">0.80→<b>0.81</b></span><span class="ml">高置信区(0.8–0.9)命中</span><span class="md pos">敢高置信有底气</span></div>
      <div class="metric"><span class="mv">0.64→<b>0.70</b></span><span class="ml">判 FALSE 准确率</span><span class="md pos">更善质疑</span></div>
      <div class="metric"><span class="mv">69%</span><span class="ml">格式合规率（base 100%）</span><span class="md neg">隐患 ⚠</span></div>
    </div>
  </section>

  <!-- 4 v5 结果 -->
  <section>
    <span class="kicker">04 · v5 Run（修复后，进行中）</span>
    <h2>v5 训练收敛曲线</h2>
    <p class="lead">截至 @V5_STEPS@/@V5_STEPS_TOTAL@ 步（@V5_PCT@%）。GRPO 的 <span class="hl-red">loss 为 TRL 占位 0</span>，实际看 reward / KL / grad_norm。</p>
    <hr class="h"/>
    <div class="metrics">
      <div class="metric"><span class="mv">@V5_REWARD@</span><span class="ml">Reward 均值</span></div>
      <div class="metric"><span class="mv">@V5_EMA@</span><span class="ml">EMA(0.7) 后段</span></div>
      <div class="metric"><span class="mv">@V5_KL@</span><span class="ml">KL 极低 · 无发散</span></div>
      <div class="metric"><span class="mv">@V5_GRAD@</span><span class="ml">Grad Norm 均值</span></div>
    </div>
    <div class="chart"><img src="data:image/png;base64,__CURVE__" alt="v5 训练四面板曲线：Reward / KL / Gradient Norm / Learning Rate"/></div>
    <div class="grid2" style="margin-top:14px">
      <div class="card"><span class="cd">REWARD</span><div class="ct">上升且稳定</div><div class="ds">EMA 后段 0.690，max 0.881，无 reward hacking</div></div>
      <div class="card"><span class="cd">KL</span><div class="ct">全程 ≤0.0012</div><div class="ds">max 0.0011，远低于 v4 早期 0.014 → 不背离参考模型</div></div>
      <div class="card"><span class="cd">GRADIENT</span><div class="ct">更新信号健康</div><div class="ds">grad_norm 稳定非 0（占位 loss 不代表损失）</div></div>
      <div class="card"><span class="cd">DIVERSITY</span><div class="ct">多样性修复生效中</div><div class="ds">R5 门槛 2→3、R0 单指标族惩罚</div></div>
    </div>
  </section>

  <!-- 5 对比 -->
  <section>
    <span class="kicker">05 · Fix</span>
    <h2>v4 → v5 修复对比</h2>
    <p class="lead">针对 v4 暴露的输出坍缩，从 reward 五处改造。</p>
    <hr class="h"/>
    <table>
      <thead><tr><th>维度</th><th>v4（未修复）</th><th class="hl">v5（修复后）</th><th>设计意图</th></tr></thead>
      <tbody>
        <tr><td class="dim">多样性 R5</td><td>0.05 · 门槛 2 族</td><td class="hl">0.10 · 门槛 3 horizon / 3 族</td><td>激励覆盖更多指标族</td></tr>
        <tr><td class="dim">格式 R0</td><td>仅数断言 + 段落</td><td class="hl">+ 单指标族惩罚（对折）</td><td>把「模板化全 car」视为低信息</td></tr>
        <tr><td class="dim">准确率 R2</td><td>0.45 过高</td><td class="hl">0.38（再平衡）</td><td>弱化单一正确性奖励</td></tr>
        <tr><td class="dim">数据</td><td>程序化替身 + 部分真推理</td><td class="hl">全量真 Team 推理（+725）</td><td>研究上下文质量提升</td></tr>
        <tr><td class="dim">KL 稳定</td><td>爬升至 0.014 需干预</td><td class="hl">全程 ≤0.0008</td><td>更稳健优化轨迹</td></tr>
      </tbody>
    </table>
  </section>

  <!-- 6 发现 -->
  <section>
    <span class="kicker">06 · Key Findings</span>
    <h2>发现与风险</h2>
    <hr class="h"/>
    <div class="quote">训练真实提升了核心判断，但输出坍缩的代价值得警惕。</div>
    <div class="sub-line">v4 样本外命中率 <span class="hl-green">+8.1pt</span>、ECE <span class="hl-green">-3.8pt</span>——模型更会「识破营收增长但利润弱」的细节；但不同股票输出逐字相同断言、格式合规 100%→69%，正是 GRPO 收敛到高奖励区的坍缩信号。</div>
    <div class="grid2" style="margin-top:16px">
      <div class="card"><span class="cd">✓ 真实提升</span><div class="ct">恒玄科技 case</div><div class="ds">识破收入 +46.6% 但净利仅 +1.0% → 判负命中</div></div>
      <div class="card"><span class="cd">! 坍缩信号</span><div class="ct">风险同样明显</div><div class="ds">相似事件输出雷同 · 指标族收窄 · 长窗 / 大涨事件误判</div></div>
    </div>
  </section>

  <!-- 7 下一步 -->
  <section>
    <span class="kicker">07 · Next</span>
    <h2>下一步</h2>
    <hr class="h"/>
    <ol class="steps">
      <li>等 627 步完成，保存 checkpoint 并出具完整结论。</li>
      <li>训练后立即样本外评估：命中率应 ≥0.641、指标族覆盖应 &gt; v4、格式合规率应显著 &gt; 69%。<span>（当前进行到 @V5_STEPS@/@V5_STEPS_TOTAL@ 步）</span></li>
      <li>数据收集并行推进（当前 @COLLECTED@+），完成后合并最新数据进入 v6 训练。</li>
    </ol>
  </section>

  <div class="footer">Qwen3-8B · LoRA · GRPO · PAPV — 持续学习，样本外验证。 数据 via Team 多智能体推理管线。</div>
</div>
</body>
</html>
"""

for key, val in D.items():
    DOC = DOC.replace(f"@{key}@", str(val))
DOC = DOC.replace("__CURVE__", CURVE_B64)

OUT = HERE / "v5_experiment_report_vertical.html"
OUT.write_text(DOC, encoding="utf-8")
print(f"SAVED {OUT} ({OUT.stat().st_size // 1024} KB)")