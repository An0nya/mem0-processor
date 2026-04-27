#!/usr/bin/env python3
"""
Accuracy scorer for session 70e8af6a-part5 summaries (zazzy-wishing-koala).

Part5 = perf fixes + calibration analysis + steps 5/6/7a (09:38–09:58).
Continuation from a compacted earlier session.

Ground truth facts:
1. preSessionIdleGb null root cause: guard was `provider === "lmstudio"` but llama
   mode sets `provider: "llama"` (line 1034). The correct fix is `!== "anthropic"`,
   not adding a second `=== "llama"` branch. Same three-location fix: pre-session,
   post-session, and error path.
2. Run 14 "anomaly" was committed to CHANGELOG as a documented finding ("likely
   thermal throttle or transient CPU spike") before the actual cause was known.
   User later recalled setting nGpuLayers=12 for that run (intentional CPU offload
   test). Required a corrective second commit (fd1b2cb) after 167a625. The catch
   mechanism was user memory, not a verification step or automated check.
3. Edit ambiguity TOOL_ERROR: two identical `msg.content`/`msg.reasoning_content`
   extraction blocks existed (one in lmstudio branch, one in llama branch). The
   `replace_all: false` Edit on the llama branch failed with "Found 2 matches."
   Claude had to re-read the file at a specific offset to get enough surrounding
   context to uniquely identify the llama instance.
4. Git commit without `cd` prefix: first commit attempt issued from the wrong
   directory, returning exit code 128 "fatal: not a git repository." Re-ran with
   `cd /Users/anya/Projects/mem0-processor && ...` prefix.
5. Flag over-analysis when user wanted note-taking only. User said the llama-server
   flags were "interesting" and wanted them noted. Claude responded with a full
   categorized deep-dive (reasoning control, MoE memory tricks, speculative
   decoding, perf/telemetry, KV cache). User correction: "i didn't mean right now,
   im more using you as a note taker sorry." Claude then wrote the note.

Note: parts 4 and 5 of this session are contaminated by compaction duplication
in some scorers — this scorer only discovers part5 summaries.

Usage:
  python score-session-70e8af6a-part5.py                  # auto-discover
  python score-session-70e8af6a-part5.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "70e8af6a-part5"
SESSION_ID_BARE = "70e8af6a"
SUMMARIES_DIR   = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR     = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. preSessionIdleGb null: provider === "lmstudio" guard missed "llama"; fix is !== "anthropic"
    ('presession_provider_guard',
     r'(provider.{0,20}(lmstudio|===.{0,10}lmstudio).{0,50}(llama|miss|wrong|null|not.*catch)'
     r'|lmstudio.{0,20}(guard|check|condition).{0,40}(llama|miss|wrong|null)'
     r'|provider.{0,20}llama.{0,20}(not.lmstudio|miss|null|excluded)'
     r'|(!==.{0,10}anthropic|not.*anthropic).{0,40}(fix|correct|right|instead)'
     r'|anthropic.{0,20}(fix|only.exclusion|correct.guard|not.lmstudio)'
     r'|three.{0,20}(location|place|guard|fix).{0,50}(presession|provider|lmstudio)'
     r'|preSessionIdleGb.{0,50}(null|lmstudio|llama|provider|guard|fix)'
     r'|guard.{0,20}(presession|idle|provider).{0,40}(lmstudio|llama|wrong)'
     r'|provider.{0,10}==={0,5}.{0,10}lmstudio.{0,30}(missed|failed|wrong|null)'
     r'|llama.mode.{0,30}(provider|guard|null|idle|preSession))'
    ),

    # 2. Run 14 committed as anomaly/thermal before user revealed nGpuLayers=12; required corrective commit
    ('run14_committed_before_verified',
     r'(run.14.{0,40}(commit|document|logged|anomaly).{0,50}(wrong|incorrect|before|later)'
     r'|commit.{0,40}(anomaly|thermal).{0,40}(before|premature|wrong|corrective)'
     r'|corrective.commit.{0,40}(run.14|anomaly|thermal|nGpuLayers)'
     r'|thermal.{0,30}(committed|logged|wrong|incorrect).{0,40}(run.14|nGpuLayers|user)'
     r'|nGpuLayers.{0,20}12.{0,40}(reveal|recall|user|correct|later|after)'
     r'|user.{0,20}(recall|remembered|revealed).{0,30}(nGpuLayers|12|offload|run.14)'
     r'|two.commit.{0,30}(run.14|anomaly|corrective)'
     r'|fd1b2cb|167a625'
     r'|anomaly.{0,30}(baked|committed|logged|documented).{0,40}(before|incorrect|wrong)'
     r'|catch.mechanism.{0,20}(user.memory|user.recall|memory|recalled)'
     r'|cpu.offload.{0,30}(intentional|test|nGpuLayers|12).{0,40}(recall|user|later)'
     r'|committed.{0,30}(incorrect|wrong|thermal|anomaly).{0,30}(before|premature))'
    ),

    # 3. Edit ambiguity TOOL_ERROR: two identical msg.content blocks; replace_all: false failed
    ('edit_ambiguity_tool_error',
     r'(two.{0,20}(identical|match|instance|block).{0,40}(edit|replace|msg|content)'
     r'|replace_all.{0,20}(false|fail|error|two.match)'
     r'|found.2.match|2.matches'
     r'|msg\.content.{0,30}(two|duplicate|identical|ambiguous)'
     r'|lmstudio.{0,20}(llama.{0,20})?branch.{0,30}(identical|same|duplicate|ambiguous)'
     r'|duplicate.{0,20}(block|string|extraction).{0,40}(edit|replace|lmstudio|llama)'
     r'|ambiguous.{0,20}edit.{0,30}(two|match|replace|msg|content)'
     r'|tool.error.{0,30}(edit|replace|msg|content|two|match)'
     r'|edit.{0,30}(fail|error|ambiguous).{0,30}(two|duplicate|identical|msg)'
     r'|reasoning_content.{0,30}(two|duplicate|identical|ambiguous).{0,30}(match|block|edit)'
     r'|offset.{0,20}(re.read|unique|context).{0,30}(edit|identify|llama)'
     r'|surrounding.context.{0,30}(unique|identify|edit|llama))'
    ),

    # 4. Git commit without cd; exit code 128; re-ran with directory prefix
    ('git_cd_failure',
     r'(git.{0,20}(commit|add).{0,40}(without.cd|cd.missing|wrong.directory|exit.128)'
     r'|exit.code.128'
     r'|not.a.git.repository'
     r'|wrong.{0,15}(directory|dir|cwd).{0,30}(git|commit)'
     r'|cd.{0,30}(missing|prefix|forgot|required).{0,30}git'
     r'|git.{0,20}(outside|from.wrong).{0,30}(repo|directory|dir)'
     r'|fatal.{0,20}not.a.git'
     r'|commit.{0,30}(failed|error|128).{0,30}(directory|cd|cwd|wrong)'
     r'|git.*commit.*exit.128|128.*git.*commit'
     r'|re.ran.{0,20}(cd|directory|prefix).{0,30}(git|commit))'
    ),

    # 5. Flag over-analysis when user wanted note-taking only
    ('flag_overanalysis',
     r'(note.tak.{0,30}(flag|over|analysis|deep.dive|categoriz)'
     r'|over.{0,20}(analyz|deliver|engage).{0,30}(flag|llama.server)'
     r'|user.{0,20}(note.tak|just.not|didn.t.mean.right.now)'
     r'|didn.t.mean.right.now'
     r'|llama.server.flag.{0,40}(over|analysis|deep.dive|note|categoriz)'
     r'|flag.{0,20}(analysis|deep.dive|categoriz).{0,30}(over|user|note|not.asked)'
     r'|user.{0,20}(clarified|corrected|sorry).{0,40}(note.tak|not.now|flag)'
     r'|flag.{0,20}(catalog|categoriz|survey).{0,30}(note|not.request|user.wanted)'
     r'|full.analysis.{0,30}(flag|note|not.asked|over)'
     r'|more.using.you.as.a.note.taker'
     r'|note.taker.{0,30}(flag|llama|over|analysis)'
     r'|over.{0,10}deliver.{0,30}(flag|note|analysis))'
    ),
]

CHECK_LABELS = [
    'Col 1: preSessionIdleGb null — guard was === "lmstudio", missed "llama"; fix is !== "anthropic"',
    'Col 2: Run 14 committed as thermal anomaly before user recalled nGpuLayers=12; required corrective commit',
    'Col 3: Edit ambiguity TOOL_ERROR — two identical msg.content blocks; replace_all:false failed',
    'Col 4: Git commit without cd prefix → exit code 128; re-ran with directory prefix',
    'Col 5: Flag deep-dive when user wanted notes only; user: "im more using you as a note taker"',
]


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
    }


def discover_files():
    results = []
    for pattern in [f"*{SESSION_ID_BARE}*part5*.txt", f"*part5*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            if (f, label) not in results:
                results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part5*.txt", f"*part5*{SESSION_ID_BARE}*.txt"]:
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
