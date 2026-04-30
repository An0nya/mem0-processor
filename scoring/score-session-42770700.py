#!/usr/bin/env python3
"""
Accuracy scorer for session 42770700 summaries. v2 - dropped C4 (large_output_gap),
fixed false negatives in C1, C3, C5, C6.

Usage:
  python score-session-42770700.py                  # auto-discover in summaries + archive
  python score-session-42770700.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "42770700"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Cold-open / no prior context — Claude reconstructed from mem0 + handoff file
    ('cold_open',
     r'(no.{0,20}(prior|embedded|existing).{0,20}context'
     r'|cold.{0,10}open'
     r'|open[s]?.{0,20}(without|no).{0,20}context'
     r'|context.{0,20}(reconstruct|establish|infer).{0,20}(from|via|using)'
     r'|inferred.{0,20}from.{0,20}mem0'
     r'|had.to.{0,20}(reconstruct|infer|check).{0,20}(context|step|prior)'
     r'|started.{0,20}with.{0,30}(search|mem0|handoff)'
     r'|(read|opened|analyzed).{0,20}handoff'
     r'|handoff.{0,20}(read|check|opened|file|notes|document)'
     r'|search.{0,20}mem0.{0,20}(before|to.{0,10}(find|establish|check|understand))'
     r'|established.{0,20}context.{0,20}from'
     r'|session.{0,20}(begin|start|open).{0,30}(handoff|mem0|file.read))'),

    # 2. Three approaches for step 3 RAM fix (all three must be present or implied)
    ('three_approaches',
     r'(os\.freemem|system.free.memory.{0,30}(noisy|useless|unreliable)'
     r'|three.{0,20}(approach|attempt|method)'
     r'|ps.{0,10}rss.{0,30}(wrong|fail|inadequate|abandon|mmap|invisible|limitation)'
     r'|(dead.end|failed.approach).{0,40}(ps|rss|ioreg))'),

    # 3. ps rss silent failure — wrong numbers, no error (the key "drama")
    ('ps_rss_silent_failure',
     r'(rss.{0,40}(silent|invisib|wrong|mmap|metal.wired|cpu.fault)'
     r'|mmap.{0,30}(invisible|not.counted|miss)'
     r'|mlx.{0,30}(mmap|wired|metal).{0,30}(miss|invisible|rss)'
     r'|ps.{0,15}rss.{0,60}(Metal|MLX|memory.map|mmap)'
     r'|memory.mapping.{0,40}(rss|ps|miss|wrong|invisible)'
     r'|ps.{0,10}rss.{0,30}(only|misses|undercount)'
     r'|70.{0,10}mb|170.{0,10}mb)'),

    # 4. Step 4 design: summarized + uploaded booleans + ?? true backward compat
    ('state_redesign',
     r'(summarized.{0,20}upload'
     r'|upload.{0,20}summarized'
     r'|two.boolean'
     r'|two.phase.state'
     r'|backward.compat'
     r'|null.{0,10}coalesce|\?\?.{0,10}true'
     r'|old.{0,20}state.{0,20}(default|compat|true)'
     r'|separate.{0,20}(state|track).{0,20}(summarized|upload)'
     r'|split.{0,20}(state|flag).{0,20}(summarized|upload))'),

    # 5. Clean session — no user corrections or tool denials
    ('clean_session',
     r'(no.{0,20}(correction|error|denied|friction|rejection)'
     r'|no.{0,20}reject'
     r'|zero.{0,15}friction'
     r'|no.{0,15}(pivot|redo|re.do)'
     r'|clean.{0,20}(session|run|execution|progression|interaction)'
     r'|smooth.{0,20}(session|implementation)'
     r'|no.{0,20}tool.{0,10}denied'
     r'|no.{0,20}user.{0,20}(correction|pushback|catch))'),
]

CHECK_LABELS = [
    'C1: Cold open (no prior context)',
    'C2: Three RAM approaches identified',
    'C3: ps rss silent failure (key drama detail)',
    'C4: State redesign (summarized+uploaded+compat)',
    'C5: Clean session (no tool denials / user corrections)',
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
