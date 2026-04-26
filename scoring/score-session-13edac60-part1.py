#!/usr/bin/env python3
"""
Accuracy scorer for session 13edac60-part1 summaries.

Session context: post-compaction continuation; user and Claude discuss roadmap
ordering for v8/v9/v10, update CHANGELOG.md, discover undocumented hotfixes via
git diff, and commit before the next compact.

Ground truth facts:
1. Claude proactively recommended swapping v8 and v9 in the roadmap — putting
   programmatic model launch first, benchmarking second. This was wrong.
2. User pushed back specifically because v8 provides prerequisites for v9: the
   stateful registry and runtime stats are needed to safely set launch parameters
   (context size, RAM headroom). Not "simpler," but structurally dependent.
3. Claude explicitly conceded: "I was wrong to suggest the swap."
4. User then partially reversed their own correction — acknowledged the swap had
   merit priority-wise ("you're not wrong to suggest the reorder"), but still
   chose v8 first for simplicity. Three-step dynamic: wrong → correction → partial
   walkback.
5. TOOL_DENIED on a changelog edit: Claude wrote the v9 pre-launch monitoring note
   without including swap and memory pressure. User denied specifically to add those
   ("swap and memory pressure should be sampled pre-model-launch as well").
6. The phrase "overwhelm vs. orient" originated from Claude, applied to the open
   question of whether cross-session context injection helps or hurts analysis focus.
   User explicitly credited it: "great phrasing there by the way."

Usage:
  python score-session-13edac60-part1.py                  # auto-discover
  python score-session-13edac60-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "13edac60-part1"
SESSION_ID_BARE = "13edac60"
PART            = "part1"
SUMMARIES_DIR   = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR     = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Claude recommended swapping v8 and v9 (wrong call)
    ('v8_v9_swap_wrong',
     r'(swap.*v8.*v9'
     r'|v8.*v9.*swap'
     r'|claude.*suggest.*swap'
     r'|claude.*recommend.*swap'
     r'|wrong.*swap'
     r'|swap.*wrong'
     r'|v9.*before.*v8.*claude'
     r'|reorder.*v8.*v9'
     r'|claude.*reorder.*wrong)'),

    # 2. User's pushback was specifically about v8 prerequisites for v9
    ('user_prereq_pushback',
     r'(prerequisite'
     r'|prereq'
     r'|data.inform.*launch'
     r'|launch.*param.*need.*v8'
     r'|v8.*before.*v9.*because'
     r'|registry.*before.*launch'
     r'|runtime.*stat.*before.*launch'
     r'|user.*correct.*swap.*because'
     r'|v8.*provides.*v9'
     r'|needed.*safely.*launch)'),

    # 3. Claude explicitly conceded the swap suggestion was wrong
    ('claude_concedes',
     r'(i was wrong'
     r'|wrong to suggest'
     r'|claude.*concede'
     r'|conceded.*swap'
     r'|acknowledged.*wrong'
     r'|admitted.*wrong.*swap'
     r'|claude.*wrong.*v8.*v9)'),

    # 4. User partially walked back their own correction
    ('user_partial_reversal',
     r'(not wrong.*reorder'
     r'|you.re not wrong'
     r'|user.*reconsidered'
     r'|user.*walked.*back'
     r'|partial.*reversal'
     r'|user.*ambivalent'
     r'|merit.*swap'
     r'|priority.*bigger.*impact'
     r'|user.*acknowledged.*merit'
     r'|user.*partially.*reversed'
     r'|user.*still.*v8.*first.*but)'),

    # 5. TOOL_DENIED because Claude omitted swap + memory pressure from pre-launch note
    ('tool_denied_swap_pressure',
     r'(tool.denied.{0,60}(swap|pressure)'
     r'|denied.{0,40}(swap|pressure)'
     r'|(swap|pressure).{0,40}(missing|omit|not.*includ).{0,40}(denied|rejected)'
     r'|user.*denied.*changelog.{0,40}(swap|pressure)'
     r'|denied.*pre.launch'
     r'|denied.*pre.load'
     r'|user.*denied.*because.{0,40}(swap|pressure)'
     r'|user.*specified.*swap.*pressure)'),

    # 6. "overwhelm vs. orient" originated from Claude; user credited the phrase
    ('overwhelm_vs_orient_claude',
     r'(overwhelm.{0,10}vs.{0,10}orient'
     r'|orient.{0,10}vs.{0,10}overwhelm'
     r'|overwhelm.*orient'
     r'|orient.*overwhelm'
     r'|great.phrasing'
     r'|user.*credited.*claude.*phrase'
     r'|claude.*coined.*phrase'
     r'|user.*praised.*phrase'
     r'|claude.*originated.*phrase'
     r'|user.*complimented.*phrasing)'),
]

CHECK_LABELS = [
    'Col 1: Claude wrongly recommended v8/v9 swap',
    'Col 2: User pushed back on prerequisites (v8 needed before v9)',
    'Col 3: Claude explicitly conceded ("I was wrong")',
    'Col 4: User partially reversed their own correction',
    'Col 5: TOOL_DENIED — Claude omitted swap+pressure from pre-launch note',
    'Col 6: "overwhelm vs. orient" originated from Claude; user credited it',
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

    for f in SUMMARIES_DIR.glob(f"*{PART}*{SESSION_ID_BARE}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{PART}*{SESSION_ID_BARE}*.txt"):
            model = f.parent.name
            timestamp_match = re.search(rf'{SESSION_ID_BARE}--(.+)$', f.stem)
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
        print(f"No summary files found for session {SESSION_ID} {PART}.")
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
