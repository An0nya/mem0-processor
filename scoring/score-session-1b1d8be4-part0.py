#!/usr/bin/env python3
"""
Accuracy scorer for session 1b1d8be4-part0 summaries.

SESSION: Code review / diagnostic session. User asked Claude to evaluate the
mem0-processor codebase against the CHANGELOG and memory files and identify issues.
Two explicit constraints: NO changes, NO plan file, budget-conscious.

Ground truth facts:
1. User constraint was triple: no changes, no plan file, use-budget-sparingly.
   Claude correctly honored all three throughout. A summary that says Claude
   implemented fixes or wrote a plan file is simply wrong.
2. One file read returned "Large output — persisted to disk" (offset 400, 400 lines)
   — Claude was analyzing a 1544-line file from non-contiguous slices.
3. KV quant: code records `llamaRegistryEntry?.launch.kvQuantK ?? null` (registry
   value) not the resolved `kvQuant` computed in buildLlamaFlags. Models without
   an explicit registry override record null — will corrupt v8 regression data.
4. YAML frontmatter (v7.3 feature) described as shipped in CHANGELOG but absent
   from code — saveCachedSummary only prepends a timestamp line, not a YAML block.
5. batchIndex is off-by-one between success and failure paths: success records
   batchIndex after incrementing; failure records batchIndex - 1 after incrementing.
6. avgSwap formula is a midpoint (startingSwap + maxSwap / 2*count), not a
   running average — samples are taken but thrown away in sampler.stop.
7. Claude correctly identified the top-3 priority before v8: KV quant recording,
   batchIndex consistency, frontmatter (either implement or correct CHANGELOG).
8. Stale memory flagged: project_v9_plan.md (3 days old) said 7b/7c pending
   when CHANGELOG and code confirmed both shipped.

Usage:
  python score-session-1b1d8be4-part0.py                  # auto-discover
  python score-session-1b1d8be4-part0.py file1.txt ...    # score specific files
"""

import re
import sys
from pathlib import Path

SESSION_ID = "1b1d8be4"
PART = "part0"
SUMMARIES_DIR = Path.home() / ".claude/mem0/summaries"
ARCHIVE_DIR = SUMMARIES_DIR / "archive"

CHECKS_DEF = [
    # 1. No-changes constraint honored (and optionally budget noted)
    # Audit: models use circumlocution — adhering/adhered, without attempting/generating,
    # respected this, correctly honored, etc. Original patterns too narrow.
    ('constraint_honored',
     r'(no.changes.{0,30}(honor|correct|comply|follow|respect|adhered)'
     r'|constraint.{0,20}(honor|correct|follow|respected)'
     r'|read.only.{0,20}session'
     r'|evaluation.only'
     r'|diagnostic.only'
     r'|no.changes.{0,20}made'
     r'|correctly.{0,20}(refrained|abstained|avoided).{0,20}(change|modif|edit)'
     r'|no.plan.file.{0,20}(honor|writ|creat)'
     r'|user.{0,20}said.{0,20}no.change'
     r'|adhering.to.{0,30}constraint'
     r'|adhered.to.this'
     r'|without.{0,20}(attempting|making|generat).{0,20}(change|plan|modif|unreq)'
     r'|no.modifications.made'
     r'|respected.{0,10}(this|constraint|it)'
     r'|claude.respected.this'
     r'|correctly.honored'
     r'|honored.{0,10}(all|constraint|it))'
    ),

    # 2. Large output / persisted to disk — read gap
    ('large_output_gap',
     r'(large.output.{0,30}(disk|persist)'
     r'|persisted.to.disk'
     r'|non.contiguous.{0,20}(read|slice|chunk)'
     r'|read.{0,20}gap'
     r'|incomplete.{0,20}(read|file.read)'
     r'|file.{0,20}read.{0,20}(partial|incomplete|gap|missing.chunk)'
     r'|chunk.{0,20}(missing|not.in.context|dropped|lost)'
     r'|1544.line.{0,30}(chunk|slice|partial))'
    ),

    # 3. KV quant: resolved value not recorded in perf store
    # Audit: window too narrow between kv/quant and null/miss; need registry→not-resolved pattern
    ('kv_quant_not_recorded',
     r'(kv.quant.{0,80}(not.record|missing|null|registry.value|wrong)'
     r'|kvQuantK.{0,50}null'
     r'|resolved.{0,40}kv.quant.{0,50}(not|miss|lost|wrong)'
     r'|registry.{0,20}(key|value|entry).{0,50}not.{0,20}(resolv|auto.calcul|the.resolv)'
     r'|records.{0,30}registry.{0,30}(not|instead|rather)'
     r'|registry.value.{0,40}not.resolved'
     r'|perf.{0,20}store.{0,40}kv.quant.{0,40}(null|wrong|miss)'
     r'|kvQuant.{0,40}not.{0,20}record'
     r'|kvQuantK.{0,100}(registry|records)'
     r'|quant.{0,30}v8.{0,30}(corrupt|wrong|miss|broken)'
     r'|auto.calcul.{0,30}(not.record|miss|skip))'
    ),

    # 4. YAML frontmatter: CHANGELOG says shipped, code doesn't have it
    ('frontmatter_discrepancy',
     r'(frontmatter.{0,40}(not.implement|absent|missing|not.in.code|shipped.in.changelog)'
     r'|yaml.{0,30}(not.implement|absent|missing|frontmatter)'
     r'|changelog.{0,30}(wrong|incorrect|mismatch|diverge).{0,30}(frontmatter|yaml|7c)'
     r'|7c.{0,30}(not.implement|missing|absent|shipped.{0,20}changelog)'
     r'|frontmatter.{0,30}only.{0,20}timestamp'
     r'|said.shipped.{0,30}not.implement'
     r'|changelog.claims.{0,30}(done|shipped).{0,30}(frontmatter|yaml))'
    ),

    # 5. batchIndex off-by-one
    # Audit: qwen iq2 uses "batch index parity"; add parity + differ variants
    ('batchindex_offbyone',
     r'(batchIndex.{0,30}(off.by.one|inconsistent|mismatch|wrong|differ|parity)'
     r'|off.by.one.{0,30}batch'
     r'|batchIndex.{0,30}success.{0,30}fail'
     r'|success.{0,20}fail.{0,20}batchIndex.{0,30}inconsist'
     r'|batch.index.{0,30}(off|wrong|inconsist|parity|differ|mismatch)'
     r'|failure.path.{0,30}batchIndex'
     r'|batchIndex.{0,30}minus.one)'
    ),

    # 6. avgSwap midpoint not average
    # Audit: some models say "average swap formula accuracy" without "wrong" — add formula alone
    ('avgswap_formula',
     r'(avgSwap.{0,40}(midpoint|wrong|incorrect|not.average|formula|suspect)'
     r'|midpoint.{0,30}(avgSwap|swap|average)'
     r'|swap.{0,30}(midpoint|formula.wrong|not.average|incorrect.formula)'
     r'|average.swap.{0,40}(wrong|midpoint|incorrect|formula|accuracy)'
     r'|startingSwap.{0,30}maxSwap.{0,30}midpoint'
     r'|avgSwap.{0,20}suspect'
     r'|swap.formula.{0,30}(wrong|midpoint|suspect))'
    ),

    # 7. Top-3 priority correctly identified (KV quant + batchIndex + frontmatter)
    ('top3_priority',
     r'(top.3.{0,30}(fix|priorit|before.v8)'
     r'|three.{0,20}(highest.priorit|most.important|fix.before.v8)'
     r'|priorit.{0,30}(kv.quant|batch|frontmatter).{0,60}(batch|frontmatter|kv)'
     r'|before.v8.{0,40}(kv.quant|batchIndex|frontmatter)'
     r'|biggest.three|biggest.3'
     r'|highest.leverage.{0,30}(kv|batch|front))'
    ),

    # 8. Stale memory file (project_v9_plan.md said 7b/7c pending when shipped)
    # Audit: some models write "stale memories (project_v9_plan.md)" — need bidirectional
    ('stale_memory',
     r'(stale.{0,20}memory.{0,30}(v9|7b|7c|plan)'
     r'|v9.plan.{0,30}(stale|outdated|incorrect|wrong|3.days)'
     r'|3.days.old.{0,30}(stale|wrong|incorrect|v9)'
     r'|7b.{0,10}7c.{0,20}(pending.{0,20}wrong|stale|incorrect|already.done)'
     r'|memory.{0,20}(stale|outdated).{0,30}(v9|plan|7b|7c)'
     r'|project_v9_plan.{0,60}(stale|wrong|3.days|outdated)'
     r'|stale.{0,50}project_v9'
     r'|update.stale.{0,30}(project_v9|memories|plan))'
    ),
]

CHECK_LABELS = [
    'Col 1: No-changes constraint correctly honored',
    'Col 2: Large output / read gap noted (offset 400)',
    'Col 3: KV quant resolved value not recorded in perf store',
    'Col 4: YAML frontmatter — CHANGELOG says shipped, code doesn\'t have it',
    'Col 5: batchIndex off-by-one between success/failure paths',
    'Col 6: avgSwap formula is midpoint not running average',
    'Col 7: Top-3 priority correctly identified (KV quant + batchIndex + frontmatter)',
    'Col 8: Stale memory flagged (v9 plan said 7b/7c pending, actually shipped)',
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

    # Flat summaries dir — match part0 specifically to avoid mixing with part1
    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID}*{PART}*.txt"):
        stem = f.stem
        match = re.search(rf'{SESSION_ID}.+?--(.+)$', stem)
        label = match.group(1) if match else stem
        results.append((f, label))

    # Also match flat naming without explicit part tag (full session IDs)
    for f in SUMMARIES_DIR.glob(f"*{SESSION_ID}*.txt"):
        # Skip part1 files
        if 'part1' in f.name:
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
