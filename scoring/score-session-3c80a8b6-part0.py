#!/usr/bin/env python3
"""
Accuracy scorer for session 3c80a8b6 summaries.

Ground truth facts:
1. Initial pgrep target was 'LM Studio' process name — wrong; USER caught that the model
   runs as a node process, not the Electron app
2. ps rss= proved inadequate on Apple Silicon — MLX weights are mmap'd, RSS only sees
   CPU-faulted pages (~1.9 GB reported vs 8–12 GB actual)
3. Machine crashed during Devstral/heavy-model inference test
4. USER independently identified the ioreg solution (AGXAccelerator, field names,
   parsing approach) — not a Claude suggestion
5. Two regex bugs in the ioreg implementation: wrong field name suffix, spaces around '='
6. Final ioreg validation succeeded: ~8.64 GB peak matched Activity Monitor

Penalty facts (false claims that should subtract from score):
P1. Claiming Ministral 14B caused the machine crash — the actual machine crash (requiring
    restart) was during the Devstral inference test; Ministral had LM Studio connection
    drops under memory pressure, which is a distinct event.
P2. Claiming Claude introduced or independently discovered the ioreg solution — the user
    brought the complete solution (AGXAccelerator class, field names, Node.js sketch)
    after Claude had been suggesting vmmap and the LM Studio API as alternatives.

Changes from v1:
- Check 5 (regex_bugs): added quote-agnostic patterns for the space-around-= bug so
  summaries that use escaped quotes in code blocks (e.g. \\\"Alloc system memory\\\")
  still match. Specifically added: missing.space, space.{0,10}around.{0,10}=,
  without.{0,10}space, had.no.space.
- Check 4 (user_ioreg): removed AGXAccelerator as a standalone trigger. AGXAccelerator
  appearing anywhere in a summary doesn't establish that the USER brought the solution;
  now requires AGXAccelerator near user-attribution language, or other explicit attribution
  phrases. This fixes false positives where models mention AGXAccelerator while describing
  Claude implementing it.
- Penalty P1: deducts 1 for summaries that claim Ministral 14B caused the machine crash.

Usage:
  python score-session-3c80a8b6-part0.py                  # auto-discover in summaries + archive
  python score-session-3c80a8b6-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "3c80a8b6"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. pgrep targeted 'LM Studio' name — user caught it runs as a node process
    ('pgrep_error',
     r'(pgrep.*lm.studio|lm.studio.*pgrep|node process|user.*caught|user.*corrected|wrong.*process|electron)'),

    # 2. ps rss= inadequate on Apple Silicon — MLX weights mmap'd, RSS only sees faulted pages
    ('rss_inadequate',
     r'(rss.*inadequate|ps.*rss.*insufficient|mmap|apple.silicon.*rss|rss.*undercount|unified.memory.*rss|rss.*wrong)'),

    # 3. Machine crashed during Devstral/heavy-model inference test
    #    Note: Ministral 14B had LM Studio connection drops (distinct from machine crash).
    #    This check now requires either Devstral specifically, or a generic crash near
    #    "heavy model / inference test" language — not just any Ministral mention.
    ('machine_crash',
     r'(devstral.{0,60}(crash|oom|restart|died|rebooted)'
     r'|(crash|oom|out.of.memory|machine.*died|kernel.panic|reboot|restart).{0,60}(devstral|heavy.model|inference.test)'
     r'|machine.{0,20}(crashed|died|rebooted).{0,60}(before|during|while|after).{0,40}(model|inference|test|run))'),

    # 4. USER independently brought the ioreg solution — Claude was still exploring vmmap/API.
    #    Requires user-attribution language alongside ioreg/AGXAccelerator. AGXAccelerator
    #    alone is no longer sufficient (too easy to mention while describing Claude implementing it).
    ('user_ioreg',
     r'(user.{0,50}(brought|provided|introduced|identified|found|discovered|researched|independently).{0,60}(ioreg|AGXAccelerator)'
     r'|(ioreg|AGXAccelerator).{0,60}(brought|provided|identified|found|discovered|researched).{0,30}(by.{0,10}user|user.{0,10}|by.them)'
     r'|user.{0,30}(research|found|brought).{0,30}ioreg'
     r'|ioreg.{0,40}user.{0,30}(brought|provided|solution|independent|research)'
     r'|user.{0,30}(independently|themselves|own.research).{0,60}(ioreg|AGXAccelerator))'),

    # 5. Two regex bugs: wrong field name suffix ("from IOKit" extra), spaces around '='
    #    Expanded to catch quote-agnostic descriptions of the space bug, since some summaries
    #    use escaped quotes in code blocks which breaks the literal \" = \" match.
    ('regex_bugs',
     r'(regex.*bug|wrong.*field|field.*name|from iokit'
     r'|spacing|\" = \"|\\\" = \\\"|=\d'
     r'|missing.{0,5}space|space.{0,10}around.{0,10}='
     r'|without.{0,10}space|had.no.space'
     r'|space.{0,20}(mismatch|issue|wrong|incorrect).{0,20}(regex|format|pattern)'
     r'|two.{0,20}(regex|bug|fix|error|correction))'),

    # 6. ioreg validation succeeded: ~8.64 GB peak matched Activity Monitor
    ('ioreg_validated',
     r'(8\.6[0-9]|activity.monitor.{0,30}(match|align|verified|correct)|ioreg.{0,30}(correct|working|success).{0,30}(gb|memory)|gpu.wired)'),
]

# Penalty checks: each hit subtracts 1 from adjusted score.
PENALTY_DEF = [
    # P1. Claiming Ministral 14B caused the machine crash (restart/reboot).
    #     The actual machine crash was during Devstral; Ministral had LM Studio
    #     connection drops under memory pressure, which is a different event.
    #     Pattern targets explicit "Ministral caused machine crash" attribution,
    #     not just any mention of Ministral having issues.
    ('ministral_machine_crash',
     r'(ministral.{0,40}(machine.crash|machine.crashed|crashed.the.machine|caused.the.crash|system.crash|full.crash|hard.crash|required.restart|forced.restart|machine.restart)'
     r'|machine.{0,20}(crash|crashed|restart|reboot).{0,40}ministral.{0,10}(14b|14 b|inference|run|test|during))'),

]

CHECK_LABELS = [
    'Col 1: pgrep error (node proc)   Col 2: ps rss inadequate (mmap)',
    'Col 3: Machine crash             Col 4: User brought ioreg (attribution required)',
    'Col 5: Regex bug(s)              Col 6: ioreg validated (~8.64 GB)',
]

PENALTY_LABELS = [
    'Pen 1: Claims Ministral 14B caused machine crash (it was Devstral)',
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
      score_norm_raw  float 0–1 (full content, penalty-adjusted)
      score_max       float(len(CHECKS_DEF))
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

    print("=== ACCURACY SCORES ===\n")
    print(f"{'ADJ':>3}  {'RAW':>3}  {'PEN':>3}  CHECKS (1-6)         PENALTIES (P1-P2)  MODEL")
    print("-" * 100)
    for adj, raw, pen, model, checks, penalties in scores:
        check_str   = ' '.join('✓' if v else '✗' for v in checks.values())
        penalty_str = ' '.join('!' if v else '·' for v in penalties.values())
        pen_note    = f"-{int(pen)}" if pen > 0 else "  "
        print(f"{int(adj):>3}  {int(raw):>3}  {pen_note:>3}  {check_str}  {penalty_str}  {model}")

    print("\n=== LEGEND ===")
    print("Checks: ✓ = fact present   ✗ = fact missing")
    print("Penalties: ! = false claim triggered   · = clean")
    for line in CHECK_LABELS:
        print(line)
    for line in PENALTY_LABELS:
        print(line)

    print(f"\n=== SUMMARY ({len(scores)} files, max adjusted = 6) ===")
    print(f"Perfect (6/6): {sum(1 for a,*_ in scores if a == 6)}")
    print(f"Strong  (5/6): {sum(1 for a,*_ in scores if a == 5)}")
    print(f"Good    (4/6): {sum(1 for a,*_ in scores if a == 4)}")
    print(f"Poor   (≤3/6): {sum(1 for a,*_ in scores if a <= 3)}")
    print(f"Any penalty:   {sum(1 for _,_,p,*_ in scores if p > 0)}")


if __name__ == '__main__':
    main()
