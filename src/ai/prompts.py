"""All Claude prompts — centralised. JSON-only output required from all."""
from __future__ import annotations

BLOCK_ANALYZER_SYSTEM = """\
You are a senior software architect performing code evolution analysis.
You receive pre-grouped commits (draft groups) and real code diffs.
Your job: finalize grouping, name blocks, score each, assess architecture impact.
CRITICAL: Respond ONLY with valid JSON. No markdown, no explanation, no backticks.
"""

BLOCK_ANALYZER_USER = """\
Repository: {repo_name}
Stack: {stack}
Total commits: {total_commits}

Pre-grouped commit blocks (heuristic, you refine):
{draft_groups}

File tree at project start (first commit):
{file_tree_start}

File tree now (HEAD):
{file_tree_now}

Code diffs per draft group:
{block_diffs}

Respond with JSON:
{{
  "blocks": [
    {{
      "id": 1,
      "name": "Infrastructure Setup",
      "type": "infra | feat | fix | refactor | docs | test | maintenance | mixed",
      "commits": ["hash1", "hash2"],
      "commit_range": "hash1..hash3",
      "summary": "What changed and why it matters (2-3 sentences)",
      "quality_score": 6.5,
      "architecture_impact": "low | medium | high | breaking",
      "issues": ["Concrete issue"],
      "positive_signals": ["What this block did well"],
      "verdict": "One sentence: was this block necessary and well-executed?"
    }}
  ],
  "grouping_notes": "Notes on why you split or merged draft groups"
}}

Scoring: 9-10 clean, 7-8 minor issues, 5-6 functional problems, 3-4 problematic, 1-2 harmful
"""

ARCHITECTURE_AGENT_SYSTEM = """\
You are a senior software architect analysing codebase evolution.
Build an architecture timeline and detect structural drift.
CRITICAL: Respond ONLY with valid JSON. No markdown, no backticks.
"""

ARCHITECTURE_AGENT_USER = """\
Repository: {repo_name}
Stack: {stack}
Services: {services}

Semantic blocks:
{blocks_summary}

File tree at start:
{file_tree_start}

File tree at end:
{file_tree_end}

Respond with JSON:
{{
  "timeline": [
    {{
      "after_block": 1,
      "architecture_state": "Single-file script with no modules",
      "modules_exist": ["main.py"],
      "key_dependencies": [],
      "health": "healthy | degraded | broken"
    }}
  ],
  "drift": {{
    "detected": true,
    "original_intent": "Clean MVC structure started in block 1",
    "current_reality": "Business logic mixed into routes by block 4",
    "drift_started_at_block": 3,
    "description": "Concrete description of architectural drift"
  }},
  "architecture_verdict": {{
    "overall_health": "healthy | degraded | broken",
    "strongest_block": 1,
    "weakest_block": 3,
    "key_finding": "Most important architectural insight in 1-2 sentences"
  }}
}}
"""

DYNAMIC_ANALYZER_SYSTEM = """\
You are a senior engineer analysing impact of each development block on project quality.
CRITICAL: Respond ONLY with valid JSON. No markdown, no backticks.
"""

DYNAMIC_ANALYZER_USER = """\
Repository: {repo_name}
Stack: {stack}

Block quality scores (chronological):
{quality_curve}

Architecture timeline:
{arch_timeline}

Block summaries:
{block_summaries}

Code quality results:
{quality_results}

Respond with JSON:
{{
  "quality_curve": [
    {{"block_id": 1, "block_name": "Infrastructure", "score": 6.5, "trend": "baseline"}}
  ],
  "inflection_points": [
    {{
      "block_id": 3,
      "type": "degradation | improvement | recovery",
      "description": "What happened and why the curve changed",
      "impact": "How this affected subsequent blocks"
    }}
  ],
  "harmful_blocks": [
    {{
      "block_id": 4,
      "name": "Redis Cache",
      "reason": "Why this block hurt more than helped",
      "suggestion": "What should have been done differently"
    }}
  ],
  "best_blocks": [
    {{"block_id": 1, "name": "Infrastructure", "reason": "Why exemplary"}}
  ],
  "dynamics_summary": "2-3 sentences: the story of how quality evolved"
}}
"""

RELEASE_READINESS_SYSTEM = """\
You are a senior DevOps engineer assessing repository release readiness.
CRITICAL: Respond ONLY with valid JSON. No markdown, no backticks.
"""

RELEASE_READINESS_USER = """\
Repository: {repo_name}
Stack: {stack}
Framework: {framework}
Services: {services}

Architecture health: {arch_health}
Architecture drift: {arch_drift}
Dynamics summary: {dynamics_summary}

Block overview:
{blocks_overview}

Code quality:
{quality_results}

Environment & docs:
{env_summary}

Branch health:
{branch_summary}

Respond with JSON:
{{
  "score": 68,
  "status": "not_ready | needs_work | almost_ready | ready",
  "blockers": ["Critical issue that MUST be fixed before release"],
  "warnings": ["Important but non-blocking issue"],
  "recommendations": [
    {{
      "priority": "high | medium | low",
      "category": "testing | docs | ci_cd | architecture | security | environment | code_quality",
      "action": "Specific actionable step",
      "effort": "small | medium | large"
    }}
  ],
  "summary": "Executive summary: current state and what is needed (3-4 sentences)"
}}

Scoring: 0-40 not_ready, 41-60 needs_work, 61-80 almost_ready, 81-100 ready
"""