# Chapter 14: What Gets Measured Gets Managed — FinOps, Observability, and the Dollar-per-Decision Metric

---

## Opening Hook

On a Thursday evening in late 2023, a mid-sized legal technology company deployed a document-review agent to their staging environment. The agent's job was straightforward: ingest a corpus of contracts, classify each clause against a predefined ontology, flag anomalies, and produce a structured summary. The engineering team estimated the job would cost roughly $800 in API fees — call it a thousand documents at seventy cents each, rough math. They set no budget cap. They went home for the night.

By Friday morning, the agent had spent $147,000.

It had not gone rogue in any dramatic sense. It had not hallucinated wildly or sent emails to clients. It had done something far more mundane and far more instructive: it had looped. A retry logic error caused the agent to resubmit failed classification calls. A context management flaw caused each retry to include the entire prior conversation history, compounding the token count with each attempt. The agent was, in a technical sense, working hard. It was generating tens of thousands of API calls, faithfully logging each one, producing output that looked plausible. It was just doing all of this against a document corpus it had already processed, at a cost per call that grew quadratically as the context window bloated.

The postmortem identified three proximate causes: no budget ceiling, no per-call token accounting, and no anomaly detection on cost velocity. The underlying cause was simpler than any of those. Nobody had asked the question that should precede every production deployment of an agentic system: *for each decision this agent makes, what am I paying, and is that price proportional to the value the decision creates?*

---

## The Question

How do you make cost a first-class property of an agentic system — not an afterthought audited from a billing dashboard, but a measured, observable quantity that shapes architecture, routing, and runtime behavior the same way latency and accuracy do?

---

## Narrative Bridge

The field of FinOps — Financial Operations for cloud infrastructure — spent the better part of a decade learning a lesson that agentic AI is now relearning at speed: *the unit of cost that matters is not the invoice line item; it is the cost per outcome*. A company running 10,000 EC2 instances does not care primarily about total compute spend. It cares about cost per API call served, cost per transaction processed, cost per active user retained. The aggregate bill is a symptom. The unit economics are the diagnosis.

For traditional cloud workloads, establishing unit economics is annoying but tractable. You tag resources, you allocate costs to services, you divide by throughput metrics. The denominator — requests served, users active, transactions committed — is straightforward to count.

Agentic systems make the denominator ambiguous. What is the unit of work an agent produces? A user message answered? A task completed? A tool call made? A decision rendered? These are not equivalent. An agent answering a trivial clarifying question by invoking a 128,000-token context window and four tool calls has produced something far less valuable than an agent that routes a complex multi-step task to a lightweight model, executes it in three focused calls, and returns a structured result. If you count both as "one response," your unit economics are lies.

This is not a billing problem. It is a measurement problem, and measurement problems in engineering always precede control problems. You cannot build a circuit breaker for runaway cost if you do not know what normal cost looks like, at the level of individual decisions, in real time.

The concept this chapter builds toward — the dollar-per-decision metric — is the agentic analog of cost-per-request in traditional FinOps. Getting there requires three capabilities working in concert: an accounting layer that attributes costs at the span level, an observability stack that makes those attributed costs visible across the agent's execution graph, and a set of architectural patterns — budget guardrails, model routing, cache economics — that let you act on what you see before the invoice arrives.

---

## Core Claim

The dollar-per-decision (DpD) metric — defined as total API expenditure divided by the count of agent-originated actions requiring genuine probabilistic reasoning — is the correct unit of economic accountability for agentic systems, and systems instrumented to minimize DpD while holding decision quality constant will outperform, in both cost and reliability, systems instrumented only at the aggregate billing level.

---

## Mechanism

### Token Economics: The Atomic Unit

Every API call to a large language model generates two costs: an input cost and an output cost. As of this writing, frontier models price these asymmetrically — input tokens typically cost between one-third and one-half the price of output tokens on a per-token basis. For GPT-4-class models, representative pricing runs approximately $2.50 per million input tokens and $10.00 per million output tokens; for Claude Sonnet-class models, comparable figures are $3.00 and $15.00 respectively. These numbers move as the market evolves, but the ratio — output costs three to four times more per token than input — is structurally durable because generating tokens is computationally more expensive than attending to them.

This asymmetry matters immediately for agentic design. An agent that produces verbose chain-of-thought reasoning in its output, then feeds that reasoning as context into subsequent calls, is paying the output premium once (for generation) and then paying a discounted input premium every time that text appears in a future context window. The economics of reasoning verbosity are not free. A 2,000-token internal monologue that persists across ten subsequent calls costs roughly:

$$C_{\text{reasoning}} = 2000 \times P_{\text{out}} + 10 \times 2000 \times P_{\text{in}}$$

At the rates above, this comes to approximately $0.02 + $0.06 = $0.08 for that single reasoning trace. Across a million agent invocations, the same reasoning trace costs $80,000 — before accounting for any actual task work.

The precise accounting equation for a single LLM call within an agent span is:

$$C_{\text{call}} = n_{\text{in}} \cdot P_{\text{in}} + n_{\text{out}} \cdot P_{\text{out}} - n_{\text{cached}} \cdot P_{\text{cache\_discount}}$$

where $n_{\text{in}}$ is the total input token count, $n_{\text{out}}$ is the generated output token count, $n_{\text{cached}}$ is the subset of input tokens that hit a prompt cache, and $P_{\text{cache\_discount}}$ is the per-token savings from caching (typically 80–90% of the base input price for providers offering prompt caching).

The total cost of an agent task is then the sum of all call costs across all spans in the execution graph, plus any non-LLM costs — tool execution, vector database queries, retrieval pipeline calls — that carry their own pricing.

### Distributed Tracing and the Execution Graph

A single agent task rarely executes as a single LLM call. It executes as a *graph*: an initial planning call, branching tool calls, possibly recursive sub-agent invocations, aggregation calls, and a final synthesis. The execution graph of a moderately complex document-review agent might look like this:

```
root_task
├── plan_subtasks [LLM, 1,200 tokens in, 340 out]
├── retrieve_relevant_sections [vector_db, $0.002]
├── classify_clause_type [LLM, 890 tokens in, 45 out]
│   ├── clarify_ambiguous_term [LLM, 1,100 tokens in, 80 out]
│   └── lookup_precedent [retrieval, $0.001]
├── flag_anomaly [LLM, 950 tokens in, 120 out]
└── synthesize_summary [LLM, 3,400 tokens in, 560 out]
```

To make cost observable at this level of granularity, every span must carry a cost annotation. This is not a post-hoc calculation from the billing dashboard — it is an instrumentation requirement. Each LLM call must emit a structured trace event containing at minimum: span ID, parent span ID, model name, input token count, output token count, cached token count, computed cost, and wall-clock latency.

The trace collection pattern that has emerged as standard practice in production agentic systems borrows from OpenTelemetry, the distributed tracing standard developed for microservices. The agent runtime instruments each LLM call the same way a web framework instruments each HTTP request: with a context-propagating span that records attributes at entry and exit. A simplified representation of the required span schema is:

```json
{
  "span_id": "a3f2c1",
  "parent_span_id": "root_00",
  "operation": "classify_clause_type",
  "model": "claude-sonnet-4",
  "input_tokens": 890,
  "output_tokens": 45,
  "cached_tokens": 712,
  "cost_usd": 0.00191,
  "latency_ms": 843,
  "decision_bearing": true
}
```

The `decision_bearing` flag is not standard in most observability frameworks. It is introduced here deliberately, because it is the hinge on which the dollar-per-decision metric turns.

### Defining "Decision"

Not every LLM call in an agent's execution graph represents a *decision* in the economically meaningful sense. Consider the following call taxonomy:

A *decision-bearing call* is one whose output changes the agent's subsequent behavior. A classification that routes a document to one processing path versus another is decision-bearing. A planning call that decomposes a task into subtasks is decision-bearing. A call that generates final output delivered to a user is decision-bearing.

A *non-decision call* is one that could, in principle, be replaced by a deterministic function without loss of semantic quality. A call that extracts a structured JSON schema from a text that is already well-structured is often non-decision. A call that reformats output from one syntactic form to another is typically non-decision. A call that summarizes a passage the agent has already processed in full is borderline.

The distinction is not always clean, but it is always worth attempting, because conflating decision calls with non-decision calls inflates your denominator and understates your true cost per meaningful action. A system that routes 80% of its API budget through formatting and reformatting calls while making only 20% decision-bearing calls has a real DpD approximately five times higher than naively calculated.

The formal definition:

$$\text{DpD} = \frac{\sum_{i \in \mathcal{D}} C_i + \sum_{j \in \mathcal{S}} C_j}{|\mathcal{D}|}$$

where $\mathcal{D}$ is the set of decision-bearing spans, $\mathcal{S}$ is the set of supporting (non-decision) spans, $C_i$ and $C_j$ are the respective span costs, and the denominator counts only decision-bearing spans. The numerator includes all costs because supporting calls are real expenditures in service of decisions; the denominator counts only the decisions those costs are meant to produce.

For the legal technology agent described in the opening, a single document classification — *this clause is a limitation-of-liability provision* — is one decision. The full execution graph to reach that decision, including retrieval, formatting, and clarifying sub-calls, might cost $0.08. The DpD for that task type is therefore $0.08.

Whether $0.08 per clause classification is acceptable depends entirely on what that classification is worth. In a legal workflow where a misclassified clause could introduce contractual liability, $0.08 might be spectacularly cheap. In a commodity document indexing pipeline where the same task can be accomplished by a fine-tuned 7-billion-parameter open-weights model at $0.001 per call, it represents an 80× overspend. The metric does not tell you the answer. It tells you the question.

### Budget Guardrails and Circuit Breakers

Knowing your DpD in production requires more than instrumentation after the fact. It requires *runtime cost accounting* — the agent knows, at each step, how much it has spent on the current task, and that knowledge influences its execution strategy.

The minimal implementation is a budget envelope: a hard ceiling on per-task spend, enforced by the agent orchestration layer before each LLM call. The check is straightforward:

```python
def before_llm_call(span_context: SpanContext, estimated_cost: float) -> None:
    current_spend = span_context.task_cost_so_far
    budget_remaining = span_context.task_budget - current_spend
    if estimated_cost > budget_remaining:
        raise BudgetExceededError(
            f"Estimated call cost {estimated_cost:.4f} exceeds "
            f"remaining budget {budget_remaining:.4f}"
        )
```

The estimated cost requires knowing the expected input token count before the call executes. This is computable from the rendered prompt template, which exists before the API request is sent. A 10–15% overestimate buffer is standard practice to account for tokenization variance.

Budget envelopes prevent disaster. They do not prevent waste. The more sophisticated control mechanism is a *cost-velocity circuit breaker*: a rolling window calculation that monitors the rate of spend over the preceding N calls and triggers a graceful degradation when that rate exceeds a threshold.

The underlying signal is the ratio of actual per-call cost to the expected per-call cost for the task type:

$$\text{cost\_velocity\_ratio} = \frac{\bar{C}_{\text{recent}}}{\bar{C}_{\text{baseline}}}$$

where $\bar{C}_{\text{recent}}$ is the exponentially weighted moving average of per-call costs over the last ten spans, and $\bar{C}_{\text{baseline}}$ is the empirically established mean cost for this task type under normal operating conditions. A ratio above 2.0 signals that something anomalous is occurring — context window bloat, retry amplification, or unintended sub-agent spawning — and the orchestrator should interrupt execution, log the anomaly, and escalate to human review.

This is the architectural lesson the legal technology company's postmortem identified but did not articulate precisely: the retry loop was not the root cause. The absence of a cost-velocity monitor was. A loop that doubled context window size on each retry produces a cost-velocity ratio that grows exponentially — it is among the most detectable anomalies in the cost signal, visible within three or four iterations if anyone is watching.

### Model Routing and the Cost-Quality Frontier

An agentic system that routes every call to the same model regardless of task complexity is economically equivalent to a software engineer who uses a compiled language with full static analysis for every script, including throwaway shell utilities. The tool is correct; the application is not calibrated to the problem.

Model routing — the practice of selecting a model from a tiered portfolio based on the complexity and value of the task — is the primary lever for reducing DpD without degrading decision quality. The routing decision can be formalized as an optimization over the cost-quality frontier:

$$\text{route}(t) = \arg\min_{m \in \mathcal{M}} C_m \quad \text{subject to} \quad Q_m(t) \geq Q_{\min}(t)$$

where $t$ is the task, $\mathcal{M}$ is the set of available models, $C_m$ is the per-call cost for model $m$ on task $t$, and $Q_{\min}(t)$ is the minimum acceptable quality for that task type.

In practice, model tiers map roughly to complexity tiers. High-complexity, high-stakes tasks — multi-step reasoning under uncertainty, cross-document synthesis, ambiguous legal or medical classification — warrant frontier models. Medium-complexity tasks — structured extraction from well-formatted source, single-document summarization, routine classification with a clear schema — can often be handled by mid-tier models at one-fifth to one-tenth the cost. Simple formatting, schema validation, and short-text classification often run adequately on fine-tuned small models or even deterministic functions that do not invoke an LLM at all.

The routing classifier itself must be cheap to operate — a meta-model that costs more than the savings it produces is self-defeating. Lightweight task complexity classifiers, trained on labeled examples from the agent's own execution logs, have achieved routing accuracy exceeding 90% in production deployments at inference costs under $0.0001 per routing decision.

### Cache Economics

Prompt caching — the ability to reuse the KV cache from a prior identical prefix without recomputing attention over those tokens — is the highest-leverage cost reduction available for agentic systems with stable system prompts and repeated context patterns. The economic model is a straightforward threshold condition: caching is net-positive when:

$$n_{\text{cached}} \cdot (P_{\text{in}} - P_{\text{cache}}) > C_{\text{cache\_write}}$$

where $P_{\text{cache}}$ is the discounted price for cached input tokens and $C_{\text{cache\_write}}$ is the one-time cost of writing the cache entry (typically charged at 25 basis points above the normal input rate for a single invocation).

For a system prompt of 5,000 tokens at $3.00 per million input tokens, with a cache hit discount of 90%, each cache hit saves approximately $0.0135. If the system prompt is identical across calls — which it is for any well-designed agent with a stable persona and tool schema — and the agent is processing a task type it handles hundreds of times per day, the cache write cost amortizes to near zero within the first few calls.

The underappreciated caching opportunity in agentic systems is not the system prompt but the *retrieved context*. Agents that perform RAG-style retrieval frequently pull the same document chunks into context across multiple tasks in a session. Semantic-level caching — storing retrieved chunks against their embedding fingerprint and serving them from a local cache before querying the retrieval pipeline or re-encoding them into a new prompt — can eliminate substantial redundant retrieval cost while also reducing input token counts.

---

## The Complication

The dollar-per-decision framework described above is correct as a first-order model. It becomes dangerous if treated as the complete story.

The first complication is *quality drift under cost pressure*. An agent architecture instrumented to minimize DpD will, absent careful constraint specification, route tasks to cheaper models and shorter contexts. Some of those routing decisions degrade decision quality in ways that are invisible to the cost accounting layer. A contract clause misclassified by a mid-tier model because the routing classifier underestimated task complexity does not show up as a cost anomaly — it shows up as a downstream business failure: a clause the system flagged as standard that a human reviewer would have escalated, or a compliance gap that survives document review because the cheaper model's context window was insufficient to hold the relevant precedent.

This means the constraint $Q_m(t) \geq Q_{\min}(t)$ in the routing optimization is not optional. It is the entire point. A DpD metric without a paired quality metric — accuracy on held-out examples, human evaluation on sampled decisions, downstream task success rate — is an optimization target that will reliably be met by degrading quality to its minimum acceptable threshold. The minimum acceptable threshold is often set too low, because it is set by engineers optimizing a cost metric, not by domain experts who understand what a wrong decision costs.

The second complication is *hidden costs at system boundaries*. The DpD framework as described accounts for LLM API costs and, if carefully implemented, retrieval and tool execution costs. It does not account for the cost of human review triggered by agent errors, the cost of downstream rework when an agent decision is wrong, or the amortized cost of the engineering time required to maintain cost monitoring infrastructure itself. A system with a DpD of $0.03 per decision that generates errors requiring $2.00 of human review time on 5% of decisions has an effective decision cost of $0.13 — more than four times the naive figure. Fully-loaded decision cost is the correct metric; DpD is a component of it.

The third complication is *context window economics under multi-turn state*. The per-call token count for an agent that maintains conversation history grows with session length. For a session of length $k$ turns with average per-turn tokens $\bar{n}$, the input tokens on turn $k$ are at minimum:

$$n_{\text{in},k} \geq \sum_{i=1}^{k-1} (n_{\text{in},i} + n_{\text{out},i}) + n_{\text{current}}$$

This is the O(k²) problem of naive conversation state management: the cost of processing turn $k$ is proportional to the total tokens produced in all prior turns. An agent session that feels inexpensive for the first five turns can become economically unsustainable by turn twenty if conversation history is not actively managed through summarization, selective retention, or windowing strategies. The DpD metric will catch this — cost per decision will trend upward across session length — but only if the monitoring window is long enough to observe the trend. Metrics computed over individual calls will look normal until they suddenly do not.

---

## Failure Case: The Overnight Document Review

Return to the legal technology company. Armed with the framework developed above, the postmortem reads differently the second time.

The agent's baseline DpD for single-document clause classification was $0.08, established from a sample of 500 successful classifications during development. On the night of the incident, the agent processed each document correctly on first attempt for the first 217 documents. At document 218, a malformed contract triggered a classification error. The retry logic, rather than applying exponential backoff with a maximum attempt count, retried indefinitely with the full conversation history appended on each attempt.

By the fifth retry of document 218, the context window contained the system prompt (5,000 tokens), the 217 successfully processed documents' classification output (approximately 40,000 tokens), and four prior failed attempts with their error traces (approximately 3,200 tokens) — a total of 48,200 input tokens against a baseline of 890. The per-call cost for this single classification attempt was $0.12 rather than $0.0025 — a cost-velocity ratio of 48.

If the circuit breaker threshold had been set at a cost-velocity ratio of 3.0, it would have triggered after the second anomalous retry — conserving the remaining $146,900 of spend, flagging document 218 for human review, and resuming processing on document 219.

The root architectural failure was not the retry bug. It was the absence of per-span cost instrumentation. Without span-level cost annotation, the orchestration layer had no signal to differentiate "this call cost 48× the baseline" from "this call cost the expected amount." The cost-velocity ratio was computable from available data at every point during the overnight run. No infrastructure existed to compute it.

The secondary failure was the absence of a task-level budget ceiling. Had the agent been initialized with a per-task budget of $1.50 — roughly double the expected cost of $0.08, providing margin for legitimate complexity variation — the budget envelope would have interrupted the anomalous retry sequence at the third attempt. The total cost of the incident would have been bounded by the product of the per-task ceiling and the total document count: 1,000 documents × $1.50 = $1,500 — still a notable overage from the intended $800, but not a career-ending incident.

This case is not exceptional. It is representative of the failure mode that emerges when agentic systems are treated as black boxes at the billing level rather than as observable distributed systems at the span level. The legal technology company had excellent monitoring on their retrieval pipeline, their database queries, and their frontend API latency. They had no monitoring on the only component whose cost was unbounded: the LLM.

---

## Connections to Design and Operations

The dollar-per-decision metric sits at the intersection of three concerns that are usually addressed by different teams at different points in the development lifecycle: system design (which models and context strategies to use), runtime operations (how to detect and interrupt anomalous behavior), and economic governance (whether the cost structure is sustainable at scale).

From a design perspective, DpD is a forcing function for architectural discipline. A system with a target DpD forces the architect to enumerate the tasks the agent will perform, estimate the token footprint of each, select models from the tier appropriate to each task's complexity and value, and identify opportunities for caching and deterministic replacement of LLM calls. This is good engineering independent of the cost outcome — it produces a system with well-defined task boundaries, explicit model selection rationale, and a cost model that can be validated before production.

From an operations perspective, per-span cost instrumentation is the enabling layer for the class of monitoring that all distributed systems require: anomaly detection on rate-of-change metrics, not just point-in-time thresholds. The cost-velocity ratio is semantically equivalent to the p99 latency spike detection that operations teams already know how to monitor. The same alerting infrastructure, the same on-call escalation paths, and the same runbooks apply — with cost substituted for latency as the measured quantity.

From a governance perspective, DpD makes the question of model selection legible to non-engineers. A product manager or CFO can engage with "we pay $0.08 per contract clause classified" in a way they cannot engage with "we use 890 input tokens and 45 output tokens per call at $3.00 per million." Unit economics translate technical choices into business decisions, and business decisions about AI spend — which tasks justify frontier model costs, which justify investment in fine-tuning a cheaper model, which do not justify LLM use at all — cannot be made without unit economics.

The processing implications run in both directions. Investment in prompt compression — tightening system prompts, shortening tool schemas, summarizing retrieved context — reduces DpD directly by reducing input token counts. Investment in output structuring — constrained generation formats, JSON mode, structured output schemas — reduces DpD by reducing output token variance. Both are processing choices that have been understood as quality engineering practices; DpD measurement reveals them also to be cost engineering practices.

---

## Student Activities

**Activity 1: Span-Level Cost Attribution**

You are given an execution trace from a research summarization agent. The trace contains twelve spans across four LLM calls, two vector database queries, one web search tool call, and three string formatting operations. The LLM calls used two different models: a frontier model for planning and synthesis, a mid-tier model for initial retrieval ranking. Token counts and model names are provided for each span; pricing tables for both models are provided in the appendix.

Compute the total task cost and the DpD for this trace, assuming that the planning call, the retrieval ranking call, and the final synthesis call are decision-bearing, and that all other calls are supporting. Identify the single span contributing the highest fraction of total cost, and propose one architectural change that would reduce that span's cost by at least 40% without changing the task output.

**Activity 2: Circuit Breaker Design**

Design a cost-velocity circuit breaker for a customer support agent with the following characteristics: average DpD of $0.04 under normal operation, 90th percentile DpD of $0.11, maximum recorded DpD of $0.28 (from a known edge case involving a customer with an unusually complex history). Your circuit breaker must interrupt anomalous sessions with false-positive rate below 5% — meaning it should not interrupt sessions that fall within the 90th percentile of normal operation. Specify: the monitoring window length in number of spans, the threshold cost-velocity ratio, the fallback behavior on trigger (graceful degradation vs. hard stop vs. human escalation), and the criteria for resuming normal operation.

**Activity 3: Open-Ended Design — The Budget-Aware Agent**

A research assistant agent is given a user query and a per-query budget of $0.50. Design the agent's budget-aware execution loop. Your design must specify: how the agent estimates the cost of its next planned action before taking it, how it adjusts its strategy when the remaining budget drops below a threshold you define, what minimum acceptable output it produces when the budget is nearly exhausted, and how it communicates budget constraints to the user without degrading the user experience. Implement a prototype of the budget accounting module in pseudocode or your preferred language. Evaluate your design against the criterion that a user receiving a budget-constrained response should be no worse off than a user who received no response at all.

**Activity 4: Model Routing Analysis**

Using the execution logs from a production-grade document processing agent (provided in the course data repository), train a task complexity classifier that predicts whether a given task should be routed to a frontier model or a mid-tier model. Use only features derivable from the prompt before the LLM call executes: prompt length, number of distinct entities, presence of ambiguous terms (from a predefined lexicon), task type (from a small taxonomy you define). Evaluate your classifier on a held-out test set. Calculate the expected cost savings if your classifier were applied to the full log, and estimate the quality degradation by comparing misclassified tasks' actual outputs against the outputs that would have been produced by the tier your classifier selected.

---

## LLM/AI Integration

**Scaffolded Activity: Cost Anomaly Report Generation**

*Cognitive load reduced:* Narrative construction from structured trace data — translating span-level cost telemetry into a coherent incident report with the correct level of technical and business detail.

*Higher-order thinking freed up:* Causal analysis. The agent can generate a report; it cannot determine whether the reported cost anomaly represents a bug, an edge case the system should handle gracefully, or a legitimate use case that warrants a higher per-task budget ceiling.

*Task design:* Provide the student with a set of five execution traces, two of which contain cost anomalies (context window bloat and retry amplification respectively), three of which represent normal operation with legitimate complexity variation. Ask the student to use an LLM assistant to generate a structured cost anomaly report for each trace, following a template you supply. The report should describe what happened, quantify the cost deviation, and propose a remediation.

*Human decision node:* After reviewing the five reports, the student must classify each anomaly as: (a) a system bug requiring a code fix, (b) an edge case requiring a guardrail, or (c) acceptable variation within the designed operating envelope. This classification requires the student to integrate the technical report with an understanding of the system's intended behavior, the business context for the task type, and the risk tolerance of the deployment environment. The LLM cannot make this judgment because it does not have access to the business context, and even if it did, the act of exercising that judgment is the learning objective.

*What the student must still do:* Write the final remediation recommendation — a specific, prioritized list of code changes, configuration adjustments, or monitoring additions — and defend it against an adversarial critique generated by the LLM from a prompt the student writes. The quality of the critique prompt is itself an assessed artifact: a prompt that elicits superficial objections demonstrates surface-level understanding; a prompt that elicits fundamental tradeoff objections demonstrates mastery.

---

## Chapter Summary

An agentic system without span-level cost instrumentation is not a deployed system — it is a billing event waiting to happen. The dollar-per-decision metric is the unit of economic accountability that makes the connection between LLM expenditure and business value legible, auditable, and actionable. Building toward it requires four things: an accounting model that traces cost to the token level across every span in the execution graph; an observability stack that makes those attributed costs visible as a streaming signal, not a monthly report; architectural patterns — budget envelopes, circuit breakers, model routing, cache economics — that allow the system to act on cost signals at runtime; and a commitment to pairing cost metrics with quality metrics, because a DpD target optimized in isolation will reliably be met by degrading the decisions it is supposed to measure.

The engineering discipline required to build all of this is not new. It is distributed systems observability, applied to a new kind of workload. The LLM call is the new database query: expensive, variable in latency, unbounded in cost if misused, and entirely observable if you decide to observe it. The teams that instrument their agentic systems at this level of granularity will have something the teams that do not will lack: the ability to say, with precision, what each decision cost, what it was worth, and what they would do differently next time.

---

*Chapter 15: Failure Modes at Scale — When Agents Interact with Other Agents*

---
