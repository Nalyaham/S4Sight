import io
import os
import tempfile
import time

os.environ["SMEARSIGHT_DATA"] = tempfile.mkdtemp(prefix="ss_test_")
os.environ.pop("SMEARSIGHT_PIN", None)

import pytest
from fastapi.testclient import TestClient

from app import grading, synth
from app.main import app

c = TestClient(app)
H = lambda n: {"X-Reader": n}


# ---------- grading ----------
def test_grading_scale():
    assert grading.grade_slide([0] * 100)["grade"] == "negative"
    assert grading.grade_slide([1] + [0] * 99)["grade"] == "scanty"
    assert grading.grade_slide([1] * 10 + [0] * 90)["grade"] == "1+"
    assert grading.grade_slide([3] * 50 + [0] * 50)["grade"] == "2+"
    assert grading.grade_slide([15] * 20 + [0] * 80)["grade"] == "3+"
    g = grading.grade_slide([0, 0, 1])
    assert g["provisional"] and g["grade"] == "1+"   # 1 in 3 fields scales to 33 per 100
    assert grading.grade_slide([])["grade"] is None


# ---------- dataset + two-reader rule ----------
def test_synthetic_freeze_split_by_slide():
    assert c.post("/api/synthetic", json={"count": 80, "seed": 7}).json()["made"] == 80
    r = c.post("/api/datasets/freeze", json={"name": "t"})
    assert r.status_code == 200, r.text
    from app.db import db, rows
    with db() as con:
        sp = rows(con.execute("SELECT i.slide_id, d.split FROM dataset_images d JOIN images i ON i.id=d.image_id WHERE d.version_id=?", (r.json()["id"],)))
    by = {}
    for x in sp:
        by.setdefault(x["slide_id"], set()).add(x["split"])
    assert all(len(v) == 1 for v in by.values()), "a slide leaked across splits"


def test_two_reader_verification_and_consent():
    import numpy as np
    im = synth.make_field(999)[0].astype(np.float32)
    im = np.clip(im + np.random.default_rng(0).normal(0, 6, im.shape), 0, 255).astype(np.uint8)   # camera-like grain
    png = synth.encode_jpeg(im)
    up = c.post("/api/images/upload", files=[("files", ("a.jpg", png, "image/jpeg"))], data={"consent": 0}, headers=H("Lab technician")).json()
    assert up["added"] == 1
    iid = c.get("/api/images?status=unlabelled").json()["items"][0]["id"]
    c.put(f"/api/images/{iid}/annotations", json={"boxes": [{"cx": .5, "cy": .5, "w": .05, "h": .02}]}, headers=H("Lab technician"))
    assert c.post(f"/api/images/{iid}/verify", headers=H("Lab technician")).status_code == 409   # same reader
    assert c.post(f"/api/images/{iid}/verify", headers=H("Senior reader")).status_code == 200
    from app.datasets import eligible_images
    from app.db import db
    with db() as con:
        assert iid not in [i["id"] for i in eligible_images(con)], "image without consent must not be eligible"
    c.post(f"/api/images/{iid}/consent")
    with db() as con:
        assert iid in [i["id"] for i in eligible_images(con)]


# ---------- review quorum ----------
def test_review_quorum():
    from app.db import db
    with db() as con:
        iid = con.execute("SELECT id FROM images LIMIT 1").fetchone()[0]
        rid = con.execute("INSERT INTO review_items(image_id,cx,cy,w,h,conf,status,created_at) VALUES(?,?,?,?,?,?,'open',?)",
                          (iid, .5, .5, .05, .02, .4, time.time())).lastrowid
    assert c.post(f"/api/review/{rid}/vote", json={"vote": "afb"}, headers=H("Lab technician")).json()["resolution"] is None
    assert c.post(f"/api/review/{rid}/vote", json={"vote": "afb"}, headers=H("Lab technician")).status_code == 409  # no double vote
    assert c.post(f"/api/review/{rid}/vote", json={"vote": "not_afb"}, headers=H("Laboratory lead")).json()["resolution"] == "disputed"
    assert c.post(f"/api/review/{rid}/vote", json={"vote": "afb"}, headers=H("Senior reader")).json()["resolution"] == "afb"


# ---------- training, promotion, analysis (small and fast) ----------
def test_train_promote_analyse_confirm():
    pytest.importorskip("ultralytics")
    from app import train_worker
    from app.db import db, one
    fr = c.post("/api/datasets/freeze", json={"name": "tiny"}).json()
    with db() as con:
        rid = con.execute("INSERT INTO training_runs(dataset_version_id,params,status,started_at,started_by) VALUES(?,?,?,?,?)",
                          (fr["id"], '{"epochs":2,"imgsz":160,"batch":8,"base":"scratch"}', "queued", time.time(), "t")).lastrowid
    train_worker.main(rid)
    models = c.get("/api/models").json()
    m = models[0]
    assert m["status"] == "candidate" and m["demo"] == 1 and m["metrics"]["test_images"] > 0
    # only senior/lead may approve
    assert c.post(f"/api/models/{m['id']}/promote", json={"approved_by": "Lab technician"}).status_code == 403
    assert c.post(f"/api/models/{m['id']}/promote", json={"approved_by": "Senior reader"}).status_code == 200
    # analyse a slide
    s = c.post("/api/slides", json={"code": "T-1", "site": "Test"}, headers=H("Lab technician")).json()
    img = synth.encode_jpeg(synth.make_field(4242, n_rods=6)[0])
    d = c.post(f"/api/slides/{s['id']}/fields", files=[("files", ("f.jpg", img, "image/jpeg"))], headers=H("Lab technician")).json()
    assert len(d["fields"]) == 1 and d["fields"][0]["analysis"]["inference_ms"] > 0
    assert c.post("/api/slides", json={"code": "T-1"}).status_code == 409
    # override without reason is rejected when it differs from the suggestion
    sug = d["suggested"]["grade"]
    other = "3+" if sug != "3+" else "negative"
    assert c.post(f"/api/slides/{s['id']}/confirm", json={"final_grade": other}, headers=H("Lab technician")).status_code == 400
    # adding to dataset requires consent confirmation
    assert c.post(f"/api/slides/{s['id']}/confirm", json={"final_grade": sug, "add_to_dataset": True}, headers=H("Lab technician")).status_code == 400
    ok = c.post(f"/api/slides/{s['id']}/confirm", json={"final_grade": sug, "manual_seconds": 400}, headers=H("Lab technician"))
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    c.patch(f"/api/slides/{s['id']}/reference", json={"reference_result": "pos", "reference_method": "Xpert"})
    p = c.get("/api/performance?include_demo=1").json()
    assert p["slides"] == 1 and p["manual_median_seconds"] == 400
    assert c.get("/api/export/slides.csv?include_demo=1").text.count("T-1") == 1
