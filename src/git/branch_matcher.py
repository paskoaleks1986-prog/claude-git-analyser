"""Branch matcher — structural block comparison between parent and child branches.

For each block in a child branch (preprod, dev), determines whether a
structurally equivalent block exists in the parent branch (prod, main).

Matching is file-based, not name-based:
  - collect the set of files touched in each block
  - two blocks match if their touched-file sets overlap >= MATCH_THRESHOLD
  - env-specific files (settings_prod, .env.prod, etc.) are ignored
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Files that differ legitimately between branches — ignore when comparing
_ENV_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"settings_\w+",
        r"\.env(\.\w+)?$",
        r"config[\\/]\w*(prod|dev|staging|preprod)\w*",
        r"docker-compose\.\w+\.ya?ml",
        r"\.?nginx\.\w+\.conf",
    ]
]

# Fraction of overlapping files required to call two blocks "matched"
_MATCH_THRESHOLD = 0.35

# Valid commit hash: 7–40 hex chars (short or full SHA)
_HASH_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def _is_valid_hash(h: str) -> bool:
    return bool(h and _HASH_RE.match(h))


def _is_env_file(path: str) -> bool:
    return any(p.search(path) for p in _ENV_PATTERNS)


def _block_files(block: dict) -> set[str]:
    """Extract touched file paths from a block, filtering env-specific files."""
    files: set[str] = set()
    for entry in block.get("files_touched", []):
        if isinstance(entry, str) and not _is_env_file(entry):
            files.add(entry)
    return files


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


@dataclass
class BlockMatch:
    child_block_id: int
    child_block_name: str
    matched: bool
    parent_block_id: int | None = None
    parent_block_name: str | None = None
    similarity: float = 0.0
    reason: str = ""


@dataclass
class BranchMatchResult:
    child_branch: str
    parent_branch: str
    block_matches: list[BlockMatch] = field(default_factory=list)
    matched_count: int = 0
    total_count: int = 0

    @property
    def match_rate(self) -> float:
        if not self.total_count:
            return 0.0
        return self.matched_count / self.total_count

    def as_ref_dict(self) -> dict[int, bool]:
        """Dict suitable for terminal.print_blocks(match_ref=...)."""
        return {m.child_block_id: m.matched for m in self.block_matches}


def match_blocks(
    parent_blocks: list[dict],
    child_blocks: list[dict],
    child_branch: str,
    parent_branch: str,
) -> BranchMatchResult:
    """
    Compare child branch blocks against parent branch blocks.

    Strategy:
    1. Build file sets for every parent block.
    2. For each child block, find the best-matching parent block by Jaccard similarity.
    3. If similarity >= _MATCH_THRESHOLD → matched.
    4. Fallback: if both blocks have no file data, match by commit hash overlap.
    """
    result = BranchMatchResult(
        child_branch=child_branch,
        parent_branch=parent_branch,
        total_count=len(child_blocks),
    )

    parent_file_sets = [
        (b.get("id"), b.get("name", ""), _block_files(b), set(b.get("commits", [])))
        for b in parent_blocks
    ]

    for cb in child_blocks:
        child_id     = cb.get("id")
        child_name   = cb.get("name", "")
        child_files  = _block_files(cb)
        child_hashes = set(cb.get("commits", []))

        best_sim   = 0.0
        best_pid   = None
        best_pname = ""

        for pid, pname, pfiles, phashes in parent_file_sets:
            if child_files or pfiles:
                sim = _jaccard(child_files, pfiles)
            else:
                # fallback: commit hash overlap (cherry-pick scenario)
                sim = _jaccard(child_hashes, phashes)

            if sim > best_sim:
                best_sim   = sim
                best_pid   = pid
                best_pname = pname

        matched = best_sim >= _MATCH_THRESHOLD
        reason  = (
            f"similarity {best_sim:.0%} with parent block {best_pid} ({best_pname})"
            if matched
            else (
                f"best similarity {best_sim:.0%} — below threshold {_MATCH_THRESHOLD:.0%}"
                if best_pid is not None
                else "no file data available for comparison"
            )
        )

        bm = BlockMatch(
            child_block_id=child_id,
            child_block_name=child_name,
            matched=matched,
            parent_block_id=best_pid if matched else None,
            parent_block_name=best_pname if matched else None,
            similarity=round(best_sim, 3),
            reason=reason,
        )
        result.block_matches.append(bm)
        if matched:
            result.matched_count += 1

    return result


def enrich_block_data_with_files(
    block_data: dict,
    repo,
    stack,
) -> dict:
    """
    Enrich each block with files_touched list by running git diff --name-only
    between first and last commit of the block.

    Modifies block_data["blocks"] in place, returns the same dict.
    """
    source_exts = set(stack.source_extensions or [])
    blocks = block_data.get("blocks", [])

    for block in blocks:
        commits = block.get("commits", [])
        block.setdefault("files_touched", [])

        if not commits:
            continue

        first_h = commits[0]
        last_h  = commits[-1]

        # Validate hashes before passing to git — guards against malformed
        # LLM output that could carry git option-like strings (e.g. --option)
        if not (_is_valid_hash(first_h) and _is_valid_hash(last_h)):
            continue

        try:
            result = repo._run([
                "git", "diff", "--name-only",
                f"{first_h}^", last_h,
            ])
            files = [
                f for f in (
                    Path(line.strip())
                    for line in result.stdout.strip().splitlines()
                    if line.strip()
                )
                if not source_exts or f.suffix.lower() in source_exts
            ]
            block["files_touched"] = [str(f) for f in files]
        except Exception:
            # best-effort enrichment — leave files_touched as []
            pass

    return block_data
