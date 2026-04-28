#!/usr/bin/env python3
"""
Accuracy scorer for session 5024455a summaries.

Ground truth facts:
1. Script still had the v6 SUMMARIZATION_PROMPT (flat bullet-list format), not v7
   — the v7 swap had been documented in the handoff notes but never executed
2. User self-identified the omission ("classic me error") — Claude confirmed by
   reading the script, not by catching anything independently
3. User denied the initial git bash call (TOOL_DENIED), then resumed with "continue"
   after checking for spacing issues in the prompt (found none, proceeded)
4. v7 prompt structure: sectioned narrative (Goal / What Happened & Why /
   Competence Signals / Mistakes / Decisions / Open Threads) vs v6 bullet list
5. Commit message explained both what changed (prompt format) and why
   (standalone analytical vs atomic decomposition)

Usage:
  python score-session-5024455a.py                  # auto-discover in summaries + archive
  python score-session-5024455a.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "5024455a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. v6 prompt still in script (bullet list, not v7 sections)
    ('v6_prompt_present',
     r'(v6.{0,20}prompt'
     r'|prompt.{0,20}v6'
     r'|still.{0,20}(on|using).{0,20}v6'
     r'|old.{0,20}prompt'
     r'|bullet.{0,20}(list|format)'
     r'|flat.{0,20}format'
     r'|never.{0,20}(swapped|replaced|updated).{0,20}prompt'
     r'|prompt.{0,20}(not|never).{0,20}(updated|replaced|swapped))'),

    # 2. User self-caught the omission — Claude confirmed, didn't discover
    ('user_self_caught',
     r'(user.{0,40}(self|own|themselves|classic|acknowledged|identified|caught)'
     r'|classic.{0,20}(me|my).{0,20}error'
     r'|user.{0,30}(forgot|missed|omitted).{0,30}(prompt|swap|step)'
     r'|user.{0,20}noticed.{0,20}(own|their)'
     r'|user.{0,30}(caught|identified).{0,30}miss)'),

    # 3. TOOL_DENIED on git bash — user paused to check spacing then resumed
    ('tool_denied_git',
     r'(tool.denied|denied.{0,20}(git|bash|command)'
     r'|user.{0,30}(denied|rejected|interrupted).{0,30}(git|bash|commit)'
     r'|user.{0,30}(paused|interrupted).{0,30}(spacing|extra)'
     r'|spacing.{0,30}(check|concern|look)'
     r'|interrupted.{0,20}git)'),

    # 4. v7 prompt format described (sectioned narrative, specific headers)
    ('v7_prompt_format',
     r'(sectioned.{0,20}(narrative|format)'
     r'|narrative.{0,20}format'
     r'|standalone.{0,20}(analytical|readable|summar)'
     r'|what.happened.{0,20}why'
     r'|competence.signal'
     r'|open.thread[s]?'
     r'|v7.{0,20}(section|format|structure|narrative))'),

    # 5. Commit explained what and why
    ('commit_quality',
     r'(commit.{0,40}(explain|what|why|clear|good|detailed)'
     r'|commit.{0,30}(message|description).{0,30}(explain|includes)'
     r'|why.{0,20}(changed|swapped|replaced).{0,20}(commit|noted)'
     r'|commit.{0,20}(rationale|reason|context))'),
]

CHECK_LABELS = [
    'Col 1: v6 prompt still in script    Col 2: User self-caught omission',
    'Col 3: TOOL_DENIED on git bash      Col 4: v7 prompt format described',
    'Col 5: Commit explained what & why',
]


def score_summary(content):
    checks = {}
    score = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, content, re.I))
        checks[name] = hit
        if hit:
            score += 1

    return {
        'score_norm': score / len(CHECKS_DEF),
        'score_raw':  float(score),
        'score_max':  float(len(CHECKS_DEF)),
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

    max_score = len(CHECKS_DEF)
    print("=== ACCURACY SCORES ===\n")
    for score_raw, model, checks in scores:
        check_str = ' '.join('✓' if v else '✗' for v in checks.values())
        print(f"{int(score_raw)}/{max_score}  {check_str}  {model}")

    print("\n=== LEGEND ===")
    for line in CHECK_LABELS:
        print(line)

    print(f"\n=== SUMMARY ({len(scores)} files) ===")
    print(f"Perfect ({max_score}/{max_score}): {sum(1 for s, _, _ in scores if s == max_score)}")
    print(f"Strong  ({max_score-1}/{max_score}): {sum(1 for s, _, _ in scores if s == max_score - 1)}")
    print(f"Good    ({max_score-2}/{max_score}): {sum(1 for s, _, _ in scores if s == max_score - 2)}")
    print(f"Poor   (≤{max_score-3}/{max_score}): {sum(1 for s, _, _ in scores if s <= max_score - 3)}")


if __name__ == '__main__':
    main()
