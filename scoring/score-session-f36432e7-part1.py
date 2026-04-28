#!/usr/bin/env python3
"""
Accuracy scorer for session f36432e7 part1 summaries (eager-sniffing-stream).

Ground truth facts:
1. LM Studio stream mode does NOT emit tps/usage stats in SSE chunks — the only
   chunk returned after [DONE] was {"finish_reason": "stop"}, confirmed via debug
   logging. This is an endpoint limitation, not a code bug.
2. Claude added debug logging to the script unprompted (overreach) — the user had
   only agreed to *see* debug output, not to make code changes. User rolled back
   to the previous commit rather than keeping the patch.
3. The 917,504-char max displayed came from context_tokens × 3.5
   (262,144 tokens × 3.5 chars/token), not from the 32k session ctx or the
   112k RAM-constrained cap. This was Claude's explanation; user accepted it.
4. qwen3.5-9b-optiq and qwen3.5-9b-mlx are stored as separate keys in the perf
   store — the 14.99 GB peak and resulting 112k cap applied to optiq only; mlx
   had no entry yet, so its cap had not yet triggered.
5. User deferred both fixes (stream-tps and universal RAM cap) — chose to keep
   testing rather than hardcoding a cap or patching the stream parser.

Usage:
  python score-session-f36432e7-part1.py                  # auto-discover
  python score-session-f36432e7-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "f36432e7-part1"
SESSION_ID_BARE = "f36432e7"
PART_FILTER = "part1"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Stream mode doesn't return tps/stats — endpoint limitation, not a code bug
    ('stream_no_stats',
     r'(lm.studio.{0,30}(stream|sse).{0,40}(no|not|doesn.t|missing|without).{0,20}(stat|tps|usage|token)'
     r'|stream.{0,30}(no|not|doesn.t|missing).{0,20}(stat|tps|usage|emit)'
     r'|sse.{0,30}(no|not|doesn.t).{0,20}(stat|tps|emit)'
     r'|finish.reason.{0,20}(only|stop|no.stat)'
     r'|stream.{0,20}(endpoint|api|limitation).{0,30}(stat|tps)'
     r'|stat.{0,20}(not.emitted|missing.in.stream|not.in.stream)'
     r'|not.a.code.bug.{0,40}(stream|lm.studio|endpoint)'
     r'|(endpoint|api).limitation.{0,30}(tps|stat|stream)'
     r'|tps.{0,30}null.{0,30}(stream|lm.studio|endpoint)'
     r'|only.{0,20}(chunk|data).{0,20}(finish.reason|stop))'),

    # 2. Claude added debug logging unprompted (overreach) — user rolled back
    ('debug_overreach_rollback',
     r'(debug.{0,30}(unprompted|overreach|without.asking|without.being.asked)'
     r'|overreach.{0,30}debug'
     r'|added.{0,20}(debug|logging).{0,30}(unprompted|without.explicit|without.ask)'
     r'|user.{0,20}(roll.?back|revert|undo).{0,30}(debug|commit|change)'
     r'|roll.?back.{0,30}(debug|commit|change).{0,20}user'
     r'|prev.{0,10}commit.{0,20}(roll.?back|revert)'
     r'|debug.log.{0,30}(roll.?back|revert|removed)'
     r'|user.{0,20}roll.?back'
     r'|rejected.{0,20}(debug|patch|fix).{0,30}(roll|revert)'
     r'|unprompted.{0,30}(debug|code.change|log))'),

    # 3. 917k chars = context_tokens × 3.5 (262k model context)
    ('context_chars_explanation',
     r'(917.?504|917.?k|917,?504'
     r'|262.{0,10}(k|000|144).{0,30}(3\.5|chars|context|token)'
     r'|3\.5.{0,30}(char|token|context).{0,30}(262|917|mult)'
     r'|context.length.{0,30}(char|3\.5|conversion)'
     r'|token.{0,10}to.{0,10}char.{0,20}(3\.5|conversion|factor)'
     r'|chars?.per.token'
     r'|model.context.{0,30}(token|length).{0,30}(3\.5|convert|multiply|chars?)'
     r'|max.transcript.{0,30}(917|262).{0,20}(context|token|model))'),

    # 4. optiq and mlx are separate perf-store keys — cap only on optiq, not mlx
    ('separate_model_keys',
     r'(optiq.{0,30}mlx.{0,30}(different|separate|distinct).{0,20}key'
     r'|mlx.{0,30}optiq.{0,30}(different|separate|distinct).{0,20}key'
     r'|different.{0,10}(key|entry|id).{0,30}(optiq|mlx)'
     r'|separate.{0,10}(key|entry|id).{0,30}(optiq|mlx)'
     r'|(optiq|mlx).{0,20}(key|entry|id).{0,30}(not.match|mismatch|differ)'
     r'|perf.store.{0,30}(optiq|mlx).{0,30}(different|separate|distinct)'
     r'|cap.{0,30}(not.trigger|not.apply|no.entry).{0,30}(mlx|optiq)'
     r'|mlx.{0,30}(no.entry|no.record|not.in.perf|no.perf)'
     r'|(14\.99|14.99).{0,30}(optiq|cap).{0,30}(mlx|not.apply|different)'
     r'|model.id.{0,20}(mismatch|differ).{0,30}(cap|perf|key))'),

    # 5. User deferred both stream-tps fix and RAM cap — chose to keep testing
    ('deferred_both_fixes',
     r'(keep.testing|ill.keep.testing|defer.{0,20}(both|fix|cap|stream)'
     r'|both.{0,20}defer|deferred.{0,20}(stream|cap|fix)'
     r'|user.{0,20}defer.{0,30}(stream|tps|cap|fix)'
     r'|decided.to.{0,20}(defer|delay|keep.testing|not.fix)'
     r'|not.implement.{0,30}(cap|stream|fix).{0,30}(user|decision|defer)'
     r'|user.chose.{0,30}(test|wait|defer)'
     r'|(stream.fix|tps.fix|cap.fix).{0,30}(defer|delay|not.implement)'
     r'|wait.{0,30}(more.data|test|result).{0,30}(before|cap|stream)'
     r'|hardcode.{0,20}(cap|limit).{0,30}(not|defer|user)'
     r'|112.?k.{0,30}(defer|not.set|not.implement|keep.testing))'),
]

CHECK_LABELS = [
    'Col 1: Stream mode → no tps/stats (LM Studio endpoint limitation)',
    'Col 2: Claude added debug logging unprompted → user rolled back',
    'Col 3: 917k char max = 262k tokens × 3.5 chars (model context)',
    'Col 4: optiq vs mlx are separate perf-store keys → cap only on optiq',
    'Col 5: User deferred both stream-tps fix and RAM cap (keep testing)',
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

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID_BARE}*{PART_FILTER}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID_BARE}.+?({PART_FILTER}.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID_BARE}*{PART_FILTER}*.txt"):
            model = f.parent.name
            match = re.search(rf'{SESSION_ID_BARE}.+?({PART_FILTER}.+)$', f.stem)
            label_suffix = match.group(1) if match else ''
            label = f"{model}  [{label_suffix}]" if label_suffix else model
            results.append((f, label))

    return results


def main():
    if len(sys.argv) > 1:
        files = [(Path(p), Path(p).stem) for p in sys.argv[1:]]
    else:
        files = discover_files()

    if not files:
        print(f"No part1 summary files found for session {SESSION_ID}.")
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
    print("=== ACCURACY SCORES (f36432e7 part1) ===\n")
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
