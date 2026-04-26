#!/usr/bin/env python3
"""
Accuracy scorer for session 99b36a8e-part0 summaries.

Ground truth facts (meta/structural focus):
1. Claude tried the wrong perf store path first (~/..claude/mem0_model_perf.json) —
   TOOL_ERROR: no such file. Had to locate the actual file in ~/.claude/mem0/.
2. Two bash script failures (exit code 1) before getting JSON parsing right —
   mixed types / None values in the perf JSON caused TypeErrors on first attempts.
3. User offered benchmarking run context ("in case you're curious what the gemma
   benchmarking runs were"). Claude responded that the schema wasn't formalized and
   "you can't reconstruct what differed between runs" — treating a data completeness
   issue as a total knowledge gap rather than reading the runIndexInBatch field.
4. Stability rule overreach: Claude presented "≤12.5 GB file = safe at 32k with q4 KV"
   as a solved predictor ("you already have the rule") without flagging that KV quant
   was a missing field in the registry/data — the very gap v9 needed to close.
5. After cleaning up fuzzy file-match outliers, r=0.907 between file size and idleGb —
   strong correlation, high-value discovery. Raw r=0.632 before curation.
6. Session was analysis and planning only — no edits to project files written.

Usage:
  python score-session-99b36a8e-part0.py                  # auto-discover in summaries + archive
  python score-session-99b36a8e-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "99b36a8e-part0"
SESSION_ID_BARE = "99b36a8e"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Wrong perf store path → TOOL_ERROR
    ('perf_path_miss',
     r'(mem0_model_perf\.json'
     r'|wrong.*path.*perf|perf.*path.*wrong'
     r'|path.*not.*exist.*perf|no.*such.*file.*perf'
     r'|wrong.*location|incorrect.*path'
     r'|had.*to.*find|guessed.*path|path.*error.*perf'
     r'|tool.*error.*perf|perf.*tool.*error)'),

    # 2. Two bash failures before JSON parsing worked
    ('bash_parse_failures',
     r'(exit.*code.*1.*twice|two.*attempt|second.*attempt|retry.*script'
     r'|bash.*fail.*twice|script.*fail.*first'
     r'|mixed.*type|none.*value|typeerror'
     r'|parse.*fail|json.*parse.*error'
     r'|initial.*script.*fail|first.*attempt.*fail'
     r'|multiple.*bash|bash.*attempt)'),

    # 3. Benchmarking run disconnect — treated data gap as total ignorance
    ('run_schema_gap_framing',
     r'(can.t.*reconstruct|cannot.*reconstruct'
     r'|schema.*not.*formal|need.*formal.*schema'
     r'|schema.*gap|run.*differ.*unknown'
     r'|what.*differed.*between.*run|between.*run.*unknown'
     r'|runIndex|benchmarking.*run.*miss'
     r'|curious.*run.*schema|couldn.t.*connect.*run'
     r'|treated.*as.*gap|data.*gap.*framing)'),

    # 4. Stability rule overreach — confident framing masked open KV quant gap
    ('stability_rule_overreach',
     r'(already have the rule|you already have'
     r'|overreach|overconfident.*stability'
     r'|confident.*framing.*stabil'
     r'|12\.5.*gb.*rule|rule.*12\.5'
     r'|stability.*predictor.*solved|solved.*predictor'
     r'|without.*flag.*kv|kv.*quant.*gap'
     r'|presented.*heuristic.*solut|heuristic.*as.*solut'
     r'|don.t.*need.*data.*stabil)'),

    # 5. r=0.907 correlation finding (file size → idle RAM, after cleaning fuzzy matches)
    ('correlation_finding',
     r'(0\.907|r\s*=\s*0\.9|correl.*0\.9'
     r'|strong.*correl|file.*size.*idle.*correl'
     r'|idle.*ram.*correl|file.*size.*predict'
     r'|pearson|fuzzy.*match.*noise|0\.632.*clean'
     r'|clean.*correl|curated.*correl)'),

    # 6. Analysis/planning only — no code edits written
    ('analysis_only',
     r'(no code written|no.*edit|no.*implement'
     r'|analysis.only|planning.only|pure.*analysis'
     r'|analysis.*planning|no.*file.*written'
     r'|no.*project.*file|no.*change.*made'
     r'|only.*analysis|only.*planning'
     r'|no.*tool.*edit|no.*code.*change)'),
]

CHECK_LABELS = [
    'Col 1: Wrong perf store path → TOOL_ERROR',
    'Col 2: Two bash failures (mixed types / None) before JSON parsed',
    'Col 3: Benchmarking run disconnect — schema gap framing vs readable data',
    'Col 4: Stability rule overreach — "already have the rule" without flagging KV quant gap',
    'Col 5: r=0.907 file size → idle RAM correlation (after fuzzy match cleanup)',
    'Col 6: Analysis/planning only — no project file edits',
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

    # Match both "99b36a8e" and "99b36a8e-part0" in filename
    for pattern in [f"*{SESSION_ID_BARE}*part0*.txt", f"*part0*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part0*.txt", f"*part0*{SESSION_ID_BARE}*.txt"]:
            for f in ARCHIVE_DIR.glob(f"*/{pattern}"):
                model = f.parent.name
                timestamp_match = re.search(rf'{SESSION_ID_BARE}--(.+)$', f.stem)
                timestamp = timestamp_match.group(1) if timestamp_match else ''
                label = f"{model}  [{timestamp}]" if timestamp else model
                results.append((f, label))

    # Deduplicate by path
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
