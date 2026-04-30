#!/usr/bin/env python3
"""
Accuracy scorer for session f36432e7 summaries (eager-sniffing-stream).

Ground truth facts:
1. Session 416d6086 had transcriptChars: 0 (essentially empty) — this caused
   the hallucination, not a model quality issue.
2. Gemma's hallucinated output was a knapsack DP algorithm tutorial —
   completely unrelated to the actual session content.
3. User independently identified the hallucination and traced the root cause
   (empty transcript → model fabricates content).
4. User independently proposed the 500-char cutoff threshold. Claude suggested
   800–1000 as the safe minimum; user chose 500 and accepted some bad data.
5. Claude committed without confirming the commit message. User said "feel free
   to commit" without specifying a message; Claude picked its own and ran.

Usage:
  python score-session-f36432e7.py                  # auto-discover
  python score-session-f36432e7.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "f36432e7-part0"
SESSION_ID_BARE = "f36432e7"
PART            = "part0"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Empty transcript (transcriptChars: 0 / empty log) caused the hallucination
    ('empty_transcript_cause',
     r'(transcript.{0,20}(chars?|length|content|lines?).{0,30}(0|empty|blank|null)'
     r'|empty.{0,20}(transcript|log|session|content)'
     r'|blank.{0,20}(transcript|log|session|content)'
     r'|transcriptChars.{0,10}0'
     r'|0.chars?.{0,20}(transcript|session|log)'
     r'|ghost.session|stub.session'
     r'|no.{0,10}(real|actual|substantive|meaningful).{0,20}(content|messages|exchange)'
     r'|session.was.empty|empty.session.log)'),

    # 2. Hallucinated output was specifically a knapsack DP tutorial
    ('knapsack_hallucination',
     r'(knapsack'
     r'|hallucin.{0,30}(knapsack|dynamic.programming|DP|algorithm|tutorial)'
     r'|knapsack.{0,30}hallucin'
     r'|fabricat.{0,30}(knapsack|DP|algorithm)'
     r'|unrelated.{0,30}(knapsack|tutorial|algorithm)'
     r'|knapsack.problem.{0,50}(hallucin|fabricat|generat|invent))'),

    # 3. User independently caught and identified the root cause
    ('user_identified_root_cause',
     r'(user.{0,30}(identif|caught|noticed|discover|traced|found).{0,50}(root.cause|hallucin|empty|cause)'
     r'|user.{0,30}(independently|alone|themselves|themsel).{0,50}(identif|caught|noticed|found)'
     r'|root.cause.{0,30}(user|traced.by.user|identif.by.user)'
     r'|user.flagged|user.noticed.unexpected|user.spotted'
     r'|catch.mechanism.{0,30}user|caught.by.{0,20}user'
     r'|user.{0,20}(observation|observ).{0,30}(hallucin|empty|unexpected)'
     r'|luck.{0,20}observation|happened.to.look)'),

    # 4. User independently proposed 500-char cutoff (Claude suggested higher)
    ('user_proposed_500_cutoff',
     r'(500.char.{0,20}(cutoff|threshold|minimum|filter|limit)'
     r'|cutoff.{0,20}500'
     r'|minimum.{0,20}500'
     r'|user.{0,20}(proposed|chose|picked|set|decided).{0,30}500'
     r'|500.{0,30}(user|independently|proposed|chose)'
     r'|accept.{0,20}(some.bad|bad.data).{0,30}500'
     r'|500.chars?.{0,30}accept.{0,20}(bad|some)'
     r'|user.set.{0,10}500|set.it.to.500'
     r'|(claude|model|assistant).{0,30}(suggest|recommend).{0,30}(800|1000|higher)'
     r'|800.{0,30}(suggest|recommend).{0,20}user.{0,20}(chose|picked|selected|set).500)'),

    # 5. Overreach: Claude committed without confirming the commit message
    ('commit_overreach',
     r'(commit.{0,30}(without|no).{0,30}(confirm|ask|check|verify|approv)'
     r'|commit.{0,30}overreach'
     r'|overreach.{0,30}commit'
     r'|(commit.message|message.commit).{0,30}(not.confirm|unconfirm|without.asking|own.message)'
     r'|feel.free.to.commit.{0,50}(without|no|own|self)'
     r'|proceeded.to.commit.{0,30}without'
     r'|committed.{0,30}(without.asking|without.confirm|own.choice|unprompted.message)'
     r'|claude.{0,20}commit.{0,20}(own|its.own|without.asking|without.confirm)'
     r'|no.pause.{0,30}commit|commit.without.pausing)'),
]

CHECK_LABELS = [
    'Col 1: Empty transcript (transcriptChars: 0) caused the hallucination',
    'Col 2: Hallucinated output was a knapsack DP tutorial',
    'Col 3: User independently identified the root cause',
    'Col 4: User independently proposed the 500-char cutoff (Claude had suggested 800–1000)',
    'Col 5: Claude committed without confirming commit message (overreach)',
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
    for pattern in [f"*{SESSION_ID_BARE}*{PART}*.txt", f"*{PART}*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            if (f, label) not in results:
                results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*{PART}*.txt", f"*{PART}*{SESSION_ID_BARE}*.txt"]:
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
