#!/usr/bin/env python3
"""
Accuracy scorer for session 2503c51c part1 summaries.

Ground truth facts:
1. isReprocess scoping bug was CLAUDE's error, CLAUDE self-caught — user did not flag it.
   The user's --reprocess pivot changed the architecture and made the scoping gap visible,
   but Claude caught it during its own code inspection of the function call site, in the
   same edit turn. Models that credit the user with catching this are wrong.
2. Claude started implementing --archive-summaries flag before the design was locked —
   user interrupted mid-edit to redirect. This is overreach: files were being modified
   before the user confirmed the implementation approach.
3. The --reprocess linkage idea was the USER's design insight, not Claude's. Claude had
   proposed a dedicated --archive-summaries flag; the user pivoted to the cleaner design.
4. CHANGELOG edit hit a TOOL_ERROR because Claude tried to replace a string that had
   been modified by an earlier rejected edit — Claude didn't re-read the file before
   the second edit attempt.
5. Memory updates (mem0 + local project memory) were user-prompted in aggregate but
   Claude executed multiple tool calls sequentially without pausing for per-call review.
6. v7.1 fully shipped — clean close. All changes committed, memories updated, no open
   implementation threads. User sent a celebratory response signaling genuine satisfaction.

Usage:
  python score-session-2503c51c-part1.py                  # auto-discover in summaries + archive
  python score-session-2503c51c-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "2503c51c-part1"
SESSION_ID_BARE = "2503c51c"
PART_TAG   = "part1"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR   = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. isReprocess bug: Claude wrote it, Claude self-caught — NOT the user
    ('iscope_claude_self_caught',
     r'(claude.{0,60}(self.catch|self.caught|self.correct|caught.own|own.bug|own.error|noticed.{0,30}scope)'
     r'|scope.{0,40}claude.{0,30}(caught|noticed|fixed|corrected)'
     r'|isReprocess.{0,60}(scope|parameter|argument).{0,60}(claude|self|own)'
     r'|claude.{0,40}isReprocess.{0,30}(scope|not.in.scope|out.of.scope|variable)'
     r'|caught.{0,30}(by.claude|itself|own).{0,40}(scope|isReprocess)'
     r'|self.{0,10}(inspect|detect|catch|correct).{0,40}(scope|isReprocess|variable)'
     r'|claude.{0,30}(realized|noticed|spotted).{0,40}(isReprocess|scope|variable.not)'
     r'|not.caught.by.user|user.did.not.catch|user.did.not.flag'
     # tool-mediated self-catch: "caught this via grep", "found via inspect"
     r'|caught.{0,40}(via|through|by).{0,20}(grep|inspect|review|own.code)'
     r'|(claude|self).{0,30}(detect|find|found).{0,30}(scope|isReprocess)'
     # nanbeige/TOOL_ERROR family: scope attributed to Claude, surfaced by tool failure
     r'|scope.{0,40}(error|issue|problem|mismatch).{0,50}(not.user|self.caught|by.claude|own)'
     r'|scope.{0,40}(error|issue).{0,30}(led.to|caused).{0,30}(rework|tool.error|correction)'
     r')'
    ),

    # 2. Premature implementation — Claude edited files before design was locked
    ('premature_implementation',
     r'(before.{0,30}design.{0,20}(lock|confirm|settled|finalized)'
     r'|design.{0,30}not.{0,20}(lock|confirm|settled).{0,30}before.{0,20}(edit|implement|cod)'
     r'|user.{0,30}interrupt.{0,40}(edit|mid.edit|mid.impl)'
     r'|you.{0,30}interrupt.{0,40}(edit|mid.edit|mid.impl|the)'
     r'|interrupt.{0,30}(to.redirect|to.pivot|mid.edit)'
     r'|started.{0,30}(editing|implementing|coding).{0,30}before.{0,30}(user|confirm|lock)'
     r'|moved.{0,30}(too.fast|ahead).{0,30}(into|with).{0,30}(edit|file|impl)'
     r'|implement.{0,30}(flag|approach).{0,30}before.{0,30}(user|confirmed|agreed)'
     r'|claude.{0,30}(jumped|dove|moved).{0,30}(into|to).{0,30}(edit|impl|file)'
     # "moved ahead without asking/confirming", "started editing without confirming scope"
     r'|(moved|went).{0,20}ahead.{0,30}without.{0,20}(ask|confirm|surface|check)'
     r'|started.{0,30}(editing|implementing|coding).{0,30}without.{0,30}(confirm|ask|approv)'
     # "before formally approved", "added code/flag before asking"
     r'|before.{0,20}(formally.approv|user.confirm|confirmed.scope|confirmed.approach)'
     r'|added.{0,20}(code|flag|constant).{0,30}before.{0,30}(ask|confirm|check)'
     r')'
    ),

    # 3. --reprocess linkage was the USER's design insight
    ('user_reprocess_insight',
     r'(user.{0,40}(proposed|suggested|pivot|redirect|came.up|idea).{0,50}reprocess'
     r'|reprocess.{0,40}user.{0,30}(idea|suggestion|pivot|decision|insight)'
     r'|user.{0,30}(not.claude|rather.than.claude|over.claude).{0,30}reprocess'
     r'|link.{0,20}reprocess.{0,40}user.{0,30}(suggest|propos|decid|insight)'
     r'|user.{0,30}(instead|alternative|rather).{0,40}reprocess.{0,30}(flag|linkage|tie)'
     r'|user.{0,30}design.{0,40}(reprocess|flag)'
     r'|user.{0,30}simplif.{0,40}reprocess'
     r'|actually.instead.of.a.flag)'
    ),

    # 4. CHANGELOG TOOL_ERROR — stale string from prior rejected edit
    ('changelog_tool_error',
     r'(changelog.{0,40}(tool.error|TOOL_ERROR|edit.fail|fail.{0,20}edit|error.{0,20}edit)'
     r'|TOOL_ERROR.{0,60}changelog'
     r'|string.{0,30}(not.found|mismatch|stale).{0,40}changelog'
     r'|changelog.{0,40}string.{0,30}(not.found|mismatch|stale|changed)'
     r'|rejected.{0,30}edit.{0,40}changelog.{0,30}(stale|mismatch|error)'
     r'|prior.{0,20}(rejected|denied).{0,30}edit.{0,40}(stale|mismatch|string)'
     r'|edit.{0,20}(failed|error).{0,30}(stale|prior.change|previous.edit)'
     r'|did.not.re.read.{0,30}changelog)'
    ),

    # 5. Memory updates executed without per-call verification
    ('memory_unverified',
     r'(memor.{0,40}without.{0,20}(review|verif|confirm|approv)'
     r'|mem0.{0,40}without.{0,20}(review|verif|confirm)'
     r'|sequential.{0,30}(memory|mem0|tool).{0,20}(call|update).{0,30}(without|no).{0,20}(review|confirm|pause)'
     r'|memory.{0,30}(update|call).{0,30}without.{0,30}(user|review|confirm|approv)'
     r'|multiple.{0,20}(mem0|memory).{0,20}(call|update).{0,30}(no.pause|without.check|unreviewed)'
     # expand radius: catches [CLAUDE-UNPROMPTED] as section label with mem0 in sub-bullet
     r'|unprompted.{0,200}(memor|mem0)'
     r'|CLAUDE.UNPROMPTED.{0,200}(memor|mem0)'
     r'|mem0.{0,30}(no.{0,20}confirm|assumed|executed.without)'
     # vibecoder/nanbeige family: "no go-ahead", "implicit trust"
     r'|(go.ahead|go-ahead).{0,60}(memor|mem0)'
     r'|memor.{0,60}(no.explicit|never.explicit|implicit.trust|no.go.ahead)'
     r'|implicit.trust.{0,60}(memor|mem0)'
     r')'
    ),

    # 6. Clean close / v7.1 fully shipped
    ('clean_close',
     r'(v7\.1.{0,40}(complete|done|shipped|finished|closed|committed)'
     r'|fully.shipped|fully.committed|fully.closed'
     r'|no.open.thread|no.loose.thread|nothing.left.open|all.committed'
     r'|celebrat|gatsby|firework'
     r'|clean.{0,20}(close|end|finish|session|outcome)'
     r'|milestone.{0,20}(complete|done|closed)'
     r'|v7\.1.{0,30}(milestone|wrap|seal))'
    ),
]

CHECK_LABELS = [
    'Col 1: isReprocess bug — Claude wrote & self-caught (not user)',
    'Col 2: Premature implementation — Claude edited before design locked; user interrupted',
    "Col 3: --reprocess linkage was USER's design insight, not Claude's",
    'Col 4: CHANGELOG TOOL_ERROR — stale string from prior rejected edit',
    'Col 5: Memory updates executed without per-call verification',
    'Col 6: v7.1 fully shipped / clean close',
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
    """Score a part1 summary on 6 key facts.

    Returns dict:
      score_norm      float 0–1, higher=better (body only)
      score_norm_raw  float 0–1, higher=better (full content)
      score_raw   int 0–6
      score_max   float(len(CHECKS_DEF))
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

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID_BARE}*{PART_TAG}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID_BARE}.+?{PART_TAG}--(.+)$', stem)
        if not match:
            match = re.search(rf'{PART_TAG}.+?{SESSION_ID_BARE}--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID_BARE}*{PART_TAG}*.txt"):
            model = f.parent.name
            timestamp_match = re.search(
                rf'(?:{SESSION_ID_BARE}.+?{PART_TAG}|{PART_TAG}.+?{SESSION_ID_BARE})--(.+)$', f.stem
            )
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
        print(f"No part1 summary files found for session {SESSION_ID}.")
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

    print("=== ACCURACY SCORES — 2503c51c part1 ===\n")
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
