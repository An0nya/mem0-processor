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

Usage:
  python score-session-3c80a8b6.py                  # auto-discover in summaries + archive
  python score-session-3c80a8b6.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "3c80a8b6"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    ('pgrep_error',     r'(pgrep.*lm.studio|lm.studio.*pgrep|node process|user.*caught|user.*corrected|wrong.*process|electron)'),
    ('rss_inadequate',  r'(rss.*inadequate|ps.*rss.*insufficient|mmap|apple.silicon.*rss|rss.*undercount|unified.memory.*rss|rss.*wrong)'),
    ('machine_crash',   r'(crash|oom|out.of.memory|machine.*died|devstral|kernel.panic)'),
    ('user_ioreg',      r'(user.*ioreg|ioreg.*user|user.*identified|user.*found|user.*provided.*ioreg|\[user\].*ioreg)'),
    ('regex_bugs',      r'(regex.*bug|wrong.*field|field.*name|from iokit|spacing|" = "|=\d)'),
    ('ioreg_validated', r'(8\.6|ioreg.*work|validated|activity.monitor.*match|peak.*gb|gpu.wired)'),
]

CHECK_LABELS = [
    'Col 1: pgrep error (node proc)   Col 2: ps rss inadequate (mmap)',
    'Col 3: Machine crash             Col 4: User brought ioreg',
    'Col 5: Regex bug(s)              Col 6: ioreg validated',
]


def score_summary(content):
    """Score a summary on 6 key facts.

    Returns dict:
      score_norm  float 0–1, higher=better
      score_raw   int 0–6
      score_max   6.0
      checks      {name: bool} one entry per fact
      extra       {} (unused for this session)
    """
    checks = {}
    score = 0
    for name, pattern in CHECKS_DEF:
        hit = bool(re.search(pattern, content, re.I))
        checks[name] = hit
        if hit:
            score += 1

    return {
        'score_norm': score / 6.0,
        'score_raw':  float(score),
        'score_max':  6.0,
        'checks':     checks,
        'extra':      {},
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
