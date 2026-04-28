#!/usr/bin/env python3
"""
report.py

Dumps dataset.db into a human-readable markdown report.
No SQL knowledge required to read the output.

Usage:
  python tools/report.py [--db <path>] [--out <path>] [--min-sessions <n>]
"""

import sqlite3
import sys
import math
import statistics
from pathlib import Path
from datetime import datetime

# ─── DEFAULTS ────────────────────────────────────────────────────────────────

DEFAULT_DB  = Path.home() / ".claude/mem0/dataset.db"
DEFAULT_OUT = Path.home() / ".claude/mem0/report.md"
MIN_SESS    = 3

# ─── ARGS ────────────────────────────────────────────────────────────────────

def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

db_path   = Path(arg("--db",  str(DEFAULT_DB)))
out_path  = Path(arg("--out", str(DEFAULT_OUT)))
min_sess  = int(arg("--min-sessions", str(MIN_SESS)))

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def pct(v):
    return f"{v*100:.0f}%" if v is not None else "—"

def fmt(v, decimals=3):
    return f"{v:.{decimals}f}" if v is not None else "—"

def bar(v, width=10):
    if v is None: return " " * width
    filled = round(v * width)
    return "█" * filled + "░" * (width - filled)

def md_table(headers, rows, aligns=None):
    if not rows:
        return "_no data_\n"
    aligns = aligns or ["l"] * len(headers)
    col_w  = [max(len(h), max((len(str(r[i])) for r in rows), default=0))
               for i, h in enumerate(headers)]
    sep_ch = {"l": "-", "r": "-", "c": "-"}
    align_marker = {"l": ":-", "r": "-:", "c": ":-:"}

    def row_str(r):
        return "| " + " | ".join(str(r[i]).ljust(col_w[i]) if aligns[i]=="l"
                                   else str(r[i]).rjust(col_w[i])
                                   for i in range(len(headers))) + " |"

    sep = "| " + " | ".join(align_marker[a] + "-"*(col_w[i]-1)
                              for i, a in enumerate(aligns)) + " |"
    lines = [row_str(headers)] + [sep] + [row_str(r) for r in rows]
    return "\n".join(lines) + "\n"

# ─── MAIN ────────────────────────────────────────────────────────────────────

conn = sqlite3.connect(db_path)
out  = []
w    = out.append

w(f"# mem0-processor score report")
w(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from `{db_path.name}`_\n")

# quick stats
counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
          for t in ("models", "summaries", "perf_runs", "scores")}
w(f"**DB:** {counts['models']} models · {counts['summaries']} summaries "
  f"· {counts['scores']} scores · {counts['perf_runs']} perf runs\n")

# ─── SESSION DIFFICULTY ───────────────────────────────────────────────────────
w("## Session difficulty")
w("Sorted hardest → easiest. `spread` = avg − min (how much models diverge).\n")

rows = conn.execute("""
    SELECT sc.session_id,
           COUNT(DISTINCT sc.model_norm)         AS n,
           ROUND(AVG(sc.score_norm), 3)          AS avg,
           ROUND(MIN(sc.score_norm), 3)          AS min,
           ROUND(MAX(sc.score_norm), 3)          AS max,
           ROUND(AVG(sc.score_norm)-MIN(sc.score_norm), 3) AS spread
    FROM scores sc
    GROUP BY sc.session_id
    HAVING n >= 5
    ORDER BY avg ASC
""").fetchall()

sess_lookup = {}
table_rows = []
for sid, n, avg, mn, mx, spread in rows:
    short = sid[:8]
    sess_lookup[short] = sid
    table_rows.append((short, n, fmt(avg), fmt(mn), fmt(mx), fmt(spread), bar(avg)))

w(md_table(
    ["session", "models", "avg", "min", "max", "spread", "difficulty"],
    table_rows,
    ["l","r","r","r","r","r","l"]
))

# ─── MODEL RANKINGS ───────────────────────────────────────────────────────────
w("## Model rankings (quality pool, ≥ 3 scored sessions)")
w("`z` = z-score vs quality pool (models avg ≥ 0.45). Higher = better relative to peers on same sessions.\n")

# check if score_normed_quality exists
views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()]
if "score_normed_quality" in views:
    view = "score_normed_quality"
else:
    view = "score_normed"

rows = conn.execute(f"""
    SELECT sn.model_norm,
           COUNT(DISTINCT sn.session_id)    AS n_sess,
           ROUND(AVG(sn.score_norm), 3)     AS raw_avg,
           ROUND(AVG(sn.z_score), 3)        AS z_avg,
           ROUND(MIN(sn.score_norm), 3)     AS raw_min,
           ROUND(MAX(sn.score_norm), 3)     AS raw_max,
           m.source,
           ROUND(m.file_size_gb, 1)         AS gb,
           m.tags
    FROM {view} sn
    LEFT JOIN models m ON m.model_norm = sn.model_norm
    GROUP BY sn.model_norm
    HAVING n_sess >= {min_sess}
    ORDER BY z_avg DESC
""").fetchall()

table_rows = []
for norm, n, raw, z, mn, mx, src, gb, tags in rows:
    src_short = (src or "?")[:3]
    gb_str    = f"{gb}G" if gb else "?"
    table_rows.append((norm[:52], n, fmt(raw), fmt(z), fmt(mn), fmt(mx), src_short, gb_str))

w(md_table(
    ["model", "sess", "raw", "z", "min", "max", "src", "size"],
    table_rows,
    ["l","r","r","r","r","r","l","r"]
))

# ─── COVERAGE MATRIX ─────────────────────────────────────────────────────────
w("## Coverage matrix (quality candidates, scored sessions)")
w("Score shown per session. `—` = not run.\n")

# quality candidates only
qc_models = [r[0] for r in conn.execute("""
    SELECT model_norm FROM scores
    WHERE model_norm IN (
        SELECT model_norm FROM models WHERE tags LIKE '%quality-candidate%'
    )
    GROUP BY model_norm
    HAVING COUNT(DISTINCT session_id) >= 1
    ORDER BY AVG(score_norm) DESC
""").fetchall()]

# sessions with enough coverage
scored_sessions = [r[0] for r in conn.execute("""
    SELECT session_id FROM scores
    GROUP BY session_id
    HAVING COUNT(DISTINCT model_norm) >= 5
    ORDER BY AVG(score_norm) ASC
""").fetchall()]

# build lookup
cell = {}
for norm in qc_models:
    for row in conn.execute("""
        SELECT s.filename, sc.score_norm
        FROM scores sc JOIN summaries s ON sc.summary_id = s.id
        WHERE sc.model_norm = ?
    """, (norm,)).fetchall():
        parts = row[0].replace(".txt","").split("--")
        key = f"{parts[0]}--{parts[1]}" if len(parts) >= 3 else parts[0]
        cell[(norm, key)] = row[1]

# shorten session keys
def short_sess(sid):
    return sid.split("--")[1][:8] if "--" in sid else sid[:8]

sess_shorts = [short_sess(s) for s in scored_sessions]
unique_short = []
seen_s = set()
for s in sess_shorts:
    if s not in seen_s:
        unique_short.append(s)
        seen_s.add(s)

# map short → full session keys that match
sess_key_map = {}
for full in scored_sessions:
    sh = short_sess(full)
    sess_key_map.setdefault(sh, []).append(full)

headers = ["model"] + unique_short
table_rows = []
for norm in qc_models:
    row = [norm.split("/")[-1][:35] if "/" in norm else norm[:35]]
    for sh in unique_short:
        keys = sess_key_map.get(sh, [])
        scores = [cell.get((norm, k)) for k in keys if (norm, k) in cell]
        if scores:
            row.append(fmt(max(scores)))
        else:
            row.append("—")
    table_rows.append(row)

w(md_table(headers, table_rows))

# ─── SESSION DETAIL ───────────────────────────────────────────────────────────
w("## Per-session top performers")
w("Top 5 models per session by score, with z vs quality pool.\n")

for sid, in conn.execute("""
    SELECT DISTINCT session_id FROM scores
    GROUP BY session_id HAVING COUNT(DISTINCT model_norm) >= 5
    ORDER BY AVG(score_norm) ASC
""").fetchall():
    short = sid[:8]
    rows = conn.execute(f"""
        SELECT sn.model_norm, sn.score_norm, sn.z_score
        FROM {view} sn
        WHERE sn.session_id = ?
        ORDER BY sn.score_norm DESC, sn.z_score DESC
        LIMIT 5
    """, (sid,)).fetchall()
    if not rows: continue
    sess_avg = conn.execute("SELECT ROUND(AVG(score_norm),3) FROM scores WHERE session_id=?", (sid,)).fetchone()[0]
    w(f"### `{short}` (session avg {sess_avg})")
    table_rows = [(r[0][:55], fmt(r[1]), fmt(r[2]) if r[2] else "—") for r in rows]
    w(md_table(["model","score","z"], table_rows, ["l","r","r"]))

# ─── NEW / THIN MODELS ────────────────────────────────────────────────────────
w("## Models with 1–2 scored sessions (need more coverage)")
rows = conn.execute("""
    SELECT sc.model_norm,
           COUNT(DISTINCT sc.session_id) AS n,
           ROUND(AVG(sc.score_norm), 3)  AS avg,
           m.source
    FROM scores sc
    LEFT JOIN models m ON m.model_norm = sc.model_norm
    GROUP BY sc.model_norm
    HAVING n BETWEEN 1 AND 2
    ORDER BY avg DESC
""").fetchall()
table_rows = [(r[0][:55], r[1], fmt(r[2]), r[3] or "?") for r in rows]
w(md_table(["model","sess","avg","src"], table_rows, ["l","r","r","l"]))

conn.close()

out_path.write_text("\n".join(out) + "\n")
print(f"Report written to {out_path}")
print(f"  {len(out)} sections, {out_path.stat().st_size // 1024} KB")