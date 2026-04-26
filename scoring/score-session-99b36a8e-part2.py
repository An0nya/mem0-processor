#!/usr/bin/env python3
"""
Accuracy scorer for session 99b36a8e-part2 summaries.

Ground truth facts (meta/structural focus):
1. User hit Escape intending to refocus their chat window; it interrupted Claude's output
   instead. Claude had been mid-output on slug analysis — user clarified and resumed.
2. Claude over-theorized before reading the relevant function directly: speculated through
   summaryPath mismatch, buildSegments partSuffix logic, newer JSONL format differences,
   and null+string concatenation behavior across multiple exchanges before finally just
   reading extractSessionSlug — where the bug was immediately visible.
3. Root cause of caching bug: extractSessionSlug scanned only the first 30 lines
   (lines.slice(0, 30)), but slug fields in newer Claude Code sessions appear at line ~115.
4. segSlug null propagation: when sessionSlug is null, segSlug is constructed as null,
   so all parts of a multi-part session save under the same filename and overwrite each other.
   User ends up with only the last part cached locally.
5. Changelog framing error: after updating CHANGELOG.md, Claude left two implemented items
   in the "pending" framing by mistake. User noticed; Claude caught and corrected it.
6. All three bugs fixed and committed together in 778d3db: slug extraction cap removed,
   segSlug null propagation fixed, --reprocess by slug added as a related improvement.

Usage:
  python score-session-99b36a8e-part2.py                  # auto-discover in summaries + archive
  python score-session-99b36a8e-part2.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "99b36a8e-part2"
SESSION_ID_BARE = "99b36a8e"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Escape key accident — user interrupted Claude trying to refocus window
    ('escape_key_interrupt',
     r'(escape.*interrupt|interrupt.*escape'
     r'|refocus.*window|window.*refocus'
     r'|escape.*key|crap.*escape|escape.*accidental'
     r'|accidental.*interrupt|meant.*refocus'
     r'|escape.*refocus|escape.*chat|chat.*escape)'),

    # 2. Over-theorized before reading extractSessionSlug directly
    ('over_theorized_bug',
     r'(over.theori|speculat.*before.*read|multiple.*hypothes'
     r'|theori.*without.*check|verbose.*debug'
     r'|before.*read.*function|before.*check.*code'
     r'|summaryPath.*theori|buildSegments.*theori'
     r'|newer.*jsonl.*hypothes|hypothes.*newer.*session'
     r'|several.*cause|multiple.*cause.*before'
     r'|should.*have.*read|read.*earlier|direct.*read.*faster'
     r'|inefficien.*invest|circuitous|roundabout'
     r'|walked.*through.*without|spent.*time.*theori)'),

    # 3. 30-line cap in extractSessionSlug — slug at line ~115
    ('thirty_line_cap',
     r'(30.line|thirty.line|line.*30\b|\bslice.*30\b'
     r'|first.*30|30.*line.*cap|scan.*30\b'
     r'|\blines.*30\b|cap.*30|30.*scan'
     r'|115|line.*115|slug.*at.*line'
     r'|beyond.*30|past.*30|exceeds.*30)'),

    # 4. segSlug null propagation → all parts overwrite same filename
    ('segslug_null_overwrite',
     r'(segSlug.*null|null.*propagat'
     r'|null.*segSlug|segSlug.*propagat'
     r'|parts.*overwrite|overwrite.*parts'
     r'|same.*filename|filename.*same'
     r'|null.*part.*suffix|part.*suffix.*null'
     r'|sessionSlug.*null.*segSlug|slug.*null.*overwrite'
     r'|all.*parts.*same.*file|last.*part.*only)'),

    # 5. Changelog framing error — implemented items left as "pending"
    ('changelog_pending_error',
     r'(changelog.*pending|pending.*implement'
     r'|marked.*pending|left.*pending'
     r'|framing.*error.*changelog|changelog.*framing'
     r'|implement.*marked.*pending|pending.*framing'
     r'|changelog.*wrong|incorrect.*pending'
     r'|pending.*mistake|mistake.*pending'
     r'|changelog.*correct|corrected.*changelog)'),

    # 6. Three bugs committed in 778d3db
    ('three_bugs_committed',
     r'(778d3db'
     r'|three.*bug|3.*bug|three.*fix|3.*fix'
     r'|all.*three.*fix|all.*bug.*fix'
     r'|slug.*segSlug.*reprocess|slug.*cap.*null.*reprocess'
     r'|three.*interconnect|interconnect.*bug'
     r'|committed.*three|three.*commit'
     r'|single.*commit.*three|unified.*commit)'),
]

CHECK_LABELS = [
    'Col 1: Escape key interrupted output (user meant to refocus window)',
    'Col 2: Over-theorized bug cause before reading extractSessionSlug directly',
    'Col 3: 30-line scan cap in extractSessionSlug — slug at line ~115',
    'Col 4: segSlug null propagation → all parts overwrite same filename',
    'Col 5: Changelog framing error — implemented items left as "pending"',
    'Col 6: All three bugs committed in 778d3db (slug cap + segSlug null + reprocess by slug)',
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

    for pattern in [f"*{SESSION_ID_BARE}*part2*.txt", f"*part2*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part2*.txt", f"*part2*{SESSION_ID_BARE}*.txt"]:
            for f in ARCHIVE_DIR.glob(f"*/{pattern}"):
                model = f.parent.name
                timestamp_match = re.search(rf'{SESSION_ID_BARE}--(.+)$', f.stem)
                timestamp = timestamp_match.group(1) if timestamp_match else ''
                label = f"{model}  [{timestamp}]" if timestamp else model
                results.append((f, label))

    seen = set()
    deduped = []
    for f, label in results:
        if f not in seen:
            seen.add(f)
            deduped.append((f, label))
    return deduped


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
