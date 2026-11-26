"""Freezing dataset versions (split by slide) and importing YOLO-format data."""
import io
import json
import random
import shutil
import time
import zipfile
from pathlib import Path

from .config import DATASETS_DIR
from .db import db, rows, audit
from .imaging import BadImage, save_image


def eligible_images(con, include_single_read=False, include_synthetic=True):
    """Images that may enter a training set: consent confirmed, not excluded, good enough
    quality, and labelled by two readers (verified) unless single-read labels are allowed."""
    statuses = ("verified", "labelled") if include_single_read else ("verified",)
    q = ",".join("?" * len(statuses))
    sql = (f"SELECT * FROM images WHERE consent=1 AND status IN ({q}) "
           f"AND (quality_flag IS NULL OR quality_flag='' OR synthetic=1)")
    params = list(statuses)
    if not include_synthetic:
        sql += " AND synthetic=0"
    return rows(con.execute(sql, params))


def _split_groups(groups, seed):
    """groups: {group_key: has_positive}. Stratified 70/15/15 split of groups."""
    rng = random.Random(seed)
    out = {}
    for stratum in (True, False):
        keys = sorted(k for k, v in groups.items() if v == stratum)
        rng.shuffle(keys)
        n = len(keys)
        n_test = max(1, round(n * 0.15)) if n >= 4 else (1 if n == 3 else 0)
        n_val = max(1, round(n * 0.15)) if n >= 4 else (1 if n >= 2 else 0)
        for i, k in enumerate(keys):
            out[k] = "test" if i < n_test else ("val" if i < n_test + n_val else "train")
    return out


def preview(include_single_read=False, include_synthetic=True):
    with db() as con:
        imgs = eligible_images(con, include_single_read, include_synthetic)
        pos = 0
        for im in imgs:
            n = con.execute("SELECT COUNT(*) FROM annotations WHERE image_id=? AND label='afb'", (im["id"],)).fetchone()[0]
            pos += 1 if n else 0
        slides = {(f"s{im['slide_id']}" if im["slide_id"] else f"i{im['id']}") for im in imgs}
        return {"images": len(imgs), "positive_images": pos, "negative_images": len(imgs) - pos,
                "groups": len(slides), "synthetic": sum(1 for i in imgs if i["synthetic"])}


def freeze(name, seed, include_single_read, include_synthetic, reader):
    with db() as con:
        imgs = eligible_images(con, include_single_read, include_synthetic)
        if len(imgs) < 12:
            raise ValueError(f"Only {len(imgs)} eligible images. Label and verify at least 12 images first "
                             "(or generate demo images).")
        ann = {}
        groups = {}
        for im in imgs:
            a = rows(con.execute("SELECT cx,cy,w,h FROM annotations WHERE image_id=? AND label='afb'", (im["id"],)))
            ann[im["id"]] = a
            g = (f"s{im['slide_id']}" if im["slide_id"] else f"i{im['id']}")
            groups[g] = groups.get(g, False) or bool(a)
        split_of = _split_groups(groups, seed)
        counts = {"train": 0, "val": 0, "test": 0}
        cur = con.execute(
            "INSERT INTO dataset_versions(name, created_at, seed, path, n_train, n_val, n_test, includes_synthetic, config, created_by) "
            "VALUES(?,?,?,?,0,0,0,?,?,?)",
            (name, time.time(), seed, "", int(any(i["synthetic"] for i in imgs)),
             json.dumps({"include_single_read": include_single_read, "include_synthetic": include_synthetic}), reader))
        vid = cur.lastrowid
        root = DATASETS_DIR / f"v{vid}"
        for s in ("train", "val", "test"):
            (root / "images" / s).mkdir(parents=True, exist_ok=True)
            (root / "labels" / s).mkdir(parents=True, exist_ok=True)
        for im in imgs:
            g = (f"s{im['slide_id']}" if im["slide_id"] else f"i{im['id']}")
            sp = split_of[g]
            counts[sp] += 1
            shutil.copy(im["path"], root / "images" / sp / f"{im['id']}.jpg")
            lines = [f"0 {a['cx']:.6f} {a['cy']:.6f} {a['w']:.6f} {a['h']:.6f}" for a in ann[im["id"]]]
            (root / "labels" / sp / f"{im['id']}.txt").write_text("\n".join(lines))
            con.execute("INSERT INTO dataset_images(version_id,image_id,split) VALUES(?,?,?)", (vid, im["id"], sp))
        (root / "data.yaml").write_text(
            f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: afb\n")
        con.execute("UPDATE dataset_versions SET path=?, n_train=?, n_val=?, n_test=? WHERE id=?",
                    (str(root), counts["train"], counts["val"], counts["test"], vid))
        audit(con, reader, "dataset.freeze", f"v{vid} train={counts['train']} val={counts['val']} test={counts['test']}")
        return {"id": vid, "name": name, "n_train": counts["train"], "n_val": counts["val"],
                "n_test": counts["test"], "slides": len(groups)}


def import_yolo_zip(data: bytes, reader, site, consent):
    """Zip with images/ and labels/ folders (YOLO txt, class 0 = AFB). Imported images are marked
    labelled (one source), so a second reader still verifies them before training."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    labels = {Path(n).stem: n for n in names if n.lower().endswith(".txt") and "label" in n.lower()}
    added = skipped = 0
    with db() as con:
        for n in names:
            if not n.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                info = save_image(zf.read(n))
            except BadImage:
                skipped += 1
                continue
            exists = con.execute("SELECT id FROM images WHERE sha256=? AND slide_id IS NULL", (info["sha256"],)).fetchone()
            if exists:
                skipped += 1
                continue
            cur = con.execute(
                "INSERT INTO images(slide_id, filename, path, width, height, sha256, blur_score, quality_flag, status, "
                "source, added_at, added_by, site, consent, last_labelled_by) VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (Path(n).name, info["path"], info["width"], info["height"], info["sha256"], info["blur_score"],
                 info["quality_flag"], "labelled", "import", time.time(), reader, site, int(bool(consent)), "import"))
            iid = cur.lastrowid
            lab = labels.get(Path(n).stem)
            if lab:
                for line in zf.read(lab).decode("utf-8", "ignore").splitlines():
                    p = line.split()
                    if len(p) >= 5 and p[0] == "0":
                        cx, cy, w, h = (float(x) for x in p[1:5])
                        con.execute("INSERT INTO annotations(image_id,label,cx,cy,w,h,reader,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                    (iid, "afb", cx, cy, w, h, "import", time.time()))
            added += 1
        audit(con, reader, "import.yolo", f"added={added} skipped={skipped}")
    return {"added": added, "skipped": skipped}
