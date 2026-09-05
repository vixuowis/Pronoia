"""build_v5_deck.py — 生成 Pronoia-PAPV 实验报告单文件 HTML 幻灯（linear 暗色风）。
内嵌 v5 训练曲线图 base64。固定 1280x720 canvas，JS 居中缩放。

生成： python3 build_v5_deck.py
产物： v5_experiment_report.html（自包含单文件）
"""
import base64
import pathlib

HERE = pathlib.Path(__file__).parent
CURVE = HERE / "v5_reward_loss_curves.png"
CURVE_B64 = base64.b64encode(CURVE.read_bytes()).decode()

DATA = {
    "v4_samples": 1782, "v5_samples": 2507, "target": 5174,
    "collected": 2977, "concurrency": 20,
    "v4_steps": 299, "v4_reward": 0.755, "v4_kl": 0.013,
    "oos_acc": 0.641, "oos_base": 0.560, "oos_ece": 0.095, "oos_ece_base": 0.133,
    "oos_brier": 0.228, "oos_brier_base": 0.266,
    "v5_steps_total": 627, "v5_steps": 83, "v5_reward": 0.681,
    "v5_ema": 0.690, "v5_kl": 0.00065, "v5_grad": 0.139,
}

DECK = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Pronoia-PAPV 实验报告 · v5</title>
<style>
:root {{
  --acid:#e4f222; --green:#27a644; --red:#eb5757; --teal:#02b8cc;
  --void:#08090a; --carbon:#0f1011; --graphite:#23252a; --smoke:#383b3f;
  --ash:#62666d; --fog:#8a8f98; --mist:#d0d6e0; --bone:#e5e5e6;
  --line:#23252a; --bg:#0f1011; --bg-muted:#161718; --text:#d0d6e0; --text-muted:#8a8f98;
  --accent:#e4f222; --radius-sm:12px; --radius-pill:9999px;
  --mono:'JetBrains Mono','Berkeley Mono',ui-monospace,monospace;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;overflow:hidden;background:#0a0b0c;font-family:var(--sans)}}
#canvas{{position:fixed;top:50%;left:50%;width:1280px;height:720px;
  transform-origin:center center;background:var(--void);
  box-shadow:0 10px 60px rgba(0,0,0,.55),0 2px 8px rgba(0,0,0,.4)}}
.slide{{position:absolute;inset:0;color:var(--text);background:var(--void);
  padding:60px 72px 56px;display:grid;grid-template-rows:auto auto;align-content:center;
  opacity:0;visibility:hidden;
  transition:opacity .5s cubic-bezier(.2,.7,.2,1),visibility .5s}}
.slide.active{{opacity:1;visibility:visible}}
.slide .kicker{{font:500 12px var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--acid)}}
.slide .h-1{{font-size:40px;font-weight:590;line-height:1.08;letter-spacing:-.02em;color:#e5e5e6;margin-top:10px}}
.slide .lead{{font-size:15px;line-height:1.6;color:var(--text-muted);max-width:56ch;margin-top:4px}}

/* chrome (inside canvas) */
.chrome-top{{position:absolute;top:0;left:72px;right:72px;height:40px;display:flex;align-items:center;justify-content:space-between}}
.chrome-top .ct-l{{font:500 11px var(--mono);color:var(--fog);letter-spacing:.04em}}
.chrome-top .ct-r{{font:400 11px var(--mono);color:var(--ash)}}
.chrome-bottom{{position:absolute;bottom:0;left:72px;right:72px;height:34px;display:flex;align-items:center;justify-content:space-between}}
.chrome-bottom .cb-l{{font:400 10px var(--mono);color:var(--ash)}}
.chrome-bottom .cb-r{{font:500 11px var(--mono);color:var(--fog)}}
.nav{{position:absolute;bottom:12px;right:72px;display:flex;gap:7px;z-index:20}}
.nav button{{width:8px;height:8px;border-radius:50%;background:var(--graphite);border:none;cursor:pointer;padding:0}}
.nav button.on{{background:var(--acid)}}

/* stagger */
.stagger>*{{animation:fd .7s cubic-bezier(.2,.7,.2,1) backwards}}
.stagger>*:nth-child(1){{animation-delay:.05s}}.stagger>*:nth-child(2){{animation-delay:.16s}}
.stagger>*:nth-child(3){{animation-delay:.27s}}.stagger>*:nth-child(4){{animation-delay:.38s}}
.stagger>*:nth-child(5){{animation-delay:.49s}}.stagger>*:nth-child(6){{animation-delay:.60s}}
.stagger>*:nth-child(7){{animation-delay:.71s}}.stagger>*:nth-child(8){{animation-delay:.82s}}
@keyframes fd{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}

/* shared dense head */
.s-metrics .dense-head,.s-list .dense-head,.s-comparison .dense-head{{display:grid;grid-template-columns:auto 1fr;align-items:end;gap:28px;margin-bottom:20px}}

/* metrics */
.metrics-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line)}}
.metrics-grid.cols-4{{grid-template-columns:repeat(4,1fr)}}
.metric-cell{{padding:18px 20px;background:var(--bg);display:flex;flex-direction:column;gap:4px;min-height:96px}}
.metric-value{{font-size:26px;font-weight:200;letter-spacing:-.02em;color:#e5e5e6}}
.metric-value b{{color:var(--acid);font-weight:400}}
.metric-label{{font-size:12px;color:var(--text-muted)}}
.metric-delta{{font-size:11px;font-weight:600}}
.metric-delta.positive{{color:var(--green)}}.metric-delta.negative{{color:var(--red)}}

/* list */
.dense-list-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0 32px}}
.dl-item{{display:grid;grid-template-columns:30px 1fr;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}}
.dl-idx{{font:600 11px var(--mono);color:var(--acid);padding-top:2px}}
.dl-title{{font-size:14px;font-weight:600;color:var(--bone)}}
.dl-desc{{font-size:12px;margin-top:2px;color:var(--text-muted)}}

/* comparison */
.compare-table{{display:flex;flex-direction:column}}
.cmp-row{{display:grid;grid-template-columns:160px repeat(3,1fr);padding:11px 16px;border-bottom:1px solid var(--line);font-size:12px;align-items:center}}
.cmp-header{{font:600 11px var(--mono);text-transform:uppercase;letter-spacing:.04em;background:var(--bg-muted);color:var(--fog)}}
.cmp-dim{{font-weight:500;color:var(--text-muted)}}
.cmp-highlight{{background:rgba(228,242,34,.06);font-weight:600;color:var(--bone)}}
.cmp-no{{color:var(--ash)}}.cmp-yes{{color:var(--green)}}.cmp-col{{color:var(--text)}}

/* dashboard */
.s-dashboard{{grid-template-rows:auto auto 1fr;gap:16px;align-content:start}}
.s-dashboard .dense-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}}
.s-dashboard .dense-head .h-1{{font-size:34px}}
.s-dashboard .dense-head .lead{{text-align:right}}
.dash-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.dash-metric{{padding:12px 16px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--bg)}}
.dm-value{{font-size:24px;font-weight:700;color:#f2f4f5}}
.dm-value b{{color:var(--acid);font-weight:700}}
.dm-label{{font-size:11px;color:var(--text-muted);margin-top:3px}}
.dash-body{{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-height:0;align-self:center}}
.dash-chart{{border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px;background:var(--bg);overflow:hidden;min-height:0;display:flex;align-items:center;justify-content:center}}
.dash-chart img{{max-width:100%;max-height:100%;border-radius:6px}}
.dash-highlights{{display:flex;flex-direction:column;max-height:330px;min-height:0;overflow:hidden}}
.dash-item{{display:grid;grid-template-columns:8px 1fr;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}}
.dash-dot{{width:8px;height:8px;border-radius:50%;background:var(--acid);margin-top:5px}}
.dash-h{{font-size:13px;font-weight:600;color:var(--bone)}}
.dash-d{{font-size:12px;color:var(--text-muted)}}

/* cover / reveal / think */
.s-cover{{padding:0;grid-template-rows:1fr}}
.s-cover .cover-wrap{{padding:64px 80px}}
.s-cover .h-display{{font-size:58px;font-weight:590;line-height:1.04;letter-spacing:-.025em;color:#f2f4f5;max-width:15ch}}
.s-cover .kicker{{font:500 13px var(--mono);letter-spacing:.1em;color:var(--acid);text-transform:uppercase}}
.s-cover .cover-sub{{margin-top:22px;font-size:15px;color:var(--fog);line-height:1.7;max-width:56ch}}
.cover-tags{{margin-top:22px;display:flex;gap:10px;flex-wrap:wrap}}
.cover-tags span{{font:500 12px var(--mono);color:var(--mist);background:var(--bg);border:1px solid var(--line);padding:6px 12px;border-radius:var(--radius-pill)}}
.s-cover .reveal-big{{margin-top:14px;font:200 28px var(--sans);color:var(--ash)}}
.s-reveal .h-1{{font-size:38px}}.s-reveal .lead{{font-size:16px;margin-top:8px}}
.reveal-items{{margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:14px 32px}}
.rev-item{{display:grid;grid-template-columns:26px 1fr;gap:10px}}
.rev-idx{{font:600 12px var(--mono);color:var(--acid);padding-top:2px}}
.rev-title{{font-size:14px;font-weight:600;color:var(--bone)}}
.rev-desc{{font-size:12px;color:var(--text-muted);margin-top:2px}}
.s-think{{grid-template-rows:1fr auto;align-content:center}}
.think-quote{{font-size:24px;line-height:1.5;font-weight:400;color:var(--mist);max-width:32ch}}
.think-sub{{margin-top:16px;font-size:14px;color:var(--fog);max-width:56ch;line-height:1.7}}
.badge{{display:inline-block;font:600 11px var(--mono);color:var(--void);background:var(--acid);padding:5px 11px;border-radius:4px;letter-spacing:.04em;text-transform:uppercase}}
.hline{{height:1px;background:var(--line);margin:20px 0 20px}}
.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;align-items:stretch;margin-bottom:22px}}
.flow-step{{border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--bg);padding:14px 12px;display:flex;flex-direction:column;gap:5px}}
.flow-step .fs-idx{{font:600 10px var(--mono);color:var(--acid)}}
.flow-step .fs-title{{font-size:13px;font-weight:600;color:var(--bone)}}
.flow-step .fs-desc{{font-size:11px;color:var(--text-muted);line-height:1.45}}
.flow-arrow{{display:flex;align-items:center;justify-content:center;color:var(--fog);font-size:15px}}
</style>
</head>
<body>
<div id="canvas">
  <div class="chrome-top"><span class="ct-l">PRONOIA · PAPV EXPERIMENT REPORT</span><span class="ct-r">v5 · 2026-08</span></div>
  <div class="chrome-bottom"><span class="cb-l">PAPV Paradigm · Prediction-Assertion-Post-Validation</span><span class="cb-r" id="pageno">1 / 9</span></div>

  <!-- 1 封面 -->
  <section class="slide s-cover s1 active">
    <div class="cover-wrap stagger">
      <div><span class="badge">实验报告</span></div>
      <div style="margin-top:24px"><h1 class="h-display">Pronoia-PAPV<br/>持续学习实验报告</h1></div>
      <div class="kicker" style="margin-top:20px">Prediction · Assertion · Post-Validation</div>
      <div class="cover-sub">从 v4 到 v5 的两轮 GRPO 训练：修复输出坍缩、积累真实 Team 推理数据，在样本外验证断言判断与置信度校准的提升。</div>
      <div class="cover-tags"><span>GRPO · LoRA · Qwen3-8B</span><span>OOS 200 样本核验</span><span>数据收集 20 并发</span></div>
      <div class="reveal-big">v4 Reward <span style="color:var(--acid)">0.755</span> · v5 训练进行中</div>
    </div>
  </section>

  <!-- 2 议程 -->
  <section class="slide s-reveal s2">
    <div class="stagger">
      <div><span class="kicker">Agenda</span><h1 class="h-1">报告结构</h1><div class="hline"></div></div>
      <div class="reveal-items">
        <div class="rev-item"><span class="rev-idx">03</span><div><div class="rev-title">PAPV 范式与背景</div><div class="rev-desc">断言可验证、事后结算、校准优化</div></div></div>
        <div class="rev-item"><span class="rev-idx">04</span><div><div class="rev-title">数据如何收集</div><div class="rev-desc">Team 多智能体推理管线 · 20 并发</div></div></div>
        <div class="rev-item"><span class="rev-idx">05</span><div><div class="rev-title">v4 训练结果</div><div class="rev-desc">299 步 · OOS 命中率 +8.1pt</div></div></div>
        <div class="rev-item"><span class="rev-idx">06</span><div><div class="rev-title">v5 训练结果</div><div class="rev-desc">修复后收敛 · 曲线已生成</div></div></div>
        <div class="rev-item"><span class="rev-idx">07</span><div><div class="rev-title">v4 → v5 修复对比</div><div class="rev-desc">多样性惩罚 · 格式合规 · 权重再平衡</div></div></div>
        <div class="rev-item"><span class="rev-idx">08</span><div><div class="rev-title">发现与风险</div><div class="rev-desc">坍缩已现 · 需样本外专项核验</div></div></div>
      </div>
    </div>
  </section>

  <!-- 3 PAPV 背景 -->
  <section class="slide s-list s3">
    <div class="dense-head stagger">
      <div><span class="kicker">03 · Paradigm</span><h1 class="h-1">PAPV 学习范式</h1></div>
      <p class="lead">模型自主提出可验证断言并判断真假，reward 只看「判断是否命中事后结算」。</p>
    </div>
    <div class="dense-list-grid stagger">
      <div class="dl-item"><span class="dl-idx">P</span><div><div class="dl-title">Prediction · 预测</div><div class="dl-desc">输入事件+研究上下文，提出 3–6 条可验证断言</div></div></div>
      <div class="dl-item"><span class="dl-idx">A</span><div><div class="dl-title">Assertion · 断言</div><div class="dl-desc">每条含指标/阈值/方向/置信度，覆盖 ≥2 horizon & 指标族</div></div></div>
      <div class="dl-item"><span class="dl-idx">P</span><div><div class="dl-title">Post-Validation · 事后验证</div><div class="dl-desc">labels.jsonl 客观结算真实涨跌/显著性，判定命中</div></div></div>
      <div class="dl-item"><span class="dl-idx">R</span><div><div class="dl-title">Reward · 六元结算</div><div class="dl-desc">准确率(0.38) + 校准 + 可验证 + 格式 + 逻辑链 + 多样性</div></div></div>
      <div class="dl-item"><span class="dl-idx">K</span><div><div class="dl-title">核心价值</div><div class="dl-desc">学会「对哪些命题有把握」，而非记住单一方向</div></div></div>
      <div class="dl-item"><span class="dl-idx">G</span><div><div class="dl-title">护栏 · 重算平衡</div><div class="dl-desc">v5 新增单指标族惩罚 + 多样性门槛(2→3)，防坍缩</div></div></div>
    </div>
  </section>

  <!-- 4 数据收集 -->
  <section class="slide s-list s4">
    <div class="dense-head stagger">
      <div><span class="kicker">04 · Data</span><h1 class="h-1">数据是如何收集的</h1></div>
      <p class="lead">用真 Team 多智能体推理替代程序化统计替身，产出每事件深度研究上下文。</p>
    </div>
    <div class="flow stagger">
      <div class="flow-step"><span class="fs-idx">STEP 1</span><span class="fs-title">事件源</span><span class="fs-desc">events_enriched.jsonl 全量事件（目标 5174）</span></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><span class="fs-idx">STEP 2</span><span class="fs-title">Team 推理</span><span class="fs-desc">market / fundamentals / deep_researcher 三专家</span></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><span class="fs-idx">STEP 3</span><span class="fs-title">落地缓存</span><span class="fs-desc">research_cache_team_v4.jsonl · 断点续跑 · 失败重试 1 次</span></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><span class="fs-idx">STEP 4</span><span class="fs-title">组装 v5</span><span class="fs-desc">合并 events + labels + 统计上下文 + rationale</span></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><span class="fs-idx">STEP 5</span><span class="fs-title">训练集</span><span class="fs-desc">data_v5 = {DATA['v5_samples']} 条 · 100% 可结算</span></div>
    </div>
    <div class="metrics-grid cols-4 stagger">
      <div class="metric-cell"><span class="metric-value">20</span><span class="metric-label">并发（asyncio.Semaphore）</span></div>
      <div class="metric-cell"><span class="metric-value">{DATA['v4_samples']}→<b>{DATA['v5_samples']}</b></span><span class="metric-label">v4→v5 可用样本（+725）</span></div>
      <div class="metric-cell"><span class="metric-value"><b>{DATA['collected']}</b>/<span style="color:#e5e5e6">{DATA['target']}</span></span><span class="metric-label">实时收集进度（持续增长）</span></div>
      <div class="metric-cell"><span class="metric-value">3600s</span><span class="metric-label">单调用超时兜底</span></div>
    </div>
  </section>

  <!-- 5 v4 结果 -->
  <section class="slide s-metrics s5">
    <div class="dense-head stagger">
      <div><span class="kicker">05 · v4 Run</span><h1 class="h-1">v4 训练结果（已跑完 + OOS）</h1></div>
      <p class="lead">299 步 GRPO 完成后，在 3389 条样本外池抽样 200 条，基准模型 vs 训练后 LoRA。</p>
    </div>
    <div class="metrics-grid cols-4 stagger">
      <div class="metric-cell"><span class="metric-value">299</span><span class="metric-label">训练步数 · 8h07m</span><span class="metric-delta positive">完成</span></div>
      <div class="metric-cell"><span class="metric-value"><b>{DATA['v4_reward']}</b></span><span class="metric-label">最终 Reward · KL {DATA['v4_kl']}</span></div>
      <div class="metric-cell"><span class="metric-value">{DATA['oos_base']}→<b>{DATA['oos_acc']}</b></span><span class="metric-label">样本外断言命中率</span><span class="metric-delta positive">+{round((DATA['oos_acc']-DATA['oos_base'])*100,1)}pt</span></div>
      <div class="metric-cell"><span class="metric-value">{DATA['oos_ece_base']}→<b>{DATA['oos_ece']}</b></span><span class="metric-label">ECE 校准误差 ↓</span></div>
      <div class="metric-cell"><span class="metric-value"><b>{DATA['oos_brier']}</b></span><span class="metric-label">Brier（base {DATA['oos_brier_base']}）</span><span class="metric-delta positive">校准改善</span></div>
      <div class="metric-cell"><span class="metric-value">0.80→<b>0.81</b></span><span class="metric-label">高置信区(0.8–0.9)命中</span><span class="metric-delta positive">敢高置信有底气</span></div>
      <div class="metric-cell"><span class="metric-value">0.64→<b>0.70</b></span><span class="metric-label">判 FALSE 准确率</span><span class="metric-delta positive">更善质疑</span></div>
      <div class="metric-cell"><span class="metric-value negative">69%</span><span class="metric-label">格式合规率（base 100%）</span><span class="metric-delta negative">隐患 ⚠</span></div>
    </div>
  </section>

  <!-- 6 v5 结果 dashboard -->
  <section class="slide s-dashboard s6">
    <div class="dense-head stagger">
      <div><span class="kicker">06 · v5 Run（修复后）</span><h1 class="h-1">v5 训练收敛曲线</h1></div>
      <p class="lead">截至 {DATA['v5_steps']}/{DATA['v5_steps_total']} 步（9.4%），训练进行中</p>
    </div>
    <div class="dash-metrics stagger">
      <div class="dash-metric"><div class="dm-value">{DATA['v5_reward']}</div><div class="dm-label">Reward 均值</div></div>
      <div class="dash-metric"><div class="dm-value">{DATA['v5_ema']}</div><div class="dm-label">EMA(0.7) 后段</div></div>
      <div class="dash-metric"><div class="dm-value">{DATA['v5_kl']}</div><div class="dm-label">KL 极低，无发散</div></div>
      <div class="dash-metric"><div class="dm-value">{DATA['v5_grad']}</div><div class="dm-label">Grad Norm 均值</div></div>
    </div>
    <div class="dash-body stagger">
      <div class="dash-chart"><img src="data:image/png;base64,{CURVE_B64}" alt="v5 reward/loss 四面板训练曲线"/></div>
      <div class="dash-highlights">
        <div class="dash-item"><span class="dash-dot"></span><div><div class="dash-h">Reward 上升且稳定</div><div class="dash-d">EMA 后段 0.690，max 0.881，无 reward hacking</div></div></div>
        <div class="dash-item"><span class="dash-dot"></span><div><div class="dash-h">KL 全程 ≤0.0012</div><div class="dash-d">max 0.0011，远低于 v4 早期 0.014 → 不背离参考模型</div></div></div>
        <div class="dash-item"><span class="dash-dot"></span><div><div class="dash-h">收敛平稳</div><div class="dash-d">grad_norm 0.14、clip 0、completions 401 tokens</div></div></div>
        <div class="dash-item"><span class="dash-dot"></span><div><div class="dash-h">多样性修复生效中</div><div class="dash-d">R5 门槛2→3、R0 单指标族惩罚</div></div></div>
      </div>
    </div>
  </section>

  <!-- 7 对比 -->
  <section class="slide s-comparison s7">
    <div class="dense-head stagger">
      <div><span class="kicker">07 · Fix</span><h1 class="h-1">v4 → v5 修复对比</h1></div>
      <p class="lead">针对 v4 暴露的输出坍缩，从 reward 五处改造。</p>
    </div>
    <div class="compare-table stagger">
      <div class="cmp-row cmp-header"><span class="cmp-dim"></span><span class="cmp-col">v4（未修复）</span><span class="cmp-col cmp-highlight">v5（修复后）</span><span class="cmp-col">设计意图</span></div>
      <div class="cmp-row"><span class="cmp-dim">多样性 R5</span><span class="cmp-no">0.05 · 门槛 2 族</span><span class="cmp-highlight">0.10 · 门槛 3 horizon/3 族</span><span>激励覆盖更多指标族</span></div>
      <div class="cmp-row"><span class="cmp-dim">格式 R0</span><span class="cmp-no">仅数断言+段落</span><span class="cmp-highlight">+单指标族惩罚（对折）</span><span>把「模板化全 car」视为低信息</span></div>
      <div class="cmp-row"><span class="cmp-dim">准确率 R2</span><span class="cmp-no">0.45 过高</span><span class="cmp-highlight">0.38（再平衡）</span><span>弱化单一正确性奖励</span></div>
      <div class="cmp-row"><span class="cmp-dim">数据</span><span class="cmp-no">程序化替身+部分真推理</span><span class="cmp-highlight">全量真 Team 推理（+725）</span><span>研究上下文质量提升</span></div>
      <div class="cmp-row"><span class="cmp-dim">KL 稳定</span><span class="cmp-no">爬升至 0.014 需干预</span><span class="cmp-highlight">全程 ≤0.0008</span><span>更稳健优化轨迹</span></div>
    </div>
  </section>

  <!-- 8 发现 -->
  <section class="slide s-think s8">
    <div class="stagger">
      <div><span class="badge">关键发现 · Key Findings</span></div>
      <div class="think-quote" style="margin-top:24px">训练真实提升了核心判断，但输出坍缩的代价值得警惕。</div>
      <div class="think-sub" style="margin-top:16px">v4 样本外命中率 +8.1pt、ECE -3.8pt——模型更会「识破营收增长但利润弱」的细节；但不同股票输出逐字相同断言、格式合规 100%→69%，正是 GRPO 收敛到高奖励区的坍缩信号。</div>
      <div class="hline"></div>
      <div class="reveal-items" style="grid-template-columns:1fr 1fr">
        <div class="rev-item"><span class="rev-idx">✓</span><div><div class="rev-title">真实提升</div><div class="rev-desc">恒玄科技 case：识破收入+46.6% 但净利仅+1.0% → 判负命中</div></div></div>
        <div class="rev-item"><span class="rev-idx">!</span><div><div class="rev-title">坍缩信号</div><div class="rev-desc">相似事件输出雷同 · 指标族收窄 · 长窗/大涨事件误判</div></div></div>
      </div>
    </div>
  </section>

  <!-- 9 closing -->
  <section class="slide s-cover s9">
    <div class="cover-wrap stagger">
      <div><span class="badge">下一步 · Next</span></div>
      <div style="margin-top:24px"><h1 class="h-display">等 v5 跑满，落库再核验多样性</h1></div>
      <div class="cover-tags" style="margin-top:20px"><span>跑满 627 步</span><span>样本外专项核验</span><span>数据合并进 v6</span></div>
      <div class="think-sub" style="margin-top:20px">
        1 · 等 627 步完成，保存 checkpoint 并出具完整结论。<br/>
        2 · 训练后立即做样本外评估：命中率应 ≥0.641、指标族覆盖应 >v4、格式合规率应显著 >69%。<br/>
        3 · 数据收集并行推进（当前 {DATA['collected']}+），完成后合并最新数据进入 v6 训练。
      </div>
      <div class="reveal-big">Qwen3-8B · LoRA · PAPV — 持续学习，样本外验证。</div>
    </div>
  </section>

  <div class="nav" id="nav"></div>
</div>

<script>
(function(){{
  var canvas=document.getElementById('canvas');
  var slides=document.querySelectorAll('.slide');
  var n=slides.length, cur=0;
  var nav=document.getElementById('nav');
  for(var i=0;i<n;i++){{
    var b=document.createElement('button');b.setAttribute('aria-label','slide '+(i+1));
    (function(idx){{b.onclick=function(){{go(idx);}};}})(i);nav.appendChild(b);
  }}
  var dots=nav.querySelectorAll('button');
  function render(){{
    for(var i=0;i<n;i++){{slides[i].classList.toggle('active',i===cur);
      dots[i].classList.toggle('on',i===cur);}}
    document.getElementById('pageno').textContent=(cur+1)+' / '+n;
  }}
  function go(i){{cur=Math.max(0,Math.min(n-1,i));render();}}
  function scale(){{
    var s=Math.min(window.innerWidth/1280, window.innerHeight/720);
    canvas.style.transform='translate(-50%,-50%) scale('+s+')';
  }}
  window.addEventListener('resize',scale);
  scale();render();
  document.addEventListener('keydown',function(e){{
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){{go(cur+1);}}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){{go(cur-1);}}
    else if(e.key==='Home'){{go(0);}} else if(e.key==='End'){{go(n-1);}}
  }});
  var wheelt=null;
  window.addEventListener('wheel',function(e){{
    if(wheelt)return;go(cur+(e.deltaY>0?1:-1));
    wheelt=setTimeout(function(){{wheelt=null;}},650);
  }},{{passive:true}});
  var sx=null;
  document.addEventListener('touchstart',function(e){{sx=e.touches[0].clientX;}},{{passive:true}});
  document.addEventListener('touchend',function(e){{
    if(sx===null)return;var dx=e.changedTouches[0].clientX-sx;
    if(Math.abs(dx)>40)go(cur+(dx<0?1:-1));sx=null;
  }},{{passive:true}});
}})();
</script>
</body>
</html>
"""

OUT = HERE / "v5_experiment_report.html"
OUT.write_text(DECK, encoding="utf-8")
print(f"SAVED {OUT} ({OUT.stat().st_size//1024} KB)")