#!/usr/bin/env python3
"""
build-dataset.py

Builds ~/.claude/mem0/dataset.db from:
  - summaries/         YAML-headered summary files (post-2026-04-23 only, no archive)
  - perf.json          per-run performance records
  - config/models-registry.json  model metadata
  - scoring/           session scoring scripts

Rebuilds from scratch on every run. Safe to re-run.

Usage:
  python build-dataset.py [--db <path>]
"""

import json
import re
import sys
import sqlite3
import importlib.util
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml required: pip install pyyaml")
    sys.exit(1)

# ─── PATHS ───────────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).parent.parent
MEM0_DIR      = Path.home() / ".claude/mem0"
SUMMARIES_DIR = MEM0_DIR / "summaries"
PERF_PATH     = MEM0_DIR / "perf.json"
REGISTRY_PATH = SCRIPT_DIR / "config/models-registry.json"
SCORING_DIR   = SCRIPT_DIR / "scoring"
DEFAULT_DB    = MEM0_DIR / "dataset.db"

# YAML header presence is the cutoff filter — files with YAML were produced after 2026-04-23
# when the header was introduced. started_at is the original session time, not production time.

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def normalize_id(s):
    """Lowercase, collapse non-alphanumeric runs to '-', trim edges."""
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def parse_yaml_header(content):
    """Extract and parse the leading ---...--- YAML block. Returns dict or None."""
    if not content.startswith('---'):
        return None
    end = content.find('\n---', 3)
    if end == -1:
        return None
    try:
        return yaml.safe_load(content[3:end])
    except Exception:
        return None


def load_scorers():
    """Import score_summary from each scoring/score-session-*.py.
    Returns {session_id: fn}."""
    scorers = {}
    if not SCORING_DIR.exists():
        return scorers
    for p in sorted(SCORING_DIR.glob("score-session-*.py")):
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            scorers[mod.SESSION_ID] = mod.score_summary
        except Exception as e:
            print(f"  Warning: could not load {p.name}: {e}")
    return scorers


# ─── SCHEMA ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE models (
    model_norm   TEXT PRIMARY KEY,
    model_key    TEXT,
    tags         TEXT,
    source       TEXT,
    file_path    TEXT,
    file_size_gb REAL,
    quant_type   TEXT,
    arch         TEXT,
    model_type   TEXT,
    ctx_size     INTEGER
);

CREATE TABLE summaries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path         TEXT UNIQUE,
    filename          TEXT,
    session_id        TEXT,
    session_slug      TEXT,
    model_norm        TEXT,
    model_raw         TEXT,
    started_at        TEXT,
    ended_at          TEXT,
    run_tag           TEXT,
    transcript_chars  INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens  INTEGER,
    tps               REAL,
    ttft              REAL,
    gen_time          REAL,
    ctx_size          INTEGER,
    max_output_tokens INTEGER,
    kv_quant_k        TEXT,
    kv_quant_v        TEXT,
    temp              REAL,
    min_p             REAL,
    top_k             INTEGER,
    cache_hit         TEXT,
    provider          TEXT,
    FOREIGN KEY (model_norm) REFERENCES models(model_norm)
);

CREATE TABLE perf_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_norm          TEXT,
    model_key           TEXT,
    session_id          TEXT,
    ts                  TEXT,
    idle_gb             REAL,
    pre_session_idle_gb REAL,
    peak_gb             REAL,
    avg_gb              REAL,
    ttft                REAL,
    gen_time            REAL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    reasoning_tokens    INTEGER,
    tps                 REAL,
    transcript_chars    INTEGER,
    loaded_context      INTEGER,
    starting_swap       REAL,
    max_swap            REAL,
    peak_pressure       INTEGER,
    pressure_avg        REAL,
    FOREIGN KEY (model_norm) REFERENCES models(model_norm)
);

CREATE TABLE scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id  INTEGER,
    session_id  TEXT,
    model_norm  TEXT,
    score_norm  REAL,
    score_raw   REAL,
    score_max   REAL,
    checks_json TEXT,
    extra_json  TEXT,
    FOREIGN KEY (summary_id) REFERENCES summaries(id)
);

CREATE INDEX idx_summaries_session ON summaries(session_id);
CREATE INDEX idx_summaries_model   ON summaries(model_norm);
CREATE INDEX idx_summaries_started ON summaries(started_at);
CREATE INDEX idx_summaries_run_tag ON summaries(run_tag);
CREATE INDEX idx_perf_session      ON perf_runs(session_id);
CREATE INDEX idx_perf_model        ON perf_runs(model_norm);
CREATE INDEX idx_scores_session    ON scores(session_id);
CREATE INDEX idx_scores_model      ON scores(model_norm);
"""

# ─── LOADERS ─────────────────────────────────────────────────────────────────

def load_models(conn):
    reg = json.loads(REGISTRY_PATH.read_text())
    rows = []
    for key, entry in reg.items():
        rows.append((
            normalize_id(key),
            key,
            json.dumps(entry.get('tags', [])),
            entry.get('source'),
            entry.get('path'),
            entry.get('fileSizeGb'),
            entry.get('quantType'),
            entry.get('arch'),
            entry.get('modelType'),
            entry.get('launch', {}).get('ctxSize'),
        ))
    conn.executemany(
        "INSERT OR IGNORE INTO models VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    return len(rows)


def load_summaries(conn):
    inserted = skipped_no_yaml = 0
    archive_dir = SUMMARIES_DIR / "archive"

    for f in sorted(SUMMARIES_DIR.glob("*.txt")):
        content = f.read_text(errors='replace')
        if 'TRANSCRIPT FORMAT' in content[:200] or len(content) < 500:
            continue

        meta = parse_yaml_header(content)
        if not meta:
            skipped_no_yaml += 1
            continue

        started_str = str(meta.get('started_at') or meta.get('startedAt') or '')

        stem = f.stem
        parts = stem.split('--')
        if len(parts) >= 3:
            session_slug     = parts[0]
            session_id_short = parts[1]
        elif len(parts) == 2:
            session_slug     = None
            session_id_short = parts[0]
        else:
            session_slug     = None
            session_id_short = stem

        session_id = str(meta.get('session') or session_id_short)
        model_raw  = str(meta.get('model') or '')
        model_norm = normalize_id(model_raw) if model_raw else normalize_id(parts[-1] if parts else '')

        conn.execute(
            """INSERT OR IGNORE INTO summaries
               (file_path, filename, session_id, session_slug, model_norm, model_raw,
                started_at, ended_at, run_tag, transcript_chars,
                prompt_tokens, completion_tokens, reasoning_tokens,
                tps, ttft, gen_time, ctx_size, max_output_tokens,
                kv_quant_k, kv_quant_v, temp, min_p, top_k, cache_hit, provider)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(f), f.name, session_id, session_slug, model_norm, model_raw,
                started_str,
                str(meta.get('ended_at') or meta.get('endedAt') or ''),
                str(meta.get('run_tag') or ''),
                meta.get('transcript_chars'),
                meta.get('prompt_tokens'),
                meta.get('completion_tokens'),
                meta.get('reasoning_tokens'),
                meta.get('tps'),
                meta.get('ttft'),
                meta.get('gen_time'),
                meta.get('ctx_size'),
                meta.get('max_output_tokens'),
                str(meta.get('kv_quant_k') or ''),
                str(meta.get('kv_quant_v') or ''),
                meta.get('temp'),
                meta.get('min_p'),
                meta.get('top_k'),
                str(meta.get('cache_hit') or ''),
                str(meta.get('provider') or ''),
            )
        )
        inserted += 1

    return inserted, skipped_no_yaml


def load_perf(conn):
    data = json.loads(PERF_PATH.read_text())
    rows = []
    for model_key, entry in data.items():
        model_norm = normalize_id(model_key)
        for run in entry.get('runs', []):
            rows.append((
                model_norm, model_key,
                run.get('session'),
                run.get('ts'),
                run.get('idleGb'),
                run.get('preSessionIdleGb'),
                run.get('peakGb'),
                run.get('avgGb'),
                run.get('ttft'),
                run.get('genTime'),
                run.get('promptTokens'),
                run.get('completionTokens'),
                run.get('reasoningTokens'),
                run.get('tps'),
                run.get('transcriptChars'),
                run.get('loadedContext'),
                run.get('startingSwap'),
                run.get('maxSwap'),
                run.get('peakPressure'),
                run.get('pressureAvg'),
            ))
    conn.executemany(
        """INSERT INTO perf_runs
           (model_norm, model_key, session_id, ts, idle_gb, pre_session_idle_gb,
            peak_gb, avg_gb, ttft, gen_time, prompt_tokens, completion_tokens,
            reasoning_tokens, tps, transcript_chars, loaded_context,
            starting_swap, max_swap, peak_pressure, pressure_avg)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows
    )
    return len(rows)


def load_scores(conn, scorers):
    if not scorers:
        return 0

    # Split into part-aware (SESSION_ID like "abc123-part0") and plain scorers.
    # Part-aware scorers match on both session_id substring and a part tag in the filename.
    _part_re = re.compile(r'^(.+)-(part\d+)$')
    part_scorers  = {}   # (base_id, part_tag) -> fn
    plain_scorers = {}   # session_id -> fn
    for sid, fn in scorers.items():
        m = _part_re.match(sid)
        if m:
            part_scorers[(m.group(1), m.group(2))] = fn
        else:
            plain_scorers[sid] = fn

    rows = conn.execute(
        "SELECT id, file_path, session_id, model_norm FROM summaries"
    ).fetchall()

    scored = 0
    for summary_id, file_path, session_id, model_norm in rows:
        filename = Path(file_path).name
        scorer_fn = None

        for (base_id, part_tag), fn in part_scorers.items():
            if base_id in session_id and f'-{part_tag}-' in filename:
                scorer_fn = fn
                break

        if scorer_fn is None:
            if '-part1-' in filename:
                continue
            for sid, fn in plain_scorers.items():
                if sid in session_id:
                    scorer_fn = fn
                    break

        if not scorer_fn:
            continue

        try:
            content = Path(file_path).read_text(errors='replace')
            result = scorer_fn(content)
        except Exception as e:
            print(f"  Warning: scoring failed for {Path(file_path).name}: {e}")
            continue

        conn.execute(
            """INSERT INTO scores
               (summary_id, session_id, model_norm, score_norm, score_raw, score_max,
                checks_json, extra_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                summary_id, session_id, model_norm,
                result['score_norm'], result['score_raw'], result['score_max'],
                json.dumps(result['checks']),
                json.dumps(result.get('extra', {})),
            )
        )
        scored += 1

    return scored


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    db_path = DEFAULT_DB
    if '--db' in sys.argv:
        i = sys.argv.index('--db')
        if i + 1 < len(sys.argv):
            db_path = Path(sys.argv[i + 1])

    if db_path.exists():
        db_path.unlink()

    print(f"Building {db_path}")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    print("  Loading models...")
    n = load_models(conn)
    print(f"    {n} models")

    print("  Loading summaries...")
    inserted, no_yaml = load_summaries(conn)
    print(f"    {inserted} inserted  |  {no_yaml} skipped (no YAML or too short)")

    print("  Loading perf runs...")
    n = load_perf(conn)
    print(f"    {n} runs")

    print("  Loading scorers...")
    scorers = load_scorers()
    print(f"    {len(scorers)} session scorer(s): {', '.join(scorers) or 'none'}")
    n = load_scores(conn, scorers)
    print(f"    {n} summaries scored")

    conn.commit()
    conn.close()

    size_kb = db_path.stat().st_size // 1024
    print(f"\nDone — {db_path} ({size_kb} KB)")
    print(f"\nQuick stats:")
    conn2 = sqlite3.connect(db_path)
    for table in ('models', 'summaries', 'perf_runs', 'scores'):
        count = conn2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<12} {count}")
    conn2.close()


if __name__ == '__main__':
    main()
