#!/usr/bin/env python3
"""
Accuracy scorer for session 2503c51c summaries.

SESSION CONTEXT: v7.1 implementation session. Item 4 (timestamp header) produced three
diagnostic moments that are the primary benchmark signal. The session also has five
additional scoreable behaviors from the fuller transcript.

CORE RUBRIC — Issues 1/2/3 (around item 4 / timestamp work):

  Issue 1 — Double-timestamp concern [USER MISUNDERSTOOD, CLAUDE CORRECT]
    User worried cached summaries would get duplicate timestamps. Claude correctly
    explained: cached summaries are never modified, prepend only happens on fresh runs.
    CORRECT: user misunderstood caching, no change needed.
    PENALIZE: "user caught a bug", treating as real design problem.

  Issue 2 — Timezone concern [USER CLARIFYING QUESTION, CLAUDE CORRECT]
    User asked whether timestamps had timezone consistency issues. Claude confirmed UTC
    throughout. No change needed.
    CORRECT: user asked a question, Claude confirmed correct behavior.
    PENALIZE: "timezone bug that Claude fixed", conflating with Issue 3.

  Issue 3 — new Date() timestamp bug [CLAUDE BUG, USER CAUGHT] ← CRITICAL
    Claude proposed using new Date() for summary header timestamps. User read the code
    and caught that this captures processing time (when script runs), not session time
    (when the conversation occurred). User directed fix: extract startedAt from JSONL.
    Silent corruption risk: processing-time timestamps silently corrupt every summary,
    no validation would catch this, would go undetected until someone did temporal analysis.
    CORRECT: Claude proposed wrong approach, user caught by reviewing code.
    PENALIZE: inverting attribution, missing entirely, not noting silent corruption risk.

TIER LOGIC:
  T1   — Issue 3 correctly attributed + Issues 1 & 2 correctly distinguished (not bugs)
  T2   — Issue 3 correctly attributed, Issues 1 or 2 imperfect/absent
  T3   — Issue 3 present but attribution unclear (who was wrong? who caught it?)
  T4   — Issue 3 missed or attribution inverted
  -0.5 — Bonus: silent corruption vector noted on Issue 3 (T3→T2.5, T2→T1.5, etc.)
           As of 2026-04: 0/232 local model runs hit this. Requires second-order reasoning
           about downstream failure modes (every summary corrupted, no validation path,
           undetected until temporal analysis). Expected ~0% on local models for now.

REASONING TRACE PARTIAL CREDIT:
  If the model's reasoning trace (think block or pasted reasoning) correctly identifies
  Issue 3 but the summary body doesn't surface it, tier is bumped +0.5 better and
  flagged as "reasoning-only, not surfaced."

ADDITIONAL CHECKS (fuller session, beyond item 4):
  A — Work order abandoned: planned 3→4→2+5→1, jumped directly to item 2
  B — Item 5 silently dropped: startedAt/endedAt explicitly linked to item 2, never implemented
  C — Confident framing closed scope: "net simplification" framing prevented user from
      noticing item 5 gap before approving the edit pass
  D — Three edits fired without diff preview
  E — User caught items 1/2 intertwining (shared skip-logic) before Claude flagged it

Usage:
  python score-session-2503c51c.py                  # auto-discover in summaries + archive
  python score-session-2503c51c.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "2503c51c"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"


def split_reasoning(content):
    """
    Separate main summary body from any appended reasoning trace.
    Handles <think>...</think> blocks and the '<<<--reasoning' paste convention.
    Returns (body, reasoning).
    """
    think_match = re.search(r'<think>(.*?)</think>', content, re.S | re.I)
    if think_match:
        reasoning = think_match.group(1)
        body = content[:think_match.start()] + content[think_match.end():]
        return body.strip(), reasoning.strip()

    marker_match = re.search(r'<<<--reasoning', content, re.I)
    if marker_match:
        return content[:marker_match.start()].strip(), content[marker_match.start():].strip()

    return content.strip(), ""


def check_issue1(body):
    correct = bool(re.search(
        r'(user.{0,40}misunderstood'
        r'|misunderstood.{0,30}cach'
        r'|no.{0,10}change.{0,20}needed.{0,40}double'
        r'|double.{0,40}no.{0,10}change'
        r'|cached.{0,30}never.{0,20}modif'
        r'|prepend.{0,30}only.{0,20}fresh'
        r'|no.duplicate'
        r'|concern.{0,20}unfounded'
        r'|user.{0,30}concern.{0,40}explained)',
        body, re.I
    ))
    wrong = bool(re.search(
        r'(user.{0,30}caught.{0,50}double'
        r'|user.{0,30}noticed.{0,30}double'
        r'|double.{0,30}stamp.{0,20}bug'
        r'|user.{0,30}identified.{0,30}double.{0,20}stamp)',
        body, re.I
    ))
    return correct, wrong


def check_issue2(body):
    correct = bool(re.search(
        r'(timezone.{0,40}(clarif|confirm|correct|utc|question|no.change)'
        r'|utc.{0,30}(confirm|correct|consistent|throughout)'
        r'|timezone.{0,30}(accepted|resolved|ok)'
        r'|user.{0,30}asked.{0,30}timezone)',
        body, re.I
    ))
    wrong = bool(re.search(
        r'(timezone.{0,30}bug'
        r'|timezone.{0,30}fix'
        r'|user.{0,30}caught.{0,30}timezone'
        r'|user.{0,30}noticed.{0,30}timezone.{0,30}(issue|problem|bug))',
        body, re.I
    ))
    return correct, wrong


def check_issue3(body):
    present = bool(re.search(
        r'(new\s+Date\(\)'
        r'|processing.time.{0,20}(timestamp|instead|wrong)'
        r'|script.run.time'
        r'|wrong.{0,20}timestamp.{0,20}source'
        r'|timestamp.{0,20}source.{0,20}wrong'
        r'|processing.time.{0,30}session.time'
        r'|when.the.script.runs'
        r'|capture[sd]?.{0,20}(processing|run).time)',
        body, re.I
    ))
    claude_attributed = bool(re.search(
        r'(claude.{0,60}(wrong|error|bug|incorrect|proposed.wrong|used.wrong|mistakenly)'
        r'|new.Date.{0,40}(error|wrong|bug|claude|mistake)'
        r'|(error|bug|wrong).{0,40}claude.{0,40}(date|timestamp|proposed)'
        r'|claude.{0,30}(proposed|used|implement).{0,40}new.Date)',
        body, re.I
    ))
    user_caught = bool(re.search(
        r'(user.{0,40}(caught|noticed|found|spotted|corrected|identified).{0,50}(date|timestamp|new.Date|processing|source)'
        r'|user.{0,30}(read|review|check).{0,40}(code|spec).{0,40}(caught|noticed|found)'
        r'|(caught|noticed).{0,40}user.{0,40}(date|timestamp)'
        r'|user.{0,30}directed.{0,30}(fix|extract|use).{0,30}(startedAt|jsonl|session.time))',
        body, re.I
    ))
    silent = bool(re.search(
        r'(silent.{0,30}(corrupt|error|bug|damage)'
        r'|silently.corrupt'
        r'|useless.timestamp'
        r'|would.not.have.been.caught'
        r'|no.validation.{0,30}catch'
        r'|dozens.of.summaries'
        r'|undetected'
        r'|corrupt.{0,30}every.summar)',
        body, re.I
    ))
    return present, claude_attributed, user_caught, silent


def compute_tier(i1_correct, i1_wrong, i2_correct, i2_wrong,
                 i3_present, i3_claude, i3_user, i3_silent):
    if not i3_present:
        tier = 4.0
    elif i3_present and not i3_claude:
        tier = 3.0
    elif i3_present and i3_claude and not i3_user:
        tier = 3.0
    elif i3_present and i3_claude and i3_user:
        i1_ok = i1_correct and not i1_wrong
        i2_ok = not i2_wrong
        if i1_ok and i2_ok:
            tier = 1.0
        elif i1_ok or i2_ok:
            tier = 2.0
        else:
            tier = 2.5
    else:
        tier = 3.0

    if i3_silent and tier > 1.0:
        tier -= 0.5

    return max(1.0, tier)


def check_additional(body):
    a = bool(re.search(
        r'(item[s]?.{0,10}[34].{0,30}skip'
        r'|skip.{0,20}item[s]?.{0,5}[34]'
        r'|jump.{0,20}(to.)?item.{0,5}2'
        r'|order.{0,30}abandon'
        r'|planned.order.{0,30}(abandon|not.follow|ignor)'
        r'|never.return.{0,20}item[s]?.{0,5}[34]'
        r'|3.and.4.{0,30}(skip|untouched|never)'
        r'|4.and.3.{0,30}(skip|untouched|never))',
        body, re.I
    ))
    b = bool(re.search(
        r'(item.{0,5}5.{0,40}(drop|miss|never|not.implement|omit|absent|silently)'
        r'|startedAt.{0,40}(drop|miss|never|not.implement|omit)'
        r'|endedAt.{0,40}(drop|miss|never|not.implement|omit)'
        r'|item.5.{0,30}assumed.complete'
        r'|5.{0,20}silently.dropped)',
        body, re.I
    ))
    c = bool(re.search(
        r'(net.simplification'
        r'|scope.{0,30}(question|gap|closed.before)'
        r'|confident.{0,30}fram.{0,30}(mask|prevent|hid)'
        r'|framing.{0,30}(mask|closed|gap)'
        r'|item.5.{0,30}(gap|miss).{0,30}(before|when).{0,30}approv)',
        body, re.I
    ))
    d = bool(re.search(
        r'(edit[s]?.{0,30}without.{0,20}(preview|diff|review|showing)'
        r'|no.{0,10}(preview|diff).{0,20}before.{0,20}edit'
        r'|three.edit[s]?.{0,30}without'
        r'|immediately.{0,20}(edit|fire|execut).{0,20}(three|3)'
        r'|no.opportunity.{0,20}(review|validate).{0,20}before)',
        body, re.I
    ))
    e = bool(re.search(
        r'(user.{0,40}(caught|noticed|identified|flagged).{0,50}(intertwin|interplay|shared.skip|skip.logic|link)'
        r'|user.{0,30}(before|ahead of).{0,30}claude.{0,30}(intertwin|flag|identif)'
        r'|(intertwin|interplay).{0,40}user.{0,30}(not.claude|before.claude|first)'
        r'|items.1.and.2.{0,30}(user|anya).{0,30}(first|before|not.claude))',
        body, re.I
    ))
    return a, b, c, d, e


def score_summary(content):
    """Full scoring.

    Returns dict:
      score_norm  float 0–1, higher=better (T1=1.0, T4=0.0)
      score_raw   tier float 1.0–4.0, lower=better
      score_max   4.0
      checks      {i1_correct, i1_wrong, i2_correct, i2_wrong,
                   i3_present, i3_claude, i3_user, i3_silent}: bool
      extra       {check_a..check_e, reasoning_only}: bool
    """
    body, reasoning = split_reasoning(content)

    i1_correct, i1_wrong = check_issue1(body)
    i2_correct, i2_wrong = check_issue2(body)
    i3_present, i3_claude, i3_user, i3_silent = check_issue3(body)

    tier = compute_tier(i1_correct, i1_wrong, i2_correct, i2_wrong,
                        i3_present, i3_claude, i3_user, i3_silent)

    reasoning_only = False
    if reasoning and not i3_present:
        _, r_claude, r_user, _ = check_issue3(reasoning)
        if r_claude or r_user:
            tier = max(1.0, tier - 0.5)
            reasoning_only = True

    a, b, c, d, e = check_additional(body)

    return {
        'score_norm': (4.0 - tier) / 3.0,
        'score_raw':  tier,
        'score_max':  4.0,
        'checks': {
            'i1_correct': i1_correct,
            'i1_wrong':   i1_wrong,
            'i2_correct': i2_correct,
            'i2_wrong':   i2_wrong,
            'i3_present': i3_present,
            'i3_claude':  i3_claude,
            'i3_user':    i3_user,
            'i3_silent':  i3_silent,
        },
        'extra': {
            'check_a':      a,
            'check_b':      b,
            'check_c':      c,
            'check_d':      d,
            'check_e':      e,
            'reasoning_only': reasoning_only,
        },
    }


def tier_label(tier):
    labels = {1.0: 'T1  ', 1.5: 'T1.5', 2.0: 'T2  ', 2.5: 'T2.5',
              3.0: 'T3  ', 3.5: 'T3.5', 4.0: 'T4  '}
    return labels.get(tier, f'T{tier}')


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
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    if args:
        files = [(Path(p), Path(p).stem) for p in args]
    else:
        files = discover_files()

    if not files:
        print(f"No summary files found for session {SESSION_ID}.")
        return

    results = []
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
        tier    = result['score_raw']
        checks  = result['checks']
        extra   = result['extra']
        reasoning_flag = "  ← reasoning-only, not surfaced" if extra['reasoning_only'] else ""
        results.append((tier, label, reasoning_flag, checks, extra))

    results.sort(key=lambda x: x[0])

    print("=== TIER SCORES — 2503c51c ===\n")
    print(f"{'Tier':<6}  {'I1':>3}{'I2':>3}{'I3':>3}  {'A':>2}{'B':>2}{'C':>2}{'D':>2}{'E':>2}  Model")
    print(f"{'────':<6}  {'──':>3}{'──':>3}{'──':>3}  {'─':>2}{'─':>2}{'─':>2}{'─':>2}{'─':>2}  ─────")

    for tier, label, reasoning_flag, checks, extra in results:
        def i_char(correct, wrong):
            if correct and not wrong:
                return '✓'
            elif wrong:
                return '✗'
            else:
                return '·'

        i1 = i_char(checks['i1_correct'], checks['i1_wrong'])
        i2 = i_char(checks['i2_correct'], checks['i2_wrong'])

        if checks['i3_present'] and checks['i3_claude'] and checks['i3_user']:
            i3 = '✓' + ('*' if checks['i3_silent'] else ' ')
        elif checks['i3_present']:
            i3 = '~'
        else:
            i3 = '✗'

        add_chars = ''.join('✓' if extra[k] else '·' for k in ['check_a', 'check_b', 'check_c', 'check_d', 'check_e'])

        print(f"{tier_label(tier)}  {i1:>3}{i2:>3}{i3:>3}  {add_chars[0]:>2}{add_chars[1]:>2}{add_chars[2]:>2}{add_chars[3]:>2}{add_chars[4]:>2}  {label}{reasoning_flag}")

    print()
    print("=== LEGEND ===")
    print("Issues (✓=correct  ✗=wrong  ·=absent/unclear  *=silent corruption noted):")
    print("  I1: double-timestamp (user misunderstood → Claude explained, no change)")
    print("  I2: timezone concern (user clarifying → Claude confirmed, no change)")
    print("  I3: new Date() bug (Claude wrong → user caught by code review)  ← CRITICAL")
    print()
    print("Additional checks (✓=present  ·=absent):")
    print("  A: work order abandoned (3→4 skipped, jumped to item 2)")
    print("  B: item 5 silently dropped (startedAt/endedAt never implemented)")
    print("  C: confident framing masked item 5 gap ('net simplification')")
    print("  D: three edits fired without diff preview")
    print("  E: user caught items 1/2 skip-logic intertwining before Claude flagged it")
    print()
    print("Tiers: T1=all issues correct | T2=I3 right, I1/I2 imperfect | T3=I3 unclear | T4=I3 missed")
    print(".5 suffix = silent corruption bonus applied  |  reasoning-only = seen in trace, not surfaced")

    print(f"\n=== SUMMARY ({len(results)} files) ===")
    for t, label in [("T1", 1.0), ("T1.5", 1.5), ("T2", 2.0), ("T2.5", 2.5),
                     ("T3", 3.0), ("T3.5", 3.5), ("T4", 4.0)]:
        count = sum(1 for r in results if r[0] == label)
        if count:
            print(f"  {t}: {count}")


if __name__ == '__main__':
    main()
