"""SmearSight: TB smear screening web app. Run with:  python run.py"""
import csv
import hashlib
import io
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import datasets, grading, imaging, inference, synth
from .config import (BASE_DIR, CONF_FLOOR, CONF_POSITIVE, CONF_REVIEW, DATA_DIR, PIN, STATIC_DIR)
from .db import audit, db, init_db, jloads, one, rows

app = FastAPI(title="SmearSight", version="1.0")
init_db()

DEMO_BANNER = ("DEMO model: trained on synthetic pictures. Not for diagnostic use.")


# ------------------------------------------------------------------ access PIN (optional)
def _token():
    return hashlib.sha256(("smearsight:" + PIN).encode()).hexdigest()[:32]


LOGIN_HTML = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>SmearSight</title>
<body style="font-family:system-ui;background:#0F2A33;display:grid;place-items:center;height:100vh;margin:0">
<form method=post action=/login style="background:#fff;padding:32px;border-radius:12px;width:280px;display:grid;gap:14px">
<h2 style="margin:0">SmearSight</h2><label>Access PIN<input name=pin type=password autofocus
style="width:100%;box-sizing:border-box;padding:12px;font-size:16px;margin-top:6px"></label>
<button style="padding:12px;font-size:16px;background:#0B6E78;color:#fff;border:0;border-radius:8px">Enter</button>{msg}</form>"""


@app.middleware("http")
async def pin_gate(request: Request, call_next):
    if PIN and request.url.path not in ("/login",):
        if request.cookies.get("ss_auth") != _token():
            if request.url.path.startswith("/api"):
                return JSONResponse({"detail": "PIN required"}, status_code=401)
            return RedirectResponse("/login")
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML.replace("{msg}", "")


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    if PIN and form.get("pin") == PIN:
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("ss_auth", _token(), httponly=True, samesite="lax", max_age=60 * 60 * 12)
        return r
    return HTMLResponse(LOGIN_HTML.replace("{msg}", "<p style='color:#B42318;margin:0'>Wrong PIN.</p>"), status_code=401)


def who(request: Request):
    name = request.headers.get("x-reader", "").strip()
    return name or "Lab technician"


def reader_role(con, name):
    r = one(con.execute("SELECT role FROM readers WHERE name=?", (name,)))
    return r["role"] if r else "technician"


# ------------------------------------------------------------------ helpers
def counted(det):
    return det["status"] in ("kept", "added") or (det["status"] == "pending" and det["conf"] >= CONF_POSITIVE)


def slide_fields(con, slide_id):
    imgs = rows(con.execute("SELECT * FROM images WHERE slide_id=? ORDER BY field_no, id", (slide_id,)))
    for im in imgs:
        an = one(con.execute("SELECT * FROM analyses WHERE image_id=? ORDER BY id DESC LIMIT 1", (im["id"],)))
        im["analysis"] = an
        im["detections"] = rows(con.execute("SELECT * FROM detections WHERE image_id=? ORDER BY conf DESC", (im["id"],))) if an else []
    return imgs


def slide_detail(con, slide_id):
    s = one(con.execute("SELECT * FROM slides WHERE id=?", (slide_id,)))
    if not s:
        raise HTTPException(404, "Slide not found")
    fields = slide_fields(con, slide_id)
    counts = [sum(1 for d in f["detections"] if counted(d)) for f in fields if f["analysis"]]
    ai_counts = [sum(1 for d in f["detections"] if d["conf"] >= CONF_POSITIVE) for f in fields if f["analysis"]]
    s["fields"] = fields
    s["suggested"] = grading.grade_slide(counts)
    s["ai_only"] = grading.grade_slide(ai_counts)
    s["elapsed_seconds"] = (s["confirmed_at"] or time.time()) - s["started_at"]
    m = one(con.execute("SELECT id, name, demo FROM models WHERE id=?", (s["model_id"],))) if s["model_id"] else None
    s["model"] = m
    return s


def create_analysis(con, slide, image_id, image_path, model):
    res = inference.detect(image_path, model)
    if res is None:
        return None
    dets, inf_ms, tot_ms = res
    cur = con.execute("INSERT INTO analyses(slide_id,image_id,model_id,inference_ms,total_ms,created_at) VALUES(?,?,?,?,?,?)",
                      (slide["id"], image_id, model["id"], inf_ms, tot_ms, time.time()))
    aid = cur.lastrowid
    for d in dets:
        c2 = con.execute("INSERT INTO detections(analysis_id,image_id,cx,cy,w,h,conf,status) VALUES(?,?,?,?,?,?,?,'pending')",
                         (aid, image_id, d["cx"], d["cy"], d["w"], d["h"], d["conf"]))
        if d["conf"] < CONF_REVIEW:
            con.execute("INSERT INTO review_items(detection_id,image_id,cx,cy,w,h,conf,status,created_at) VALUES(?,?,?,?,?,?,?,'open',?)",
                        (c2.lastrowid, image_id, d["cx"], d["cy"], d["w"], d["h"], d["conf"], time.time()))
    return aid


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0, (c - a) / d), min(1, (c + a) / d)]


def pct(x, q):
    if not x:
        return None
    x = sorted(x)
    k = (len(x) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return x[f] if f == c else x[f] + (x[c] - x[f]) * (k - f)


# ------------------------------------------------------------------ state / readers
@app.get("/api/state")
def state():
    with db() as con:
        m = inference.active_model()
        return {"readers": rows(con.execute("SELECT * FROM readers ORDER BY id")),
                "active_model": ({**m, "metrics": jloads(m["metrics"], {})} if m else None),
                "thresholds": {"floor": CONF_FLOOR, "review": CONF_REVIEW, "positive": CONF_POSITIVE},
                "pin_enabled": bool(PIN), "demo_banner": DEMO_BANNER,
                "open_review": con.execute("SELECT COUNT(*) FROM review_items WHERE status IN ('open','disputed')").fetchone()[0]}


class ReaderIn(BaseModel):
    name: str
    role: str = "technician"


@app.post("/api/readers")
def add_reader(r: ReaderIn, request: Request):
    if r.role not in ("technician", "reader", "senior", "lead"):
        raise HTTPException(400, "Role must be technician, reader, senior or lead.")
    name = r.name.strip()
    if not name:
        raise HTTPException(400, "Name is required.")
    with db() as con:
        con.execute("INSERT OR REPLACE INTO readers(id, name, role) VALUES((SELECT id FROM readers WHERE name=?),?,?)",
                    (name, name, r.role))
        audit(con, who(request), "reader.save", f"{name} ({r.role})")
    return {"ok": True}


# ------------------------------------------------------------------ slides + analysis
class SlideIn(BaseModel):
    code: str
    site: str = ""
    stain: str = "Ziehl-Neelsen"
    magnification: str = "1000x"


@app.post("/api/slides")
def new_slide(s: SlideIn, request: Request):
    code = s.code.strip()
    if not code:
        raise HTTPException(400, "Slide ID is required (use an anonymous lab code, never a patient name).")
    with db() as con:
        if one(con.execute("SELECT id FROM slides WHERE code=?", (code,))):
            raise HTTPException(409, f"Slide {code} already exists.")
        cur = con.execute("INSERT INTO slides(code,site,stain,magnification,status,started_at,started_by) VALUES(?,?,?,?,?,?,?)",
                          (code, s.site.strip(), s.stain, s.magnification, "open", time.time(), who(request)))
        audit(con, who(request), "slide.start", code)
        return slide_detail(con, cur.lastrowid)


@app.get("/api/slides")
def list_slides(status: str = "", limit: int = 50, include_demo: int = 1):
    with db() as con:
        sql = "SELECT * FROM slides WHERE status!='synthetic'"
        p = []
        if status:
            sql += " AND status=?"; p.append(status)
        if not include_demo:
            sql += " AND demo=0"
        sql += " ORDER BY started_at DESC LIMIT ?"; p.append(limit)
        out = rows(con.execute(sql, p))
        for s in out:
            s["n_fields"] = con.execute("SELECT COUNT(*) FROM images WHERE slide_id=?", (s["id"],)).fetchone()[0]
        return out


@app.get("/api/slides/{sid}")
def get_slide(sid: int):
    with db() as con:
        return slide_detail(con, sid)


@app.post("/api/slides/{sid}/fields")
async def add_fields(sid: int, request: Request, files: List[UploadFile] = File(...)):
    reader = who(request)
    results = []
    with db() as con:
        s = one(con.execute("SELECT * FROM slides WHERE id=?", (sid,)))
        if not s:
            raise HTTPException(404, "Slide not found")
        if s["status"] != "open":
            raise HTTPException(409, "This slide is already confirmed. Start a new slide.")
        model = inference.active_model()
        for f in files:
            data = await f.read()
            try:
                info = imaging.save_image(data)
            except imaging.BadImage as e:
                results.append({"file": f.filename, "error": str(e)})
                continue
            dup = one(con.execute("SELECT id FROM images WHERE slide_id=? AND sha256=?", (sid, info["sha256"])))
            if dup:
                results.append({"file": f.filename, "error": "Already added to this slide."})
                continue
            fno = con.execute("SELECT COALESCE(MAX(field_no),0)+1 FROM images WHERE slide_id=?", (sid,)).fetchone()[0]
            cur = con.execute(
                "INSERT INTO images(slide_id,filename,path,width,height,sha256,blur_score,quality_flag,status,source,added_at,added_by,site,field_no,consent) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (sid, f.filename, info["path"], info["width"], info["height"], info["sha256"], info["blur_score"],
                 info["quality_flag"], "unlabelled", "analysis", time.time(), reader, s["site"], fno))
            iid = cur.lastrowid
            r = {"file": f.filename, "image_id": iid, "quality_flag": info["quality_flag"]}
            if model:
                try:
                    create_analysis(con, s, iid, info["path"], model)
                except Exception as e:
                    r["error"] = f"Model failed on this image: {e}"
            results.append(r)
        if model and not s["model_id"]:
            con.execute("UPDATE slides SET model_id=?, demo=? WHERE id=?", (model["id"], model["demo"], sid))
        audit(con, reader, "slide.fields", f"{s['code']} +{sum(1 for r in results if 'image_id' in r)} fields")
        detail = slide_detail(con, sid)
    detail["upload_results"] = results
    detail["model_missing"] = model is None
    return detail


class ConfirmIn(BaseModel):
    final_grade: str
    override_reason: str = ""
    manual_seconds: Optional[float] = None
    add_to_dataset: bool = False
    consent_confirmed: bool = False


@app.post("/api/slides/{sid}/confirm")
def confirm_slide(sid: int, c: ConfirmIn, request: Request):
    reader = who(request)
    if c.final_grade not in grading.GRADES:
        raise HTTPException(400, "Grade must be one of: " + ", ".join(grading.GRADES))
    with db() as con:
        s = slide_detail(con, sid)
        if s["status"] != "open":
            raise HTTPException(409, "Slide already confirmed.")
        if not s["fields"]:
            raise HTTPException(400, "Add at least one field image before confirming.")
        role = reader_role(con, reader)
        sug = s["suggested"]["grade"]
        if s["model_id"] and c.final_grade != sug and not c.override_reason.strip():
            raise HTTPException(400, "The grade differs from the suggestion. Please give a reason for the override.")
        now = time.time()
        con.execute("UPDATE slides SET status='confirmed', confirmed_at=?, session_seconds=?, final_grade=?, confirmed_by=?, "
                    "override_reason=?, manual_seconds=?, ai_grade=?, ai_bacilli=?, ai_fields=? WHERE id=?",
                    (now, now - s["started_at"], c.final_grade, reader, c.override_reason.strip() or None,
                     c.manual_seconds, s["ai_only"]["grade"], s["ai_only"]["total"], s["ai_only"]["fields"], sid))
        added = 0
        if c.add_to_dataset:
            if not c.consent_confirmed:
                raise HTTPException(400, "Confirm that consent / ethics approval covers training use before adding images.")
            for f in s["fields"]:
                con.execute("DELETE FROM annotations WHERE image_id=?", (f["id"],))
                for d in f["detections"]:
                    if counted(d):
                        con.execute("INSERT INTO annotations(image_id,label,cx,cy,w,h,reader,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                    (f["id"], "afb", d["cx"], d["cy"], d["w"], d["h"], reader, now))
                con.execute("UPDATE images SET consent=1, status='labelled', last_labelled_by=? WHERE id=?", (reader, f["id"]))
                added += 1
        audit(con, reader, "slide.confirm", f"{s['code']} grade={c.final_grade} ai={s['ai_only']['grade']} dataset+={added}")
        return slide_detail(con, sid)


class RefIn(BaseModel):
    reference_result: Optional[str] = None   # pos | neg | None
    reference_method: str = ""


@app.patch("/api/slides/{sid}/reference")
def set_reference(sid: int, r: RefIn, request: Request):
    if r.reference_result not in (None, "", "pos", "neg"):
        raise HTTPException(400, "Reference result must be pos or neg.")
    with db() as con:
        con.execute("UPDATE slides SET reference_result=?, reference_method=? WHERE id=?",
                    (r.reference_result or None, r.reference_method, sid))
        audit(con, who(request), "slide.reference", f"{sid} {r.reference_result} {r.reference_method}")
        return slide_detail(con, sid)


class DetIn(BaseModel):
    status: str


@app.patch("/api/detections/{did}")
def patch_detection(did: int, d: DetIn, request: Request):
    if d.status not in ("pending", "kept", "removed"):
        raise HTTPException(400, "Bad status")
    with db() as con:
        con.execute("UPDATE detections SET status=? WHERE id=?", (d.status, did))
        row = one(con.execute("SELECT * FROM detections WHERE id=?", (did,)))
        audit(con, who(request), "detection.edit", f"{did} -> {d.status}")
        return row


class BoxIn(BaseModel):
    cx: float
    cy: float
    w: float
    h: float


@app.post("/api/images/{iid}/detections")
def add_missed(iid: int, b: BoxIn, request: Request):
    with db() as con:
        an = one(con.execute("SELECT id FROM analyses WHERE image_id=? ORDER BY id DESC LIMIT 1", (iid,)))
        if not an:
            raise HTTPException(400, "This image has not been analysed.")
        cur = con.execute("INSERT INTO detections(analysis_id,image_id,cx,cy,w,h,conf,status) VALUES(?,?,?,?,?,?,1.0,'added')",
                          (an["id"], iid, b.cx, b.cy, b.w, b.h))
        audit(con, who(request), "detection.add", f"image {iid}")
        return one(con.execute("SELECT * FROM detections WHERE id=?", (cur.lastrowid,)))


# ------------------------------------------------------------------ images + labelling
def _img_row(con, iid):
    im = one(con.execute("SELECT * FROM images WHERE id=?", (iid,)))
    if not im:
        raise HTTPException(404, "Image not found")
    return im


@app.get("/api/images/{iid}/file")
def image_file(iid: int):
    with db() as con:
        return FileResponse(_img_row(con, iid)["path"], media_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/images/{iid}/thumb")
def image_thumb(iid: int, size: int = 220):
    with db() as con:
        p = _img_row(con, iid)["path"]
    return Response(imaging.thumb_bytes(p, min(max(size, 60), 640)), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/images")
def list_images(status: str = "", slide_id: Optional[int] = None, quality: int = 0, positive: str = "",
                limit: int = 60, offset: int = 0, in_library: int = 1):
    with db() as con:
        sql = ("SELECT i.*, (SELECT COUNT(*) FROM annotations a WHERE a.image_id=i.id AND a.label='afb') AS n_boxes "
               "FROM images i WHERE 1=1")
        p = []
        if in_library:
            sql += " AND (i.consent=1 OR i.source IN ('upload','import','synthetic'))"
        if status:
            sql += " AND i.status=?"; p.append(status)
        if slide_id:
            sql += " AND i.slide_id=?"; p.append(slide_id)
        if quality:
            sql += " AND i.quality_flag IS NOT NULL AND i.quality_flag!=''"
        if positive == "yes":
            sql += " AND EXISTS(SELECT 1 FROM annotations a WHERE a.image_id=i.id AND a.label='afb')"
        if positive == "no":
            sql += " AND NOT EXISTS(SELECT 1 FROM annotations a WHERE a.image_id=i.id AND a.label='afb')"
        total = con.execute(sql.replace("SELECT i.*, (SELECT COUNT(*) FROM annotations a WHERE a.image_id=i.id AND a.label='afb') AS n_boxes", "SELECT COUNT(*)"), p).fetchone()[0]
        sql += " ORDER BY i.id DESC LIMIT ? OFFSET ?"
        p += [limit, offset]
        return {"total": total, "items": rows(con.execute(sql, p))}


@app.get("/api/images/{iid}")
def get_image(iid: int):
    with db() as con:
        im = _img_row(con, iid)
        im["annotations"] = rows(con.execute("SELECT * FROM annotations WHERE image_id=?", (iid,)))
        return im


@app.get("/api/dataset/stats")
def dataset_stats():
    with db() as con:
        def c(sql, *p):
            return con.execute(sql, p).fetchone()[0]
        lib = "(consent=1 OR source IN ('upload','import','synthetic'))"
        return {
            "total": c(f"SELECT COUNT(*) FROM images WHERE {lib}"),
            "unlabelled": c(f"SELECT COUNT(*) FROM images WHERE {lib} AND status='unlabelled'"),
            "labelled": c(f"SELECT COUNT(*) FROM images WHERE {lib} AND status='labelled'"),
            "verified": c(f"SELECT COUNT(*) FROM images WHERE {lib} AND status='verified'"),
            "excluded": c(f"SELECT COUNT(*) FROM images WHERE {lib} AND status='excluded'"),
            "quality_flagged": c(f"SELECT COUNT(*) FROM images WHERE {lib} AND quality_flag IS NOT NULL AND quality_flag!=''"),
            "synthetic": c("SELECT COUNT(*) FROM images WHERE synthetic=1"),
            "consent_pending": c("SELECT COUNT(*) FROM images WHERE consent=0 AND source IN ('upload','import')"),
            "preview": datasets.preview(False, True),
        }


@app.post("/api/images/upload")
async def upload_library(request: Request, files: List[UploadFile] = File(...), site: str = Form(""),
                         consent: int = Form(0)):
    reader = who(request)
    added, skipped, errors = 0, 0, []
    with db() as con:
        for f in files:
            try:
                info = imaging.save_image(await f.read())
            except imaging.BadImage as e:
                errors.append(f"{f.filename}: {e}")
                continue
            if one(con.execute("SELECT id FROM images WHERE sha256=? AND slide_id IS NULL", (info["sha256"],))):
                skipped += 1
                continue
            con.execute(
                "INSERT INTO images(slide_id,filename,path,width,height,sha256,blur_score,quality_flag,status,source,added_at,added_by,site,consent) "
                "VALUES(NULL,?,?,?,?,?,?,?,'unlabelled','upload',?,?,?,?)",
                (f.filename, info["path"], info["width"], info["height"], info["sha256"], info["blur_score"],
                 info["quality_flag"], time.time(), reader, site, int(bool(consent))))
            added += 1
        audit(con, reader, "images.upload", f"added={added} skipped={skipped} consent={consent}")
    return {"added": added, "skipped": skipped, "errors": errors}


@app.post("/api/images/{iid}/consent")
def set_consent(iid: int, request: Request):
    with db() as con:
        con.execute("UPDATE images SET consent=1 WHERE id=?", (iid,))
        audit(con, who(request), "image.consent", str(iid))
    return {"ok": True}


class AnnIn(BaseModel):
    boxes: List[BoxIn] = []
    negative: bool = False


@app.put("/api/images/{iid}/annotations")
def save_annotations(iid: int, a: AnnIn, request: Request):
    reader = who(request)
    boxes = []
    for b in a.boxes:
        cx, cy = min(max(b.cx, 0), 1), min(max(b.cy, 0), 1)
        w, h = min(max(b.w, 0), 1), min(max(b.h, 0), 1)
        if w * h < 1e-4:
            continue
        boxes.append((cx, cy, w, h))
    with db() as con:
        _img_row(con, iid)
        con.execute("DELETE FROM annotations WHERE image_id=?", (iid,))
        for cx, cy, w, h in boxes:
            con.execute("INSERT INTO annotations(image_id,label,cx,cy,w,h,reader,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (iid, "afb", cx, cy, w, h, reader, time.time()))
        status = "labelled" if (boxes or a.negative) else "unlabelled"
        con.execute("UPDATE images SET status=?, last_labelled_by=? WHERE id=?", (status, reader if status != "unlabelled" else None, iid))
        audit(con, reader, "image.label", f"{iid} boxes={len(boxes)} negative={a.negative}")
        im = _img_row(con, iid)
        im["annotations"] = rows(con.execute("SELECT * FROM annotations WHERE image_id=?", (iid,)))
        return im


@app.post("/api/images/{iid}/verify")
def verify_image(iid: int, request: Request):
    reader = who(request)
    with db() as con:
        im = _img_row(con, iid)
        if im["status"] != "labelled":
            raise HTTPException(409, "Only labelled images can be verified.")
        if im["last_labelled_by"] == reader:
            raise HTTPException(409, "A different reader must verify this image (two readers are required).")
        con.execute("UPDATE images SET status='verified' WHERE id=?", (iid,))
        audit(con, reader, "image.verify", str(iid))
    return {"ok": True}


@app.post("/api/images/{iid}/exclude")
def exclude_image(iid: int, request: Request):
    with db() as con:
        con.execute("UPDATE images SET status='excluded' WHERE id=?", (iid,))
        audit(con, who(request), "image.exclude", str(iid))
    return {"ok": True}


@app.delete("/api/images/{iid}")
def delete_image(iid: int, request: Request):
    with db() as con:
        im = _img_row(con, iid)
        if con.execute("SELECT COUNT(*) FROM dataset_images WHERE image_id=?", (iid,)).fetchone()[0]:
            raise HTTPException(409, "This image is part of a frozen dataset version, so it is excluded instead of deleted.")
        if im["slide_id"]:
            raise HTTPException(409, "Images attached to a slide record cannot be deleted.")
        con.execute("DELETE FROM annotations WHERE image_id=?", (iid,))
        con.execute("DELETE FROM images WHERE id=?", (iid,))
        audit(con, who(request), "image.delete", str(iid))
    return {"ok": True}


class SynthIn(BaseModel):
    count: int = 80
    seed: int = 1


@app.post("/api/synthetic")
def make_synthetic(s: SynthIn, request: Request):
    n = max(8, min(s.count, 400))
    reader = who(request)
    made = 0
    with db() as con:
        for k in range(0, n, 4):
            code = f"SYN-{s.seed}-{k // 4 + 1:03d}"
            if one(con.execute("SELECT id FROM slides WHERE code=?", (code,))):
                continue
            sid = con.execute("INSERT INTO slides(code,site,status,started_at,demo,notes) VALUES(?,?,?,?,1,'synthetic demo slide')",
                              (code, "Synthetic", "synthetic", time.time())).lastrowid
            for j in range(min(4, n - k)):
                img, boxes = synth.make_field(s.seed * 100000 + k + j)
                info = imaging.save_image(synth.encode_jpeg(img))
                if one(con.execute("SELECT id FROM images WHERE slide_id=? AND sha256=?", (sid, info["sha256"]))):
                    continue
                iid = con.execute(
                    "INSERT INTO images(slide_id,filename,path,width,height,sha256,blur_score,quality_flag,status,synthetic,source,added_at,added_by,site,field_no,consent,last_labelled_by) "
                    "VALUES(?,?,?,?,?,?,?,?,'verified',1,'synthetic',?,?,?,?,1,'synthetic-generator')",
                    (sid, f"{code}-f{j + 1}.jpg", info["path"], info["width"], info["height"], info["sha256"],
                     info["blur_score"], None, time.time(), reader, "Synthetic", j + 1)).lastrowid
                for (cx, cy, w, h) in boxes:
                    con.execute("INSERT INTO annotations(image_id,label,cx,cy,w,h,reader,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                (iid, "afb", cx, cy, w, h, "synthetic-generator", time.time()))
                made += 1
        audit(con, reader, "synthetic.generate", f"{made} demo images")
    return {"made": made}


@app.post("/api/import/yolo")
async def import_yolo(request: Request, file: UploadFile = File(...), site: str = Form(""), consent: int = Form(0)):
    try:
        return datasets.import_yolo_zip(await file.read(), who(request), site, consent)
    except zipfile.BadZipFile:
        raise HTTPException(400, "That file is not a zip archive.")


# ------------------------------------------------------------------ expert review
@app.get("/api/review")
def review_queue(request: Request, status: str = "open"):
    reader = who(request)
    with db() as con:
        sts = ("open",) if status == "open" else ("disputed",) if status == "disputed" else ("open", "disputed")
        items = rows(con.execute(
            f"SELECT r.*, s.code AS slide_code FROM review_items r LEFT JOIN images i ON i.id=r.image_id "
            f"LEFT JOIN slides s ON s.id=i.slide_id WHERE r.status IN ({','.join('?' * len(sts))}) ORDER BY r.conf ASC LIMIT 120", sts))
        out = []
        for it in items:
            votes = rows(con.execute("SELECT reader, vote FROM review_votes WHERE item_id=?", (it["id"],)))
            it["n_votes"] = len(votes)
            it["voters"] = [v["reader"] for v in votes]
            it["my_vote"] = next((v["vote"] for v in votes if v["reader"] == reader), None)
            out.append(it)
        counts = {k: con.execute("SELECT COUNT(*) FROM review_items WHERE status=?", (k,)).fetchone()[0]
                  for k in ("open", "disputed", "resolved")}
        return {"items": out, "counts": counts, "role": reader_role(con, reader)}


@app.get("/api/review/{rid}/crop")
def review_crop(rid: int):
    with db() as con:
        it = one(con.execute("SELECT * FROM review_items WHERE id=?", (rid,)))
        if not it:
            raise HTTPException(404, "Not found")
        im = _img_row(con, it["image_id"])
    return Response(imaging.crop_bytes(im["path"], it["cx"], it["cy"], it["w"], it["h"]), media_type="image/jpeg")


class VoteIn(BaseModel):
    vote: str


def _resolve(con, it, votes, roles):
    if it["status"] == "disputed":
        # only a senior/lead vote cast AFTER the dispute arose can settle it
        for v in votes:
            if v["id"] > (it.get("disputed_after") or 0) and roles.get(v["reader"]) in ("senior", "lead") \
                    and v["vote"] in ("afb", "not_afb"):
                return v["vote"]
        return None
    a = sum(1 for v in votes if v["vote"] == "afb")
    n = sum(1 for v in votes if v["vote"] == "not_afb")
    u = sum(1 for v in votes if v["vote"] == "unsure")
    if a >= 2: return "afb"
    if n >= 2: return "not_afb"
    if a >= 1 and n >= 1: return "disputed"
    if u >= 2: return "unclear"
    return None


@app.post("/api/review/{rid}/vote")
def review_vote(rid: int, v: VoteIn, request: Request):
    reader = who(request)
    if v.vote not in ("afb", "not_afb", "unsure"):
        raise HTTPException(400, "Vote must be afb, not_afb or unsure.")
    with db() as con:
        it = one(con.execute("SELECT * FROM review_items WHERE id=?", (rid,)))
        if not it or it["status"] not in ("open", "disputed"):
            raise HTTPException(409, "This item is already resolved.")
        try:
            vid = con.execute("INSERT INTO review_votes(item_id,reader,vote,created_at) VALUES(?,?,?,?)",
                              (rid, reader, v.vote, time.time())).lastrowid
        except Exception:
            raise HTTPException(409, "You have already voted on this item.")
        votes = rows(con.execute("SELECT id, reader, vote FROM review_votes WHERE item_id=? ORDER BY id", (rid,)))
        roles = {r["name"]: r["role"] for r in rows(con.execute("SELECT name, role FROM readers"))}
        res = _resolve(con, it, votes, roles)
        if res == "disputed":
            con.execute("UPDATE review_items SET status='disputed', disputed_after=? WHERE id=?", (vid, rid))
        elif res:
            con.execute("UPDATE review_items SET status='resolved', resolution=? WHERE id=?", (res, rid))
            if it["detection_id"] and res in ("afb", "not_afb"):
                con.execute("UPDATE detections SET status=? WHERE id=?", ("kept" if res == "afb" else "removed", it["detection_id"]))
        audit(con, reader, "review.vote", f"item {rid} {v.vote} -> {res or 'waiting'}")
        return {"resolution": res, "item": one(con.execute("SELECT * FROM review_items WHERE id=?", (rid,)))}


# ------------------------------------------------------------------ datasets
@app.get("/api/datasets")
def list_datasets():
    with db() as con:
        return rows(con.execute("SELECT * FROM dataset_versions ORDER BY id DESC"))


class FreezeIn(BaseModel):
    name: str = ""
    seed: int = 42
    include_single_read: bool = False
    include_synthetic: bool = True


@app.get("/api/datasets/preview")
def datasets_preview(include_single_read: int = 0, include_synthetic: int = 1):
    return datasets.preview(bool(include_single_read), bool(include_synthetic))


@app.post("/api/datasets/freeze")
def freeze(f: FreezeIn, request: Request):
    try:
        return datasets.freeze(f.name.strip() or f"Dataset {datetime.now():%Y-%m-%d %H:%M}", f.seed,
                               f.include_single_read, f.include_synthetic, who(request))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ training + models
class TrainIn(BaseModel):
    dataset_version_id: int
    epochs: int = 30
    imgsz: int = 512
    batch: int = 8
    base: str = "auto"


def _refresh_runs(con):
    for r in rows(con.execute("SELECT * FROM training_runs WHERE status IN ('queued','running')")):
        alive = False
        if r["pid"]:
            try:
                os.kill(r["pid"], 0)
                # a zombie child still answers signal 0, so reap if it is ours
                try:
                    if os.waitpid(r["pid"], os.WNOHANG)[0] != 0:
                        alive = False
                    else:
                        alive = True
                except ChildProcessError:
                    alive = True
            except OSError:
                alive = False
        if not alive and time.time() - (r["started_at"] or time.time()) > 5:
            fresh = one(con.execute("SELECT status FROM training_runs WHERE id=?", (r["id"],)))
            if fresh["status"] in ("queued", "running"):
                con.execute("UPDATE training_runs SET status='failed', finished_at=?, message=? WHERE id=?",
                            (time.time(), "The training process stopped unexpectedly.", r["id"]))


@app.post("/api/training/start")
def start_training(t: TrainIn, request: Request):
    reader = who(request)
    with db() as con:
        _refresh_runs(con)
        if one(con.execute("SELECT id FROM training_runs WHERE status IN ('queued','running')")):
            raise HTTPException(409, "A training run is already in progress.")
        ds = one(con.execute("SELECT * FROM dataset_versions WHERE id=?", (t.dataset_version_id,)))
        if not ds:
            raise HTTPException(404, "Dataset version not found. Freeze a dataset version first.")
        if ds["n_train"] < 8:
            raise HTTPException(400, "The training split is too small to train on.")
        params = {"epochs": max(1, min(t.epochs, 300)), "imgsz": max(160, min(t.imgsz, 1280)),
                  "batch": max(1, min(t.batch, 64)), "base": t.base, "seed": 42}
        rid = con.execute("INSERT INTO training_runs(dataset_version_id, params, status, epochs, started_at, started_by, message) "
                          "VALUES(?,?,?,?,?,?,?)",
                          (ds["id"], json.dumps(params), "queued", params["epochs"], time.time(), reader, "Starting...")).lastrowid
        log = open(DATA_DIR / "runs" / f"run_{rid}.log", "w")
        proc = subprocess.Popen([sys.executable, "-m", "app.train_worker", str(rid)], cwd=str(BASE_DIR),
                                stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
        con.execute("UPDATE training_runs SET pid=? WHERE id=?", (proc.pid, rid))
        audit(con, reader, "training.start", f"run {rid} dataset v{ds['id']} {params}")
        return {"id": rid}


@app.get("/api/training")
def list_training():
    with db() as con:
        _refresh_runs(con)
        runs = rows(con.execute("SELECT * FROM training_runs ORDER BY id DESC LIMIT 20"))
        for r in runs:
            r["history"] = jloads(r["history"], [])
            r["params"] = jloads(r["params"], {})
        return runs


@app.post("/api/training/{rid}/cancel")
def cancel_training(rid: int, request: Request):
    with db() as con:
        r = one(con.execute("SELECT * FROM training_runs WHERE id=?", (rid,)))
        if not r or r["status"] not in ("queued", "running"):
            raise HTTPException(409, "That run is not active.")
        if r["pid"]:
            try:
                os.kill(r["pid"], signal.SIGTERM)
            except OSError:
                pass
        con.execute("UPDATE training_runs SET status='cancelled', finished_at=?, message='Cancelled by user.' WHERE id=?",
                    (time.time(), rid))
        audit(con, who(request), "training.cancel", str(rid))
    return {"ok": True}


@app.get("/api/models")
def list_models():
    with db() as con:
        out = rows(con.execute("SELECT * FROM models ORDER BY id DESC"))
        for m in out:
            m["metrics"] = jloads(m["metrics"], {})
        return out


class PromoteIn(BaseModel):
    approved_by: str


@app.post("/api/models/{mid}/promote")
def promote(mid: int, p: PromoteIn, request: Request):
    with db() as con:
        m = one(con.execute("SELECT * FROM models WHERE id=?", (mid,)))
        if not m:
            raise HTTPException(404, "Model not found")
        if m["status"] == "active":
            raise HTTPException(409, "Already active.")
        role = reader_role(con, p.approved_by)
        if role not in ("senior", "lead"):
            raise HTTPException(403, "Only a senior reader or the laboratory lead can approve a model.")
        metrics = jloads(m["metrics"], {})
        cur = one(con.execute("SELECT * FROM models WHERE status='active'"))
        if m["status"] == "candidate":
            if not metrics.get("test_images"):
                raise HTTPException(409, "No held-out test result for this model, so it cannot be approved.")
            if cur:
                cm = jloads(cur["metrics"], {})
                if (cm.get("sensitivity") is not None and metrics.get("sensitivity") is not None
                        and metrics["sensitivity"] < cm["sensitivity"]):
                    raise HTTPException(409, f"Blocked: sensitivity {metrics['sensitivity']:.1%} is lower than the active "
                                             f"model's {cm['sensitivity']:.1%}.")
        if cur:
            con.execute("UPDATE models SET status='archived' WHERE id=?", (cur["id"],))
        con.execute("UPDATE models SET status='active', approved_by=?, approved_at=? WHERE id=?", (p.approved_by, time.time(), mid))
        audit(con, who(request), "model.promote", f"{m['name']} approved by {p.approved_by}")
    inference.forget()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard + performance
def _confirmed(con, include_demo, days):
    sql = "SELECT * FROM slides WHERE status='confirmed'"
    p = []
    if not include_demo:
        sql += " AND demo=0"
    if days:
        sql += " AND confirmed_at>=?"; p.append(time.time() - days * 86400)
    return rows(con.execute(sql, p))


@app.get("/api/performance")
def performance(days: int = 0, include_demo: int = 0):
    with db() as con:
        sl = _confirmed(con, include_demo, days)
        sess = [s["session_seconds"] for s in sl if s["session_seconds"] is not None]
        manual = [s["manual_seconds"] for s in sl if s["manual_seconds"]]
        bins = [(0, 30, "under 0:30"), (30, 60, "0:30 to 1:00"), (60, 90, "1:00 to 1:30"), (90, 120, "1:30 to 2:00"),
                (120, 180, "2:00 to 3:00"), (180, 300, "3:00 to 5:00"), (300, 1e9, "over 5:00")]
        hist = [{"label": b[2], "count": sum(1 for x in sess if b[0] <= x < b[1])} for b in bins]

        def conf(key):
            c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
            for s in sl:
                if s["reference_result"] in ("pos", "neg") and s[key]:
                    pred = grading.is_positive(s[key]); truth = s["reference_result"] == "pos"
                    c["tp" if pred and truth else "fp" if pred else "fn" if truth else "tn"] += 1
            pos, neg = c["tp"] + c["fn"], c["tn"] + c["fp"]
            c["sensitivity"] = c["tp"] / pos if pos else None
            c["specificity"] = c["tn"] / neg if neg else None
            c["sens_ci"] = wilson(c["tp"], pos); c["spec_ci"] = wilson(c["tn"], neg)
            c["n_with_reference"] = pos + neg
            return c
        weeks = {}
        for s in sl:
            if s["session_seconds"] is None:
                continue
            wk = datetime.fromtimestamp(s["confirmed_at"]).strftime("%G-W%V")
            weeks.setdefault(wk, {"app": [], "manual": []})
            weeks[wk]["app"].append(s["session_seconds"])
            if s["manual_seconds"]:
                weeks[wk]["manual"].append(s["manual_seconds"])
        trend = [{"week": k, "app": statistics.median(v["app"]),
                  "manual": statistics.median(v["manual"]) if v["manual"] else None, "n": len(v["app"])}
                 for k, v in sorted(weeks.items())][-12:]
        sites = {}
        for s in sl:
            sites.setdefault(s["site"] or "(no site)", []).append(s)
        by_site = []
        for name, ss in sorted(sites.items()):
            t = [x["session_seconds"] for x in ss if x["session_seconds"] is not None]
            ref = [x for x in ss if x["reference_result"] in ("pos", "neg") and x["ai_grade"]]
            tp = sum(1 for x in ref if x["reference_result"] == "pos" and grading.is_positive(x["ai_grade"]))
            pos = sum(1 for x in ref if x["reference_result"] == "pos")
            by_site.append({"site": name, "slides": len(ss), "median_seconds": statistics.median(t) if t else None,
                            "overrides": sum(1 for x in ss if x["ai_grade"] and x["final_grade"] != x["ai_grade"]),
                            "with_ai": sum(1 for x in ss if x["ai_grade"]),
                            "sensitivity": tp / pos if pos else None, "positives_with_reference": pos})
        inf = [r[0] for r in con.execute(
            "SELECT inference_ms FROM analyses a JOIN slides s ON s.id=a.slide_id WHERE a.inference_ms IS NOT NULL"
            + ("" if include_demo else " AND s.demo=0")).fetchall()]
        return {"slides": len(sl), "median_seconds": statistics.median(sess) if sess else None,
                "p90_seconds": pct(sess, 0.9), "manual_median_seconds": statistics.median(manual) if manual else None,
                "manual_n": len(manual), "histogram": hist, "trend": trend, "ai": conf("ai_grade"),
                "assisted": conf("final_grade"), "by_site": by_site,
                "overrides": sum(1 for s in sl if s["ai_grade"] and s["final_grade"] != s["ai_grade"]),
                "with_ai": sum(1 for s in sl if s["ai_grade"]),
                "inference_median_ms": statistics.median(inf) if inf else None, "inference_p90_ms": pct(inf, 0.9)}


@app.get("/api/summary")
def summary():
    with db() as con:
        sl = _confirmed(con, True, 30)
        sess = [s["session_seconds"] for s in sl if s["session_seconds"] is not None]
        manual = [s["manual_seconds"] for s in sl if s["manual_seconds"]]
        m = inference.active_model()
        return {"slides_30d": len(sl),
                "median_seconds": statistics.median(sess) if sess else None,
                "manual_median_seconds": statistics.median(manual) if manual else None,
                "flagged_positive": sum(1 for s in sl if s["ai_grade"] and grading.is_positive(s["ai_grade"])),
                "awaiting_review": con.execute("SELECT COUNT(*) FROM review_items WHERE status IN ('open','disputed')").fetchone()[0],
                "open_slides": con.execute("SELECT COUNT(*) FROM slides WHERE status='open'").fetchone()[0],
                "images": con.execute("SELECT COUNT(*) FROM images WHERE consent=1").fetchone()[0],
                "active_model": ({**m, "metrics": jloads(m["metrics"], {})} if m else None)}


@app.get("/api/export/slides.csv")
def export_slides(include_demo: int = 0):
    with db() as con:
        sl = rows(con.execute("SELECT * FROM slides WHERE status='confirmed' ORDER BY confirmed_at"))
    buf = io.StringIO()
    cols = ["code", "site", "stain", "magnification", "started_by", "confirmed_by", "session_seconds", "manual_seconds",
            "ai_grade", "ai_bacilli", "ai_fields", "final_grade", "override_reason", "reference_result",
            "reference_method", "demo"]
    w = csv.writer(buf)
    w.writerow(cols)
    for s in sl:
        if s["demo"] and not include_demo:
            continue
        w.writerow([s.get(c, "") if s.get(c) is not None else "" for c in cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=smearsight_slides.csv"})


@app.get("/api/audit")
def get_audit(limit: int = 200):
    with db() as con:
        return rows(con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)))


@app.get("/api/backup.zip")
def backup(request: Request):
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("images", "models"):
            for p in (DATA_DIR / sub).rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(DATA_DIR))
        with db() as con:
            con.execute("PRAGMA wal_checkpoint(FULL)")
        z.write(DATA_DIR / "smearsight.db", "smearsight.db")
    with db() as con:
        audit(con, who(request), "backup.download", "")
    return FileResponse(tmp.name, filename=f"smearsight_backup_{datetime.now():%Y%m%d_%H%M}.zip", media_type="application/zip")


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
