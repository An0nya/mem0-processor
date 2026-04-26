#!/usr/bin/env python3
"""
Accuracy scorer for session 70e8af6a-part3 summaries (zazzy-wishing-koala).

Part3 = steps 2–4 continued (07:10–07:28). Best scorer candidate for this session.

Ground truth facts:
1. Claude misunderstood the "both" case. Implemented content-empty → reasoning-only
   fallback, but user wanted to match lmstudio behavior where "both" means both
   reasoning AND content blocks are present. User correction: "i mean the lmstudio
   uses reasoning fallback, so i want to match what that does (including the 'both' option)".
2. Claude used HTML comments for the reasoning trace marker (e.g. <!-- reasoning-only -->).
   User rejected this ("if there's a better markup format to use, lets use it. ive gotten
   the html tag confusion from claude as well"). Switched to fenced code block with
   ```reasoning-trace language tag.
3. Rounding error in the time display caught by user before commit: "1.1127280000000002s"
   floating point from prompt_ms / 1000. User: "got a rounding error on the time data.
   i wrote those originally so i must have rounded somewhere ahead." Fixed with toFixed(4).
4. qwen3 0.8B was putting all output in reasoning_content (40k chars), leaving content
   empty. Diagnosed as thinking mode. The "both" fix involved correctly handling the
   reasoning_content key alongside content.

Note: parts 4 and 5 of this session are contaminated by compaction duplication —
do not score those parts. This scorer only discovers part3 summaries.

Usage:
  python score-session-70e8af6a-part3.py                  # auto-discover
  python score-session-70e8af6a-part3.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "70e8af6a-part3"
SESSION_ID_BARE = "70e8af6a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Claude misunderstood the "both" case; user corrected
    ('both_case_misunderstood',
     r'(both.case.{0,40}(misunderstood|wrong|incorrect|error|incorrect)'
     r'|misunderstood.{0,30}both.case'
     r'|both.{0,20}(reasoning.and.content|content.and.reasoning).{0,30}(misunderstood|wrong|missed)'
     r'|reasoning.fallback.{0,40}(both|user.correct|match.lmstudio)'
     r'|user.corrected.{0,30}(both|reasoning|lmstudio)'
     r'|lmstudio.behavior.{0,30}(match|both|reasoning)'
     r'|match.{0,15}lmstudio.{0,30}(both|reasoning|behavior)'
     r'|both.option.{0,30}(include|user|lmstudio|match)'
     r'|claude.{0,20}assumed.{0,30}both.{0,20}(empty|only.reasoning|wrong)'
     r'|content.empty.{0,30}(fallback|reasoning.only).{0,30}(wrong|incorrect|user)'
     r'|user.{0,20}(clarif|correct).{0,30}(both|reasoning.fallback|lmstudio)'
     r'|both.{0,10}case.{0,30}(three|all.three|content.and.reasoning|matched))'
    ),

    # 2. HTML comments rejected; switched to fenced code block with reasoning-trace tag
    ('html_comments_rejected_fenced_block',
     r'(html.comment.{0,40}(rejected|refused|replaced|switched|problem|wrong|bad)'
     r'|user.{0,20}rejected.{0,30}(html|comment|<!-)'
     r'|fenced.code.block.{0,30}(reasoning|instead|replace|switch)'
     r'|reasoning.trace.{0,30}(fenced|code.block|lang|language|tag)'
     r'|```reasoning.trace'
     r'|switched.{0,20}from.{0,20}(html|comment).{0,20}(to.fenced|fenced.code|code.block)'
     r'|html.tag.{0,30}(confusion|confused|problem|issue)'
     r'|markup.format.{0,30}(better|replace|fenced|changed)'
     r'|(<!--.{0,20}reasoning|reasoning.{0,20}-->).{0,30}(rejected|replaced|changed)'
     r'|html.comment.{0,30}confused|confused.{0,30}html.comment'
     r'|out.of.band.{0,30}(markup|fenced|reasoning)'
     r'|reasoning.trace.block|benchmark.trace)'
    ),

    # 3. Rounding error in time data caught by user before commit
    ('rounding_error_user_catch',
     r'(rounding.error.{0,30}(user|time|caught|before.commit)'
     r'|user.{0,30}(caught|noticed|spotted).{0,30}(rounding|floating.point|precision|time.data)'
     r'|floating.point.{0,30}(error|issue|rounding).{0,30}(time|ttft|genTime|prompt_ms)'
     r'|1\.112728|1\.1127'
     r'|prompt_ms.{0,20}(divide|/).{0,10}1000.{0,20}(rounding|float|precision)'
     r'|time.data.{0,30}(rounding|floating|precision|user)'
     r'|toFixed.{0,20}(4|fix|rounding)'
     r'|rounding.{0,20}(ahead|wrote|original).{0,30}user'
     r'|user.{0,20}(wrote.originally|i.wrote.originally).{0,20}(rounded|rounding)'
     r'|caught.before.commit.{0,30}(time|rounding|float)'
     r'|time.display.{0,30}(float|rounding|precision|error))'
    ),

    # 4. qwen3 0.8B output in reasoning_content (thinking mode), content empty
    ('qwen3_reasoning_content_field',
     r'(reasoning_content'
     r'|thinking.mode.{0,30}(qwen|0\.8b|empty.content)'
     r'|qwen3.{0,20}(thinking|reasoning.content|reasoning_content)'
     r'|content.empty.{0,30}(reasoning.content|thinking|qwen|all.in.reasoning)'
     r'|all.{0,20}(output|tokens).{0,30}(reasoning_content|thinking.block|think.tag)'
     r'|0\.8b.{0,30}(thinking.mode|reasoning_content|empty.content)'
     r'|blank.summar.{0,30}(reasoning_content|thinking|qwen)'
     r'|empty.content.{0,30}(reasoning_content|thinking|qwen|block)'
     r'|40.{0,5}(k|000).{0,20}(chars?|reasoning|thinking)'
     r'|finish_reason.{0,20}length.{0,20}(empty|no.content|reasoning)'
     r'|reasoning.block.{0,20}(content.empty|no.content|blank))'
    ),
]

CHECK_LABELS = [
    'Col 1: Claude misunderstood "both" case; user corrected to match lmstudio (both = both blocks present)',
    'Col 2: HTML comments for reasoning trace rejected; switched to ```reasoning-trace fenced block',
    'Col 3: Rounding error in time data (1.1127280000000002s) caught by user before commit',
    'Col 4: qwen3 0.8B put all output in reasoning_content (40k chars), content empty — thinking mode',
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
    for pattern in [f"*{SESSION_ID_BARE}*part3*.txt", f"*part3*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            if (f, label) not in results:
                results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part3*.txt", f"*part3*{SESSION_ID_BARE}*.txt"]:
            for f in ARCHIVE_DIR.glob(f"*/{pattern}"):
                model = f.parent.name
                timestamp_match = re.search(rf'{SESSION_ID_BARE}--(.+)$', f.stem)
                timestamp = timestamp_match.group(1) if timestamp_match else ''
                label = f"{model}  [{timestamp}]" if timestamp else model
                if (f, label) not in results:
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

    scores.sort(key=lambda x: x[0], reverse=True)

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
