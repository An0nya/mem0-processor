#!/usr/bin/env python3
"""
Accuracy scorer for session 47b98ba9 summaries.

Ground truth facts:
1. Claude initially FAILED to find mem0 entry (said "Not in memory. Fresh ground.")
2. User had to CORRECT Claude by directing them to check mem0
3. Discussion DID exist in mem0 from April 2, 2:25am
4. Memory guardrail evolved to "context overhead calculation" (client-side), not discrete v7 item
5. Claude's memory was STALE vs CHANGELOG (v8/v9/v10 existed, items backlogged)
6. Final placement: v7.1 for timestamps, post-v10 for session grouping

Usage:
  python score-session-47b98ba9.py                  # auto-discover in summaries + archive
  python score-session-47b98ba9.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "47b98ba9"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    ('initial_not_found',    r'(not in memory|fresh ground|no prior discussion)'),
    ('user_correction',      r'(user.*check mem0|user.*directed|user.*pointed.*mem0|check mem0)'),
    ('found_in_mem0',        r'(found.*mem0|mem0.*found|april 2|2:25)'),
    ('guardrail_evolution',  r'(memory guardrail|context overhead)'),
    ('stale_memory',         r'(stale|outdated|divergen)'),
    ('v8_v9_v10_structure',  r'(v8|v9|v10)'),
]

CHECK_LABELS = [
    'Col 1: Initial error    Col 2: User correction',
    'Col 3: Found in mem0    Col 4: Guardrail evolution',
    'Col 5: Stale memory     Col 6: v8/v9/v10 structure',
]


def score_summary(content):
    """Score a summary on 6 key facts.

    Returns dict:
      score_norm  float 0–1, higher=better
      score_raw   int 0–6
      score_max   6.0
      checks      {name: bool} one entry per fact
      extra       {} (unused for this session)
    """
    checks = {}
    score = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, content, re.I))
        checks[name] = hit
        if hit:
            score += 1

    return {
        'score_norm': score / 6.0,
        'score_raw':  float(score),
        'score_max':  6.0,
        'checks':     checks,
        'extra':      {},
    }


def discover_files():
    results = []

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID}--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID}*.txt"):
            model = f.parent.name
            timestamp_match = re.search(rf'{SESSION_ID}--(.+)$', f.stem)
            timestamp = timestamp_match.group(1) if timestamp_match else ''
            label = f"{model}  [{timestamp}]" if timestamp else model
            results.append((f, label))

    return results


def main():
    if len(sys.argv) > 1:
        files = [(Path(p), Path(p).stem) for p in sys.argv[1:]]
    else:
        files = discover_files()

    if not files:
        print(f"No summary files found for session {SESSION_ID}.")
        return

    scores = []
    for filepath, label in sorted(files, key=lambda x: str(x[0])):
        try:
            content = filepath.read_text()
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

        if 'TRANSCRIPT FORMAT' in content[:200]:
            continue
        if len(content) < 500:
            continue

        result = score_summary(content)
        scores.append((result['score_raw'], label, result['checks']))

    scores.sort(reverse=True)

    print("=== ACCURACY SCORES ===\n")
    for score_raw, model, checks in scores:
        check_str = ' '.join('✓' if v else '✗' for v in checks.values())
        print(f"{int(score_raw)}/6  {check_str}  {model}")

    print("\n=== LEGEND ===")
    for line in CHECK_LABELS:
        print(line)

    print(f"\n=== SUMMARY ({len(scores)} files) ===")
    print(f"Perfect (6/6): {sum(1 for s, _, _ in scores if s == 6)}")
    print(f"Strong  (5/6): {sum(1 for s, _, _ in scores if s == 5)}")
    print(f"Good    (4/6): {sum(1 for s, _, _ in scores if s == 4)}")
    print(f"Poor   (≤3/6): {sum(1 for s, _, _ in scores if s <= 3)}")


if __name__ == '__main__':
    main()
