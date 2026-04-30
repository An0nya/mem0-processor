#!/usr/bin/env python3
"""
Accuracy scorer for session 1b1d8be4-part1 summaries.

SESSION: Bug fix session. User described an orphaned llama-server issue and provided
the complete fix design (module-scope _llamaProc + signal handlers). Claude applied it.
Contrasts with part0's read-only diagnostic session.

Ground truth facts:
1. Mode shift: This session involved active file modifications — code was changed.
   Summaries that frame this as another review-only session are wrong.
2. User supplied the complete fix: signal handler block, _llamaProc module-scope
   variable, two sync points in main(), and the exit-handler caveat (process.exit()
   inside an 'exit' listener is a no-op → use SIGINT/SIGTERM with explicit exit).
   This is a strong competence signal; the user diagnosed and designed the fix.
3. Placement clarification: User asked "top of the script where?" twice before
   accepting Claude's answer. This was genuine uncertainty about module scope vs
   main() placement, resolved correctly. Summaries should note this as a friction
   point or competence signal, not ignore it.
4. Three edits applied: (a) signal handler block inserted after setGlobalDispatcher,
   (b) _llamaProc = llamaProc at first launch point, (c) same at --llama-fresh
   relaunch. Inline handlers at ~L1120-1122 were removed as redundant.
5. Claude acted without surfacing the diff: after the placement Q&A, Claude ran
   grep + Read + Edit×3 without showing the changes or asking "ready to proceed?"
   The user accepted without reviewing the actual diff output.
6. No verification step: There was no post-edit check (run the script, test SIGINT).
   The fix is untested in this session.
7. User correctly identified the exit-handler no-op caveat — this is non-obvious
   Node.js behavior that most developers miss.

Usage:
  python score-session-1b1d8be4-part1.py                  # auto-discover
  python score-session-1b1d8be4-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "1b1d8be4"
PART = "part1"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Mode shift correctly noted: this was an active modification session
    # (contrast with part0 read-only). Summaries claiming "no changes" are wrong.
    ('mode_shift_active',
     r'(active.{0,20}(modif|change|edit|fix|implement)'
     r'|code.was.{0,20}(modif|changed|edited|updated)'
     r'|shift.{0,30}(read.only|review.only|diagnostic).{0,30}(modif|change|fix)'
     r'|shift.{0,20}(to|from).{0,20}(active|modif|implement|fix)'
     r'|(implement|applied|executed).{0,30}(fix|change|edit)'
     r'|three.edits|3.edits'
     r'|edits.applied|applied.{0,10}edits'
     r'|made.{0,10}(three|3).{0,10}(edit|change)'
     r'|read.only.{0,30}(contrast|shift|versus|unlike|follow.on)'
     r'|(earlier|prior|part0|part.0).{0,40}(read.only|no.changes|review)'
     r'|fix.was.{0,20}(implement|applied|complet))'
    ),

    # 2. User provided the complete fix design (not Claude's idea)
    ('user_provided_fix',
     r'(user.{0,20}(provid|wrote|supply|suppli|design|diagnos).{0,30}(fix|solution|code|handler|approach)'
     r'|user.{0,20}(already.knew|independently.knew|knew.the.fix)'
     r'|(fix|solution).{0,20}(came.from|provided.by|supplied.by).{0,20}user'
     r'|user.wrote.{0,30}(signal|handler|code)'
     r'|user.{0,20}proposed.{0,30}(fix|approach|solution|handler)'
     r'|user.diagnosed.{0,30}(issue|problem|bug|orphan)'
     r'|complete.{0,20}(fix|solution).{0,30}(user|provid|already)'
     r'|user.{0,20}(had|has).{0,20}(the.fix|full.fix|complete.fix|exact.code)'
     r'|implementation.guidance.rather.than.problem.solving)'
    ),

    # 3. Placement clarification: user asked "where?" twice, was a genuine
    # uncertainty about module scope vs. function scope
    ('placement_clarification',
     r'(top.of.the.script.where'
     r'|where.{0,10}(twice|2.times|repeated|again)'
     r'|placement.{0,30}(question|clarif|uncertain|ask)'
     r'|asked.{0,10}(twice|two.times|again).{0,30}(where|placement|location)'
     r'|module.scope.{0,30}(vs|versus|or).{0,30}(main|function)'
     r'|placement.uncertain'
     r'|(where.to.put|where.to.insert|where.to.place).{0,30}(signal|handler|code)'
     r'|asked.for.clarif.{0,30}(exact|specific).{0,30}(placement|location)'
     r'|(above.functions|below.global).{0,30}(confirm|clarif|question|ask))'
    ),

    # 4. Three edits: signal block + two _llamaProc sync points (+ inline removal)
    ('three_edits',
     r'(three.{0,20}edit|3.{0,20}edit'
     r'|three.{0,20}(change|modif|location|point)'
     r'|(signal.handler.{0,60}(two|2).{0,20}(assign|sync|point|launch))'
     r'|(_llamaProc.{0,50}(two|2|both).{0,20}(point|location|assign|launch))'
     r'|(two.{0,20}(assign|sync|launch).{0,50}_llamaProc)'
     r'|three.separate.{0,20}edit'
     r'|(signal.block|handler.block).{0,60}(first|initial).{0,20}launch'
     r'|(first.launch|initial.launch).{0,40}(relaunch|fresh|llama.fresh)'
     r'|removed.{0,20}(inline|redundant).{0,20}handler)'
    ),

    # 5. Claude acted without surfacing diff / skipped approval step
    ('no_diff_shown',
     r'(without.{0,20}(show|display|surfac).{0,20}(diff|change|edit)'
     r'|diff.{0,20}(not.shown|never.shown|not.reviewed|not.surfaced)'
     r'|(show|display).{0,20}diff.{0,20}(not|never|skip|before)'
     r'|acted.without.{0,20}(confirm|approv|review|show)'
     r'|implicit.approv'
     r'|(approv|confirm).{0,20}(implicit|assumed|without.asking)'
     r'|proceeded.without.{0,20}(showing|confirm|approv)'
     r'|no.{0,10}(diff|review|confirm).{0,20}(step|shown|asked)'
     r'|user.accepted.without.{0,20}(review|see|check).{0,20}(diff|change|actual)'
     r'|changes.were.{0,20}(accepted|approved).{0,20}without.{0,20}(review|see|diff))'
    ),

    # 6. No post-edit verification (fix is untested in session)
    ('no_verification',
     r'(no.{0,20}(test|verif|check|validat).{0,30}(fix|change|handler|signal)'
     r'|fix.{0,20}(untested|not.tested|unverified|not.verif)'
     r'|(test|run|verif).{0,30}(not.done|never.done|not.attempt|pending|skipped)'
     r'|remains.untested'
     r'|no.post.edit'
     r'|without.{0,20}(testing|verifying|running)'
     r'|should.{0,30}(test|verif|run.the.script|sigint|ctrl.c)'
     r'|(ctrl.c|SIGINT).{0,30}(test|verif|check|not.tested)'
     r'|untested.{0,30}(signal|process|cleanup|handler)'
     r'|verify.{0,30}(orphan|process|cleanup|terminat).{0,30}(not.done|pending|needed|should))'
    ),

    # 7. User correctly identified exit-handler no-op caveat
    # (process.exit() in 'exit' listener → no-op/infinite loop; use SIGINT/SIGTERM)
    ('exit_handler_caveat',
     r'(exit.handler.{0,30}(no.op|noop|caveat|infinite.loop|process.exit)'
     r'|process\.exit.{0,40}(no.op|noop|exit.handler|inside.exit|caveat)'
     r'|inside.{0,10}(an.)?exit.{0,20}handler.{0,20}(no.op|noop|infinite|loop)'
     r'|exit.listener.{0,30}(no.op|noop|caveat)'
     r'|(no.op|noop).{0,30}(exit.handler|exit.listener)'
     r'|exit.code.{0,20}(130|143)'
     r'|(SIGINT|SIGTERM).{0,30}(exit.code|code.130|code.143))'
    ),

    # 8. Overreach: Claude read file and ran edits before user explicitly asked
    # (user was still in clarification mode when Claude started tool calls)
    ('premature_action',
     r'(read.{0,30}(before|without).{0,30}(ask|approv|confirm|explicit)'
     r'|ran.{0,20}(tool|read|grep|edit).{0,30}(before|without).{0,20}(ask|approv|confirm)'
     r'|tool.call.{0,30}(before|without).{0,20}(ask|approv|confirm)'
     r'|immediately.{0,20}(read|ran|edit|grep).{0,20}(without|before)'
     r'|did.not.{0,20}(ask|confirm|pause).{0,20}(before|before.proceeding)'
     r'|moved.fast|moved.too.fast|acting.too.fast'
     r'|clarif.{0,30}(mode|question).{0,30}(already|immediately|before)'
     r'|jumped.{0,20}(straight|directly|immediately).{0,20}(to.edit|to.read|to.implement)'
     r'|skipped.{0,20}(confirm|approv|check).{0,20}(before.edit|before.implement))'
    ),
]

CHECK_LABELS = [
    'Col 1: Mode shift correctly noted (active modification, not read-only)',
    'Col 2: User provided complete fix design (competence signal)',
    'Col 3: Placement clarification noted ("where?" asked twice)',
    'Col 4: Three edits described (signal block + 2 sync points + inline removal)',
    'Col 5: Claude acted without showing diff / implicit approval noted',
    'Col 6: No post-edit verification noted (fix untested)',
    'Col 7: User correctly identified exit-handler no-op caveat',
    'Col 8: Overreach noted (Claude ran tools before user explicitly asked)',
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
    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID}*{PART}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID}.+?--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID}*.txt"):
        if 'part0' in f.name:
            continue
        if f not in [r[0] for r in results]:
            stem = f.stem
            match = re.search(rf'{SESSION_ID}--(.+)$', stem)
            label = match.group(1) if match else stem
            results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID}*{PART}*.txt"):
            model = f.parent.name
            timestamp_match = re.search(rf'{SESSION_ID}.+?--(.+)$', f.stem)
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
        print(f"No summary files found for session {SESSION_ID} ({PART}).")
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
