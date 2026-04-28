#!/usr/bin/env python3
"""
Accuracy scorer for session 13edac60-part0 summaries.

Session context: status-check session; user asks for a top-level audit of
mem0-processor v7.3, asks Claude to pull bug reports from mem0, check memories
and changelog, and discuss next steps for bugs + v8/v9/v10 roadmap.
Session ends with user asking for a pre-compact bug-fix tally; no fixes are
implemented.

Ground truth facts:
1. The project_mem0processor_repo.md memory file carried a "16 days old"
   staleness warning in the TOOL_AUTO system-reminder. Claude read it and used
   it without flagging the stale-data risk — the warning was present and visible
   in the tool output.
2. The session counter shows "Session 22 of 51" on the first Phase-3 unit
   because Phase 1 noise/no_content skips push ~21 entries to runStats before
   Phase 3 begins. The numerator (runStats.length + 1) and denominator
   (processUnits.length) measure different populations: Phase 1+3 output vs
   Phase 2 output only.
3. Already-done ("Skipping past") sessions are invisible to the final tally
   entirely — they push to neither runStats nor transcriptRecords, so they
   don't appear in the final summary count at all. This is distinct from noise/
   no_content skips, which DO push to runStats and do appear in the final count.
4. Bug 3 (token artifact in compaction cache) was user-classified in this session
   as a likely one-time gemma model template quirk, not a systemic issue. User
   explicitly wanted to note it without stripping data, and stated a preference
   to preserve incoming data even if malformed, until the pipeline is stable.
5. The v9 urgency argument — that compaction-boundary session slicing already
   fits most sessions within 32k tokens, making right-sizing urgent — was stated
   by the USER in the opening message. Claude endorsed it ("v9 urgency argument
   is solid") but did not originate the insight. Attribution matters for
   distinguishing user-driven roadmap priorities from Claude recommendations.
6. The Glob({"pattern": "**/*.md"}) call returned a result set dominated by
   node_modules markdown files rather than project documentation. The glob was
   unscoped and produced noise; Claude did not use the results and pivoted to a
   direct Read of CHANGELOG.md.

Usage:
  python score-session-13edac60-part0.py                  # auto-discover
  python score-session-13edac60-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "13edac60-part0"
SESSION_ID_BARE = "13edac60"
PART            = "part0"
SUMMARIES_DIR   = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR     = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. 16-day-old memory warning was visible; Claude relied on it without flagging
    ('stale_memory_16_days',
     r'(16.day'
     r'|16.*days.*old'
     r'|memory.*16.*day'
     r'|stale.*memory.*file'
     r'|stale.*memory.*16'
     r'|memory.*stale.*16'
     r'|point.in.time.*16'
     r'|16.*day.*stale'
     r'|weeks.*old.*memory'
     r'|memory.*weeks.*old)'),

    # 2. Counter = 22 because Phase 1 noise/no_content pushes 21 runStats entries
    #    before Phase 3 starts; numerator and denominator are different populations
    ('counter_phase1_runstats_mismatch',
     r'(phase.1.*push.*runstats'
     r'|runstats.*phase.1.*push'
     r'|noise.*push.*runstats'
     r'|runstats.*noise.*push'
     r'|phase.1.*runstats.*before.*phase.3'
     r'|runstats.*already.*21'
     r'|21.*entries.*runstats'
     r'|21.*phase.1.*noise'
     r'|noise.*21.*runstats'
     r'|different.*population.*counter'
     r'|counter.*different.*population'
     r'|mixed.*population.*runstats'
     r'|numerator.*denominator.*different.*population'
     r'|phase.1.*skips.*runstats.*phase.3'
     r'|numerator.*mixed.*phase'
     r'|denominator.*phase.?2.*numerator'
     r'|phase.1.*noise.*numerator'
     r'|runstats.*length.*phase.1'
     r'|phase.1.*runstats.*length'
     r'|phase.1.*skips.*numerator'
     r'|counting.*phase.1.*noise.*numerator)'),

    # 3. Already-done sessions are invisible to the final tally (no runStats push at all)
    ('already_done_invisible_to_tally',
     r'(already.done.*not.*tally'
     r'|already.done.*invisible'
     r'|invisible.*final.*tally'
     r'|tally.*already.done.*miss'
     r'|already.done.*no.*runstats'
     r'|already.done.*push.*runstats'
     r'|already.done.*don.t.*push'
     r'|skipping.past.*not.*counted'
     r'|already.done.*final.*count.*absent'
     r'|already.done.*not.*appear.*final'
     r'|not.*appear.*tally.*already'
     r'|already.done.*excluded.*tally'
     r'|skipping.past.*no.*runstats'
     r'|already.done.*absent.*summary'
     r'|already.done.*not.*push.*runstats'
     r'|skipping.past.*runstats.*push'
     r'|no.*runstats.*push.*already)'),

    # 4. Bug 3: user called it a gemma template quirk; preserve raw data, don't strip
    ('bug3_gemma_quirk_preserve_raw',
     r'(gemma.*quirk'
     r'|quirk.*gemma'
     r'|gemma.*template.*quirk'
     r'|one.time.*gemma'
     r'|gemma.*one.time'
     r'|preserve.*raw.*data'
     r'|raw.*data.*preserv'
     r'|not.*strip.*data'
     r'|user.*not.*strip'
     r'|preserve.*incoming.*data'
     r'|malform.*preserv.*data'
     r'|bug.?3.*gemma'
     r'|token.*artifact.*quirk)'),

    # 5. v9 urgency argument originated from the USER's opening message, not Claude
    ('v9_urgency_user_originated',
     r'(user.*v9.*urgent'
     r'|v9.*urgent.*user'
     r'|user.*raised.*v9'
     r'|user.*identified.*v9.*urgent'
     r'|v9.*user.*opening'
     r'|user.*stated.*v9'
     r'|user.*mention.*v9.*urgent'
     r'|user.*indep.*v9'
     r'|user.*already.*knew.*v9'
     r'|user.*original.*v9'
     r'|v9.*user.*initiat'
     r'|opening.*message.*v9'
     r'|user.*independently.*v9)'),

    # 6. Glob for *.md returned node_modules noise; Claude didn't use the results
    ('glob_returned_node_modules_noise',
     r'(node.modules.*glob'
     r'|glob.*node.modules'
     r'|glob.*md.*node.modules'
     r'|node.modules.*md.*result'
     r'|glob.*return.*node.modules'
     r'|glob.*return.*noise'
     r'|glob.*return.*irrelevant'
     r'|unscoped.*glob'
     r'|glob.*unscoped'
     r'|glob.*md.*unscoped'
     r'|glob.*noise.*node'
     r'|md.*glob.*node.modules)'),
]

CHECK_LABELS = [
    'Col 1: 16-day-old memory staleness warning present; Claude relied on it without flagging',
    'Col 2: Counter=22 because Phase 1 noise pushes 21 runStats entries before Phase 3; mismatched populations',
    'Col 3: Already-done sessions are invisible to final tally (no runStats push, not counted at all)',
    'Col 4: Bug 3 was user-classified as a gemma template quirk; user said preserve raw data, no stripping',
    'Col 5: v9 urgency argument originated from USER\'s opening message, not from Claude',
    'Col 6: Glob(**/*.md) returned node_modules noise; unscoped call, results unused',
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
