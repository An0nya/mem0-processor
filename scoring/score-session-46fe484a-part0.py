#!/usr/bin/env python3
"""
Accuracy scorer for session 46fe484a summaries.

Ground truth facts:
1. Session was planning only — no code written, no tool executions beyond memory reads
2. USER corrected Claude's short-tail framing: tails are epilogues to their own session,
   not prologues to the next one
3. Settled design: compaction summary = canonical forward-propagating context artifact
4. USER identified that sessions are intentionally self-contained (siloed tasks,
   carried-over planning context) — this was user-stated, not Claude-proposed
5. USER raised model quality risk for self-referential injection: weak model getting its
   own bad summary as context could produce hallucinations/tangents
6. Chronological session ordering was entirely missing from the roadmap — discovered
   via a post-compaction notes check-in, not from the CHANGELOG review

Usage:
  python score-session-46fe484a.py                  # auto-discover in summaries + archive
  python score-session-46fe484a.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "46fe484a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    ('planning_only',          r'(planning.only|no.code|no.implement|plan.lite|design.session|no.changes.made)'),
    ('user_tail_correction',   r'(epilogue|user.*pushed.back|user.*corrected|tail.*same.session|not.*next.session|user.*rejected)'),
    ('compaction_canonical',   r'(compaction.*canonical|canonical.*forward|forward.propagat|compaction.*inject)'),
    ('sessions_self_contained',r'(self.contained|session.*silo|silo.*session|intentionally.*self|tasks.*silo)'),
    ('injection_quality_risk', r'(hallucin|shitty.model|bad.model|quality.*inject|inject.*quality|model.*own.summary)'),
    ('chrono_missing',         r'(chronolog.*missing|missing.*roadmap|notes.*check|post.compaction.*notes|not.*roadmapped)'),
]

CHECK_LABELS = [
    'Col 1: Planning only (no code)   Col 2: User corrected tail framing',
    'Col 3: Compaction = canonical    Col 4: User: sessions self-contained',
    'Col 5: User: injection quality   Col 6: Chrono sort missing from roadmap',
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
    """Score a summary on 6 key facts.

    Returns dict:
      score_norm      float 0–1, higher=better (body only)
      score_norm_raw  float 0–1, higher=better (full content)
      score_raw   int 0–6
      score_max   6.0
      checks      {name: bool} one entry per fact
      extra       {} (unused for this session)
    """
    body, _ = split_reasoning(content)
    body    = normalize_entity_names(body)
    content = normalize_entity_names(content)

    checks = {}
    score = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, body, re.I))
        checks[name] = hit
        if hit:
            score += 1

    score_raw_count = sum(1 for _, p in CHECKS_DEF if re.search(p, content, re.I))

    return {
        'score_norm':     score / len(CHECKS_DEF),
        'score_norm_raw': score_raw_count / len(CHECKS_DEF),
        'score_raw':      float(score),
        'score_max':      float(len(CHECKS_DEF)),
        'checks':         checks,
        'extra':          {},
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

    print("=== ACCURACY SCORES ===\n")
    for score_raw, model, checks in scores:
        check_str = ' '.join('✓' if v else '✗' for v in checks.values())
        print(f"{int(score_raw)}/6  {check_str}  {model}")

    print("\n=== LEGEND ===")
    for line in CHECK_LABELS:
        print(line)

    print(f"\n=== SUMMARY ({len(scores)} files) ===")
    print(f"Perfect (6/6): {sum(1 for s, _, _ in scores if s == 6)}")
    print(f"Strong  (5/6): {sum(1 for s, _, _ in scores if s == 5)}")
    print(f"Good    (4/6): {sum(1 for s, _, _ in scores if s == 4)}")
    print(f"Poor   (≤3/6): {sum(1 for s, _, _ in scores if s <= 3)}")


if __name__ == '__main__':
    main()
