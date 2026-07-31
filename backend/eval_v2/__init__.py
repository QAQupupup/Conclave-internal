"""Conclave Eval V2 - Multi-level, LLM-as-Judge based evaluation framework.

Architecture (5-level scoring):
    L0 System Health    - SUT reachability, auth, basic connectivity (0% weight, gates all)
    L1 Process Integrity- API correctness, artifact existence, no errors (20% weight)
    L2 Internal Quality - JSON structure, schema compliance, stage completeness (20% weight)
    L3 Semantic Quality - LLM-as-Judge across 5 dimensions (45% weight)
    L4 Comparative      - Reference baseline comparison, ablation (15% weight)

Usage:
    python -m eval_v2.run --mode standard --pass-k 3
    python -m eval_v2.run --mode full --html-report --vault-export
    python -m eval_v2.run --service-check
    python -m eval_v2.run --compare latest --html-report
"""

__version__ = "2.0.0"
