#!/usr/bin/env python3
"""
Accuracy scorer for session 14ea1072 summaries.

Ground truth facts (interaction-dynamics focus):
1. Claude's first memory write was imprecise — framed the RAM bug as "14 GB is when
   LM Studio starts acting funky." User corrected: it's not a crash, it's an internal
   LM Studio error that surfaces through the API as "fetch failed"; root cause unknown.
2. Claude tried the wrong LM Studio log path first (TOOL_ERROR: directory does not
   exist), then had to search for the actual path structure before finding the logs.
3. Claude proactively caught that existing state files used the prefix
   "mem0_upload_state--" which wouldn't match the new slug-based filename format;
   user had not noticed — Claude flagged and fixed it.
4. Claude intentionally left mem0_state in root with a "fresh start" framing — user
   pushed back ("there are a few relevant state files in there"); Claude was wrong
   to assume.
5. avg RAM is still trustworthy even when peak is contaminated by bleed from a prior
   failed inference — this distinction was noted from the output data, not user-stated.
6. The directory consolidation (mem0_* → ~/.claude/mem0/) was committed in-session
   as a standalone refactor commit (9f6da86), not deferred.

Usage:
  python score-session-14ea1072.py                  # auto-discover in summaries + archive
  python score-session-14ea1072.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "14ea1072"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Claude's first memory note was imprecise; user corrected the framing
    ('memory_note_imprecise',
     r'(imprecise|initial.*memory.*wrong|memory.*incorrect|first.*note.*wrong'
     r'|user.*corrected.*memory|acting.funky|14.gb.*funky|not.*crash'
     r'|fetch.failed.*not.*crash|not.a.crash|lmstudio.*log.*error'
     r'|user.*clarified.*ram|clarified.*not.*crash)'),

    # 2. Claude tried wrong log path first (TOOL_ERROR)
    ('log_path_miss',
     r'(wrong.*log.*path|log.*path.*wrong|path.*not.*exist|directory.*not.*exist'
     r'|tool.*error.*log|tool.*error.*path|log.*path.*error|path.*error.*log'
     r'|lmstudio.*log.*not.*found|log.*search|had.to.search.*log)'),

    # 3. Claude caught state filename prefix mismatch proactively
    ('prefix_claude_caught',
     r'(prefix.*claude|claude.*caught.*prefix|claude.*flag.*prefix'
     r'|mem0_upload_state--|prefix.*strip|strip.*prefix|slug.*format'
     r'|proactive.*prefix|prefix.*mismatch|filename.*mismatch|claude.*noticed.*prefix)'),

    # 4. Claude wrong to leave mem0_state in root; user corrected
    ('mem0_state_assumption',
     r'(intentionally.*left|left.*root|assumed.*fresh|fresh.*start.*wrong'
     r'|mem0_state.*root|root.*mem0_state|user.*pushed.back.*state'
     r'|state.*not.*empty|relevant.*state.*file|wrong.*assume|assumption.*wrong)'),

    # 5. avg RAM trustworthy even when peak is contaminated
    ('avg_trustworthy',
     r'(avg.*trust|avg.*reliable|avg.*still.*valid|avg.*accurate'
     r'|peak.*contaminat|contaminat.*peak|avg.*not.*affected'
     r'|avg.*okay|avg.*fine.*peak|peak.*bleed.*avg)'),

    # 6. Restructure committed in-session (not deferred)
    ('commit_in_session',
     r'(9f6da86|refactor.*commit|commit.*refactor|commit.*in.session'
     r'|committed.*in.session|consolidat.*commit|mem0.*path.*commit'
     r'|commit.*path.*consolidat|directory.*commit|dir.*restructure.*commit)'),
]

CHECK_LABELS = [
    'Col 1: Claude first memory note imprecise; user corrected',
    'Col 2: Wrong LM Studio log path tried first (TOOL_ERROR)',
    'Col 3: Claude proactively caught state filename prefix mismatch',
    'Col 4: Claude wrong to leave mem0_state in root; user corrected',
    'Col 5: avg RAM trustworthy even when peak is contaminated',
    'Col 6: Dir restructure committed in-session (not deferred)',
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
