# 共享信息层代码修改说明

## 目的

本次修改为团队协作模式增加了一个仅限单次 team run 的共享信息层（`research_context`）。当不同 Agent 发起相同或可安全向下裁切的 Skill 请求时，它尽量复用已成功获取的结果，并避免重复保存相同的 Artifact。

这是一项有限范围的改动：不改变单 Agent 模式的默认执行方式，也不替代现有的进程级 TTL 缓存。

## 修改文件

### `backend/app/agents/research_context.py`

新增 `ResearchContext` 类：

- 按 `Skill 名称 + 规范化参数` 生成稳定键；
- 对 `news_intel` 统一 A 股代码格式、补齐默认 `kind` / `limit`，并对 `kind` 排序去重；这仅扩大同一次 team run 内的等价请求复用，不改变 Skill 的实际检索行为；
- 只缓存成功结果；
- 后续相同请求返回深拷贝，避免调用方修改共享对象；
- 复用结果增加 `_team_shared: true` 标记；
- 对三个有明确包含关系的高层 Skill 做保守的宽结果切片：
  - `news_intel`：相同标的、相同资讯通道集合下，较大 `limit` 可服务较小 `limit`；
  - `market_research`：仅 A 股 `focus=["price"]` 的较长回溯窗口可裁成较短窗口；实时快照字段不切片；
  - `evidence_ledger`：相同标的/关键词/价格窗口下，较大 `limit` 可裁成较小的时间线；
- 宽切片结果也标记为 `_team_shared: true`，并附加 `_team_slice: true`；
- 统计总调用次数、唯一请求数、复用次数和宽切片次数。

失败结果不会缓存，以便后续 Agent 有机会重试。

### `backend/app/agents/team.py`

在 `run_team()` 中创建一个本次运行专属的 `ResearchContext`，并将其传给：

- 串行运行的各个专家 Agent；

router 综合阶段保持无 Skill（`skills: []`）：综合阶段只消费专家已有的发现，不额外发起外部数据请求。

这样不同专家之间可以共享同一次 team run 中已经成功获取的完全相同的 Skill 结果。router 综合阶段不调用 Skill，而是消费专家发现。

运行结束前，会向 `state["tool_trace"]` 追加一条统计记录：

```json
{
  "type": "research_context",
  "calls": 60,
  "unique_calls": 43,
  "reuses": 11,
  "slices": 4
}
```

示例数字仅用于说明字段含义，实际数值由每次运行决定。

### `backend/app/llm.py`

扩展 `run_agent()`，增加可选的 `skill_executor` 参数。

- 默认值仍是原来的 `execute_skill`，因此普通 Agent 调用方式保持兼容；
- 团队模式传入带共享层的执行器；
- 命中共享结果时，结果仍会传给模型，不影响后续分析；
- 命中共享结果时，不再重复执行 Artifact 落库；
- `tool_result` 事件和 `tool_trace` 会记录 `reused: true/false`；
- 前端预览会显示“复用团队数据”。

### `backend/tests/test_agent_and_team.py`

新增测试，模拟两个 Agent 请求相同 Skill，并验证：

- 底层 Skill 执行次数从 2 次降为 1 次；
- Artifact 落库次数从 2 个降为 1 个；
- 第二个 Agent 仍能收到相同结果；
- 工具轨迹正确标记复用状态。

## 当前行为边界

当前共享层处理完全相同的请求、`news_intel` 的等价参数，以及三类保守宽切片；暂不处理：

- `market_research` 中含 `sector`、`flow` 或 `lhb` 的不同字段组合；
- 不同通道集合的 `news_intel`（如 `news + announcement` 与仅 `news`）；
- 不同 Skill 之间的语义去重；
- 复合 Skill 内部所有子请求的统一共享；
- 跨 team run 的持久化共享；
- 数据新鲜度和自动刷新策略。

因此，Artifact 数量减少并不必然意味着所有 Skill 调用或总耗时都会减少。

## 验证情况

已通过共享结果复用、参数规范化和三类宽切片的定向测试、Python 编译检查及 `git diff --check`。完整测试套件未能在当前环境运行，因为系统 Python 缺少项目依赖（包括 `python-dotenv`、`openai`、`akshare`）。

## 使用方式

无需额外开关。启动项目并使用团队协作模式时，共享层会自动启用；单 Agent 模式仍使用原有执行路径。
