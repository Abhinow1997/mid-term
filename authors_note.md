# Author's Note — Chapter 14: What Gets Measured Gets Managed

**FinOps, Observability, and the Dollar-per-Decision Metric**
Abhinav Gangurde | Northeastern University | Prompt Engineering — Spring 2026

---

## Page 1 — Design Choices

### Why This Chapter

I chose Chapter 14 because its failure mode is one I could articulate before looking anything up: when an agentic system is monitored at the wrong granularity, costs compound invisibly until someone in finance kills the project — not because the agent failed technically, but because no one could justify the economics. The failure is architectural, not algorithmic. The model works fine. The measurement infrastructure around it is what's missing.

This is a Type E chapter — Operational/Production Practice — which means the core deliverable is not a pattern or a framework comparison but an operational loop: what you measure, how you measure it, and what decisions those measurements drive. The chapter teaches a practice that, if absent, produces a specific and predictable failure at scale.

### The Architectural Argument

The book's master argument is: **architecture is the leverage point, not the model.** Chapter 14 is a specific instance of that claim applied to cost. The central argument is that the unit of cost measurement determines whether an agentic system is economically viable. Cost-per-inference — the default metric most teams reach for — hides the compounding that occurs across multi-step agent trajectories. A single "decision" in an agentic system might require 15–40 LLM calls, tool invocations, retries, and coordination overhead. Cost-per-inference averages across all of these and produces a number that looks cheap. Dollar-per-decision aggregates them correctly and reveals the real economics.

The mechanism connecting design choice to system behavior is: wrong metric → wrong optimization → invisible cost compounding → project cancellation. This causal chain is what separates an architectural argument from a technology description.

### The Approach

I structured the chapter around a concrete scenario — a legal tech company that lost $147,000 overnight due to a retry loop with no span-level cost monitoring — and built every concept outward from that incident. The $147K story motivates the DpD metric, which motivates span-level instrumentation, which motivates the `decision_bearing` flag, which motivates budget envelopes and circuit breakers, which motivates tiered model routing. Each concept earns its place by solving a problem the reader has already seen.

The Tetrahedron elements for a Type E chapter map as follows. **Structure** is the operational loop itself: span-level cost annotation, the decision-bearing flag, budget envelopes, cost-velocity circuit breakers, and tiered model routing. **Logic** is why dollar-per-decision is correct and cost-per-inference is not — because a single decision spans multiple calls and cost-per-inference hides the compounding. **Implementation** is the code: the span schema, the `before_llm_call` budget check, the cost-velocity ratio formula, and the routing optimization. **Outcome** is what happens without this practice at scale — the $147K failure, and more subtly, the invisible DpD explosion when routing is removed.

### What I Left Out

I deliberately excluded two topics. First, I did not cover organizational change management — the political difficulty of getting engineering and finance teams to agree on DpD as the shared metric. This is a real obstacle in practice, but it's a management problem, not an architectural one, and the chapter's job is to make the architectural argument. Second, I did not attempt to define universal quality thresholds ($Q_{\min}$) for the model routing optimization. The chapter surfaces this as an open question — who sets the quality floor, the engineer or the domain expert — because I believe it is genuinely unresolved and presenting a false answer would be worse than presenting the tension honestly.

---

## Page 2 — Tool Usage

### Bookie

Bookie generated the initial prose structure following the Scenario → Mechanism → Design Decision → Failure Case → Exercise sequence. The bulk of the chapter's explanatory sections — token economics, distributed tracing, the DpD formula, cache economics — were drafted with Bookie and then revised for precision and tone.

**Correction 1 — The cost-velocity circuit breaker threshold.** Bookie proposed a fixed 2.0× threshold for the cost-velocity circuit breaker across all task types. I rejected this because a fixed threshold assumes all tasks have similar cost variance, and they do not. A clause classification has tight variance (±15%), so a 2.0× threshold catches anomalies appropriately. But a multi-document synthesis has wide variance (±30–40%) — a 2.0× threshold on that task triggers false alarms on legitimately complex documents. The AI proposed a fixed number because a single constant is simpler to explain. The architecturally correct answer is adaptive thresholds calibrated per task type from observed variance during a calibration phase (mean + N × standard deviation). I revised the chapter to present the fixed threshold as the initial implementation and then introduced the adaptive alternative in the Human Decision Node section of the demo, where the variance data makes the argument concrete.

**Correction 2 — Decision-bearing classification via LLM self-classification.** Bookie proposed that the `decision_bearing` flag should be assigned by the LLM itself via a self-classification prompt appended after each call. I rejected this because it introduces a recursive cost problem — you're spending tokens to classify whether the tokens you just spent were worth classifying. This directly violates the chapter's own core principle of minimizing non-decision-bearing LLM usage. The correct approach is a two-phase design: design-time tagging for obvious cases (the architect already knows that `classify_clause` is a decision and `format_output` is not), combined with Human-in-the-Loop calibration for ambiguous cases. During the first N documents of a production deployment, ambiguous spans are flagged for human review. The human classifies them once, and those labels become ground truth for production. This is a one-time human cost, not a per-call LLM cost that compounds forever. I replaced Bookie's LLM self-classification proposal with this HITL calibration approach in both the chapter prose and the demo notebook.

### Eddy the Editor

Eddy flagged two issues in my draft. First, the opening scenario initially described the $147K incident without enough specificity — "the agent looped" without tracing the exact mechanism (retry logic appending full conversation history, causing quadratic context growth). I revised to include the specific causal chain: malformed document → classification error → retry with full history → context bloat → per-call cost growing from $0.0025 to $0.12 → cost-velocity ratio of 48×. Second, Eddy identified that the "Where the simple model breaks" section was listing limitations without mechanistically explaining why they break the model. I revised each limitation (quality drift, hidden costs, context window growth) to include the causal chain from the design gap to the operational failure.

### Courses

Courses generated five Bloom's Taxonomy-compliant learning outcomes from my core claim sentence. These drove the chapter structure: Analyze (why CPI is wrong), Evaluate (compute DpD across a full trajectory), Design (build the observability pipeline), and Diagnose (trace the causal chain from wrong metric to project failure). The `showtell` output provided the Explain → Show → Try lesson sequence that structured the video storyboard.

### Figure Architect

Figure Architect scanned the stable draft and flagged four high-assertion zones requiring figures: the agent execution graph (tree diagram with cost annotations per span), the DpD vs. CPI comparison (dual-axis chart showing the gap), the cost-velocity spike timeline (scatter plot showing the malformed document retries), and the model routing tier diagram. I prioritized the execution graph and the comparison chart as critical-priority figures for the chapter.

### Eddy the Storyboarder

Eddy the Storyboarder produced an 8-minute scene-by-scene storyboard. I modified the Show segment to ensure both Human Decision Nodes appear on camera with explicit rejection statements, and adjusted the Try segment to focus specifically on the "remove tiered routing" exercise rather than a more abstract discussion.

---

## Page 3 — Self-Assessment

### Rubric Self-Scoring

**Architectural Rigor (35 pts) — Self-score: 30/35.** The chapter correctly identifies the architectural pattern (span-level cost observability with DpD as the unit metric), traces the mechanism from design choice to system behavior (wrong metric → hidden compounding → project cancellation), and demonstrates the failure case in the notebook. The causal chain is complete and mechanistically specific. I deduct 5 points because the fully-loaded decision cost concept — incorporating human review costs and downstream rework into the DpD calculation — is described in the chapter but not implemented in the demo. In a production system, this would be the more important metric; I presented it conceptually but did not build the instrumentation for it.

**Technical Implementation (25 pts) — Self-score: 21/25.** The demo handles realistic defects: the malformed document triggers retry amplification with context bloat, the budget envelope catches runaway spend, the circuit breaker detects cost-velocity anomalies, and tiered routing reduces DpD without degrading decision quality. Both Human Decision Nodes are implemented as explicit code sections with documented AI proposals, rejections, and corrections. The failure mode is triggerable — the reader can toggle `use_tiered_routing` off in the Streamlit app and watch DpD explode while the circuit breaker stays silent. I deduct 4 points because the simulation uses synthetic cost data rather than real API calls. This was a deliberate tradeoff — requiring API keys would make the demo less reproducible — but it means the token counts and cost distributions are approximations rather than empirical measurements. A stronger implementation would include a calibration mode that runs against a real API for the first N documents and then uses the observed distributions for the simulation.

**Pedagogical Clarity (20 pts) — Self-score: 17/20.** The chapter follows the Feynman Standard: every concept is motivated by the scenario before being named, jargon is introduced only after the intuition is established, and the failure mode is concrete rather than hypothetical. The execution graph, span schema, and cost formulas are presented incrementally so the reader builds understanding layer by layer. I deduct 3 points because the "Cache economics" section is more technical than the rest of the chapter and could benefit from a more grounded example — I explain the math of caching but don't tie it back to the legal tech scenario as tightly as the other sections.

**Total self-score: 68/80 for Core Competency.**

### Relative Quality Assessment

The two Human Decision Nodes represent genuine architectural corrections, not cosmetic edits. The fixed-to-adaptive threshold correction changes the system's behavior under production conditions — a fixed threshold produces false positives on high-variance tasks and false negatives on low-variance tasks, while the adaptive threshold calibrates to actual observed variance. The LLM self-classification to HITL calibration correction eliminates a recurring cost that violates the chapter's own principle. Both corrections are visible in the demo code, documented with the AI's original proposal and the architectural reasoning for rejection, and demonstrated on camera in the video.

### What Would Make It Stronger

The failure mode in my chapter is mechanistically correct — removing tiered routing causes DpD to increase dramatically while CPI stays flat and the circuit breaker never fires. This is reliably triggerable in the demo. What I could not demonstrate reliably is the *secondary* failure mode: quality drift under cost pressure. The chapter describes how a DpD metric without a quality floor leads to quality degradation, but the demo does not simulate decision quality — only decision cost. A stronger implementation would include a quality scorer that evaluates the agent's classification accuracy at each model tier, allowing the reader to observe that routing everything to the lightweight model reduces DpD further but produces incorrect classifications. This would make the $Q_{\min}$ constraint tangible rather than theoretical. The infrastructure for this exists in the simulation (the `recommended_tier` field per task), but I did not build the quality evaluation layer within the project timeline. This is the most important gap, and closing it would make the chapter's argument about cost-quality tension demonstrable rather than merely asserted.
