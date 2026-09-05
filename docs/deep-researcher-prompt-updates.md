# Deep Researcher System Prompt：主要更新说明

## 1. 更新目标

当前 Deep Researcher 的职责不再只是汇总数据并写出研究结论，而是把研究过程沉淀为一张可复核的 Evidence Graph。更新的核心目标是让图谱能够回答四个问题：

1. 这条 Claim 是什么判断？
2. 它由哪些可追溯 Evidence 支持或削弱？
3. 判断有哪些限制、还缺哪些资料？
4. 图谱在当前信息下是否已经形成可用闭环？

因此，本次 Prompt 的重点不是要求模型产出更多 Claim 或更多边，而是降低“资料堆积、结论跳跃、连接缺失”的概率。

## 2. 从固定轮次改为完整性优先的阶段流程

旧提示词以固定工具轮次安排工作，例如某一轮取数、某一轮建 Claim、最后一轮 export。这种方式在实际运行中容易受工具调用预算、批量调用数量和模型临场决策影响：模型可能过早 export，或在建立 Claim 后没有剩余机会连接 Evidence。

当前 Prompt 改为不绑定固定轮次，但明确最小闭环：

```text
Evidence → Claim → Link → audit → export
```

对应的阶段为：

| 阶段 | 模型应做什么 | 目的 |
|---|---|---|
| 继承与取证 | 优先使用预灌 Evidence，只补会改变判断的关键数据 | 避免重复取数和图谱空转 |
| 沉淀与分类 | 将关键资料写入图，并按研究维度组织 | 区分资料簇与最终判断 |
| 成案 | 基于证据簇创建少量 Claim 或 Missing | 避免从单一数据直接跳到结论 |
| 连边与校准 | 用真实节点 ID 创建实质关系、补充状态与缺口 | 让 Claim 可以追溯 |
| 自检与导出 | audit 后再 set_sufficient / export | 让不完整性可见 |

Prompt 特别禁止在空图、或尚无可用 Claim 时把 `export()` 当成“检查进度”的工具。若外部失败或预算耗尽，只能以不完整图导出，并在 `stop_reason` 说明遗漏的是哪一个环节。

## 3. Evidence：从“资料收集”到“关键证据筛选”

更新后的 Prompt 要求 Evidence 只记录可追溯的事实、数据或事件，并保留来源、日期、口径和关键数字；主观判断不应被写成 Evidence。

在形成 Claim 前，模型需要在内部按五类研究维度归类：

- 基本面与盈利质量；
- 市场表现与预期差；
- 估值；
- 事件与政策；
- 筹码、资金与行业。

每个与问题相关的维度，优先选择一到两条关键 Evidence：一条事实或比较锚点；如可获得，再选一条反方或验证锚点。这里“关键”的标准不是信息看起来很多，而是删除这条资料后，某个 Claim 的事实、比较、限制或验证基础会明显变弱。

这避免把重复的专家摘要、重复转述的工具输出或无关背景全部塞入图谱主线。

## 4. Claim：强调原子化、可证伪和完整推理链

Prompt 将 3–5 条跨维度 Claim 定义为软目标，而非必须凑足的配额。证据不足时，模型应创建 Missing，而不是制造强结论。

每条候选 Claim 在创建前都需要完成内部“解读卡片”：

```text
事实 → 比较 → 反方/限制 → 推断 → 验证条件
```

其中，`claim` 字段只保留一句原子化、可证伪的推断；数字、比较、反方意见和验证条件放入 `rationale` 与 Evidence。`rationale` 使用统一格式：

```text
事实：…；比较：…；反方/限制：…；验证条件：…
```

如果两个判断可被不同资料独立支持、反驳或更新，就应拆成两条 Claim，而不应压缩成一条笨重的综合结论。

此外，`add_claim` 会返回非阻断式 `title_check`。标题太长、数字堆叠、多分句或混入 rationale 标记时，模型应评估是否要通过 `merge(..., merge_ids=[], canonical_claim=...)` 将该 Claim 改写为更短的标题。检查是提示，不会因为单一规则命中而直接删除合理判断。

## 5. Link：从“有边”升级为“有明确语义的实质边”

当前 Prompt 与图层规则统一了关系语义：

| 关系 | 允许方向 | 作用 |
|---|---|---|
| `supports` | Claim → Evidence | 直接支持 Claim |
| `contradicts` | Claim → Evidence | 直接削弱或反驳 Claim |
| `context` | Claim → Evidence | 提供背景，但不构成实质支持 |
| `addresses` | Evidence → Missing | 新资料补足一个研究缺口 |

Prompt 明确要求：每一条最终保留的 Claim 至少有一个 `supports` 或 `contradicts`。`context` 只是背景，不能用来替代实质证据连接。

边的 `note` 也被要求说明具体关系，例如“该财务数据表明单季利润高于上年全年”，而不是只留下抽象的“支持”。这使读者能够理解边的意义，而不只是看到两个节点相连。

## 6. Audit：将自检从模型自觉变成显式步骤

Prompt 要求模型在 export 前调用 `audit()`，优先关注主结论的结构问题。audit 会报告：

- 没有 `supports` / `contradicts` 的 Claim；
- 只有 `context` 的 Claim；
- 孤立 Evidence；
- 尚未被 `addresses` 补足的 Missing；
- 重复边；
- 缺少 `note` 的边。

这里的原则是“处理重要警告”，而不是“清零所有警告”。例如，无关背景 Evidence 可以不进入主线；真正尚未解决的研究问题也应继续保留为 Missing，而不是强行补一条牵强的边。

## 7. 状态与导出门槛

Prompt 对 Claim 状态做了更严格的语义区分：

- `verified`：已有充分、直接的 Evidence 支持；
- `rejected`：已有充分 Evidence 削弱或推翻；
- `needs_more` / `exploring`：仍需要数据或处于探索阶段；
- `insufficient`：现有资料不足以支撑判断。

导出前的最低要求是：若图中已有 Claim，且现有 Evidence 足以为它建立 `supports` 或 `contradicts`，则必须先连边，再 export。Prompt 不要求所有 Claim 都变成 verified，也不要求所有 Missing 都被补齐；它要求的是把已有证据、当前推断和未解决缺口明确区分。

## 8. 预期效果与仍需观察的边界

这次更新预期带来的是研究过程透明度提升：

- Claim 更容易回溯到具体资料；
- 背景、支持、反驳和缺口不再混为一谈；
- 工具预算有限时，优先完成图谱闭环而非无止境取数；
- 不确定性以 Missing、状态和验证条件保留下来。

它不会自动保证投资判断正确，也不会替代数据源质量、事件归因、同业比较或人工研究判断。后续仍应持续观察：标题软警告是否被有效处理、孤立 Evidence 是否合理、Missing 是否在后续研究中得到补足，以及模型能否稳定遵循“Evidence → Claim → Link → audit → export”的闭环。

## 9. 代码位置

实际 system prompt 位于：

- `backend/app/agents/roster.py` 的 `deep_researcher.persona`

与之配套的图谱规则位于：

- `backend/app/skills/evidence_graph.py`
- `backend/app/skills/skill.py`
