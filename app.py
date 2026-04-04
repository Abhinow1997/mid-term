"""
Chapter 14: What Gets Measured Gets Managed
Interactive Demo — Dollar-per-Decision Metric

Run with: streamlit run app.py
Requirements: pip install streamlit plotly pandas
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import random
import uuid
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Chapter 14 — Dollar-per-Decision",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown("""
<style>
    /* Main header styling */
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #555;
        margin-bottom: 2rem;
    }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 1.2rem;
        color: white;
        text-align: center;
        margin-bottom: 1rem;
    }
    .metric-card.danger {
        background: linear-gradient(135deg, #f5365c 0%, #f56036 100%);
    }
    .metric-card.success {
        background: linear-gradient(135deg, #2dce89 0%, #2dcecc 100%);
    }
    .metric-card.warning {
        background: linear-gradient(135deg, #fb6340 0%, #fbb140 100%);
    }
    .metric-card .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
    }
    .metric-card .metric-label {
        font-size: 0.85rem;
        opacity: 0.9;
    }
    
    /* Decision node styling */
    .decision-node {
        background: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 1.2rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0;
    }
    .decision-node.rejected {
        background: #f8d7da;
        border-left-color: #dc3545;
    }
    .decision-node.accepted {
        background: #d4edda;
        border-left-color: #28a745;
    }
    
    /* Sidebar styling */
    .sidebar-section {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    
    /* Hide default streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ============================================================
# DATA MODELS (from the notebook)
# ============================================================

MODEL_PRICING = {
    "frontier": {
        "name": "claude-opus-4 (Frontier)",
        "input_per_million": 15.00,
        "output_per_million": 75.00,
        "cache_discount": 0.90,
        "color": "#f5365c",
    },
    "mid_tier": {
        "name": "claude-sonnet-4 (Mid-Tier)",
        "input_per_million": 3.00,
        "output_per_million": 15.00,
        "cache_discount": 0.90,
        "color": "#fb6340",
    },
    "lightweight": {
        "name": "claude-haiku-4 (Lightweight)",
        "input_per_million": 0.25,
        "output_per_million": 1.25,
        "cache_discount": 0.90,
        "color": "#2dce89",
    },
}


@dataclass
class TaskProfile:
    operation: str
    base_input_tokens: int
    base_output_tokens: int
    token_variance: float
    decision_bearing: bool
    recommended_tier: str
    cacheable_tokens: int = 0


TASK_GRAPH = [
    TaskProfile("plan_subtasks",      1200, 340, 0.10, True,  "mid_tier",    500),
    TaskProfile("classify_clause",     890,  45, 0.15, True,  "frontier",    500),
    TaskProfile("clarify_term",       1100,  80, 0.20, False, "lightweight", 500),
    TaskProfile("format_output",       400, 200, 0.10, False, "lightweight",   0),
    TaskProfile("validate_schema",     300,  50, 0.05, False, "lightweight",   0),
    TaskProfile("flag_anomaly",        950, 120, 0.15, True,  "mid_tier",    500),
    TaskProfile("synthesize_summary", 3400, 560, 0.10, True,  "frontier",    500),
]


@dataclass
class Span:
    span_id: str
    parent_span_id: str
    operation: str
    model_tier: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float
    latency_ms: int
    decision_bearing: bool
    doc_id: int
    is_retry: bool = False
    retry_number: int = 0


@dataclass
class Document:
    doc_id: int
    title: str
    clause_count: int
    is_malformed: bool = False
    complexity: str = "standard"


def compute_call_cost(model_tier, input_tokens, output_tokens, cached_tokens=0):
    pricing = MODEL_PRICING[model_tier]
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_million"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_million"]
    cache_savings = (cached_tokens / 1_000_000) * pricing["input_per_million"] * pricing["cache_discount"]
    return input_cost + output_cost - cache_savings


# ============================================================
# SIMULATION ENGINE
# ============================================================

def create_corpus(num_docs, malformed_index):
    random.seed(42)
    corpus = []
    for i in range(num_docs):
        complexity = random.choice(["simple"] * 5 + ["standard"] * 3 + ["complex"] * 2)
        corpus.append(Document(
            doc_id=i,
            title=f"Contract-{i+1:04d}",
            clause_count=random.randint(5, 25),
            is_malformed=(i == malformed_index),
            complexity=complexity,
        ))
    return corpus


def simulate_agent_run(corpus, use_tiered_routing, default_model, budget_per_task,
                       circuit_breaker_enabled, cb_threshold, max_retries,
                       retry_appends_history, enable_caching):
    spans = []
    random.seed(42)
    
    baseline_costs = {}
    calibration_phase = True
    
    docs_processed = 0
    docs_skipped = 0
    budget_violations = 0
    circuit_breaker_trips = 0
    
    for doc in corpus:
        task_cost_so_far = 0.0
        root_id = str(uuid.uuid4())[:8]
        doc_aborted = False
        accumulated_history_tokens = 0
        
        for task in TASK_GRAPH:
            if doc_aborted:
                break
            
            model_tier = task.recommended_tier if use_tiered_routing else default_model
            
            if doc.is_malformed and task.operation == "classify_clause":
                for retry_num in range(max_retries):
                    if retry_appends_history:
                        accumulated_history_tokens += task.base_input_tokens + task.base_output_tokens
                    
                    variance = 1.0 + random.uniform(-task.token_variance, task.token_variance)
                    input_tokens = int((task.base_input_tokens + accumulated_history_tokens) * variance)
                    output_tokens = int(task.base_output_tokens * variance * 1.5)
                    cached = int(task.cacheable_tokens * enable_caching * 0.9)
                    
                    cost = compute_call_cost(model_tier, input_tokens, output_tokens, cached)
                    
                    if budget_per_task is not None:
                        if task_cost_so_far + cost > budget_per_task:
                            budget_violations += 1
                            doc_aborted = True
                            break
                    
                    if circuit_breaker_enabled and not calibration_phase:
                        op_baseline = baseline_costs.get(task.operation, cost)
                        if op_baseline > 0:
                            velocity_ratio = cost / op_baseline
                            if velocity_ratio > cb_threshold:
                                circuit_breaker_trips += 1
                                doc_aborted = True
                                break
                    
                    span = Span(
                        span_id=str(uuid.uuid4())[:8],
                        parent_span_id=root_id,
                        operation=task.operation,
                        model_tier=model_tier,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cached_tokens=cached,
                        cost_usd=cost,
                        latency_ms=int(input_tokens * 0.8 + output_tokens * 2.5),
                        decision_bearing=task.decision_bearing,
                        doc_id=doc.doc_id,
                        is_retry=True,
                        retry_number=retry_num + 1,
                    )
                    spans.append(span)
                    task_cost_so_far += cost
                
                doc_aborted = True
                continue
            
            variance = 1.0 + random.uniform(-task.token_variance, task.token_variance)
            input_tokens = int(task.base_input_tokens * variance)
            output_tokens = int(task.base_output_tokens * variance)
            cached = int(task.cacheable_tokens * enable_caching * 0.9)
            
            cost = compute_call_cost(model_tier, input_tokens, output_tokens, cached)
            
            if budget_per_task is not None:
                if task_cost_so_far + cost > budget_per_task:
                    budget_violations += 1
                    doc_aborted = True
                    break
            
            span = Span(
                span_id=str(uuid.uuid4())[:8],
                parent_span_id=root_id,
                operation=task.operation,
                model_tier=model_tier,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached,
                cost_usd=cost,
                latency_ms=int(input_tokens * 0.8 + output_tokens * 2.5),
                decision_bearing=task.decision_bearing,
                doc_id=doc.doc_id,
                is_retry=False,
                retry_number=0,
            )
            spans.append(span)
            task_cost_so_far += cost
            
            if doc.doc_id < 10:
                if task.operation not in baseline_costs:
                    baseline_costs[task.operation] = []
                if isinstance(baseline_costs[task.operation], list):
                    baseline_costs[task.operation].append(cost)
        
        if not doc_aborted:
            docs_processed += 1
        else:
            docs_skipped += 1
        
        if doc.doc_id == 9:
            calibration_phase = False
            for op, costs in baseline_costs.items():
                if isinstance(costs, list) and costs:
                    baseline_costs[op] = sum(costs) / len(costs)
    
    return spans, docs_processed, docs_skipped, budget_violations, circuit_breaker_trips


def compute_metrics(spans):
    total_cost = sum(s.cost_usd for s in spans)
    total_calls = len(spans)
    cpi = total_cost / total_calls if total_calls > 0 else 0
    decision_count = sum(1 for s in spans if s.decision_bearing)
    dpd = total_cost / decision_count if decision_count > 0 else float('inf')
    return total_cost, total_calls, cpi, dpd, decision_count


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.markdown("## 🎛️ Simulation Controls")

st.sidebar.markdown("### 📄 Corpus")
num_docs = st.sidebar.slider("Number of documents", 10, 100, 50)
malformed_index = st.sidebar.number_input("Malformed document index", 0, num_docs - 1, min(38, num_docs - 1))

st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Model Routing")
use_tiered_routing = st.sidebar.toggle("Enable tiered model routing", value=True,
                                        help="When ON: decision-bearing → frontier, support → lightweight. When OFF: all calls use the default model.")
default_model = st.sidebar.selectbox("Default model (when routing OFF)", ["frontier", "mid_tier", "lightweight"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛡️ Guardrails")
enable_budget = st.sidebar.toggle("Enable budget envelope", value=True)
budget_per_task = st.sidebar.number_input("Budget per document ($)", 0.10, 10.00, 1.50, 0.10) if enable_budget else None

enable_cb = st.sidebar.toggle("Enable circuit breaker", value=True)
cb_threshold = st.sidebar.slider("Circuit breaker threshold (×)", 1.5, 10.0, 2.0, 0.5) if enable_cb else 2.0

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔁 Retry Behavior")
max_retries = st.sidebar.slider("Max retries on malformed doc", 1, 100, 50)
retry_appends = st.sidebar.toggle("Retries append history (context bloat)", value=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 💾 Caching")
enable_cache = st.sidebar.toggle("Enable prompt caching", value=False)


# ============================================================
# RUN SIMULATION
# ============================================================

corpus = create_corpus(num_docs, malformed_index)
spans, processed, skipped, bv, cb_trips = simulate_agent_run(
    corpus, use_tiered_routing, default_model,
    budget_per_task if enable_budget else None,
    enable_cb, cb_threshold, max_retries,
    retry_appends, enable_cache,
)
total_cost, total_calls, cpi, dpd, decision_count = compute_metrics(spans)


# ============================================================
# MAIN CONTENT
# ============================================================

st.markdown('<p class="main-header">💰 Chapter 14: What Gets Measured Gets Managed</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">FinOps, Observability, and the Dollar-per-Decision Metric — Interactive Demo</p>', unsafe_allow_html=True)

# --- Tabs ---
tab_dashboard, tab_scenario, tab_hdn, tab_exercise, tab_trace = st.tabs([
    "📊 Dashboard", "📈 Scenario Analysis", "🧠 Human Decision Nodes", "⚡ Exercise", "🔍 Trace Inspector"
])


# ============================================================
# TAB 1: DASHBOARD
# ============================================================

with tab_dashboard:
    st.markdown("### The Two Metrics That Tell Different Stories")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        card_class = "danger" if total_cost > 5 else "warning" if total_cost > 1 else "success"
        st.markdown(f"""
        <div class="metric-card {card_class}">
            <div class="metric-value">${total_cost:.2f}</div>
            <div class="metric-label">Total Cost</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">${cpi:.4f}</div>
            <div class="metric-label">Cost-per-Inference (WRONG metric)</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        dpd_class = "danger" if dpd > 1.0 else "warning" if dpd > 0.2 else "success"
        st.markdown(f"""
        <div class="metric-card {dpd_class}">
            <div class="metric-value">${dpd:.4f}</div>
            <div class="metric-label">Dollar-per-Decision (RIGHT metric)</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        ratio = dpd / cpi if cpi > 0 else 0
        st.markdown(f"""
        <div class="metric-card warning">
            <div class="metric-value">{ratio:.1f}×</div>
            <div class="metric-label">DpD / CPI Gap</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Summary stats
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Total LLM Calls", f"{total_calls:,}")
    col_b.metric("Documents Processed", f"{processed}/{num_docs}")
    col_c.metric("Documents Aborted", f"{skipped}", delta=f"-{bv} budget, -{cb_trips} circuit breaker" if (bv + cb_trips) > 0 else None)
    
    st.markdown("---")
    
    # Per-call cost timeline
    st.markdown("### Per-Call Cost Timeline")
    st.caption("Each point is one LLM call. Spikes = the malformed document retries. This is what span-level monitoring reveals.")
    
    df_spans = pd.DataFrame([{
        "call_index": i,
        "cost": s.cost_usd,
        "operation": s.operation,
        "model": MODEL_PRICING[s.model_tier]["name"],
        "doc_id": s.doc_id,
        "is_retry": s.is_retry,
        "retry_num": s.retry_number,
        "decision_bearing": "Decision" if s.decision_bearing else "Support",
        "input_tokens": s.input_tokens,
        "label": f"Doc {s.doc_id} | {s.operation}" + (f" (retry #{s.retry_number})" if s.is_retry else ""),
    } for i, s in enumerate(spans)])
    
    if not df_spans.empty:
        fig_timeline = px.scatter(
            df_spans, x="call_index", y="cost",
            color="is_retry",
            color_discrete_map={True: "#f5365c", False: "#667eea"},
            hover_data=["label", "model", "input_tokens", "decision_bearing"],
            labels={"call_index": "Call Sequence", "cost": "Cost (USD)", "is_retry": "Retry?"},
        )
        fig_timeline.update_layout(
            height=400,
            yaxis_title="Cost per Call ($)",
            xaxis_title="Call Index (chronological)",
            showlegend=True,
        )
        # Add CPI line
        fig_timeline.add_hline(y=cpi, line_dash="dash", line_color="orange",
                               annotation_text=f"CPI = ${cpi:.4f} (hides the spike)")
        st.plotly_chart(fig_timeline, use_container_width=True)
    
    # Per-document cost bar chart
    st.markdown("### Cost by Document")
    st.caption("One bar per document. The malformed document dominates Scenario 1 (no guardrails).")
    
    doc_costs = []
    for i in range(num_docs):
        dc = sum(s.cost_usd for s in spans if s.doc_id == i)
        call_count = sum(1 for s in spans if s.doc_id == i)
        is_mal = i == malformed_index
        doc_costs.append({"doc_id": i, "cost": dc, "calls": call_count, "malformed": is_mal})
    
    df_docs = pd.DataFrame(doc_costs)
    if not df_docs.empty:
        fig_docs = px.bar(
            df_docs, x="doc_id", y="cost",
            color="malformed",
            color_discrete_map={True: "#f5365c", False: "#667eea"},
            hover_data=["calls"],
            labels={"doc_id": "Document ID", "cost": "Total Cost ($)", "malformed": "Malformed?"},
        )
        fig_docs.update_layout(height=350, showlegend=True)
        st.plotly_chart(fig_docs, use_container_width=True)


# ============================================================
# TAB 2: SCENARIO ANALYSIS
# ============================================================

with tab_scenario:
    st.markdown("### Side-by-Side Scenario Comparison")
    st.markdown("Watch how each architectural component reduces cost and catches failures. All four scenarios run on the same corpus.")
    
    # Run all four scenarios
    @st.cache_data
    def run_all_scenarios(num_docs, malformed_index):
        corpus = create_corpus(num_docs, malformed_index)
        results = {}
        
        configs = {
            "1. No Guardrails": dict(use_tiered_routing=False, default_model="frontier",
                                      budget_per_task=None, circuit_breaker_enabled=False,
                                      cb_threshold=2.0, max_retries=50, retry_appends_history=True, enable_caching=False),
            "2. Budget Envelope": dict(use_tiered_routing=False, default_model="frontier",
                                        budget_per_task=1.50, circuit_breaker_enabled=False,
                                        cb_threshold=2.0, max_retries=50, retry_appends_history=True, enable_caching=False),
            "3. + Circuit Breaker": dict(use_tiered_routing=False, default_model="frontier",
                                          budget_per_task=1.50, circuit_breaker_enabled=True,
                                          cb_threshold=2.0, max_retries=50, retry_appends_history=True, enable_caching=False),
            "4. Full Pipeline": dict(use_tiered_routing=True, default_model="frontier",
                                      budget_per_task=1.50, circuit_breaker_enabled=True,
                                      cb_threshold=2.0, max_retries=50, retry_appends_history=True, enable_caching=True),
        }
        
        for name, cfg in configs.items():
            s, proc, skip, bv, cb = simulate_agent_run(corpus, **cfg)
            tc, calls, cpi_val, dpd_val, dc = compute_metrics(s)
            results[name] = {
                "Total Cost": tc, "Calls": calls, "CPI": cpi_val,
                "DpD": dpd_val, "Processed": proc, "Skipped": skip,
                "Budget Violations": bv, "CB Trips": cb,
            }
        
        return results
    
    scenario_results = run_all_scenarios(num_docs, malformed_index)
    
    # Comparison table
    df_comparison = pd.DataFrame(scenario_results).T
    df_comparison["Total Cost"] = df_comparison["Total Cost"].apply(lambda x: f"${x:.2f}")
    df_comparison["CPI"] = df_comparison["CPI"].apply(lambda x: f"${x:.4f}")
    df_comparison["DpD"] = df_comparison["DpD"].apply(lambda x: f"${x:.4f}")
    
    st.dataframe(df_comparison, use_container_width=True)
    
    # Visual comparison
    raw_results = run_all_scenarios(num_docs, malformed_index)
    names = list(raw_results.keys())
    
    fig_compare = make_subplots(rows=1, cols=2, subplot_titles=("Total Cost ($)", "CPI vs DpD"))
    
    fig_compare.add_trace(
        go.Bar(x=names, y=[raw_results[n]["Total Cost"] for n in names],
               marker_color=["#f5365c", "#fb6340", "#fbb140", "#2dce89"],
               name="Total Cost"),
        row=1, col=1
    )
    
    fig_compare.add_trace(
        go.Bar(x=names, y=[raw_results[n]["CPI"] for n in names],
               name="CPI (wrong)", marker_color="#667eea"),
        row=1, col=2
    )
    fig_compare.add_trace(
        go.Bar(x=names, y=[raw_results[n]["DpD"] for n in names],
               name="DpD (right)", marker_color="#f5365c"),
        row=1, col=2
    )
    
    fig_compare.update_layout(height=450, barmode="group", showlegend=True)
    st.plotly_chart(fig_compare, use_container_width=True)
    
    st.info("""
    **Key Insight:** Cost-per-inference (CPI) barely changes across scenarios — it always looks "reasonable." 
    Dollar-per-decision (DpD) tells the real story: Scenario 1 can be 10–50× more expensive per decision than Scenario 4.
    
    CPI says "each call is cheap." DpD says "each decision is worth the cost." Only one is the right question.
    """)


# ============================================================
# TAB 3: HUMAN DECISION NODES
# ============================================================

with tab_hdn:
    st.markdown("### 🧠 Mandatory Human Decision Nodes")
    st.markdown("Points where AI proposed an architectural choice that was rejected on principled grounds.")
    
    st.markdown("---")
    
    # HDN #1: Fixed vs Adaptive Threshold
    st.markdown("#### Human Decision Node #1: Fixed vs. Adaptive Circuit Breaker Threshold")
    
    st.markdown("""
    <div class="decision-node rejected">
        <strong>🤖 AI PROPOSAL:</strong> "Use a fixed cost-velocity circuit breaker threshold of 2.0× across all task types."<br><br>
        <strong>❌ REJECTED BECAUSE:</strong> A fixed threshold assumes all tasks have similar cost variance. They don't.
        A clause classification has tight variance (±15%), so 2.0× catches anomalies well. But a multi-document synthesis
        has wide variance (±30-40%) — a 2.0× threshold produces constant false alarms on legitimately complex documents.<br><br>
        <strong>✅ IMPLEMENTED INSTEAD:</strong> Per-task-type adaptive thresholds calibrated from the variance observed 
        during a calibration phase. Threshold = mean + (N × std_dev), where N is configurable per task type.
    </div>
    """, unsafe_allow_html=True)
    
    # Demonstrate with actual numbers
    st.markdown("**Why a fixed threshold fails — with real numbers:**")
    
    random.seed(42)
    task_samples = {
        "classify_clause": {"variance": 0.15, "base_in": 890, "base_out": 45},
        "synthesize_summary": {"variance": 0.30, "base_in": 3400, "base_out": 560},
        "format_output": {"variance": 0.10, "base_in": 400, "base_out": 200},
    }
    
    threshold_data = []
    for task, params in task_samples.items():
        costs = [compute_call_cost("frontier",
                                   int(params["base_in"] * (1 + random.uniform(-params["variance"], params["variance"]))),
                                   int(params["base_out"] * (1 + random.uniform(-params["variance"], params["variance"]))),
                                   0) for _ in range(50)]
        mean = statistics.mean(costs)
        std = statistics.stdev(costs)
        cv = std / mean
        fixed = mean * 2.0
        adaptive = mean + (3 * std)
        threshold_data.append({
            "Task": task,
            "Mean Cost": f"${mean:.5f}",
            "Std Dev": f"${std:.5f}",
            "CV (variance)": f"{cv:.1%}",
            "Fixed 2.0×": f"${fixed:.5f}",
            "Adaptive (mean+3σ)": f"${adaptive:.5f}",
        })
    
    st.dataframe(pd.DataFrame(threshold_data), use_container_width=True, hide_index=True)
    
    st.caption("CV = Coefficient of Variation. Higher CV = wider natural spread. The fixed threshold treats all tasks the same; the adaptive one respects each task's actual variance.")
    
    st.markdown("---")
    
    # HDN #2: LLM Self-Classification vs HITL
    st.markdown("#### Human Decision Node #2: LLM Self-Classification vs. HITL Calibration")
    
    st.markdown("""
    <div class="decision-node rejected">
        <strong>🤖 AI PROPOSAL:</strong> "Use the LLM to self-classify each call as decision-bearing or not, 
        via a classification prompt appended after each call."<br><br>
        <strong>❌ REJECTED BECAUSE:</strong> This adds an LLM call to classify every LLM call — you're spending 
        tokens to decide if the tokens you just spent were worth tracking. This violates the chapter's core principle:
        minimize non-decision-bearing LLM usage.<br><br>
        <strong>✅ IMPLEMENTED INSTEAD:</strong> Two-phase approach:<br>
        &nbsp;&nbsp;1. <strong>Design-time tagging</strong> for obvious cases (classify_clause = decision, format_output = support)<br>
        &nbsp;&nbsp;2. <strong>HITL calibration</strong> for ambiguous cases — a human reviews a sample during the calibration 
        phase, classifies them, and those labels become ground truth for production.
    </div>
    """, unsafe_allow_html=True)
    
    # Cost comparison
    st.markdown("**Cost of the AI's proposal at scale:**")
    
    self_classify_cost_per_call = compute_call_cost("lightweight", 200, 20)
    daily_docs = 10000
    calls_per_doc = len(TASK_GRAPH)
    daily_calls = daily_docs * calls_per_doc
    daily_self_cost = daily_calls * self_classify_cost_per_call
    monthly_self_cost = daily_self_cost * 30
    
    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        st.markdown("""
        <div class="metric-card danger">
            <div class="metric-value">${:.2f}/mo</div>
            <div class="metric-label">LLM Self-Classification (AI Proposal)</div>
        </div>
        """.format(monthly_self_cost), unsafe_allow_html=True)
    with col_sc2:
        st.markdown("""
        <div class="metric-card success">
            <div class="metric-value">$0.00/mo</div>
            <div class="metric-label">Design-time Tags + HITL Calibration</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.caption(f"Based on {daily_docs:,} documents/day × {calls_per_doc} calls/doc × ${self_classify_cost_per_call:.6f}/classification call × 30 days.")
    
    # HITL simulation
    st.markdown("---")
    st.markdown("#### Simulated HITL Calibration Interface")
    st.markdown("During the first 10 documents, these ambiguous spans were flagged for human review:")
    
    ambiguous_cases = [
        {"Operation": "clarify_term", "Current Tag": "support",
         "For Decision": "Clarification changes how the clause is classified",
         "Against": "It's a lookup — the classification call makes the actual decision",
         "Human Verdict": "✅ Confirmed as SUPPORT"},
        {"Operation": "plan_subtasks", "Current Tag": "decision",
         "For Decision": "Plan determines which clauses get processed",
         "Against": "For standard contracts, the plan is always the same",
         "Human Verdict": "⚠️ RECLASSIFIED: support for standard, decision for complex"},
        {"Operation": "flag_anomaly", "Current Tag": "decision",
         "For Decision": "Flagging triggers human lawyer review",
         "Against": "Could be rule-based for common anomaly patterns",
         "Human Verdict": "✅ Confirmed as DECISION"},
    ]
    
    st.dataframe(pd.DataFrame(ambiguous_cases), use_container_width=True, hide_index=True)
    st.caption("The human decides once during calibration. The system applies those labels forever. Zero per-call cost.")


# ============================================================
# TAB 4: EXERCISE
# ============================================================

with tab_exercise:
    st.markdown("### ⚡ Exercise: Trigger the Failure Yourself")
    
    st.markdown("""
    **The setup:** You have a working DpD pipeline with budget envelope, circuit breaker, and tiered model routing.
    
    **Your task:** Remove tiered model routing and observe what happens.
    
    **Use the sidebar** → turn OFF "Enable tiered model routing" → watch the dashboard update.
    """)
    
    st.markdown("---")
    
    # Run both scenarios for direct comparison
    corpus_ex = create_corpus(num_docs, malformed_index)
    
    spans_with, proc_w, skip_w, bv_w, cb_w = simulate_agent_run(
        corpus_ex, True, "frontier", 1.50, True, 2.0, 50, True, True)
    tc_w, calls_w, cpi_w, dpd_w, dc_w = compute_metrics(spans_with)
    
    spans_without, proc_wo, skip_wo, bv_wo, cb_wo = simulate_agent_run(
        corpus_ex, False, "frontier", 1.50, True, 2.0, 50, True, False)
    tc_wo, calls_wo, cpi_wo, dpd_wo, dc_wo = compute_metrics(spans_without)
    
    st.markdown("#### Direct Comparison: Routing ON vs. Routing OFF")
    
    col_ex1, col_ex2 = st.columns(2)
    
    with col_ex1:
        st.markdown("##### ✅ With Tiered Routing")
        st.metric("Total Cost", f"${tc_w:.4f}")
        st.metric("Cost-per-Inference", f"${cpi_w:.6f}")
        st.metric("Dollar-per-Decision", f"${dpd_w:.4f}")
        st.metric("Circuit Breaker Trips", cb_w)
        
        tier_w = {}
        for s in spans_with:
            tier_w[s.model_tier] = tier_w.get(s.model_tier, 0) + 1
        st.markdown("**Model usage:**")
        for t, c in sorted(tier_w.items()):
            st.markdown(f"- {MODEL_PRICING[t]['name']}: {c} calls")
    
    with col_ex2:
        st.markdown("##### ❌ Without Tiered Routing (ALL → Frontier)")
        st.metric("Total Cost", f"${tc_wo:.4f}", delta=f"+${tc_wo - tc_w:.4f}", delta_color="inverse")
        st.metric("Cost-per-Inference", f"${cpi_wo:.6f}", delta=f"+${cpi_wo - cpi_w:.6f}", delta_color="inverse")
        st.metric("Dollar-per-Decision", f"${dpd_wo:.4f}", delta=f"+${dpd_wo - dpd_w:.4f}", delta_color="inverse")
        st.metric("Circuit Breaker Trips", cb_wo)
        
        tier_wo = {}
        for s in spans_without:
            tier_wo[s.model_tier] = tier_wo.get(s.model_tier, 0) + 1
        st.markdown("**Model usage:**")
        for t, c in sorted(tier_wo.items()):
            st.markdown(f"- {MODEL_PRICING[t]['name']}: {c} calls")
    
    dpd_multiplier = dpd_wo / dpd_w if dpd_w > 0 else 0
    
    st.markdown("---")
    
    st.error(f"""
    **What happened:**
    - CPI changed from ${cpi_w:.6f} to ${cpi_wo:.6f} — looks similar, each call is individually "normal"
    - DpD jumped from ${dpd_w:.4f} to ${dpd_wo:.4f} — a **{dpd_multiplier:.1f}× increase**
    - Circuit breaker trips: {cb_wo} — it **never fires** because no single call is anomalous
    
    **The blind spot:** When every call goes through the frontier model, support calls (formatting, validation) 
    cost 60× more than they need to. But each call individually looks "normal" for a frontier model call. 
    The circuit breaker can't catch uniform overspend — only anomalous spikes.
    
    **DpD is the only metric that reveals this failure mode.**
    """)
    
    st.markdown("---")
    st.markdown("#### 🤔 Open Question")
    st.warning("""
    The routing optimization is: **route(t) = argmin C_m subject to Q_m(t) ≥ Q_min(t)**
    
    **Who sets Q_min(t)?**
    
    The engineer optimizing costs sets it as low as possible. The domain expert who understands 
    what a wrong decision costs would set it higher. These incentives are in direct tension.
    
    A DpD metric without a quality floor set by the right person will reliably be met by degrading 
    quality to its minimum acceptable threshold. **The quality floor is not a technical parameter — 
    it is a governance decision.**
    """)


# ============================================================
# TAB 5: TRACE INSPECTOR
# ============================================================

with tab_trace:
    st.markdown("### 🔍 Span-Level Trace Inspector")
    st.markdown("Explore individual spans — this is what observability at the span level looks like.")
    
    if spans:
        df_trace = pd.DataFrame([{
            "Span ID": s.span_id,
            "Doc ID": s.doc_id,
            "Operation": s.operation,
            "Model": MODEL_PRICING[s.model_tier]["name"].split("(")[0].strip(),
            "Input Tokens": s.input_tokens,
            "Output Tokens": s.output_tokens,
            "Cached Tokens": s.cached_tokens,
            "Cost ($)": round(s.cost_usd, 6),
            "Latency (ms)": s.latency_ms,
            "Decision?": "✅" if s.decision_bearing else "❌",
            "Retry?": f"#{s.retry_number}" if s.is_retry else "—",
        } for s in spans])
        
        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_doc = st.selectbox("Filter by document", ["All"] + [f"Doc {i}" for i in range(num_docs)])
        with col_f2:
            filter_op = st.selectbox("Filter by operation", ["All"] + list(set(s.operation for s in spans)))
        with col_f3:
            filter_decision = st.selectbox("Filter by type", ["All", "Decision-bearing only", "Support only"])
        
        filtered = df_trace.copy()
        if filter_doc != "All":
            doc_num = int(filter_doc.split(" ")[1])
            filtered = filtered[filtered["Doc ID"] == doc_num]
        if filter_op != "All":
            filtered = filtered[filtered["Operation"] == filter_op]
        if filter_decision == "Decision-bearing only":
            filtered = filtered[filtered["Decision?"] == "✅"]
        elif filter_decision == "Support only":
            filtered = filtered[filtered["Decision?"] == "❌"]
        
        st.dataframe(filtered, use_container_width=True, height=500, hide_index=True)
        
        st.markdown(f"**Showing {len(filtered)} of {len(df_trace)} spans**")
        
        if not filtered.empty:
            st.markdown("#### Cost Distribution by Operation")
            fig_ops = px.box(
                df_trace, x="Operation", y="Cost ($)", color="Decision?",
                color_discrete_map={"✅": "#667eea", "❌": "#adb5bd"},
            )
            fig_ops.update_layout(height=400)
            st.plotly_chart(fig_ops, use_container_width=True)
    else:
        st.warning("No spans recorded. Adjust the simulation parameters.")


# ============================================================
# FOOTER
# ============================================================

st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #888; font-size: 0.85rem;">
    <strong>Chapter 14: What Gets Measured Gets Managed</strong><br>
    Design of Agentic Systems with Case Studies — Prof. Nik Bear Brown<br>
    Dollar-per-Decision Interactive Demo | Abhinav Gangurde
</div>
""", unsafe_allow_html=True)
