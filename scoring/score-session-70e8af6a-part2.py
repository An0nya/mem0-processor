#!/usr/bin/env python3
"""
Accuracy scorer for session 70e8af6a-part2 summaries (zazzy-wishing-koala).

Part2 = steps 2–4 implementation session (06:47–07:10). Strong scorer candidate.

Ground truth facts:
1. High memory pressure / fan activity traced to two models loaded simultaneously
   (LM Studio's 9B qwen + llama-server's 0.8B), NOT a llama-server problem.
   User initially suspected llama-server; revealed the LM Studio model was still
   loaded: "damn, i had a model loaded in lmstudio."
2. Raw response storage (option 3: ~/.claude/mem0/llama-responses/) was user-driven.
   User noticed the visibility gap ("but do we have any save state or visibility
   into what llama returned?"), Claude offered 3 options, user chose option 3.
3. Steps 2 and 3 were collapsed without prior discussion. Claude went straight to
   parsing choices[0].message.content instead of the planned raw JSON dump. User
   noticed ("hold up so did we already do step 3? i thought the summary file would
   be raw json"), Claude confirmed it was a judgment call, user agreed retroactively.
4. llama-server response format uses data.timings.* (predicted_per_second, prompt_ms,
   predicted_ms) — different from LM Studio's data.stats.* — noted as key for step 4.
5. Step 7 scope additions: restart on crash, --llama-fresh per-session restart to
   clear KV cache, fail-fast on server death mid-batch.

Note: parts 4 and 5 of this session are contaminated by compaction duplication —
do not score those parts. This scorer only discovers part2 summaries.

Usage:
  python score-session-70e8af6a-part2.py                  # auto-discover
  python score-session-70e8af6a-part2.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "70e8af6a-part2"
SESSION_ID_BARE = "70e8af6a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. Memory pressure traced to two models loaded simultaneously, not llama-server
    ('memory_pressure_two_models',
     r'(two.model.{0,40}(simultaneously|at.once|both.loaded|concurrent)'
     r'|lmstudio.{0,30}(9b|qwen.9b|loaded|simultaneously).{0,30}(llama|0\.8|pressure)'
     r'|simultaneous.{0,20}(model|lmstudio.and.llama)'
     r'|not.{0,20}llama.server.{0,30}(problem|issue|cause)'
     r'|llama.server.{0,20}(not|wasn.t).{0,20}(problem|issue|cause|fault|culprit)'
     r'|lmstudio.{0,30}(still.running|model.loaded|background|not.closed)'
     r'|two.{0,10}model.{0,20}(wired|metal|memory)'
     r'|memory.pressure.{0,40}(two|both|lmstudio|9b|simultaneously)'
     r'|had.{0,10}(model|9b|qwen).{0,20}(lmstudio|loaded|running)'
     r'|fan.{0,30}(two.model|lmstudio|both|simultaneously))'
    ),

    # 2. Raw response storage: user noticed gap, chose option 3
    ('raw_response_storage_user_driven',
     r'(raw.response.{0,30}(user|option.3|file|storage|visibility)'
     r'|option.3.{0,30}(raw|llama.responses|file|user)'
     r'|user.{0,30}(noticed|identified|caught|drove|proposed).{0,40}(raw|visibility|response.storage)'
     r'|visibility.{0,30}(gap|llama.return|raw|response).{0,30}user'
     r'|llama.responses.{0,20}(dir|directory|folder|file)'
     r'|save.state.{0,30}(visibility|raw|user|gap)'
     r'|user.{0,30}(asked|noticed|caught).{0,30}(no.raw|no.visibility|raw.response|save.state)'
     r'|raw.response.{0,20}(file|dump|storage).{0,20}(user|drove|proposed|option)'
     r'|option.3.{0,30}(user.chose|user.picked|user.selected|user.decided))'
    ),

    # 3. Steps 2 and 3 collapsed without prior discussion; user noticed
    ('steps_2_3_collapsed',
     r'(step.{0,5}(2.and.3|2.3|2\/3|2.+3).{0,30}(collaps|merged|combined|skipped)'
     r'|collaps.{0,30}step.{0,5}(2.and.3|2.3)'
     r'|skip.{0,20}(raw.json|intermediate|step.3)'
     r'|user.{0,30}(noticed|caught|asked).{0,30}(step.3|raw.json|raw.dump|already.done)'
     r'|raw.json.dump.{0,30}(skip|skip.{0,20}step|not.done|bypass)'
     r'|went.straight.to.{0,30}(parse|choices|content)'
     r'|judgment.call.{0,30}(step|collaps|merge|2.3|no.discussion)'
     r'|user.{0,20}retroactiv.{0,20}agree'
     r'|thought.{0,20}(summary|file).{0,20}(would.be|should.be).{0,20}raw.json'
     r'|i.thought.{0,20}(raw|json|step.3))'
    ),

    # 4. llama-server uses data.timings.* not data.stats.* (noted for step 4)
    ('llama_timings_format',
     r'(data\.timings|timings\.\*|timings\.\w+'
     r'|predicted_per_second|prompt_ms|predicted_ms'
     r'|llama.{0,20}(timings|timing.format|timing.field)'
     r'|timings.{0,20}(llama|different|not.stats|vs.stats)'
     r'|data\.stats.{0,30}(vs|different|lmstudio|not.llama)'
     r'|response.format.{0,30}(different|llama|timings|stats)'
     r'|llama.server.{0,20}(response|format).{0,20}(timings|different|vs)'
     r'|step.4.{0,30}(timings|tps|ttft|genTime|wir)'
     r'|(tps|ttft|genTime).{0,30}(timings|data\.timings|predicted))'
    ),

    # 5. Step 7 scope: restart on crash, --llama-fresh, fail-fast
    ('step7_enhancements',
     r'(step.7.{0,30}(restart|crash|fresh|fail.fast|llama.fresh)'
     r'|restart.on.crash'
     r'|llama.fresh'
     r'|fail.fast.{0,30}(server|crash|death|mid.batch)'
     r'|restart.{0,20}(between.session|per.session|each.session|clear.cache)'
     r'|clear.{0,20}(kv.cache|cache).{0,20}(restart|between|session)'
     r'|crash.{0,20}(restart|recovery|respawn)'
     r'|(earlyExit|early.exit).{0,30}(restart|respawn|detect)'
     r'|abort.{0,30}(session|batch|remain).{0,30}(crash|death|server)'
     r'|flood.{0,20}(error|session).{0,20}(crash|abort))'
    ),
]

CHECK_LABELS = [
    'Col 1: Memory pressure caused by two simultaneous models (LM Studio 9B + llama 0.8B), not llama-server',
    'Col 2: User noticed raw response visibility gap and drove option 3 (llama-responses/ files)',
    'Col 3: Steps 2+3 collapsed without discussion; user noticed ("i thought the summary would be raw json")',
    'Col 4: llama-server uses data.timings.* not data.stats.* (predicted_per_second, prompt_ms, predicted_ms)',
    'Col 5: Step 7 additions: restart on crash, --llama-fresh per-session, fail-fast on server death',
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
    for pattern in [f"*{SESSION_ID_BARE}*part2*.txt", f"*part2*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            if (f, label) not in results:
                results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part2*.txt", f"*part2*{SESSION_ID_BARE}*.txt"]:
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
