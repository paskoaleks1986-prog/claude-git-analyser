# I built a tool that analyzes not your code — but how your code evolved

Most code review tools answer: *"What's wrong with your repo right now?"*

I wanted to answer a different question: *"How did this project grow over time, and was each step intentional?"*

That's `claude-check-repo` — an AI-powered git history analyzer built with Claude.

---

## The problem I kept running into

I use Claude heavily for coding. It writes commits, generates READMEs, builds entire modules. The output is often impressive. But when I came back to a project weeks later, I had no easy way to understand:

- Which commits actually mattered
- Whether the architecture held up over time
- Which branches were dead weight
- Whether the repo was anywhere close to production-ready

Static linters tell you about today. `git log` gives you a wall of text. Neither tells you the *story* of the project.

---

## What the tool actually does

**1. Commit Evolution Analysis (via Claude)**

The tool takes your full commit history — hash, message, stats — and asks Claude to group commits into development phases:

```
Phase 1: Architecture  (commits 1–3)  score: 8.5/10
Phase 2: Features      (commits 4–8)  score: 7.2/10
Phase 3: Stabilization (commits 9–11) score: 9.0/10
```

For each commit, Claude evaluates:
- Was this commit *necessary*, or does it duplicate previous work?
- What type is it (`feat`, `fix`, `refactor`, `chore`)?
- What issues does it introduce (unclear message, missing tests, mixed concerns)?

**2. Architecture Drift Detection**

Claude compares the file structure from commit 1–3 against the current state. Did the initial design hold up? Or did the architecture silently drift into something unrecognizable? This is the feature I'm most excited about — I've never seen another tool do this.

**3. Branch Health Analysis** (pure git, no API)

```
● main          → keep
● feature/auth  → active, 3 unmerged commits
● old-payment   → stale 47 days, recommend: delete
```

**4. Code Quality** (local tools)

Runs `ruff` and `pytest --cov` against the repo. No surprises — just clear pass/fail with top issues.

**5. Release Readiness Score**

Aggregates everything into a 0–100 score with specific blockers:

```
Score: 62/100 — ALMOST READY

Blockers:
  ✗ No CI/CD pipeline
  ✗ requirements.txt missing

Recommendations:
  [HIGH] ci_cd — Add GitHub Actions workflow
  [HIGH] environment — Add requirements.txt or pyproject.toml
  [MEDIUM] testing — Measure coverage (currently unknown)
```

---

## Architecture decisions worth sharing

**Claude only gets metadata, not full code.**

The key insight: you don't need to send entire diffs to Claude. A line like:

```
4. e808e8e | 2024-01-05 | "add config module" | files:2 +45 -5
```

...gives Claude everything it needs to analyze commit intent, necessity, and phase. Token usage stays lean. Analysis stays sharp.

**Two Claude calls for the entire pipeline.**

1. Commit evolution analysis
2. Release readiness summary

Everything else — branches, linting, test runs, file scanning — is pure Python + subprocess. No unnecessary API calls.

**Sequential agents, not parallel.**

Simple orchestrator passes data downstream:

```
repo_scan → branch_agent → commit_agent(Claude) → quality_agent → release_agent(Claude) → reporter
```

Each stage enriches the context for the next. Release agent gets the full picture — branch health, commit quality, test results, documentation gaps — and produces a grounded assessment.

---

## Output

Terminal (Rich) + YAML file:

```yaml
commit_evolution:
  phases:
    - name: architecture
      quality_score: 8.5
      summary: "Initial project setup and module structure"
  commits:
    - hash: e808e8e
      ai_analysis:
        type: feat
        necessary: true
        issues: ["Missing input validation — has TODO comment"]
        quality_score: 6.5

release_readiness:
  score: 62
  status: almost_ready
  blockers:
    - "No CI/CD pipeline"
```

---

## Why this matters

Most AI coding tools focus on the present: autocomplete, code generation, PR review.

`claude-check-repo` focuses on the *history* — treating a git log as a narrative that can be analyzed, scored, and improved.

When Claude generates code and writes commits autonomously, you need a tool that can review the *evolution*, not just the snapshot. This is that tool.

---

## Quick start

```bash
git clone https://github.com/your-handle/claude-check-repo
cd claude-check-repo
pip install -e .
export ANTHROPIC_API_KEY=your_key
claude-check-repo ./your-project
```

---

Built with Python, Claude API, Rich, and a strong belief that commit history is underrated data.

Happy to hear what you'd add — architecture drift detection, multi-repo comparison, PR readiness score?

#AI #Python #DevTools #Claude #GitAnalysis #OpenSource #CodeReview