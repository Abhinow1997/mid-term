# The $147,000 Bug: Why Every AI Agent Needs a Price Tag on Every Decision

*How the dollar-per-decision metric turns runaway AI costs from overnight disasters into observable, controllable engineering problems.*

---

A legal tech company left an AI agent running overnight. By morning, it had spent $147,000 — not because it went rogue, but because nobody had asked one question before deploying it.

On a Thursday evening in late 2023, a document-review agent was deployed to process a corpus of contracts: classify each clause, flag anomalies, produce a summary. The engineering team estimated roughly $800 in API fees. They set no budget cap. They went home.

The agent had not hallucinated wildly or sent emails to clients. It had done something far more mundane and far more instructive: it had looped. A retry logic error caused the agent to resubmit failed classification calls. A context management flaw caused each retry to include the entire prior conversation history, compounding the token count with each attempt. The agent was, in a technical sense, working hard — generating tens of thousands of API calls, faithfully logging each one, producing output that looked plausible. It was just doing all of this against a corpus it had already processed, at a cost per call that grew quadratically as the context window bloated.

The postmortem identified three proximate causes: no budget ceiling, no per-call token accounting, and no anomaly detection on cost velocity. The underlying cause was simpler than any of those. Nobody had asked the question that should precede every production deployment of an agentic system: *for each decision this agent makes, what am I paying, and is that price proportional to the value the decision creates?*

---

How do you make cost a first-class property of an agentic system — not an afterthought audited from a billing dashboard, but a measured, observable quantity that shapes architecture, routing, and runtime behavior the same way latency and accuracy do?

---

## The number that matters is cost per outcome, not the invoice total

Cloud computing spent a decade learning one lesson: the number that matters isn't the monthly bill — it's the cost per outcome. Agentic AI is relearning that lesson at triple speed. A company running 10,000 EC2 instances does not care primarily about total compute spend. It cares about cost per API call served, cost per transaction processed, cost per active user retained. The aggregate bill is a symptom. The unit economics are the diagnosis.

For traditional cloud workloads, establishing unit economics is annoying but tractable. You tag resources, allocate costs to services, divide by throughput metrics. The denominator — requests served, users active, transactions committed — is straightforward to count.

Agentic systems make the denominator ambiguous. What is the unit of work an agent produces? A user message answered? A task completed? A tool call made? A decision rendered? These are not equivalent. An agent that throws a 128,000-token context window and four tool calls at a trivial clarifying question has wasted most of its budget on nothing. An agent that routes a complex multi-step task to a lightweight model and nails it in three focused calls has created real value. If you count both as "one response," your unit economics are fiction.

> **This is not a billing problem. It is a measurement problem, and measurement problems in engineering always precede control problems.**

You cannot build a circuit breaker for runaway cost if you do not know what normal cost looks like, at the level of individual decisions, in real time.

The framework this piece builds toward — the dollar-per-decision metric — is the agentic analog of cost-per-request in traditional cloud FinOps. Getting there requires three capabilities working in concert: an accounting layer that attributes costs at the span level, an observability stack that makes those attributed costs visible across the agent's execution graph, and a set of architectural patterns — budget guardrails, model routing, cache economics — that let you act on what you see before the invoice arrives.


---

## The dollar-per-decision metric, defined plainly then precisely

![alt text](<diagrams/Figure 1 — Execution Graph.png>)

Dollar-per-decision (DpD) asks one question: for each real choice your agent makes, what did you pay? Not reformatting calls. Not schema validation. The choices that actually required the model to think.

![alt text](<diagrams/Figure 2 — DpD Formula Decomposition.png>)

Formally: DpD is total API expenditure divided by the count of agent-originated actions requiring genuine probabilistic reasoning. Systems instrumented to minimize DpD while holding decision quality constant will outperform — in both cost and reliability — systems instrumented only at the aggregate billing level.

### Token economics: the atomic unit

Every API call to a large language model generates two costs: an input cost and an output cost. Frontier models price these asymmetrically — check your provider's rate card, these shift quarterly — but the structural ratio is durable: output tokens cost 3–5× more per token than input tokens, because generating tokens is computationally more expensive than attending to them.

This asymmetry matters immediately for agentic design. An agent that produces verbose chain-of-thought reasoning in its output, then feeds that reasoning as context into subsequent calls, pays the output premium once for generation and then pays a discounted input premium every time that text appears in a future context window. The economics of reasoning verbosity are not free. A 2,000-token internal monologue persisting across ten subsequent calls costs roughly:

$$C_{\text{reasoning}} = 2000 \times P_{\text{out}} + 10 \times 2000 \times P_{\text{in}}$$

Plug in your provider's current rates and multiply by a million agent invocations. That single reasoning trace — 20,000 tokens of input cost carried across ten calls before a single useful decision is made — scales to five or six figures of annual spend. Before the agent has done any actual work. The ratio does the damage; the absolute prices just determine how fast.

The precise accounting equation for a single LLM call within an agent span is:

$$C_{\text{call}} = n_{\text{in}} \cdot P_{\text{in}} + n_{\text{out}} \cdot P_{\text{out}} - n_{\text{cached}} \cdot P_{\text{cache\_discount}}$$

where $n_{\text{in}}$ is the total input token count, $n_{\text{out}}$ is the generated output token count, $n_{\text{cached}}$ is the subset of input tokens that hit a prompt cache, and $P_{\text{cache\_discount}}$ is the per-token savings from caching (typically 80–90% of the base input price for providers offering prompt caching).

### Distributed tracing and the execution graph



A single agent task rarely executes as a single LLM call. It executes as a graph: an initial planning call, branching tool calls, possibly recursive sub-agent invocations, aggregation calls, and a final synthesis. The execution graph of a moderately complex document-review agent might look like this:

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

To make cost observable at this granularity, every span must carry a cost annotation — not a post-hoc calculation from the billing dashboard, but an instrumentation requirement. Each LLM call emits a structured trace event containing at minimum: span ID, parent span ID, model name, input token count, output token count, cached token count, computed cost, and wall-clock latency. This borrows directly from OpenTelemetry, the distributed tracing standard developed for microservices. The LLM call is instrumented the same way a web framework instruments each HTTP request.

A simplified representation of the required span schema:

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

The `decision_bearing` flag is not standard in most observability frameworks. It is introduced deliberately, because it is the hinge on which the DpD metric turns.

### What counts as a "decision"

That schema is plumbing. The `decision_bearing` flag is where it gets interesting — because not every LLM call is worth measuring the same way.

A *decision-bearing call* is one whose output changes the agent's subsequent behavior. A classification that routes a document to one processing path versus another. A planning call that decomposes a task into subtasks. A call that generates final output delivered to a user.

A *non-decision call* is one that could, in principle, be replaced by a deterministic function without loss of quality. Extracting structured JSON from already well-structured text. Reformatting output from one syntactic form to another. Summarizing a passage the agent has already processed in full.

The distinction is not always clean, but it is always worth resolving — and the method of resolution matters. The instinct is to ask an LLM to classify each call at runtime, letting the model decide on every invocation whether it just made a decision. Reject that instinct. It compounds a per-call LLM cost onto every span in perpetuity, and it introduces variance into the denominator of your core metric.

The correct approach is simpler and cheaper. For obvious cases — a routing call, a planning call, a final output call — tag at design time. The call is decision-bearing because the architect said so, in the code, once. For ambiguous cases — the summarization call that might be reducing redundancy or might be generating novel synthesis — bring a human in during the calibration phase to decide. Review a sample of the call's actual outputs, ask whether changing any of them would have changed the agent's behavior, and tag accordingly. That judgment is made once, validated against new samples periodically, and baked into the system as a static annotation. The cost is an hour of a domain expert's time during development, not a per-call LLM inference compounding forever across production traffic.

The formal definition:

$$\text{DpD} = \frac{\sum_{i \in \mathcal{D}} C_i + \sum_{j \in \mathcal{S}} C_j}{|\mathcal{D}|}$$

where $\mathcal{D}$ is the set of decision-bearing spans, $\mathcal{S}$ is the set of supporting spans, and the denominator counts only decision-bearing spans. The numerator includes all costs because supporting calls are real expenditures in service of decisions; the denominator counts only the decisions those costs are meant to produce.

For the legal technology agent from the opening, a single clause classification — *this is a limitation-of-liability provision* — is one decision. The full execution graph to reach that classification, including retrieval, formatting, and clarifying sub-calls, might cost $0.08. DpD for that task type: $0.08.

Whether $0.08 per clause classification is acceptable depends entirely on what that classification is worth. In a legal workflow where a misclassified clause introduces contractual liability, $0.08 is spectacularly cheap. In a commodity indexing pipeline where the same task can be done by a fine-tuned 7B open-weights model at $0.001 per call, it represents an 80× overspend. The metric does not tell you the answer. It tells you the question.

### Budget guardrails and circuit breakers

![alt text](<diagrams/Figure 3 — Cost-Velocity Circuit Breaker.png>)

Knowing your DpD in production requires more than after-the-fact instrumentation. It requires runtime cost accounting — the agent knows, at each step, how much it has spent on the current task, and that knowledge influences its execution strategy.

The minimal implementation is a budget envelope: a hard ceiling on per-task spend, enforced by the orchestration layer before each LLM call:

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

The estimated cost is computable from the rendered prompt template, which exists before the API request is sent. A 10–15% overestimate buffer is standard practice to account for tokenization variance.

Budget envelopes prevent disaster. They do not prevent waste. The more sophisticated control mechanism is a *cost-velocity circuit breaker*: a rolling window calculation monitoring the rate of spend over the preceding N calls, triggering graceful degradation when that rate exceeds a threshold.

The underlying signal is the ratio of actual per-call cost to the expected per-call cost for the task type:

$$\text{cost\_velocity\_ratio} = \frac{\bar{C}_{\text{recent}}}{\bar{C}_{\text{baseline}}}$$

where $\bar{C}_{\text{recent}}$ is the exponentially weighted moving average of per-call costs over the last ten spans, and $\bar{C}_{\text{baseline}}$ is the empirically established mean cost for this task type under normal conditions.

The threshold at which this ratio triggers an alert cannot be fixed across all task types — and the instinct to hardcode a single value is precisely the oversimplification that produces both missed anomalies and false alarms. A multi-document synthesis task has naturally wide cost variance; a ratio of 2.0 might be unremarkable. A JSON extraction task from a well-structured source has tight, predictable cost; a ratio of 1.4 might be a genuine signal. The threshold must be a function of each task type's own historical cost distribution:

$$\tau(t) = 1 + k \cdot \frac{\sigma_t}{\mu_t}$$

where $\sigma_t$ is the standard deviation of historical per-call costs for task type $t$, $\mu_t$ is the historical mean, and $k$ is a sensitivity parameter set based on acceptable false-positive rate — typically 2–3, corresponding roughly to the 95th and 99th percentiles of a normal distribution. A task type with tight cost variance gets a low threshold; one with wide natural variance gets a higher one. The circuit breaker is calibrated to the task, not to a universal intuition about what "anomalous" should mean. When the ratio exceeds $\tau(t)$, the orchestrator interrupts execution, logs the anomaly, and escalates to human review.

### Model routing and the cost-quality frontier

![alt text](<diagrams/Figure 4 — Model Routing.png>)

An agentic system routing every call to the same model regardless of task complexity is economically equivalent to using a fully compiled, statically-analyzed language for every script, including throwaway shell utilities — or, for non-engineers on your team: it's the equivalent of sending every package by overnight express, including the ones that could go standard mail. The tool is correct; the application is not calibrated to the problem.

Model routing — selecting a model from a tiered portfolio based on task complexity and value — is the primary lever for reducing DpD without degrading decision quality:

$$\text{route}(t) = \arg\min_{m \in \mathcal{M}} C_m \quad \text{subject to} \quad Q_m(t) \geq Q_{\min}(t)$$

In practice, model tiers map to complexity tiers. High-complexity, high-stakes tasks — multi-step reasoning under uncertainty, cross-document synthesis, ambiguous legal or medical classification — warrant frontier models. Medium-complexity tasks — structured extraction from well-formatted source, single-document summarization, routine classification with a clear schema — can often be handled by mid-tier models at one-fifth to one-tenth the cost. Simple formatting, schema validation, and short-text classification often run adequately on fine-tuned small models or deterministic functions that skip the LLM entirely.

The routing classifier itself must be cheap to operate. A meta-model costing more than the savings it produces is self-defeating. Lightweight task complexity classifiers, trained on labeled examples from the agent's own execution logs, have achieved routing accuracy exceeding 90% in production deployments at inference costs under $0.0001 per routing decision.

### Cache economics

Prompt caching — reusing the KV cache from a prior identical prefix without recomputing attention over those tokens — is the highest-leverage cost reduction available for agentic systems with stable system prompts and repeated context patterns. Caching is net-positive when:

$$n_{\text{cached}} \cdot (P_{\text{in}} - P_{\text{cache}}) > C_{\text{cache\_write}}$$

Most providers offering prompt caching charge a one-time write fee and then serve cached tokens at a steep discount — often an order of magnitude below the normal input rate. For a 5,000-token system prompt invoked hundreds of times per day, the write cost amortizes to near zero within the first few calls and the savings compound from there. The math favors caching aggressively for any prompt prefix that is stable across calls.

The underappreciated caching opportunity is not the system prompt but *retrieved context*. Agents performing RAG-style retrieval frequently pull the same document chunks into context across multiple tasks in a session. Semantic-level caching — storing retrieved chunks against their embedding fingerprint and serving them from a local cache before querying the retrieval pipeline — can eliminate substantial redundant retrieval cost while also reducing input token counts.

---

## Where the simple model breaks

![alt text](<diagrams/Figure 6 — Context Window Token Growth.png>)

The DpD framework above is correct as a first-order model. It becomes dangerous if treated as the complete story.

**Quality drift under cost pressure.** An agent architecture instrumented to minimize DpD will, absent careful constraint specification, route tasks to cheaper models and shorter contexts. Some of those routing decisions degrade decision quality in ways invisible to the cost accounting layer. A misclassified contract clause does not show up as a cost anomaly — it shows up as a downstream business failure. This is why the constraint $Q_m(t) \geq Q_{\min}(t)$ in the routing optimization is not optional. It is the entire point. A DpD metric without a paired quality metric is an optimization target that will reliably be met by degrading quality to its minimum acceptable threshold — which is typically set too low, because it was set by engineers optimizing a cost metric rather than domain experts who understand what a wrong decision costs.

**Hidden costs at system boundaries.** The DpD framework accounts for LLM API costs and, if carefully implemented, retrieval and tool execution costs. It does not account for the cost of human review triggered by agent errors, the cost of downstream rework when an agent decision is wrong, or the amortized cost of the engineering time required to maintain cost monitoring infrastructure itself. A system with a DpD of $0.03 per decision that generates errors requiring $2.00 of human review time on 5% of decisions has an effective decision cost of $0.13 — more than four times the naive figure. Fully-loaded decision cost is the correct metric; DpD is a component of it.

**Context window O(k²) growth.** The per-call token count for an agent maintaining conversation history grows with session length. For a session of length $k$ turns with average per-turn tokens $\bar{n}$, the input tokens on turn $k$ are at minimum:

$$n_{\text{in},k} \geq \sum_{i=1}^{k-1} (n_{\text{in},i} + n_{\text{out},i}) + n_{\text{current}}$$

The cost of processing turn $k$ is proportional to the total tokens produced in all prior turns. An agent session that feels inexpensive for the first five turns can become economically unsustainable by turn twenty without active conversation management through summarization, selective retention, or windowing strategies. The DpD metric will catch this — cost per decision will trend upward across session length — but only if the monitoring window is long enough to observe the trend. Metrics computed over individual calls will look normal until they suddenly do not.

---

## Two failures, one root cause

The $147,000 overnight disaster is a loud failure. A runaway retry loop, a number that shocks, a postmortem with clear villains. Easy to learn from because impossible to ignore.

The second failure mode is quiet. No loop, no incident ticket, no 2 AM alert. The system works exactly as designed. It processes thousands of documents correctly. It never exceeds its per-call budget. It just gets canceled by finance after three months — not because it failed technically, but because no one could justify the economics. Both failures trace back to the same root cause: measuring cost at the wrong granularity.

### Failure Mode 1: the $147,000 overnight loop

Return to the legal technology company. Armed with the DpD framework, the postmortem reads differently.

The agent's baseline DpD for single-document clause classification was $0.08, established from 500 successful classifications during development. On the night of the incident, the agent processed correctly for the first 217 documents. At document 218, a malformed contract triggered a classification error. The retry logic retried indefinitely with the full conversation history appended on each attempt.

By the fifth retry of document 218, the context window contained the system prompt (5,000 tokens), the 217 successfully processed documents' classification output (approximately 40,000 tokens), and four prior failed attempts with their error traces (approximately 3,200 tokens) — a total of 48,200 input tokens against a baseline of 890. The per-call cost for this single attempt was $0.12 rather than $0.0025. A cost-velocity ratio of 48.

If an adaptive circuit breaker had been in place — threshold set at $\tau(t) = 1 + 3 \cdot (\sigma_t / \mu_t)$, calibrated against the tight cost distribution of a well-structured extraction task — it would have triggered after the second anomalous retry. Cost conserved: $146,900. Document 218 flagged for human review. Document 219 processed normally.

The root architectural failure was not the retry bug. It was the absence of per-span cost instrumentation. Without span-level cost annotation, the orchestration layer had no signal to differentiate "this call cost 48× the baseline" from "this call cost the expected amount." The cost-velocity ratio was computable from available data at every point during the overnight run. No infrastructure existed to compute it.

### Failure Mode 2: the system that looked fine until it didn't

![alt text](<diagrams/Figure 5 — Non-Decision Spend Waterfall.png>)

Now consider a different team building a similar document-review agent. They do not have a retry bug. They have a monitoring philosophy: track cost-per-inference. Every LLM call costs roughly $0.003. The dashboard shows a flat, healthy line. Sprint reviews are calm. The system ships to production.

Three months later, finance cancels the project. The agent processed 200,000 contract clauses. Total LLM spend: $188,000. The business case had projected $12,000.

What happened? Walk through a single clause classification and count the calls.

| Span | Operation | Model used | Decision-bearing? | Cost |
|---|---|---|---|---|
| 1 | Parse contract structure | Frontier | No | $0.003 |
| 2 | Extract candidate clauses | Frontier | No | $0.003 |
| 3 | Reformat clauses to schema | Frontier | No | $0.003 |
| 4 | Validate schema output | Frontier | No | $0.003 |
| 5 | Classify clause type | Frontier | **Yes** | $0.003 |
| 6 | Reformat classification to JSON | Frontier | No | $0.003 |
| 7 | Validate classification schema | Frontier | No | $0.003 |
| 8–12 | Lookup and reformat precedents (×5) | Frontier | No | $0.015 |
| 13 | Assess anomaly flag | Frontier | **Yes** | $0.003 |
| 14 | Reformat anomaly output | Frontier | No | $0.003 |
| 15–18 | Summarize supporting evidence (×4) | Frontier | No | $0.012 |
| 19 | Generate clause summary | Frontier | **Yes** | $0.003 |
| 20–25 | Format, validate, and verify summary (×6) | Frontier | No | $0.018 |
| **Total** | | | **3 of 25 calls** | **$0.075** |

Twenty-five calls per clause classification. Three of them are decision-bearing. The other twenty-two are formatting, schema validation, and deterministic reformatting — operations that a regex, a JSON schema validator, or a fine-tuned 1B-parameter model could perform at 1/50th the cost.

What the team's dashboard shows: $0.003 per call. Flat. Normal. Green.

What is actually happening:

$$\text{DpD} = \frac{25 \times \$0.003}{3} = \frac{\$0.075}{3} = \$0.025 \text{ per decision}$$

That does not sound alarming either — until you ask what fraction of the $0.075 per classification is doing actual work. Three calls at $0.003 each is $0.009 of decision-bearing cost. The remaining $0.066 — 88% of the total spend — is a frontier model doing the work of a schema validator.

Scale to 200,000 clause classifications:

| Metric | What the team measured | What was actually happening |
|---|---|---|
| Cost per call | $0.003 | $0.003 |
| Calls per classification | — | 25 |
| Decision-bearing calls per classification | — | 3 |
| Cost per classification | — | $0.075 |
| **Dollar-per-decision** | **Not measured** | **$0.025** |
| Non-decision spend fraction | Not visible | 88% |
| Total spend at 200K classifications | Projected: $12,000 | Actual: $188,000 |
| Addressable waste | Not visible | ~$165,000 |

The $165,000 in addressable waste is not waste in the sense of a bug. It is the entirely predictable consequence of routing 22 of every 25 LLM calls to a model that costs as much as reasoning through a complex legal question, and asking it to reformat a JSON object.

Had the team been measuring DpD from the start, the problem would have been visible in the first day of production traffic — not the third month. A DpD of $0.025 against a design target of, say, $0.005 (achievable if the non-decision calls route to a cheap model) would have flagged immediately that 88% of the budget was burning on non-decision work. The routing fix is not complex: deterministic schema validation replaces calls 4, 6, 7, and 20–25 entirely; a fine-tuned small model handles the formatting and restatement calls. Realistic post-fix cost per classification: $0.011, of which $0.009 is decision-bearing work and $0.002 is legitimately necessary support. DpD drops to $0.0037. Total cost at 200K classifications: $2,200 instead of $188,000.

The project does not get canceled. It gets a case study.

### The shared root cause

Both failures — the overnight loop and the quiet economics disaster — are the same error at different timescales. The legal technology company measured cost at the call level and missed a 48× velocity spike that would have been obvious at the span level. The second team measured cost at the call level and missed a 16× budget overrun that would have been obvious at the decision level.

The wrong metric does not produce loud failures. It produces failures that look like everything is fine, right up until someone in finance asks the question the engineering dashboard was never designed to answer: *what does each decision actually cost us?*

---

## DpD as a forcing function: design, operations, governance

DpD sits at the intersection of three concerns usually addressed by different teams at different times in the development lifecycle.

From a design perspective, DpD is a forcing function for architectural discipline. A system with a target DpD forces the architect to enumerate the tasks the agent will perform, estimate the token footprint of each, select models from the tier appropriate to each task's complexity and value, and identify opportunities for caching and deterministic replacement of LLM calls.

From an operations perspective, per-span cost instrumentation enables the class of monitoring all distributed systems require: anomaly detection on rate-of-change metrics, not just point-in-time thresholds. The cost-velocity ratio is semantically equivalent to the p99 latency spike detection that operations teams already know how to monitor. The same alerting infrastructure, the same on-call escalation paths, the same runbooks apply — with cost substituted for latency as the measured quantity.

From a governance perspective, DpD makes model selection legible to non-engineers. A product manager or CFO can engage with "we pay $0.08 per contract clause classified" in a way they cannot engage with "we use 890 input tokens and 45 output tokens per call at $3.00 per million." Unit economics translate technical choices into business decisions — which tasks justify frontier model costs, which justify investment in fine-tuning a cheaper model, which do not justify LLM use at all — and those decisions cannot be made without unit economics.

---

The engineering discipline required to build all of this is not new. It is distributed systems observability, applied to a new kind of workload. The LLM call is the new database query: expensive, variable in latency, unbounded in cost if misused, and entirely observable if you decide to observe it.

---

*If you've been burned by an unexplained AI bill — or if you're building agents and haven't instrumented cost yet — drop your war story in the comments. And if this was useful, share it with whoever on your team is responsible for the billing dashboard.*

*If you're new here: this newsletter covers the engineering and architecture of agentic AI systems — the decisions that don't show up in the model benchmarks but determine whether something actually ships. Subscribe to get the next one.*