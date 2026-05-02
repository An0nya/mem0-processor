#!/usr/bin/env python3
"""
Accuracy scorer for session 5024455a summaries.

Ground truth facts:
1. Script still had the v6 SUMMARIZATION_PROMPT (flat bullet-list format), not v7
   — the v7 swap had been documented in the handoff notes but never executed
2. User self-identified the omission ("classic me error") — Claude confirmed by
   reading the script, not by catching anything independently
3. User denied the initial git bash call (TOOL_DENIED), then resumed with "continue"
   after checking for spacing issues in the prompt (found none, proceeded)
4. v7 prompt structure: sectioned narrative (Goal / What Happened & Why /
   Competence Signals / Mistakes / Decisions / Open Threads) vs v6 bullet list
5. Commit message explained both what changed (prompt format) and why
   (standalone analytical vs atomic decomposition)

Penalty facts (false claims that should subtract from score):
P1. Claiming the commit failed or required recovery
P2. Claiming no errors or issues occurred (whitewashes the omission + spacing concern)

Usage:
  python score-session-5024455a-part0.py                  # auto-discover in summaries + archive
  python score-session-5024455a-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "5024455a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. v6 prompt still in script (bullet list, not v7 sections)
    ('v6_prompt_present',
     r'(v6.{0,20}prompt'
     r'|prompt.{0,20}v6'
     r'|still.{0,20}(on|using).{0,20}v6'
     r'|old.{0,20}prompt'
     r'|bullet.{0,20}(list|format)'
     r'|flat.{0,20}format'
     r'|never.{0,20}(swapped|replaced|updated).{0,20}prompt'
     r'|prompt.{0,20}(not|never).{0,20}(updated|replaced|swapped))'
    ),

    # 2. User self-caught the omission — Claude confirmed, didn't discover
    ('user_self_caught',
     r'(user.{0,40}(self|own|themselves|classic|acknowledged|identified|caught)'
     r'|classic.{0,20}(me|my).{0,20}error'
     r'|user.{0,30}(forgot|missed|omitted).{0,30}(prompt|swap|step)'
     r'|user.{0,20}noticed.{0,20}(own|their)'
     r'|user.{0,30}(caught|identified).{0,30}miss'
     r'|user.{0,30}(recognized|realised|realized).{0,30}(gap|miss|omission|oversight)'
     r'|user.{0,30}(independently|themselves).{0,30}(identified|noticed|caught|found)'
     r'|self.{0,10}(identified|caught|noticed|aware).{0,30}(gap|miss|omission|error))'
    ),

    # 3. TOOL_DENIED on git bash — user paused to check spacing then resumed
    ('tool_denied_git',
     r'(tool.denied'
     r'|denied.{0,20}(git|bash|command)'
     r'|user.{0,30}(denied|rejected|interrupted).{0,30}(git|bash|commit)'
     r'|user.{0,30}(paused|interrupted).{0,30}(spacing|extra|format)'
     r'|spacing.{0,30}(check|concern|look)'
     r'|interrupted.{0,20}git'
     r'|user.{0,30}interrupt.{0,30}(format|spacing|check|tool)'
     r'|paused.{0,20}(format|check|spacing|tool)'
     r'|interrupt.{0,20}(to check|before|while).{0,20}(format|spacing|file))'
    ),

    # 4. v7 prompt format described (sectioned narrative, specific headers)
    ('v7_prompt_format',
     r'(sectioned.{0,20}(narrative|format)'
     r'|narrative.{0,20}format'
     r'|standalone.{0,20}(analytical|readable|summar)'
     r'|what.happened.{0,20}why'
     r'|competence.signal'
     r'|open.thread[s]?'
     r'|v7.{0,20}(section|format|structure|narrative))'
    ),

    # 5. Commit explained what and why
    # 5. Commit explained what changed and why
    # Extended: also match "descriptive commit message" phrasing (magistral, ministral)
    # and "commit message describing v6/v7" phrasing (format-aware paraphrasers).
    ('commit_quality',
     r'(commit.{0,40}(explain|what|why|clear|good|detailed)'
     r'|commit.{0,30}(message|description).{0,30}(explain|includes)'
     r'|why.{0,20}(changed|swapped|replaced).{0,20}(commit|noted)'
     r'|commit.{0,20}(rationale|reason|context)'
     r'|descriptive.{0,20}(commit|message)'
     r'|commit.{0,40}descriptive'
     r'|commit.{0,30}message.{0,60}(v6|v7|format|prompt))'
    ),
]

# Penalty checks: if matched, subtract 1 from adjusted score.
PENALTY_DEF = [
    # P1. Claiming the commit failed or required recovery
    # (the TOOL_DENIED was on git diff, not the commit — commit succeeded first try)
    # NOTE: bare "denied" removed — fires on "commit (TOOL_DENIED)" describing the bash
    #       interruption, not a commit failure. "did not" removed — fires on
    #       "commit message...the user did not review" (oversight != failure).
    ('commit_failed',
     r'(commit.{0,30}(fail|error|rejected|couldn)'
     r'|commit.{0,20}(attempt.{0,10}fail|was.{0,10}fail)'
     r'|failed.{0,20}(to commit|commit)'
     r'|commit.{0,20}recover'
     r'|commit.{0,10}was.{0,5}denied'
     r'|had to.{0,20}(retry|re.run|redo).{0,20}commit)'
    ),

    # P2. Claiming no errors or issues occurred in the session
    # (the omission itself is an error; the spacing concern is a friction point)
    ('no_errors_occurred',
     r'(no errors?.{0,20}(occurred|were made|in this session|found)'
     r'|no.{0,20}(mistake|issue|problem|error).{0,20}(occurred|found|present|identified)'
     r'|interaction.{0,20}(was.{0,10}(clean|smooth|perfect|flawless|error.free)'
     r'|perfectly.{0,10}executed'
     r'|no.{0,20}overreach.{0,20}occurred))'
    ),
]

CHECK_LABELS = [
    'Col 1: v6 prompt still in script    Col 2: User self-caught omission',
    'Col 3: TOOL_DENIED on git bash      Col 4: v7 prompt format described',
    'Col 5: Commit explained what & why',
]

PENALTY_LABELS = [
    'Pen 1: Claims commit failed (it succeeded first try)',
    'Pen 2: Claims no errors occurred (whitewashes the omission)',
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
    """Score a summary on 5 key facts, with up to 2 penalty deductions.

    Returns dict:
      score_raw       int 0–5  (positive checks only)
      penalty_raw     int 0–2  (penalty hits)
      score_adjusted  int      max(0, score_raw - penalty_raw)
      score_max       5
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
    print(f"{'ADJ':>3}  {'RAW':>3}  {'PEN':>3}  CHECKS (1-5)   PENALTIES (P1-P2)  MODEL")
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
