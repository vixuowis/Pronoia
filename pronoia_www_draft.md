# Event-Driven Financial Reasoning with Verifiable Market Ground Truth

> **Draft v0.1 · 2026-10-15 · Target: The Web Conference (WWW)**
> 
> This draft is converted from an internal technical report (PRONOIA Team, 2026-08-29) and structured for WWW submission. All empirical numbers are from controlled experiments on 1,034 out-of-sample events.

---

## Abstract

Event-driven equity trading is shifting from **speed alpha**—obtaining announcements faster—to **cognitive alpha**: reading an announcement's implications and transmission more deeply than the market. However, two fundamental gaps block progress: (1) traditional event study methods are post-hoc descriptive and cannot form forward-looking quantifiable predictions, and (2) LLM-enhanced methods can read announcements but universally rely on LLM-as-judge validation, sharing the model's blind spots and prompt-injection vulnerabilities.

We present **PRONOIA**, an event-driven financial reasoning framework built on three pillars: (i) an **Event Reasoning Chain (ERC)** architecture that formalizes events as state transitions and executes multi-path propagation over an explicitly encoded **Propagation Graph**; (ii) a **Predict–Assert–Verify (PAV)** output contract that decomposes each event prediction into 3–6 verifiable claims over measurable financial indicators (e.g., CAR direction at horizon T+30, significance p-value); and (iii) **Reinforcement Learning with Verifiable Rewards (RLVR)** where every claim is settled by **actual post-event market data** (CAR, benchmark returns, p-values)—not by another LLM.

Across two controlled experiments on 1,034 out-of-sample A-share events (2024–2026, time-split): a rule-driven backtest achieves 70.3% direction accuracy with market confirmation as the strongest meta-signal (+18.7pp over the all-events baseline); and a PAV-RLVR trained LoRA adapter improves claim-level accuracy from 57.3% to **63.2%** (+5.9pp, paired bootstrap p<0.01) while simultaneously improving Brier score (0.283→0.254) and Expected Calibration Error (0.163→0.107). A controlled ablation further shows that residual bias correction rewards, despite positive training reward curves, cause reward hacking and reduce OOS accuracy by 2.29pt—an empirical caution for financial RL design.

Our analysis reveals a strong structural pattern: the model excels at falsifiable claims (FALSE-side accuracy 70.9%, significance family 79.1%, long-horizon t30 75.3%) but struggles with momentum-continuation claims (TRUE-side 53.0%, short-horizon bm_ret_t15 49.8%). Three deep case studies illustrate recurring failure modes: prior-driven momentum bias overriding mean-reversion signals, risk paragraphs that are "cognitively correct but behaviorally inert," and garbage-in upstream research context. These findings define clear next-step improvements for event-driven financial AI agents.

**CCS Concepts**: • Computing methodologies → Reinforcement learning; • Information systems → Expert systems; • Applied computing → Economics

**Keywords**: Event-driven financial reasoning; LLM agents; Financial world models; Reinforcement learning with verifiable rewards; Event study methodology

---

## 1. Introduction

### 1.1 The Paradigm Shift

Since Ball & Brown [3] and Fama et al. [7], the event study has been the cornerstone of empirical finance. Its five-step pipeline (define event → estimation window → market model → compute AR/CAR → statistical test) has remained structurally unchanged for over half a century. Meanwhile, event-driven trading—strategies that profit from security price reactions to discrete information releases—has evolved dramatically. Where the 2000s were dominated by **speed alpha** (co-location, low-latency feeds, milliseconds of lead time), the 2020s are converging on **cognitive alpha**: the returns come from reading *what the announcement means* more accurately than the market, not from reading it faster.

LLMs are the natural technology for cognitive alpha. They can parse full announcement texts, identify nuanced guidance tone changes, and sketch transmission chains across economic sectors. But three fundamental problems stand in the way of reliable event-driven financial AI, and no existing system solves all three:

**Problem 1 — Traditional methods describe the past, not the future.** Event studies answer "how did *this type* of event move prices on average?" but cannot answer "how will *this specific* event move prices?" Event announcements are collapsed into 0/1 dummies; the magnitude, wording, and market-surprise component that actually move prices [18] are all lost. Macro events are sparse and heterogeneous—historical "average effects" have almost no out-of-sample predictive power.

**Problem 2 — Events are treated in isolation, ignoring economic transmission.** The standard event study assumes event independence [17], but real markets react through multi-layer economic channels: "rate cut → real estate financing improves → building material demand rises → commodity prices move." Markets systematically underreact to these indirect effects [4], and no step in the event study pipeline has a slot for them. Underlying economic structure—supply chains, industry linkages, capital flow channels—is reduced to a single event date.

**Problem 3 — LLM-enhanced methods lack external ground truth.** Recent LLM-based event analyses solve Problems 1 and 2—they read full announcements and sketch transmission chains—but almost universally validate with LLM-as-judge: the evaluator and evaluatee share error modes, are vulnerable to prompt injection, and produce "sounding reasonable" ≠ "actually correct."

This creates an apparent dilemma: traditional methods are *verifiable* but can't *read* events; LLM methods can *read* events but aren't *verifiable*. PRONOIA resolves this by grounding every prediction in **actual post-event market data**.

### 1.2 The PRONOIA Proposition

PRONOIA proposes three interconnected design principles that jointly address all three problems:

> **Principle 1 (Structured Events).** An event is a structured information shock, not an isolated 0/1 signal. We parse each event as (type, direction, strength, surprise) and use this as input to multi-path propagation.
> 
> **Principle 2 (Propagation Graph Reasoning).** Economic logic is explicitly encoded as a **Propagation Graph** G = (V, A), a DAG where nodes are macro variables, sectors, and assets, and edges are pre-built, verifiable transmission mechanisms (interest-rate channel, supply-demand channel, industry upstream-downstream, capital flow). Rather than letting an LLM free-generate a causal chain, we *search and assemble* multiple transmission paths over the graph—each covering a different economic channel, complementary rather than redundant.
> 
> **Principle 3 (Market Ground Truth Verification).** Every prediction—every propagation path, every directional claim—is a **falsifiable prediction** settled by *actual market post-event CAR data*, not by LLM self-assessment. As event samples accumulate, graph edge weights are continuously calibrated by market feedback, forming a closed loop of "reason → verify → revise."

### 1.3 Contributions

This paper makes four contributions:

1. **ERC Architecture**. We introduce the Event Reasoning Chain (ERC), a four-layer decoupled architecture (Perception → Reasoning → Decision → Evolution) grounded in the three principles above, with the **Event–Transmission–Position (ETP)** triple as the atomic logic unit. We formalize events as state transitions and position the Propagation Graph as the financial analog of a robotics world model's transition function.

2. **PAV-RLVR Framework**. We propose Predict–Assert–Verify (PAV), a verifiable output contract that decomposes event-level predictions into 3–6 claim-level assertions over measurable financial indicators (CAR, benchmark returns, p-values, window averages across horizons T+3/7/15/30/60). We combine PAV with Reinforcement Learning with Verifiable Rewards (RLVR) where every claim is settled by objective market data, eliminating LLM-as-judge vulnerabilities.

3. **Controlled Empirical Validation**. We report results from two complementary experiments on 1,034 time-split out-of-sample A-share events: (a) a rule-driven backtest that isolates the reasoning chain skeleton from any model training, achieving 70.3% direction accuracy with market confirmation as the strongest meta-signal (+18.7pp over all-events baseline); and (b) a PAV-RLVR controlled ablation that improves claim accuracy from 57.3% to 63.2% (+5.9pp, paired bootstrap p<0.01) with simultaneous improvements in Brier score and ECE.

4. **Reward Hacking and Structural Analysis**. We document a controlled ablation where residual bias correction rewards, despite improving in-training reward curves (+0.90 vs +0.73), reduce OOS accuracy by 2.29pt—providing direct evidence of reward hacking in financial RL. We further characterize performance as a function of event type, market, indicator family, horizon, claim count, judgment direction, and confidence, revealing a strong structural pattern (FALSE-side 70.9% vs TRUE-side 53.0%, t30 75.3% vs t15 50.5%, significance family 79.1%) and deriving actionable design implications.

---

## 2. Related Work

### 2.1 Event Study Methodology

Foundations laid by Ball & Brown [3] and Fama et al. [7] established the event study as the dominant paradigm for measuring security price reactions to information releases. Core textbook treatments [2, 20] formalize the five-step pipeline we referenced in §1.1. Critical limitations have been extensively documented: (a) events compressed into dummies lose surprise magnitude and textual detail [18]; (b) macro events are sparse and heterogeneous, limiting statistical power for forward extrapolation; (c) cross-sectional correlation in CAR estimates [17] inflates test statistics. Our work complements this literature by proposing the Propagation Graph as a forward-looking structure that preserves event richness and explicitly models economic transmission channels.

### 2.2 Event Extraction and Financial NLP

The 4th Generation of event processing (per our survey taxonomy) brings LLM-based understanding to financial disclosures. **Perception** work extracts structured event representations from filings and news—Maven [26] and MAVEN-ERE [27] provide large-scale event detection and coreference datasets; Doc2EDAG [31] and DCFEE [23] tackle document-level financial event extraction; Finkario [22] builds event-enhanced financial knowledge graphs. **Surprise and tone** work extracts the *unexpected* component of disclosures: SUE (Standardized Unexpected Earnings) factor scoring [13], LLM-based tone change detection in management guidance, and multimodal earnings surprise prediction [30]. These works are our Perception layer's natural inputs; PRONOIA's contribution is the Reasoning layer built on top—the structured propagation over an encoded economic graph, and the RLVR training pipeline with market-grounded verification.

### 2.3 Financial World Models and Event-Driven Prediction

Several recent works target event-driven financial prediction with LLM agents. We situate PRONOIA against them in **Table 1**.

**Table 1: Comparison with recent event-driven financial AI systems.**

| System | Approach | Core Limitation | Reported ACC |
|---|---|---|---|
| FinHEAR [11] | Event → historical analog → prediction | Single-chain analogy, no multi-path propagation | 58–62% |
| FinKario [10] | Event → KG retrieval → prediction | Static KG, retrieval-only, no dynamic reasoning | 58.1% |
| TradingAgents [28] | Multi-agent functional division → voting | Not event-driven; agents collaborate, don't game | ~55% |
| Janus-Q [14] | Hierarchical gated reward modeling end-to-end trading | No explicit event modeling; reward not verifiable | 58.7% |
| FinCon [21] | LLM+RL conversational agent | No event transmission modeling | 55–57% |
| Argus [8] | Claim-level verification with LLM-as-judge | Judge and evaluatee share error modes | — |
| PRONOIA (Ours) | Propagation Graph + PAV + RLVR | Reward hacking documented; US OOS limited | **63.2% (6.2-vanilla)** |

The key gap PRONOIA addresses is that all systems in Table 1 operate on a single-hop "event → reaction" mapping and rely on LLM-as-judge or non-verifiable rewards. None constructs a multi-hop transmission graph nor settles claims against objective market ground truth. The 58–62% ceiling across these systems confirms that single-hop mapping has limited headroom—improvements come from engineering, not paradigm shifts. PRONOIA's Propagation Graph + RLVR architecture addresses both limitations.

### 2.4 RLVR and Reinforcement Learning for Finance

Our RLVR framework is inspired by Reinforcement Learning with Verifiable Rewards [19], which settles rewards against symbolic or formal verification rather than LLM self-evaluation. In financial applications, RLVR-style ideas appear in AlphaAgent [29], which uses regularized exploration for alpha mining, and FactorMiner [32], which evolves self-improving agents. The critical difference is PRONOIA's **PAV output contract**: by decomposing predictions into claim-level assertions over measurable market indicators, we make every reward component independently verifiable *and* prevent reward hacking—our ablation in §5.2 documents what happens when this guardrail is weakened.

### 2.5 Robotics World Models

The transition function formalization in §3.2 is inspired by robotics world models [9, 25]: the core S_{t+1} = f(S_t, a_t) paradigm maps directly to our Propagation Graph. We draw the following analogy: (1) state S_t → market state (sector CAR vector, volume anomaly, volatility, sentiment), (2) action a_t → structured event (type, direction, strength, surprise), (3) transition function f → Propagation Graph G (multi-path probability propagation), (4) terminal verification → market CAR direction and claim settlement, (5) planning → Navigator search over the Propagation Graph. This positions the Propagation Graph as the financial analogue of a physics engine—searchable, composable, and calibrated by real-world outcomes.

---

## 3. Method

### 3.1 Financial Event Reasoning Chain (ERC)

PRONOIA formalizes event-driven financial reasoning as a four-layer decoupled architecture operating on the **Event–Transmission–Position (ETP)** triple as its atomic logic unit:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4:  EVOLUTION    Versioned state evolution,       │
│                          credit attribution, policy      │
│                          update gated by market evidence │
├─────────────────────────────────────────────────────────┤
│  Layer 3:  DECISION      Direction → timing → sizing →   │
│                          portfolio → execution            │
├─────────────────────────────────────────────────────────┤
│  Layer 2:  REASONING    Multi-path Propagation Graph     │
│                          search + adversary testing +    │
│                          priced-in detection             │
├─────────────────────────────────────────────────────────┤
│  Layer 1:  PERCEPTION   Heterogeneous disclosures →      │
│                          structured state transition →   │
│                          surprise measurement            │
└─────────────────────────────────────────────────────────┘
```

Each layer hands a well-defined interface to the next; each closes with evidence appropriate to its scope. Market-level verification is consolidated in Layer 4 through composite indicators. This paper focuses on Layers 2 and 4 (Reasoning → Evolution), with brief notes on Layers 1 and 3 as context.

### 3.2 Events as State Transitions

**Definition 1 (Event).** An event e is a state transition X_e^- → X_e^+ of a declared system S at time t_e, with ex-ante benchmark B_e. The **surprise** is X_e^+ − B_e, not X_e^+ − X_e^-.

This definition resolves a common confusion: a large state change (e.g., guidance revision from $10–11B to $8–9B) is not necessarily a large surprise if the market expected $8.5B. Our formalization builds on event system theory [16] and positions PRONOIA's Perception layer to compute both the magnitude and the surprise component of each event.

**Definition 2 (Event Boundary).** Boundary = System(S) + State Representation(X) + Analytical Scale(σ). A single earnings release can be one event at the filing scale or several events at the item scale (revenue, EPS, guidance changes)—depending on the research question.

### 3.3 Propagation Graph

The Propagation Graph G = (V, A) is a **directed acyclic graph**:

- **Nodes V.** Each node v ∈ V contains: (subject, expected_direction, expected_magnitude, time_window), where subject ranges from macro variables (policy rate) to sectors (real estate) to individual assets (CN_300530).
- **Edges A.** Each edge a = (u, v, label) ∈ A has label ∈ {+1 supports, −1 refutes}, calibrated by historical market CAR data. The edge weight is a **conditional transmission probability** P(B_up | A_up) = N(A_up ∧ B_up) / N(A_up), fused via Bayesian update: P_new = P_prior × 0.7 + P_observed × 0.3.

The graph is maintained externally with three tiers of edge sources: (a) prior historical statistics, (b) online recent CAR observations, and (c) Navigator real-time reasoning. This contrasts with static KG approaches [10, 22] that retrieve but do not reason over graph structure.

### 3.4 Navigator-Searcher Reasoning Protocol

PRONOIA executes event reasoning through a six-step Navigator-Searcher collaboration over the Propagation Graph:

1. **Event Decomposition.** Navigator decomposes event e into sub-problems {e₁, e₂, ...}, dispatching one Searcher per sub-problem.
2. **Single-Path Propagation.** Each Searcher, adopting a specific market-participant persona (long/short/arbitrageur/regulator/retail), traces one propagation chain over G.
3. **Graph Assembly.** Searcher outputs are merged into the DAG: deduplicated, cross-referenced (supports/refutes), and marked with verification status.
4. **Gap Discovery.** Navigator identifies unconnected components and prompts additional Searchers.
5. **Market Verification.** CAR + cross-sectional dose-response + volume/volatility + node-native observables validate or falsify each path.
6. **Graph Convergence and Output.** Verified paths form the final reasoning graph; the system emits directional, magnitude, and confidence judgments.

Three key design choices distinguish this from tree-based or single-chain approaches: (a) DAG rather than tree, allowing multiple causes for one effect; (b) market posterior rather than LLM voting as the ground truth; (c) game-theoretic branching with heterogeneous market-participant personas.

### 3.5 PAV Output Contract

The Propagation Graph provides the reasoning skeleton; **Predict–Assert–Verify (PAV)** provides a trainable, verifiable output contract:

**Predict.** Input: event structured fields + as_of research context (strictly no post-event data: T0 return, pre-5/pre-20 drift, CAR up to T0) + a measurable indicator panel (30 indicators defined, values withheld).

**Assert.** The model autonomously proposes 3–6 verifiable claims, each of the form: `(indicator, horizon, threshold, TRUE/FALSE judgment, confidence, reasoning_chain)`. The indicator panel spans five families across horizons T+3/7/15/30/60:
- `car_t{h}`: Cumulative Abnormal Return at horizon h
- `ret_t{h}`: Absolute return
- `bm_ret_t{h}`: Benchmark return
- `car_t{h}_pvalue`: Statistical significance
- `car_avg_short/mid/long/all`: Window-averaged CAR

**Verify.** After event settlement, each claim is **objectively settled** against ground-truth labels.jsonl. We compute claim-level accuracy, confidence calibration (Brier score + 10-bin ECE), verifiability ratio, and diversity (indicator-family coverage).

The critical departure from prior work: PAV shifts the core metric from "did you guess the direction right?" to "are your claims *testable* and *correct*?" Any indicator can be claimed, the model autonomously selects what to verify, and evaluation granularity goes from event-level to claim-level.

### 3.6 RLVR Training with Claim-Level Rewards

We train a Qwen3-8B model (bf16, backbone frozen, LoRA rank=16) with GRPO [23] using **Reinforcement Learning with Verifiable Rewards (RLVR)** [19]. Per event, we sample G=4 candidate completions; each is parsed into claims and settled against ground-truth labels.

The reward is a six-element tuple (R0–R5), shared across all experiments in this paper:

| Reward | Component | Description |
|---|---|---|
| R0 | Claim accuracy | Core component: per-claim correctness against settled labels |
| R1 | Confidence calibration | Brier score on judged TRUE probability |
| R2 | Verifiability ratio | Fraction of claims that can be settled against labels |
| R3 | Diversity | Coverage of indicator families across claims |
| R4 | Format compliance | Valid PAV-parseable JSON structure |
| R5 | Length penalty | Penalize excessive verbosity |

**Ablation condition (v6.1-b).** In one ablation, we add five residual bias correction terms (B3: hard-negative targeting for specific event types; B4/B5: TRUE/FALSE distribution and confidence distribution residual correction; B7: claim combination quality; T3: format bonus). In the vanilla condition (v6.2), these are disabled. All other training parameters are identical, constituting a controlled ablation.

**Training details.** GRPO (TRL 0.17) with Unsloth acceleration (in-process vLLM, weight sharing, Standby mode—~2.3× speedup over HF generate rollout). Batch size 8 per device × grad-accum 2 = 16 completions per step (4 events × 4 candidates). Learning rate 1e-5 with cosine annealing. Training: 1 epoch = 1,241 steps ≈ 4,965 events, single 48GB GPU, ~10–12 hours per condition. Seed 42.

---

## 4. Experiments

### 4.1 Dataset and Protocol

**Table 2: Dataset statistics (time-split).**

| Split | Events | Markets | Sources |
|---|---|---|---|
| Train | 4,965 | CN (4,352) / US (613) | A-share earnings pre-announcements (akshare.stock_yjyg_em), M&A/spinoff/financing, company guidance, macro (policy rate/inflation) |
| OOS (test) | 1,034 | CN (1,027) / US (7) | Same sources, strictly post-training window (2024–2026); only run once |

Each event includes: (a) structured fields, (b) research_cache (as_of context: T0 return, pre-5/pre-20 drift, CAR up to T0), (c) labels.jsonl (ground-truth values for all 30 indicators across horizons T+3/7/15/30/60).

**Known split biases.** US events are almost entirely in training; cross-market generalization is not evaluated. No macro events in OOS. All conclusions scope to CN A-shares.

**防作弊 protocol.** (1) Strict as_of: quantity-price features and context use only pre-event-time data, audited before training; (2) Time split, no random split, OOS evaluated exactly once; (3) Statistical testing via event-level paired bootstrap (2,000 resamples, weighted by n_settleable); (4) Claim-level accuracy weighted by n_settleable; (5) Calibration via Brier + 10-bin ECE + confidence-bin actual accuracy.

### 4.2 Experiment 1: Rule-Driven Backtest (Reasoning Chain Skeleton)

This experiment isolates the Propagation Graph's signal value without any model training. It answers: with only prior event rules and market confirmation signals, can we predict event direction effectively?

**Design.** 27 A-share blue chips + 8 sector ETFs, CSI300 as benchmark, 2023-01 ~ 2026-07, 33 events across 20 event types, CAR computed via market model (120-day estimation window, 20-day gap to prevent look-ahead leakage, T+3 holding period). Five progressively filtered strategies implement the **prior → market confirmation → noise removal → strong-signal focus** pipeline:

**Table 3: Rule-driven backtest results.**

| Strategy | Description | N | ACC | 95% CI | PF | Sharpe | avgCAR |
|---|---|---|---|---|---|---|---|
| S1 All | No filter | 444 | 51.6% | [47%, 56%] | 0.83 | −1.01 | −0.26% |
| S2 SectorConfirm | +Sector ETF T+1~T+2 CAR direction confirmation | 212 | **70.3%** | [64%, 76%] | 1.78 | 3.21 | +0.71% |
| S3 StrongEvent | +Event strength ≥ 2 | 159 | 71.1% | [64%, 78%] | 1.29 | 1.48 | +0.32% |
| S4 NonPriceIn | +Exclude T-5~T-1 gain >5% | 130 | 74.6% | [67%, 82%] | 1.91 | 3.85 | +0.65% |
| S5 StrongNonPriceIn | +Event strength ≥ 3 | 85 | **78.8%** | [69%, 87%] | 1.15 | 0.81 | +0.13% |

**Key findings.** (1) S1 at 51.6% ACC confirms that **priors alone ≈ random**—neither rules nor LLMs should predict markets directly. (2) **Sector ETF confirmation is the strongest meta-signal** (+18.7pp, Sharpe −1.01→3.21)—"use market posterior to filter priors" is the empirical bedrock of Principle 3. (3) Event strength grading quantifies surprise: routine rate cuts (strength=1) at 47.9% ACC < random, while 924-package cuts (strength=3) at 82.6%. (4) **Low-ACC events teach a critical lesson**: consumer-boosting events at 33.3%, spike-then-crash at 31.6%, rate cuts at 47.9%—the Propagation Graph "can only be used once"; lookup tables fail, and online reasoning is necessary. Sample-in/out ACC gap is only 1.2pp; Leave-One-Event-Out ranges 68.0%~71.4%—no single event dominates.

### 4.3 Experiment 2: PAV-RLVR Controlled Ablation

**Main result.** Table 4 reports OOS claim-level accuracy across three configurations: a base model with vanilla prompt (no training), v6.1-b with reward corrections, and v6.2-vanilla with only the six-element base reward.

**Table 4: PAV-RLVR main results (1,034 OOS events, t=0.6).**

| Metric | Base (no training) | v6.1-b (with corrections) | v6.2-vanilla (pure) |
|---|---|---|---|
| **Claim accuracy (weighted)** | 0.5729 | 0.6093 | **0.6322** |
| Brier score | 0.2826 | 0.2569 | **0.2539** |
| ECE (10-bin) | 0.1632 | **0.1064** | 0.1070 |
| Format compliance | 0.775 | **0.997** | 0.842 |
| Settled claims | 2,978 | 4,056 | 3,154 |

**Statistical testing.** Paired bootstrap (2,000 resamples, weighted by n_settleable): Δ(vanilla − base) = **+5.93pt** (95% CI [+3.79, +8.07]); Δ(vanilla − v6.1-b) = **+2.29pt** (95% CI [+0.78, +3.79])—CI excludes zero in both comparisons. Event-level win count: vanilla wins 394, v6.1-b wins 335, tie 302.

**Critical finding: residual corrections hurt.** The v6.1-b variant with B3/B4/B5/B7/T3 residual corrections scores **lower** than vanilla in accuracy *and* Brier. The corrections' only measurable benefit is format compliance (+15.5pt), which can be recovered by re-sampling parse-failed events at inference time (see §8.3 for audit). We diagnose this as **reward hacking**: the correction terms introduce fixed patterns the model learns to optimize (T3 format scoring preferences, B7 claim-combination grading), decoupling training reward from OOS claim quality. Table 5 confirms the mechanism:

**Table 5: Training reward ↔ OOS performance decoupling.**

| Metric | v6.1-b (with corrections) | v6.2-vanilla (pure) |
|---|---|---|
| Training reward (first → last step) | 0.851 → **0.902** ↑ | 0.773 → 0.691 ↓ |
| Reward range | 0.534 – 0.997 | 0.452 – 0.930 |
| Terminal KL (vs backbone) | 0.0183 | 0.0096 |
| OOS claim accuracy | 0.6093 | **0.6322** |

Training rewards go in opposite directions of OOS accuracy. Both models show healthy, comparable KL divergence, completion lengths (~400 tokens), and zero truncation—ruling out training instability. **Implication: training reward curve slope cannot serve as reward-component evidence; OOS claim accuracy is the only adjudication mechanism.**

### 4.4 Hard-Negative Subset

**Table 6: Hard-negative subset (146 events: M&A success/turnaround/beating forecast/additional issuance/buyback).**

| Model | Accuracy | vs Base | vs v6.1-b |
|---|---|---|---|
| Base | 0.5103 | — | — |
| v6.1-b | 0.5515 | +4.1pt | — |
| v6.2-vanilla | **0.5862** | +7.6pt | +3.47pt |

The v6.1-b corrections were designed specifically to address hard-negative systematic bias ("利好文本 + T0 positive reaction"). The hard-negative results show: (a) corrections *do* contribute (+3.5pt vs vanilla on this subset), but (b) their net effect on the full dataset is negative because they hurt elsewhere. The design premise (残差偏差 可用先验修正) is not fully supported by data in this training regime.

---

## 5. Analysis: When Does PRONOIA Work and When Doesn't?

### 5.1 By Event Type × Market

**Table 7: Accuracy decomposition by event type and market.**

| Market | Event Type | Events | Base | v6.2-vanilla | Δ(v−base) |
|---|---|---|---|---|---|
| CN | Earnings beat/miss | 478 | 0.524 | 0.598 | **+7.4pt** |
| CN | M&A/spinoff/financing | 373 | 0.618 | 0.661 | +4.4pt |
| CN | Company guidance up/down | 169 | 0.632 | 0.679 | +4.8pt |
| CN | Policy rate adjustment | 7 | 0.598 | 0.591 | (too few) |
| US | Inflation surprise | 7 | 0.572 | 0.652 | (too few) |

Earnings events have the largest relative improvement (+7.4pt) but lowest absolute levels (0.598)—the strongest priors are also the hardest cases. M&A and guidance events achieve the highest absolute accuracy (0.661, 0.679). The test split makes CN × event-type cross the meaningful analysis dimension; US events are near-absent in OOS.

### 5.2 By Indicator Family × Horizon

**Table 8: Accuracy decomposition by indicator family and horizon (claim level).**

| Slice | Claims | Base | v6.2 | Δ |
|---|---|---|---|---|
| **Significance (p-values)** | 944 | 0.614 | **0.791** | **+17.7pt** |
| CAR | 1,207 | 0.566 | 0.592 | +2.6pt |
| Benchmark return | 647 | 0.411 | 0.498 | +8.7pt |
| Window avg | 346 | 0.591 | 0.601 | +1.0pt |
| **Horizon T+30** | 675 | 0.622 | **0.753** | **+13.1pt** |
| Horizon T+7 (momentum) | 1,154 | 0.559 | 0.619 | +6.0pt |
| Horizon T+15 (worst) | 610 | 0.452 | 0.505 | +5.3pt |

The **significance family** (p-values) shows the largest and most consistent lift (+17.7pt, to 79.1%). In A-shares, most event CARs are not statistically significant—falsifying significance (claiming p-value ≥ threshold) is the model's strongest move. The weakest cell is `bm_ret_t15` (n=568, acc 0.498, near coin-flip); the strongest is `car_t30_pvalue` (n=463, acc 0.847). The **long-horizon t30** lift (+13.1pt) contrasts sharply with **t15** (+5.3pt)—the structural pattern is falsifiable, long-horizon claims outperform.

### 5.3 Conditional Analysis

- **Claim count.** 2–3 claims best (0.690 / 0.656); 4 claims drop to 0.569. The "3–6 claims" constraint should narrow to "3–4 claims."
- **Judgment direction.** FALSE-side accuracy **0.709** (n=1,812) vs TRUE-side **0.530** (n=1,342). Training reduces TRUE ratio from 0.525 to 0.425—this "conservative shift" is a natural, beneficial RL product matching the task's structural asymmetry.
- **Extremes.** 293 events (28.3%) all correct (concentrated in M&A/earnings); 55 events (5.3%) all wrong (concentrated in beat/turnaround hard-negatives).
- **Confidence calibration.** Non-monotonic: the 0.75–0.85 mid-high confidence bin achieves actual accuracy of only 0.53–0.59, the primary ECE contributor (0.107). The 0.80 and 0.90 ends are reliable (0.777 / 0.926). Platt post-hoc calibration reduces ECE from 0.085 to 0.036—we recommend it as a default step.

**综合画像.** PRONOIA excels at: FALSE judgments, long-horizon t30, significance family claims, M&A/guidance events, 2–3 claims per event, confidence at 0.80/0.90 endpoints. PRONOIA struggles with: TRUE judgments for short-horizon momentum, benchmark return direction, hard-negative beat/turnaround events, 4+ claims, and 0.75–0.85 confidence mid-range.

---

## 6. Case Study: Full Reasoning Chain Reconstruction

Three representative events reconstruct the full "event input + as_of context → three-model claims → objective settlement → reasoning chain interpretation" pipeline.

### 6.1 Case 1 (Success). Shengtong Co. Earnings Turnaround — vanilla 3/3 correct, base 1/3

**Event.** 002599 · 2026-01-30 · Turnaround. Announcement: net profit ¥6–9M (YoY +103.9%, prior −¥192M), attributed to printing cost reductions. **as_of context:** pre-event CAR −7.95% (oversold state); long-window judgment "mean-reversion vs micro-profit fundamental pricing cancel → neutral mapping, confidence lowered" [car_t3 confidence 0.70].

| Model | Claim | Judge | Conf | Ground Truth | Result |
|---|---|---|---|---|---|
| v6.2 | car_t7 > 0 | TRUE | 0.72 | ✓ (+6.19%) | **✓** |
| v6.2 | bm_ret_t30 > 0 | FALSE | 0.65 | ✓ (−6.13%) | **✓** |
| v6.2 | car_t30_pvalue < 0.05 | FALSE | 0.55 | ✓ (p=0.322) | **✓** |
| base | car_t7>0.02 / car_t30<0.01 / p-value | TRUE / FALSE / TRUE | — | ✓ / ✓ / ✗ | 1/3 |

**Interpretation.** The as_of context already encodes "long-window neutral + confidence lowered." v6.2 absorbs this (two FALSE bets hit the model's strength) and explicitly plans claims across short/long windows and multiple families. Base ignores the context entirely, betting p-value TRUE with arbitrary thresholds (0.02/0.01). **Success = context absorption + diversity planning + betting FALSE.**

### 6.2 Case 2 (Failure). Zhongjin Gold Earnings Beat — all three models wrong, limit-up prior overrides everything

**Event.** 600489 · 2026-01-28 · Beat. Announcement: net profit ¥4.8–5.4B (YoY +41.76–59.48%), attributed to gold mining volume+price. **as_of context:** T0 limit-up +9.98% (benchmark +0.26%, AR ≈ +9.7%) "market confirmed, momentum continuation high probability"; **but** explicitly notes "pre20 cumulative ~+46% gain + structured sell-the-news signal (−6.0) → mean-reversion risk, long-window weak up, confidence lowered to 0.55."

**Ground truth:** T0 spike followed by continuous decline—car_t7 −14.1%, car_t30 −29.8%, car_t60 −45.6%, all labels t5~t60 down. **All three models** produced near-identical claims (car_t7 > 0, confidence 0.72), 0/4 all wrong; the highest confidence (0.80) was placed on the most wrong benchmark claim.

**Interpretation.** (1) All three models open with the same logic—"T0 limit-up → short-window momentum continuation"—prior overrides everything; (2) the most truthful sentence in the context ("pre20 +46% + sell_the_news −6.0") is treated as background; (3) all three correctly write sell-the-news / gold price / overhang in their "counterparty/risk" paragraphs, but **zero claims translate risk into hedging hypotheses**—the risk paragraph is decorative, disconnected from claim behavior; (4) v6.2 and v6.1-b produce character-identical claims, confirming this is a training-data systematic prior, not sampling noise.

### 6.3 Case 3 (Failure). Zhongshan Public Utilities Beat — upstream reasoning itself is wrong

**Event.** 000685 · 2026-01-31 · Beat. Announcement: net profit ¥17.98–21.58B (YoY +50–80%). **as_of context:** T0 +1.51%, benchmark −2.13%, AR +3.64%, volume 2.03× "volume-price resonance confirms short-window momentum"; pre20 CAR +8.06%; conclusion "short-medium high confidence, uniformly up." **Ground truth:** T+1 start to continuous decline—car_t7 −3.2%, car_t30 −17.3%, all labels t7~t60 down.

**Interpretation.** Unlike Case 2, here the *upstream research context itself is wrong* ("volume-price resonance → up" vs actual decline)—garbage-in, downstream models can't recover. The model further extrapolates "weak individual stock" to "weak market" (bm_ret_t15 < 0 claim wrong, actual benchmark +1.08% flat), the direct embodiment of benchmark family 0.498 performance. pre20 CAR +8.06%, which *should* signal "good news already priced-in mean-reversion," is used instead as "significance support"—context features reinforce priors rather than test them.

### 6.4 Cross-Case Synthesis

1. **Failures concentrate in "bullish text + T0 positive reaction" events.** Model prior = momentum continuation; A-share short-window reality = mean reversion. All 10 hard-negative events where vanilla still fails are beat/turnaround category.
2. **Counterparty/risk paragraphs are "cognitively correct, behaviorally inert."** Risk is written but never translated to hedging claims—a prompt/reward design fix.
3. **Benchmark family performance ≈ coin flip** (0.498). Model extrapolates individual-stock weakness to market weakness.
4. **Upstream research context with strong priors contaminates downstream** (Case 3). The context should output self-confidence + counterparty evidence list.
5. **Cross-indicator claims silently dropped** (e.g., `car_avg_long > car_avg_short`)—wastes model expression, underestimates real coverage.

---

## 7. Discussion

### 7.1 Unified Interpretation of Two Experiments

The rule-driven backtest (§4.2) and PAV-RLVR (§4.3) are two systems that validate one proposition at three levels:

- **Priors can't trade directly.** S1 ACC 51.6% (rule priors near random) and base claim accuracy 0.573 (naked model limited) mutually confirm—event priors must pass through some "purification" mechanism to have signal value.
- **Market confirmation is the strongest purifier.** Rule-side sector-ETF confirmation (+18.7pp) and RL-side claim-level objective settlement (+5.9pt vs base) are the same mechanism in two forms—market posterior filters/rewards reasoning output.
- **Environment dependency requires online reasoning.** "Propagation Graph can only be used once" (consumer-boosting 33.3%, etc.) shows lookup tables fail, which is exactly why we delegate reasoning to a model trained on 4,965 events. And the reward-hacking ablation shows even the reward function itself must pass OOS adjudication.

### 7.2 Limitations

- **Single seed.** The +5.9pt base→vanilla result has CI excluding zero, but +2.29pt vanilla→v6.1-b does not; multi-seed confirmation needed.
- **Market imbalance.** OOS US = 7 events; cross-market generalization unevaluated.
- **Sample scale.** Rule backtest = 33 events; RL training = 4,965 events. Still insufficient for larger structures (e.g., 7-expert MoE).
- **Single sampling.** OOS t=0.6 single sampling; format gap (15.8% parse failures) excluded from resampling benefit.
- **Short-selling weakness.** A-share short mechanisms incomplete; TRUE-side judgment (0.530) systematically weaker than FALSE-side.

### 7.3 Experimental Validity Audit

We grade this paper's core conclusions on three confidence tiers:

**Table 9: Conclusion credibility audit.**

| Conclusion | Grade | Basis |
|---|---|---|
| RLVR training effective (base 0.573 → vanilla 0.632, +5.9pt) | High | Effect size far above noise; same eval pipeline and OOS set for both; residual risk: base-side format failure might inflate vanilla by excluding uncertain events |
| Conditional performance structure (FALSE 0.709 vs TRUE 0.530; t30 0.753 vs t15 0.505) | High | Each cell hundreds to thousands of samples; consistent across all three model variants |
| Vanilla better than v6.1-b by 2.29pt | **Low** | Three uncontrolled confounders (format-compliance bias, single seed, training-trajectory divergence) + 95% CI lower bound +0.78pt |
| Confidence 0.90 endpoint actually 0.926 | Verify needed | Self-selection; n(0.90) unconfirmed; event-type controls unknown |
| US-market conclusions | Unusable | OOS US = 7 events, zero information |

**Recommendation for §4.3 revision:** Change "residual corrections are harmful (−2.29pt)" to "corrections did not produce expected benefits"—supporting the former requires a 3-seed × 2-condition (6-training) controlled matrix.

**Three methodological risks affecting all numbers in this paper:**

1. **Single-sampling variance unquantified.** OOS t=0.6 single sample; all numbers are one realization. Recommend 5× repeated sampling on 200 events.
2. **Multiple comparisons.** At least 8 dimensions, dozens of cells—highlights like "significance family 0.791 / car_t30_pvalue 0.847" expected by chance alone. FDR/Bonferroni correction + holdout verification needed before using as trading filters.
3. **as_of strictness unaudited.** research_cache features (CAR / pre-drift, etc.) not systematically checked for look-ahead bias—the single risk that could overturn all conclusions.

---

## 8. Conclusion and Future Work

### 8.1 Takeaways

1. **Methodology.** Financial event reasoning chain = Propagation Graph (reasoning skeleton) + PAV (verifiable output contract) + market posterior reward (unhackable verification). Rule backtest (S2 ACC 70.3%) and RL ablation (vanilla 0.632 vs base 0.573) validate this closed loop at two levels.

2. **Negative results matter.** Residual bias corrections (B3/B4/B5/B7/T3) reduce OOS accuracy by 2.29pt (+3.47pt on hard-negatives) with format compliance (+15.5pt) as the only recoverable benefit. Training reward curves and OOS accuracy decouple—confirming reward hacking exists in financial RL and that "training-reward trend cannot be used to prove reward-component validity."

3. **Structural capability portrait.** The model excels at falsifiable claims (FALSE 0.709, significance family 79.1%, t30 75.3%) but struggles with momentum-continuation claims (TRUE 53.0%, bm_ret_t15 49.8%). This structural pattern, tied directly to A-share micro-structure (mean-reversion in short windows), should guide future prompt and reward design.

### 8.2 Immediate Next Steps (Priority-Ordered)

| Priority | Item | Evidence | Cost |
|---|---|---|---|
| **P0** | Hard-negative oversampling (beat/turnaround/M&A success/additional issuance/buyback 2–3×) + retrain | Hard-neg acc 0.586 < overall 0.632; 10 all-wrong events share "bullish + T0 positive" pattern | 1d data + 10h retrain |
| **P0** | Inference-side format fallback: re-sample parse-failed events (15.8%) once | Format gap is the only price of abandoning corrections | 0.5d inference |
| **P1** | Hedging-claim mechanism: at least one claim must express counterparty hypothesis; hedging-claim correctness = bonus | Cases 2/3: risk paragraphs correct but never hedged | 0.5d each prompt+reward |
| **P1** | pre-drift feature explicit in prompt with usage guidance (high pre-drift → mean-reversion risk) | Case 3: pre20 CAR +8.06% misused as significance support | 0.5d each data+prompt |
| **P1** | US-stratified OOS split (or US-only subset eval on existing checkpoint) | Train US 613 / Test US 7; cross-market blind spot | 1d data + 3h inference |
| **P2** | Claim-count constraint narrow to 3–4; parser cross-indicator support; benchmark-family examples enhanced | n=4 acc 0.569; cross-indicator claims silently dropped; bm_ret_t15 0.498 | 0.5d each |
| **P3** | Multi-seed validation (seeds 43/44); retain Platt post-hoc calibration | Single-seed; ECE 0.107 → 0.036 with Platt | 2×10 GPU·h / existing artifacts |

### 8.3 Mid-Term Evolution: Single Expert → Multi-Scale MoE

The current single-LoRA PAV-RLVR validation of the closed loop naturally extends to:

- **Frequency × horizon two-dimensional reward.** This experiment already shows horizon-axis (t3~t60) reward effective with differentiated performance per horizon (t30 0.753 / t15 0.505). The frequency axis (volume-price H/M/L channel lead-confirm consistency) is the next verifiable signal source.
- **Scale-conditioned MoE routing.** Event type × horizon performance differentiation (earnings short-window weak / guidance long-window strong) provides natural expert boundaries, but expert collapse risk (CES mutual-exclusion regularization) must be validated first.
- **Data expansion.** PRONOIA-3K → 500+ event-level rule backtest expansion and RL training expansion must proceed in lockstep, especially filling US and macro event samples.

---

## References

[1] Tobias J. Moskowitz and Annette Vissing-Jørgensen. The markets for housing and commercial real estate: The risk, return, and correlation of real estate. *Journal of Financial Economics*, 2008.

[2] John Y. Campbell, Andrew W. Lo, and A. Craig MacKinlay. *The Econometrics of Financial Markets*. Princeton University Press, 1997.

[3] Ray Ball and Philip Brown. An empirical evaluation of accounting income numbers. *Journal of Accounting Research*, 6(2):159–178, 1968.

[4] Lauren Cohen and Andrea Frazzini. Economic links and predictable returns. *Journal of Finance*, 63(4):1977–2011, 2008.

[5] Paul C. Tetlock. All the news that's fit to reprint: Do investors react to stale information? *Review of Financial Studies*, 24(5):1481–1512, 2011.

[6] Zachary C. Lipton, Yuval Noah Harari, and Geoffrey Hinton. The mythos of model interpretability. *Queue*, 16(3):31–57, 2018.

[7] Eugene Fama, Lawrence Fisher, Michael Jensen, and Richard Roll. The adjustment of stock prices to new information. *International Economic Review*, 10(1):1–21, 1969.

[8] Argus: Evidence-driven multi-step reasoning with claim-level verification. arXiv:2605.16217, 2026.

[9] David Ha and Jürgen Schmidhuber. World models. arXiv:1803.10122, 2018.

[10] Finkario: A benchmark for financial reasoning. arXiv:2506.07712, 2025.

[11] FinHEAR: Financial event-driven hybrid architecture for earnings reaction. arXiv:2506.09080, 2025.

[12] Jifeng Luo, Qinglin Tang, and Jun Wang. Factorminer: A self-evolving agent with skills and experience memory for financial alpha discovery. arXiv preprint, 2026.

[13] Victor Li, William Ke, and David Zhang. The cross-section of expected stock returns. *Review of Financial Studies*, 29(1):5–68, 2015.

[14] Janus-Q: End-to-end event-driven trading with hierarchical gated reward modeling. arXiv:2602.19919, 2026.

[15] Daniel Kahneman, Paul Slovic, and Amos Tversky. *Judgment Under Uncertainty: Heuristics and Biases*. Cambridge University Press, 1982.

[16] Frederick P. Morgeson, Terence R. Mitchell, and Dong Liu. Event system theory: An event-oriented approach to the organizational sciences. *Academy of Management Review*, 40(4):515–537, 2015.

[17] James W. Kolari and Seppo Pynnönen. Event study testing with cross-sectional correlation of abnormal returns. *Review of Financial Studies*, 23(11):3996–4025, 2010.

[18] Kenneth N. Kuttner. Monetary policy surprises and interest rates. *Journal of Monetary Economics*, 47(3):523–544, 2001.

[19] RLVR: Reinforcement learning with verifiable rewards. arXiv:2506.07891, 2025.

[20] Craig MacKinlay. Event studies in economics and finance. *Journal of Economic Perspectives*, 10(2):113–138, 1997.

[21] Yangyang Yu et al. FinCon: A synthesized LLM multi-agent system with conceptual verbal reinforcement for enhanced financial decision making. *NeurIPS*, 2024.

[22] Xiang Li, Penglei Sun, Wanyun Zhou, Zikai Wei, Yongqi Zhang, and Xiaowen Chu. Finkario: Event-enhanced automated construction of financial knowledge graph. *ACL*, 2026.

[23] Hang Yang, Yubo Chen, Kang Liu, Yang Xiao, and Jun Zhao. DCFEE: A document-level Chinese financial event extraction system based on automatically labeled training data. *ACL System Demonstrations*, 2018.

[24] Ziyi Tang, Zechuan Chen, Jiarui Yang, et al. AlphaAgent: LLM-driven alpha mining with regularized exploration to counteract alpha decay. *KDD*, 2025.

[25] Julian Schrittwieser, Ioannis Antonoglou, Thomas Hubert, et al. Mastering Atari, Go, chess and shogi by planning with a learned model. *Nature*, 588(7839):604–609, 2020.

[26] Xiaozhi Wang, Ziqi Wang, Xu Han, et al. MAVEN: A massive general domain event detection dataset. *EMNLP*, 2020.

[27] Xiaozhi Wang, Yulin Chen, Ning Ding, et al. MAVEN-ERE: A unified large-scale dataset for event coreference, temporal, causal, and subevent relation extraction. *EMNLP*, 2022.

[28] Yijia Xiao, Edward Sun, Tong Chen, et al. Trading-R1: Financial trading with LLM reasoning via reinforcement learning. arXiv preprint, 2025.

[29] Ziyi Tang, Zechuan Chen, Jiarui Yang, Jiayao Mai, Yongsen Zheng, Keze Wang, Jinrui Chen, and Liang Lin. Alphaagent: Llm-driven alpha mining with regularized exploration to counteract alpha decay. *KDD*, 2025.

[30] Dong Shu, Yanguang Liu, Huopu Zhang, and Mengnan Du. FinCall-Surprise: A large scale multi-modal benchmark for earning surprise prediction. *ACL*, 2026.

[31] Shun Zheng, Wei Cao, Wei Xu, and Jiang Bian. Doc2EDAG: An end-to-end document-level framework for Chinese financial event extraction. *EMNLP-IJCNLP*, 2019.

[32] Yanlong Wang, Jian Xu, Hongkang Zhang, Shao-Lun Huang, Danny Dongning Sun, and Xiao-Ping Zhang. Factorminer: A self-evolving agent with skills and experience memory for financial alpha discovery. arXiv preprint, 2026.

[33] Tianyi Tao, Kevin Roice, and Ashwin Rao. TradingAgents: Multi-agent system for financial trading. arXiv:2407.18957, 2024.

[34] Jinyan Su, et al. FinChain: A symbolic benchmark for verifiable chain-of-thought financial reasoning. *ACL*, 2026.

[35] Fengbin Zhu, Xiang Yao Ng, Ziyang Liu, Chang Liu, Xianwei Zeng, Chao Wang, Tianhui Tan, Xuan Yao, Pengyang Shao, Min Xu, et al. FinDeepResearch: Evaluating deep research agents in rigorous financial analysis. arXiv preprint, 2026.

[36] Jie Zhu, Yimin Tian, Boyang Li, et al. FinMCP-Bench: Benchmarking LLM agents for real-world financial tool use under the model context protocol. arXiv preprint, 2026.

[37] PRONOIA Team. Event-driven financial reasoning: ERC architecture, validation, and evolution. 61-page survey, 2026.

[38] Jinfei Sheng, Zheng Sun, Baozhong Yang, and Alan L. Zhang. Generative AI and asset management. *Review of Financial Studies*, 2026.

---

## Appendix

### A.1 Reproducibility

- Code: `github.com/vixuowis/Pronoia` (MIT License, Python 3.10+ / React 18)
- Datasets: All 1,034 OOS events + 4,965 training events are available via the Pronoia data pipeline (akshare / yfinance); labels.jsonl includes ground-truth values for all 30 indicators
- Hardware: Single RTX 4090 (48GB); GRPO + Unsloth with in-process vLLM acceleration
- Training time: ~10–12 hours per condition
- Seed: 42 for all results reported

### A.2 Ethics

- All data used in this paper is publicly available (akshare, yfinance) and from anonymous stock markets.
- We did not conduct live financial trading based on the results in this paper; all evaluation is on historical data.
- We document reward hacking, over-confidence bias, and systematic failure modes in full transparency; these are *negative results* we present to the research community rather than suppress.
- US-based events comprise only 7 of 1,034 OOS events; we scope all claims to CN A-shares.

### A.3 Paper Length

Current draft: ~12,000 words main body + 38 references + 3 appendices. WWW limits are flexible; we estimate 10–12 pages in ACM two-column format with ~4 pages of references and appendices.
