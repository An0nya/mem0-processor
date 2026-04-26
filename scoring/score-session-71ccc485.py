#!/usr/bin/env python3
"""
Accuracy scorer for session 71ccc485 summaries.

Ground truth facts (interaction-dynamics focus):
1. User corrected Claude's attribution: changes 1/5/6/7 were from a prior Claude Code
   session, not user work — changes 2/3/4 were the user's own. Claude had reviewed
   the diff without flagging which changes came from where.
2. User explicitly put Claude on hold mid-session ("hold on until i give you a signal")
   and Claude correctly stood by without proceeding.
3. Claude hit a 10k-token limit reading the handoff doc (TOOL_ERROR) and had to
   paginate across multiple reads to get the full content.
4. Claude identified process.exit(0) as a bandaid, not a real fix — suggested
   "mitigated pending root cause investigation" framing; user accepted this.
5. git add -p / interactive staging requires a TTY — not available in Claude Code;
   Claude identified this constraint and the plan collapsed to one big commit.
6. State-file redesign and --ignore-cache fold were both explicitly TABLED by user
   for next session — not implemented, not committed.

Usage:
  python score-session-71ccc485.py                  # auto-discover in summaries + archive
  python score-session-71ccc485.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "71ccc485"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. User corrected Claude's attribution of the diff changes
    ('attribution_correction',
     r'(attribution|user.*corrected.*attribution|prior.*claude.*session|previous.*claude.*session'
     r'|user.*clarified.*change|which.*change.*whose|1.5.6.7.*claude|2.3.4.*user'
     r'|user.*own.*change|credit.*corrected|claude.*prior.*session.*change)'),

    # 2. User put Claude on hold — explicit standby signal respected
    ('user_standby_signal',
     r'(stand.?by|hold.*signal|wait.*signal|signal.*proceed|user.*hold|pause.*proceed'
     r'|give.*go.ahead|go.ahead|waiting.*user|user.*read.*first)'),

    # 3. Claude hit 10k token limit on handoff doc, had to paginate
    ('token_limit_paginate',
     r'(10.?000.token|10k.token|token.limit|token.*exceed|exceed.*token'
     r'|handoff.*limit|paginate|paginated|offset.*limit|multiple.*read.*handoff'
     r'|handoff.*too.large|too.large.*handoff|split.*read)'),

    # 4. process.exit(0) identified as bandaid / root cause still open
    ('exit_bandaid',
     r'(bandaid|band.aid|process\.exit.*mitigat|mitigat.*process\.exit'
     r'|root.cause.*open|root.cause.*not.*found|pending.*root.cause'
     r'|workaround.*hang|hang.*workaround|exit.*not.*real.fix|not.*real.fix)'),

    # 5. git add -p unavailable / no TTY / collapsed to one big commit
    ('no_tty_one_commit',
     r'(add\s*-p|interactive.*stag|stag.*interactive|tty|no.*tty'
     r'|one.*commit|single.*commit|d3631bb|collapsed.*commit|commit.*collapsed'
     r'|interactive.*terminal|git.*partial.*stage)'),

    # 6. State-file redesign and --ignore-cache fold explicitly tabled
    ('proposals_tabled',
     r'(tabled|deferred|next.*session.*state|state.*next.*session'
     r'|ignore.cache.*fold|fold.*ignore.cache|not.*implement|out.of.scope'
     r'|state.*file.*redesign|flag.*shuffle|flag.*reshuffle|next.*commit.*state)'),
]

CHECK_LABELS = [
    'Col 1: Attribution correction (prior Claude vs user changes)',
    'Col 2: User standby signal / Claude waited correctly',
    'Col 3: 10k token limit on handoff doc, paginated',
    'Col 4: process.exit(0) as bandaid, root cause open',
    'Col 5: No TTY / git add -p → one big commit',
    'Col 6: State redesign + --ignore-cache fold tabled',
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
