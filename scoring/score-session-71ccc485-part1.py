#!/usr/bin/env python3
"""
Accuracy scorer for session 71ccc485-part1 summaries.

Ground truth facts (derived from transcript):
1. Claude read the handoff file at four separate offsets (0/limit:50, 580, 744, 530)
   despite prior context already stating the file ends at line 744. The third read
   confirmed end-of-file; the fourth was a backward probe — at minimum two reads were
   unnecessary.
2. Claude called ToolSearch three separate times — once each for add_memory,
   search_memories, and update_memory — rather than batching discovery or inferring
   from prior context.
3. On 1347d378 (master task blob): Claude proactively flagged it needed extra care and
   paused rather than updating it in the parallel batch. User then said "can you show
   me?" — Claude showed current content before user gave specific direction. Both the
   Claude-side caution and the user-side review request are part of the fact.
4. User said "you can commit that" (line 516); git push to origin happened as TOOL_AUTO
   at line 618 with no explicit push instruction from the user.
5. Five mem0 updates executed in parallel (5449, 5d9c, 0f59, 9f0a, ce38); 1347d378
   handled separately after the show-me exchange and additional user direction.
6. Portability question: user asked whether CHANGELOG would fit in a mem0 entry ->
   resolved as GitHub = source of truth, mem0 = portable summary; user accepted with
   "yeah, this works."

Usage:
  python score-session-71ccc485-part1.py                  # auto-discover in summaries + archive
  python score-session-71ccc485-part1.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID      = "71ccc485-part1"
SESSION_ID_BARE = "71ccc485"
PART = "part1"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Multiple offset reads on handoff file — prior context already named line 744 as end
    ('redundant_file_reads',
     r'(four.{0,20}read|4.{0,20}(offset|read)'
     r'|multiple.{0,20}offset'
     r'|offset.{0,10}(530|580).{0,40}(unneces|redundant|waste|already)'
     r'|re.read.{0,20}handoff'
     r'|read.{0,20}handoff.{0,20}(multiple|again|chunks|four|4|three|3)'
     r'|prior.context.{0,40}(line|744)'
     r'|already.{0,20}(knew|stated|said).{0,30}(end|744|line)'
     r'|single.read.{0,20}suffice|should.have.{0,20}read.{0,20}(once|end|tail))'),

    # 2. ToolSearch called 3x for individual mem0 tools instead of batching
    ('toolsearch_redundancy',
     r'(toolsearch.{0,30}(three|3|multiple|separate|repeat|redundant)'
     r'|three.{0,20}toolsearch|3.{0,20}toolsearch'
     r'|tool.{0,5}search.{0,30}(three|3|separate|redundant|each)'
     r'|separate.{0,20}toolsearch.{0,20}(each|per|for.each)'
     r'|add_memory.{0,60}search_memories|search_memories.{0,60}update_memory'
     r'|called.{0,20}(tool.?search|toolsearch).{0,30}(three|3|multiple|again)'
     r'|tool.discover.{0,30}(three|3|repeat|overhead|separate))'),

    # 3. 1347d378 deferred: Claude proactively paused + user "can you show me?" before update
    ('master_blob_deferred',
     r'(1347|master.status|task.blob|status.blob|master.blob'
     r'|can.you.show|show.me.{0,30}(blob|entry|status|current)'
     r'|claude.{0,30}(flagged|paused|held|deferred).{0,30}(blob|status|1347)'
     r'|blob.{0,30}(care|caution|careful|separately|review)'
     r'|show.{0,20}(before|first|prior).{0,20}(approv|updat|confirm)'
     r'|user.{0,30}(asked|want).{0,30}(see|review|inspect).{0,30}(current|before)'
     r'|update.{0,30}(not.batch|handled.separate|deferred|separately))'),

    # 4. Git push happened without explicit push instruction (user said "commit")
    ('unprompted_push',
     r'(push.{0,30}(unprompted|without.ask|without.approv|not.ask|no.approv|implicit)'
     r'|unprompted.{0,30}push'
     r'|pushed.{0,20}(to.)?origin.{0,30}(without|not.ask|implicit|auto)'
     r'|git.push.{0,30}(unprompted|without|implicit|auto|assumed)'
     r'|user.{0,20}(said|asked).{0,20}commit.{0,40}(not|never|no).{0,20}push'
     r'|commit.{0,30}not.{0,20}push.{0,30}(but|yet|still).{0,20}push'
     r'|push.{0,30}(assumed|inferred).{0,20}(next|step|natural))'),

    # 5. Five mem0 updates in parallel; 1347d378 handled separately / outside batch
    ('parallel_five_one_separate',
     r'(five.{0,20}(mem0|memor|update|parallel)|5.{0,20}(mem0|memor|update|parallel)'
     r'|parallel.{0,20}(five|5|batch|memor)'
     r'|batch.{0,20}(five|5|mem0|update)'
     r'|five.{0,20}(in.)?parallel'
     r'|sixth.{0,20}(separate|outside|deferred|not.batch|handled)'
     r'|update.{0,20}(in.parallel|parallel.update).{0,40}(sixth|one|except)'
     r'|concurrent.{0,20}(mem0|update))'),

    # 6. Portability question -> GitHub source of truth / mem0 portable summary
    ('portability_resolution',
     r'(portab'
     r'|changelog.{0,30}(mem0|fit|portab)'
     r'|mem0.{0,30}changelog'
     r'|source.of.truth.{0,20}(github|git|repo)'
     r'|github.{0,30}source.of.truth'
     r'|(github|git).{0,30}(source|truth).{0,30}(mem0|portab)'
     r'|mem0.{0,20}(portable|summary).{0,30}(github|git|sync)'
     r'|changelog.{0,30}(github|in.repo).{0,30}(portab|access|claude)'
     r'|claude\.ai.{0,30}(access|portab|push))'),
]

CHECK_LABELS = [
    'Col 1: Redundant handoff reads (4 offsets despite prior context naming line 744)',
    'Col 2: ToolSearch called 3x separately for add/search/update_memory',
    'Col 3: 1347d378 — Claude paused + user "can you show me?" before update',
    'Col 4: Git push TOOL_AUTO with no explicit push instruction (user said "commit")',
    'Col 5: Five mem0 updates in parallel; 1347d378 handled separately',
    'Col 6: Portability question -> GitHub=source of truth, mem0=portable summary',
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

    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID_BARE}*{PART}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID_BARE}.+{PART}--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    for f in SUMMARIES_DIR.glob(f"*{PART}*{SESSION_ID_BARE}*.txt"):
        if f not in [r[0] for r in results]:
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}.+{PART}--(.+)$', stem) or \
                    re.search(rf'{PART}--{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            results.append((f, label))

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob(f"*/*{SESSION_ID_BARE}*{PART}*.txt"):
            model = f.parent.name
            timestamp_match = re.search(rf'{SESSION_ID_BARE}.+{PART}--(.+)$', f.stem)
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
    print(f"Poor   (<=3/{max_score}): {sum(1 for s, _, _ in scores if s <= max_score - 3)}")


if __name__ == '__main__':
    main()
