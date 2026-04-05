## STAGE 1 — Define Your Chapter's Core Claim (Day 1)

#### "After reading this chapter, a student will understand [architectural decision X] well enough to [make design choice Y] without making [mistake Z]."

After reading this chapter, a student will understand span-level cost observability and the dollar-per-decision metric as the correct unit economics for agentic systems well enough to design a FinOps pipeline with decision-bearing tagging, budget circuit breakers, and tiered model routing without making the mistake of monitoring cost at the aggregate billing level, which hides per-decision cost compounding and produces agents that look cheap per inference but are economically indefensible at production scale.

#### The Human Decision Node lives here. 

![alt text](image.png)

Ok couple of pointers to update : 
1. For the "Budget guardrails and circuit breakers" section you have defined a 2.0 cost-velocity threshold as 2.0 why have you done that specifically? A fixed version of the same should be adaptive and adjust based on the task-type variance.
2. For the decision_bearing you want the LLM to classify every call at runtime. I rejected it — for obvious cases, tag at design time. For ambiguous ones, bring a human in during calibration to decide. That's a one-time human cost, not a per-call LLM cost compounding forever


##### The Demo
The app has 5 interactive tabs:
📊 Dashboard — Live metrics cards (Total Cost, CPI, DpD, the gap ratio), a per-call cost timeline scatter plot showing the malformed document spike, and a per-document cost bar chart. All update live as you change sidebar controls.
📈 Scenario Analysis — Runs all 4 scenarios automatically (No Guardrails → Budget → Circuit Breaker → Full Pipeline) and shows them side-by-side in a table and grouped bar charts. The key insight — CPI barely moves across scenarios while DpD tells the real story — is immediately visible.
🧠 Human Decision Nodes — Both HDNs with styled cards showing AI proposal → rejection → implementation. HDN #1 includes a variance table proving why fixed thresholds fail. HDN #2 calculates the monthly cost of the AI's self-classification proposal at production scale ($X/month vs. $0/month).
⚡ Exercise — Side-by-side comparison of routing ON vs OFF with delta metrics. Shows the circuit breaker never fires when routing is removed. Ends with the open question about who sets Q_min.
🔍 Trace Inspector — Filterable table of every span (by document, operation, or decision-bearing status) plus a box plot of cost distribution by operation. This is what span-level observability actually looks like.
Everything in the sidebar is toggleable — model routing, budget envelope, circuit breaker threshold, max retries, caching — so you can demonstrate any failure mode live during your video.