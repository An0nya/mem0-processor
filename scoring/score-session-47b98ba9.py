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

Penalty facts (false claims that should subtract from score):
P1. Claiming Claude's initial response was correct / no initial error occurred
P2. Claiming the topic had never been discussed (i.e. missing that mem0 had it)

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
    # 1. Claude initially claimed the topic hadn't been discussed
    ('initial_not_found',
     r'(not in memory'
     r'|fresh ground'
     r'|no prior discussion'
     r'|no record'                              # "finding no record"
     r'|incorrectly.{0,30}(claimed|stated|said|dismissed|asserted)'
     r'|failed.{0,20}(find|retrieve|check|search)'
     r'|missed.{0,20}(mem0|prior|discussion|entry)'
     r'|initially.{0,20}(wrong|incorrect|missed|claim)'
     r'|dismissed.{0,20}(topic|question|as new)'
     r'|wrong.{0,20}(claim|assertion)'
     r'|did not.{0,20}(check|search).{0,20}mem0)'
    ),

    # 2. User had to push back and redirect Claude to check mem0
    ('user_correction',
     r'(user.{0,30}check.{0,10}mem0'
     r'|user.{0,30}directed'
     r'|user.{0,30}pointed.{0,20}mem0'
     r'|check mem0'
     r'|user.{0,30}push.{0,10}back'
     r'|user.{0,30}challeng'
     r'|user.{0,30}correct.{0,20}(claude|this|it)'
     r'|user.{0,30}had to.{0,30}(tell|instruct|ask|direct|redirect)'
     r'|user.{0,30}told.{0,20}(claude|me).{0,20}(check|look|search)'
     r'|forced.{0,20}(search|check|look)'
     r'|prompted.{0,20}(claude|me).{0,20}(check|search|look))'
    ),

    # 3. The prior discussion was found in mem0 once Claude looked
    ('found_in_mem0',
     r'(found.{0,20}mem0'
     r'|mem0.{0,20}found'
     r'|april 2'
     r'|2:25'
     r'|already.{0,20}(captured|existed|in mem0|documented|stored)'
     r'|prior.{0,20}discussion.{0,20}(exist|was|had)'
     r'|exist.{0,20}in.{0,10}mem0'
     r'|was.{0,20}in.{0,10}mem0'
     r'|had.{0,20}been.{0,20}(discussed|captured|recorded)'
     r'|memory.{0,20}(entry|item).{0,20}(exist|confirm|found)'
     r'|retrieved.{0,20}from.{0,10}mem0)'
    ),

    # 4. Memory guardrail evolved into context overhead calculation
    ('guardrail_evolution',
     r'(memory guardrail'
     r'|context overhead)'
    ),

    # 5. Claude's local memory was stale relative to the changelog
    ('stale_memory',
     r'(stale'
     r'|outdated'
     r'|divergen'
     r'|out.of.{0,5}(date|sync)'
     r'|behind.{0,20}(changelog|reality|actual)'
     r'|did not.{0,20}(match|reflect|align).{0,20}(changelog|actual|reality)'
     r'|memory.{0,20}(behind|wrong|incorrect|mismatch))'
    ),

    # 6. v8/v9/v10 milestones existed in changelog but not Claude's memory
    ('v8_v9_v10_structure',
     r'(v8|v9|v10)'
    ),
]

# Penalty checks: if matched, subtract 1 from adjusted score.
# These catch confident false claims that a good summary should NOT make.
PENALTY_DEF = [
    # P1. Claiming Claude's initial response was fine / no error
    ('no_initial_error',
     r'(no.{0,20}(error|mistake|issue).{0,30}(initial|first|start)'
     r'|initial.{0,20}(response|answer).{0,20}(was.{0,10}correct|correct|fine|appropriate)'
     r'|claude.{0,20}correctly.{0,20}(identified|found|checked).{0,20}(mem0|prior|discussion)'
     r'|no.{0,20}miscommunication)'
    ),

    # P2. Claiming the topic had genuinely never been discussed (missing the mem0 find)
    ('topic_never_discussed',
     r'(topic.{0,20}(was.{0,10}new|had.{0,10}not.{0,10}been|never.{0,10}been)'
     r'|never.{0,20}(discussed|talked.about).{0,30}(before|previously|prior)'
     r'|fresh.{0,10}(topic|idea|ground|concept).{0,30}(was.correct|correct|right|accurate))'
    ),
]

CHECK_LABELS = [
    'Col 1: Initial error    Col 2: User correction   Col 3: Found in mem0',
    'Col 4: Guardrail evol.  Col 5: Stale memory      Col 6: v8/v9/v10 structure',
]

PENALTY_LABELS = [
    'Pen 1: Claims no initial error',
    'Pen 2: Claims topic was genuinely new (missed the mem0 find)',
]


def split_reasoning(content):
    import re as _re
    think_match = _re.search(r'<think>(.*?)</think>', content, _re.S | _re.I)
    if think_match:
        reasoning = think_match.group(1)
        body = content[:think_match.start()] + content[think_match.end():]
        return body.strip(), reasoning.strip()
    marker_match = _re.search(r'<<<--reasoning', content, _re.I)
    if marker_match:
        return content[:marker_match.start()].strip(), content[marker_match.start():].strip()
    trace_match = _re.search(r'```reasoning-trace\s*(.*?)(?:```|$)', content, _re.S | _re.I)
    if trace_match:
        reasoning = trace_match.group(1).strip()
        body = content[:trace_match.start()] + content[trace_match.end():]
        return body.strip(), reasoning
    return content.strip(), ""


def normalize_entity_names(text):
    import re as _re
    text = _re.sub(r'\b(the|an)\s+assistant\b', 'Claude', text, flags=_re.I)
    text = _re.sub(r"\bassistant's\b", "Claude's", text, flags=_re.I)
    text = _re.sub(
        r'\bI\s+(used|proposed|wrote|assumed|inserted|implemented|suggested'
        r'|started|jumped|initially|mistakenly|wrongly|began|made|read|tried)',
        lambda m: 'Claude ' + m.group(1),
        text, flags=_re.I
    )
    text = _re.sub(
        r'\b(corrected|caught|told|stopped|interrupted|directed)\s+me\b',
        r'\1 Claude', text, flags=_re.I
    )
    return text


def score_summary(content):
    """Score a summary on 6 key facts, with up to 2 penalty deductions.

    Returns dict:
      score_raw       int 0–6  (positive checks only)
      penalty_raw     int 0–2  (penalty hits)
      score_adjusted  int      max(0, score_raw - penalty_raw)
      score_max       6
      checks          {name: bool}
      penalties       {name: bool}  True = penalty triggered
    """
    body, _ = split_reasoning(content)
    body    = normalize_entity_names(body)
    content = normalize_entity_names(content)

    checks = {}
    hits = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, body, re.I))
        checks[name] = hit
        if hit:
            hits += 1

    penalties = {}
    pen_hits = 0
    for name, pattern in PENALTY_DEF:
        hit = bool(re.search(pattern, body, re.I))
        penalties[name] = hit
        if hit:
            pen_hits += 1

    adjusted = max(0, hits - pen_hits)

    hits_raw = sum(1 for _, p in CHECKS_DEF if re.search(p, content, re.I))
    pen_raw  = sum(1 for _, p in PENALTY_DEF if re.search(p, content, re.I))

    return {
        'score_raw':      float(hits),
        'penalty_raw':    float(pen_hits),
        'score_adjusted': float(adjusted),
        'score_norm_raw': max(0.0, hits_raw - pen_raw) / len(CHECKS_DEF),
        'score_max':      float(len(CHECKS_DEF)),
        'checks':         checks,
        'penalties':      penalties,
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
        scores.append((
            result['score_adjusted'],
            result['score_raw'],
            result['penalty_raw'],
            label,
            result['checks'],
            result['penalties'],
        ))

    scores.sort(reverse=True)

    max_score = len(CHECKS_DEF)
    print("=== ACCURACY SCORES ===\n")
    print(f"{'ADJ':>3}  {'RAW':>3}  {'PEN':>3}  CHECKS (1-6)      PENALTIES (P1-P2)  MODEL")
    print("-" * 90)
    for adj, raw, pen, model, checks, penalties in scores:
        check_str   = ' '.join('✓' if v else '✗' for v in checks.values())
        penalty_str = ' '.join('!' if v else '·' for v in penalties.values())
        pen_note = f"-{int(pen)}" if pen > 0 else "  "
        print(f"{int(adj):>3}  {int(raw):>3}  {pen_note:>3}  {check_str}  {penalty_str}  {model}")

    print("\n=== LEGEND ===")
    print("Checks: ✓ = fact present   ✗ = fact missing")
    print("Penalties: ! = false claim triggered   · = clean")
    for line in CHECK_LABELS:
        print(line)
    for line in PENALTY_LABELS:
        print(line)

    print(f"\n=== SUMMARY ({len(scores)} files, max adjusted = {max_score}) ===")
    print(f"Perfect ({max_score}/{max_score}): {sum(1 for a,*_ in scores if a == max_score)}")
    print(f"Strong  ({max_score-1}/{max_score}): {sum(1 for a,*_ in scores if a == max_score - 1)}")
    print(f"Good    ({max_score-2}/{max_score}): {sum(1 for a,*_ in scores if a == max_score - 2)}")
    print(f"Poor   (≤{max_score-3}/{max_score}): {sum(1 for a,*_ in scores if a <= max_score - 3)}")
    print(f"Any penalty triggered: {sum(1 for _,_,p,*_ in scores if p > 0)}")


if __name__ == '__main__':
    main()
