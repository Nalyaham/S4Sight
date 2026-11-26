"""SQLite storage. One connection per call keeps things simple and thread-safe."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS readers(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL DEFAULT 'technician'
);
CREATE TABLE IF NOT EXISTS slides(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, site TEXT, stain TEXT DEFAULT 'Ziehl-Neelsen',
  magnification TEXT DEFAULT '1000x', status TEXT NOT NULL DEFAULT 'open',
  started_at REAL NOT NULL, confirmed_at REAL, session_seconds REAL, started_by TEXT,
  model_id INTEGER, demo INTEGER DEFAULT 0,
  ai_grade TEXT, ai_bacilli INTEGER, ai_fields INTEGER,
  final_grade TEXT, confirmed_by TEXT, override_reason TEXT, manual_seconds REAL,
  reference_result TEXT, reference_method TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY, slide_id INTEGER, filename TEXT, path TEXT NOT NULL,
  width INTEGER, height INTEGER, sha256 TEXT, blur_score REAL, quality_flag TEXT,
  status TEXT NOT NULL DEFAULT 'unlabelled', synthetic INTEGER DEFAULT 0,
  source TEXT DEFAULT 'upload', added_at REAL NOT NULL, added_by TEXT,
  last_labelled_by TEXT, site TEXT, field_no INTEGER, consent INTEGER DEFAULT 0,
  UNIQUE(sha256, slide_id)
);
CREATE TABLE IF NOT EXISTS annotations(
  id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL, label TEXT NOT NULL DEFAULT 'afb',
  cx REAL, cy REAL, w REAL, h REAL, reader TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS analyses(
  id INTEGER PRIMARY KEY, slide_id INTEGER NOT NULL, image_id INTEGER NOT NULL, model_id INTEGER,
  inference_ms REAL, total_ms REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS detections(
  id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, image_id INTEGER NOT NULL,
  cx REAL, cy REAL, w REAL, h REAL, conf REAL, status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS review_items(
  id INTEGER PRIMARY KEY, detection_id INTEGER, image_id INTEGER NOT NULL,
  cx REAL, cy REAL, w REAL, h REAL, conf REAL,
  status TEXT NOT NULL DEFAULT 'open', resolution TEXT, created_at REAL, disputed_after INTEGER
);
CREATE TABLE IF NOT EXISTS review_votes(
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, reader TEXT NOT NULL, vote TEXT NOT NULL,
  created_at REAL, UNIQUE(item_id, reader)
);
CREATE TABLE IF NOT EXISTS dataset_versions(
  id INTEGER PRIMARY KEY, name TEXT, created_at REAL, seed INTEGER, path TEXT,
  n_train INTEGER, n_val INTEGER, n_test INTEGER, includes_synthetic INTEGER DEFAULT 0,
  config TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS dataset_images(
  version_id INTEGER NOT NULL, image_id INTEGER NOT NULL, split TEXT NOT NULL,
  PRIMARY KEY(version_id, image_id)
);
CREATE TABLE IF NOT EXISTS models(
  id INTEGER PRIMARY KEY, name TEXT, path TEXT, base TEXT, created_at REAL,
  dataset_version_id INTEGER, run_id INTEGER, metrics TEXT, status TEXT NOT NULL DEFAULT 'candidate',
  demo INTEGER DEFAULT 0, approved_by TEXT, approved_at REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS training_runs(
  id INTEGER PRIMARY KEY, dataset_version_id INTEGER, params TEXT, status TEXT NOT NULL DEFAULT 'queued',
  epoch INTEGER DEFAULT 0, epochs INTEGER DEFAULT 0, message TEXT, pid INTEGER,
  started_at REAL, finished_at REAL, model_id INTEGER, history TEXT DEFAULT '[]', error TEXT, started_by TEXT
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts REAL, reader TEXT, action TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_slide ON images(slide_id);
CREATE INDEX IF NOT EXISTS idx_ann_image ON annotations(image_id);
CREATE INDEX IF NOT EXISTS idx_det_image ON detections(image_id);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def db():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with db() as con:
        con.executescript(SCHEMA)
        cols = [r[1] for r in con.execute("PRAGMA table_info(review_items)").fetchall()]
        if "disputed_after" not in cols:
            con.execute("ALTER TABLE review_items ADD COLUMN disputed_after INTEGER")
        if con.execute("SELECT COUNT(*) FROM readers").fetchone()[0] == 0:
            con.execute("INSERT INTO readers(name, role) VALUES('Lab technician','technician')")
            con.execute("INSERT INTO readers(name, role) VALUES('Senior reader','senior')")
            con.execute("INSERT INTO readers(name, role) VALUES('Laboratory lead','lead')")


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def one(cur):
    r = cur.fetchone()
    return dict(r) if r else None


def audit(con, reader, action, detail=""):
    con.execute("INSERT INTO audit(ts, reader, action, detail) VALUES(?,?,?,?)",
                (time.time(), reader or "unknown", action, detail))


def jloads(s, default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default
