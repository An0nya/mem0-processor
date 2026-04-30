#!/usr/bin/env python3
"""
Accuracy scorer for session 14ea1072-part1 summaries.

Ground truth facts (interaction-dynamics focus):
1. Claude proposed keeping commits (not squashing); user agreed — Claude initiated
   the recommendation, user did not arrive there independently.
   [low-pass filter — soft signal, any mention of the dynamic counts]
2. Claude treated "should we update to have the maxchars pull this data as a hard
   limit?" as a directive and implemented getModelFailCap without explicit
   confirmation — user asked a question, Claude answered with code.
3. The hard cap logic uses the *smallest* failed transcript size as the ceiling
   (not the largest successful, not an average) — a non-obvious implementation
   choice that Claude made without stating the assumption.
4. The tool_use_error (read-before-write) was a system constraint enforced by the
   tool framework, not a Claude process mistake or overreach.
5. Entity name "anya-sessions-v7" was Claude's proposal; user approved with
   "good enough" — user did not originate or specify the name.
6. User identified the script hang; Claude implemented the process.exit(0) fix —
   clean user-diagnosis / Claude-implementation split.

Usage:
  python score-session-14ea1072-part1.py                  # auto-discover in summaries + archive
  python score-session-14ea1072-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "14ea1072-part1"
SESSION_ID_BARE = "14ea1072"
PART = "part1"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Claude proposed keeping commits; user agreed (low-pass — soft signal)
    ('squash_claude_proposed',
     r'(claude.*recommend.*keep|claude.*suggest.*keep.*commit'
     r'|keep.*commit.*claude|claude.*squash.*keep'
     r'|claude.*advised.*not.*squash|not.*squash.*claude'
     r'|squash.*claude.*recommend|claude.*initiated.*keep'
     r'|claude.*proposed.*keep|user.*agreed.*claude.*commit)'),

    # 2. "Should we" treated as directive — implemented without confirmation
    ('should_we_overreach',
     r'(should.we.*implement|treated.*question.*directive'
     r'|implement.*without.*confirm|proceeded.*without.*confirm'
     r'|question.*answered.*with.*code|should.we.*hard.cap'
     r'|getModelFailCap.*without.*confirm|overreach.*hard.cap'
     r'|hard.cap.*overreach|hard.cap.*without.*ask'
     r'|interpreted.*question.*as.*directive)'),

    # 3. Hard cap uses smallest failed transcript size as ceiling
    ('smallest_fail_ceiling',
     r'(smallest.*fail|fail.*smallest|minimum.*fail.*cap'
     r'|min.*transcript.*fail|smallest.*transcript.*fail'
     r'|fail.*min.*chars|getModelFailCap.*smallest'
     r'|smallest.*failed.*transcript|cap.*smallest.*failure'
     r'|lower.*bound.*fail|most.*restrictive.*fail)'),

    # 4. tool_use_error was system constraint, not overreach
    ('tool_error_system_constraint',
     r'(tool.*error.*system|system.*constraint.*tool'
     r'|read.*before.*write.*system|framework.*enforce'
     r'|tool.*enforce.*read|not.*overreach.*tool'
     r'|tool_use_error.*constraint|constraint.*not.*mistake'
     r'|system.*requirement.*read|tool.*requirement.*not.*process)'),

    # 5. Entity name "anya-sessions-v7" was Claude's proposal
    ('entity_name_claude_proposed',
     r'(claude.*proposed.*entity|claude.*suggested.*anya.sessions.v7'
     r'|anya.sessions.v7.*claude|entity.*name.*claude'
     r'|claude.*named.*entity|user.*approved.*entity.*name'
     r'|good.enough.*entity|entity.*good.enough'
     r'|claude.*origin.*entity|claude.*came.up.*v7)'),

    # 6. User identified hang; Claude implemented process.exit fix
    ('hang_user_identified',
     r'(user.*identified.*hang|user.*caught.*hang|user.*reported.*hang'
     r'|user.*noticed.*hang|hang.*user.*diagnos'
     r'|user.*found.*exit|user.*flag.*exit|user.*hang.*claude.*fix'
     r'|process\.exit.*user.*identified|user.*script.*hang'
     r'|user.*doesn.t.*close|user.*not.*exit)'),
]

CHECK_LABELS = [
    'Col 1: Claude proposed keeping commits; user agreed (soft)',
    'Col 2: "Should we" treated as directive — getModelFailCap without confirm',
    'Col 3: Hard cap = smallest failed transcript size (non-obvious choice)',
    'Col 4: tool_use_error was system constraint, not overreach',
    'Col 5: "anya-sessions-v7" was Claude\'s proposal, not user\'s',
    'Col 6: User identified hang; Claude implemented process.exit fix',
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

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID_BARE}*{PART}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID_BARE}*{PART}*.txt"):
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
