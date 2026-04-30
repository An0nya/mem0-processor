#!/usr/bin/env python3
"""
Patch all CHECKS_DEF scorers to add split_reasoning + normalize_entity_names
and emit dual scores (score_norm = body-only, score_norm_raw = full content).

Run with --dry-run to preview diffs without writing.
"""

import sys
import difflib
from pathlib import Path

SCORING_DIR = Path(__file__).parent.parent / "scoring"

HELPERS = '''\
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
    trace_match = _re.search(r'```reasoning-trace\\s*(.*?)(?:```|$)', content, _re.S | _re.I)
    if trace_match:
        reasoning = trace_match.group(1).strip()
        body = content[:trace_match.start()] + content[trace_match.end():]
        return body.strip(), reasoning
    return content.strip(), ""


def normalize_entity_names(text):
    import re as _re
    text = _re.sub(r\'\\b(the|an)\\s+assistant\\b\', \'Claude\', text, flags=_re.I)
    text = _re.sub(r"\\bassistant\'s\\b", "Claude\'s", text, flags=_re.I)
    text = _re.sub(
        r\'\\bI\\s+(used|proposed|wrote|assumed|inserted|implemented|suggested\'
        r\'|started|jumped|initially|mistakenly|wrongly|began|made|read|tried)\',
        lambda m: \'Claude \' + m.group(1),
        text, flags=_re.I
    )
    text = _re.sub(
        r\'\\b(corrected|caught|told|stopped|interrupted|directed)\\s+me\\b\',
        r\'\\1 Claude\', text, flags=_re.I
    )
    return text


'''

STANDARD_OLD = '''\
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
    }'''

STANDARD_NEW = '''\
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
    }'''

PENALTY_OLD = '''\
    checks = {}
    hits = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, content, re.I))
        checks[name] = hit
        if hit:
            hits += 1

    penalties = {}
    pen_hits = 0
    for name, pattern in PENALTY_DEF:
        hit = bool(re.search(pattern, content, re.I))
        penalties[name] = hit
        if hit:
            pen_hits += 1

    adjusted = max(0, hits - pen_hits)

    return {
        'score_raw':      float(hits),
        'penalty_raw':    float(pen_hits),
        'score_adjusted': float(adjusted),
        'score_max':      float(len(CHECKS_DEF)),
        'checks':         checks,
        'penalties':      penalties,
    }'''

PENALTY_NEW = '''\
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
    }'''

SKIP = {"score-session-2503c51c-part0.py", "score-session-2503c51c-part1.py"}
PENALTY_FILES = {"score-session-47b98ba9.py", "score-session-3c80a8b6-part0.py", "score-session-5024455a-part0.py"}


def patch_file(path, dry_run):
    original = path.read_text()
    name = path.name

    is_penalty = name in PENALTY_FILES
    old_body   = PENALTY_OLD if is_penalty else STANDARD_OLD
    new_body   = PENALTY_NEW if is_penalty else STANDARD_NEW

    if old_body not in original:
        print(f"  SKIP {name}: score_summary body not matched")
        return False

    # Insert helpers before def score_summary
    marker = "def score_summary(content):"
    insert_at = original.index(marker)
    patched = original[:insert_at] + HELPERS + original[insert_at:]

    # Replace old score_summary body with new
    patched = patched.replace(old_body, new_body, 1)

    if patched == original:
        print(f"  UNCHANGED {name}")
        return False

    if dry_run:
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            n=2,
        )
        print(f"\n--- diff {name} ---")
        sys.stdout.writelines(diff)
    else:
        path.write_text(patched)
        print(f"  PATCHED {name}")

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"=== patch-scorers.py ({mode}) ===\n")

    files = sorted(p for p in SCORING_DIR.glob("score-session-*.py") if p.name not in SKIP)
    ok = skipped = 0
    for f in files:
        result = patch_file(f, dry_run)
        if result:
            ok += 1
        else:
            skipped += 1

    print(f"\n{'Would patch' if dry_run else 'Patched'}: {ok}  Skipped: {skipped}")
    print("(2503c51c-part0 and 2503c51c-part1 handled separately)")


if __name__ == "__main__":
    main()
