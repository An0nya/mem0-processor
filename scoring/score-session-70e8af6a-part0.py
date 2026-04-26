#!/usr/bin/env python3
"""
Accuracy scorer for session 70e8af6a-part0 summaries (zazzy-wishing-koala).

Part0 = planning session (05:26–06:20). Weaker scorer material than parts 2/3
(few crispy errors, mostly decisions). Useful primarily as a framing check.

Ground truth facts:
1. Session was a v9 planning session: programmatic model launch via llama-server
   (llama.cpp), not LM Studio. User kicked it off, Claude assessed blockers.
2. llama-server was already installed on the machine via Homebrew at
   /opt/homebrew/bin/llama-server — no installation needed.
3. User's initial "run hog wild" autonomy grant was immediately qualified and
   ultimately reversed to wanting active involvement and approval on each step.
4. The default model was changed from gemma (initial plan) to qwen 0.8B for
   faster iteration — user's decision, made mid-session.
5. Claude searched/read compaction summaries to recover the v8/v9 ordering
   rationale (v9 before v8 so v9 provides clean no-model baseline for v8
   regression). This was recovered from context rather than documentation.

Note: only 2 models have summaries for this part. Scorer value grows once
more models are run.

Usage:
  python score-session-70e8af6a-part0.py                  # auto-discover
  python score-session-70e8af6a-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "70e8af6a-part0"
SESSION_ID_BARE = "70e8af6a"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. v9 planning session: programmatic model launch via llama-server
    ('v9_llama_server_planning',
     r'(v9.{0,30}(plan|llama.server|programmatic|launch)'
     r'|llama.server.{0,30}(plan|v9|launch|programmatic)'
     r'|programmatic.{0,30}(model.launch|llama)'
     r'|llama.{0,10}(launch|server).{0,30}(planning|plan|discuss)'
     r'|llama.cpp.{0,30}(plan|v9)'
     r'|v9.{0,40}(llama.cpp|llama.server|model.launch)'
     r'|spawn.{0,30}llama|launch.{0,30}llama.server)'),

    # 2. llama-server already installed via Homebrew
    ('llama_server_installed',
     r'(llama.server.{0,30}(install|found|already|available|homebrew|opt.homebrew)'
     r'|homebrew.{0,30}llama.server'
     r'|opt.homebrew.{0,30}llama'
     r'|already.install.{0,30}llama'
     r'|llama.server.{0,30}(present|exist|available).{0,30}(machine|system)'
     r'|no.install.{0,30}(needed|required).{0,30}llama'
     r'|llama.{0,10}server.{0,20}(binary|path|found))'
    ),

    # 3. User reversed "run hog wild" → active involvement
    ('autonomy_reversed_to_active',
     r'(run.hog.wild.{0,60}(reversed|qualified|changed|active|involvement|approv)'
     r'|hog.wild.{0,40}(pulled.back|switched|changed|active)'
     r'|active.involvement.{0,40}(instead|rather|switch|changed|from)'
     r'|wanted.{0,20}approv.{0,30}(instead|rather|not.autonomous)'
     r'|initial.{0,20}(autonomous|autonomy|hog.wild).{0,40}(changed|qualified|reversed|active)'
     r'|user.{0,20}(pulled.back|backtrack|reversed|changed).{0,30}(autonomous|hog.wild|approval)'
     r'|prefer.{0,20}active.{0,20}(involvement|oversight|approv)'
     r'|oscillat|contradictory.signal'
     r'|interrupted.{0,30}(tool|during).{0,30}(clarif|plan|approv)'
     r'|sorry.{0,20}(plan|clarif|want.to.plan))'
    ),

    # 4. Default model changed from gemma to qwen 0.8B
    ('default_model_changed_to_qwen',
     r'(default.model.{0,30}(changed|switched|updated|qwen|0\.8)'
     r'|qwen.{0,10}0\.8.{0,20}(default|changed|chosen|selected)'
     r'|(gemma|initial.model).{0,30}(changed|replaced|switched).{0,30}(qwen|0\.8)'
     r'|qwen.{0,10}0\.8.{0,20}(instead.of.gemma|replace.gemma|not.gemma)'
     r'|0\.8b.{0,20}(default|iteration|fast|chosen)'
     r'|smaller.model.{0,20}(faster|iteration|qwen)'
     r'|model.{0,20}(changed|switch|update).{0,20}(gemma.to.qwen|qwen.0\.8))'
    ),

    # 5. Claude searched compaction summaries to recover v8/v9 ordering
    ('compaction_summary_search',
     r'(compaction.summar.{0,30}(search|read|scan|check|found|recover)'
     r'|read.{0,20}compaction.{0,20}(summar|files?)'
     r'|search.{0,20}compaction.{0,20}(summar|files?)'
     r'|compaction.{0,20}(files?|summar).{0,30}(v8.v9|ordering|rationale|found)'
     r'|v8.v9.ordering.{0,30}(found|recover|compaction)'
     r'|recovered.from.compaction'
     r'|compaction.{0,20}(43|many|multiple).{0,20}(files?|summar)'
     r'|prior.context.{0,30}(search|recover|compaction)'
     r'|scanning.{0,20}(compaction|prior|summary).files?)'
    ),
]

CHECK_LABELS = [
    'Col 1: v9 planning session for programmatic model launch via llama-server',
    'Col 2: llama-server already installed via Homebrew (no install needed)',
    'Col 3: User\'s "run hog wild" reversed to active involvement/approval checkpoints',
    'Col 4: Default model changed from gemma to qwen 0.8B during session',
    'Col 5: Claude searched compaction summaries to recover v8/v9 ordering rationale',
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
    for pattern in [f"*{SESSION_ID_BARE}*part0*.txt", f"*part0*{SESSION_ID_BARE}*.txt"]:
        for f in SUMMARIES_DIR.glob(pattern):
            stem = f.stem
            match = re.search(rf'{SESSION_ID_BARE}--(.+)$', stem)
            label = match.group(1) if match else stem
            if (f, label) not in results:
                results.append((f, label))

    if ARCHIVE_DIR.exists():
        for pattern in [f"*{SESSION_ID_BARE}*part0*.txt", f"*part0*{SESSION_ID_BARE}*.txt"]:
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
