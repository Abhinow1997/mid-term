# Chapter 14: What Gets Measured Gets Managed — Interactive Demo

**Dollar-per-Decision Metric | FinOps & Observability for Agentic Systems**

**Video Link** - [Video Link](https://northeastern-my.sharepoint.com/:v:/g/personal/gangurde_a_northeastern_edu/IQBEKZSv7KhgS4vnvuCophZ8ASNbtUEAR6IkDTTpjWrFG14?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJPbmVEcml2ZUZvckJ1c2luZXNzIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXciLCJyZWZlcnJhbFZpZXciOiJNeUZpbGVzTGlua0NvcHkifX0&e=8mHZTT)

**Demo Link** - [Demo](https://jjunhepkaenra5oabkptkx.streamlit.app/)


## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

## What This Demonstrates

This interactive application simulates a legal tech document-review agent processing a corpus of contracts. It demonstrates the core architectural argument of Chapter 14: **cost-per-inference is the wrong metric for agentic systems; dollar-per-decision is the correct one.**

### Tabs

| Tab | What It Shows |
|-----|--------------|
| **Dashboard** | Live metrics (CPI vs DpD), per-call cost timeline, per-document cost breakdown |
| **Scenario Analysis** | Side-by-side comparison of 4 scenarios (no guardrails → full pipeline) |
| **Human Decision Nodes** | Two points where AI proposals were rejected on architectural grounds |
| **Exercise** | Toggle tiered routing off and watch DpD explode while CPI stays flat |
| **Trace Inspector** | Explore individual spans — filter by document, operation, or decision-bearing status |

### Sidebar Controls

- **Model Routing**: Toggle tiered routing on/off
- **Budget Envelope**: Set per-document spending ceiling
- **Circuit Breaker**: Configure cost-velocity threshold
- **Retry Behavior**: Control malformed document retry logic
- **Caching**: Enable/disable prompt caching

### Human Decision Nodes

1. **Fixed vs. Adaptive Circuit Breaker Threshold** — AI proposed a universal 2.0× threshold; rejected because task types have different variance profiles
2. **LLM Self-Classification vs. HITL Calibration** — AI proposed runtime LLM classification of decision-bearing calls; rejected because it adds cost to measure cost

### The Exercise

Turn OFF tiered model routing in the sidebar. Observe:
- Cost-per-inference stays roughly flat
- Dollar-per-decision jumps 5–8×
- Circuit breaker never trips (no single call is anomalous)

This is the blind spot that DpD catches and CPI misses entirely.

## No API Keys Required

All LLM costs are simulated with realistic token counts and pricing. No external API calls are made.

---

*Chapter 14 of Design of Agentic Systems with Case Studies — Prof. Nik Bear Brown*
