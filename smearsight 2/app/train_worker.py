"""Training worker. Started by the web app as a separate process:

    python -m app.train_worker <run_id>

It trains a YOLOv8 nano model on a frozen dataset version, then evaluates the result on the
held-out TEST split (slides the model never saw) and stores a candidate model. Promotion to
"active" is a separate, signed-off step in the app.
"""
import json
import shutil
import statistics
import sys
import time
import traceback
from pathlib import Path

from .config import MODELS_DIR, RUNS_DIR, DATASETS_DIR, CONF_POSITIVE
from .db import db, one, jloads


def update_run(run_id, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    with db() as con:
        con.execute(f"UPDATE training_runs SET {cols} WHERE id=?", (*kw.values(), run_id))


def pick_base(requested):
    """Use pretrained yolov8n.pt if it is on disk or can be fetched; otherwise train from scratch."""
    local = MODELS_DIR / "base" / "yolov8n.pt"
    if requested == "scratch":
        return "yolov8n.yaml", False, "Training from scratch (no pretrained weights requested)."
    if local.exists():
        return str(local), True, "Using pretrained yolov8n.pt from the models folder."
    try:
        from ultralytics import YOLO
        YOLO("yolov8n.pt")
        src = Path("yolov8n.pt")
        if src.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), local)
            return str(local), True, "Downloaded pretrained yolov8n.pt."
    except Exception:
        pass
    return "yolov8n.yaml", False, ("Pretrained weights were not available offline, so training starts from scratch. "
                                   "With real data, put yolov8n.pt in data/models/base/ for better results.")


def evaluate(best, data_yaml, ds_root, imgsz):
    from ultralytics import YOLO
    model = YOLO(str(best))
    test_imgs = sorted((ds_root / "images" / "test").glob("*.jpg"))
    out = {"test_images": len(test_imgs)}
    if not test_imgs:
        return out
    try:
        m = model.val(data=str(data_yaml), split="test", imgsz=imgsz, conf=0.001, plots=False,
                      verbose=False, device="cpu", workers=0)
        out.update(map50=float(m.box.map50), map50_95=float(m.box.map),
                   precision=float(m.box.mp), recall=float(m.box.mr))
    except Exception as e:   # tiny test sets can break the box-level metric; keep the rest
        out["map_error"] = str(e)[:200]
    tp = fp = fn = tn = 0
    times = []
    for p in test_imgs:
        lab = ds_root / "labels" / "test" / f"{p.stem}.txt"
        truth = lab.exists() and lab.read_text().strip() != ""
        r = model.predict(str(p), imgsz=imgsz, conf=CONF_POSITIVE, verbose=False, device="cpu")[0]
        times.append(r.speed.get("preprocess", 0) + r.speed.get("inference", 0) + r.speed.get("postprocess", 0))
        pred = r.boxes is not None and len(r.boxes) > 0
        if truth and pred: tp += 1
        elif truth and not pred: fn += 1
        elif not truth and pred: fp += 1
        else: tn += 1
    out.update(tp=tp, fp=fp, fn=fn, tn=tn,
               sensitivity=(tp / (tp + fn)) if (tp + fn) else None,
               specificity=(tn / (tn + fp)) if (tn + fp) else None,
               median_inference_ms=statistics.median(times) if times else None,
               image_threshold=CONF_POSITIVE)
    return out


def main(run_id):
    with db() as con:
        run = one(con.execute("SELECT * FROM training_runs WHERE id=?", (run_id,)))
        ds = one(con.execute("SELECT * FROM dataset_versions WHERE id=?", (run["dataset_version_id"],)))
    params = jloads(run["params"], {})
    epochs = int(params.get("epochs", 30))
    imgsz = int(params.get("imgsz", 512))
    batch = int(params.get("batch", 8))
    ds_root = Path(ds["path"])
    data_yaml = ds_root / "data.yaml"
    update_run(run_id, status="running", started_at=time.time(), epochs=epochs, epoch=0,
               message="Preparing model...")
    try:
        from ultralytics import YOLO
        base, pretrained, note = pick_base(params.get("base", "auto"))
        update_run(run_id, message=note)
        model = YOLO(base)
        history = []

        def on_epoch_end(trainer):
            ep = int(trainer.epoch) + 1
            if ep > epochs:      # ultralytics fires the callback once more after the final validation
                return
            tl = getattr(trainer, "tloss", None)

            def tv(k, i):        # newer versions give a dict, older ones a tensor
                try:
                    return float(tl[k]) if isinstance(tl, dict) else float(tl[i])
                except Exception:
                    return None
            mt = trainer.metrics or {}
            entry = {"epoch": ep, "train_box": tv("box_loss", 0), "train_cls": tv("cls_loss", 1),
                     "val_box": mt.get("val/box_loss"), "val_cls": mt.get("val/cls_loss"),
                     "map50": mt.get("metrics/mAP50(B)")}
            if history and history[-1]["epoch"] == ep:
                history[-1] = entry
            else:
                history.append(entry)
            update_run(run_id, epoch=ep, history=json.dumps(history), message=f"Epoch {ep} of {epochs}")

        model.add_callback("on_fit_epoch_end", on_epoch_end)
        project = RUNS_DIR / str(run_id)
        model.train(data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=batch, device="cpu",
                    workers=0, project=str(project), name="train", exist_ok=True, plots=False,
                    amp=False, patience=max(10, epochs // 2), seed=params.get("seed", 42),
                    pretrained=pretrained, verbose=False, hsv_h=0.01, hsv_s=0.3, hsv_v=0.3,
                    degrees=180, flipud=0.5, fliplr=0.5, mosaic=1.0, val=True)
        best = project / "train" / "weights" / "best.pt"
        if not best.exists():
            best = project / "train" / "weights" / "last.pt"
        update_run(run_id, message="Evaluating on the held-out test slides...")
        metrics = evaluate(best, data_yaml, ds_root, imgsz)
        metrics.update(imgsz=imgsz, epochs=epochs, pretrained=pretrained, base=base,
                       train_images=ds["n_train"], val_images=ds["n_val"], dataset_version=ds["id"])
        with db() as con:
            ver = con.execute("SELECT COUNT(*) FROM models").fetchone()[0] + 1
            dest = MODELS_DIR / f"model_v{ver}.pt"
            shutil.copy(best, dest)
            demo = int(ds["includes_synthetic"])
            cur = con.execute(
                "INSERT INTO models(name, path, base, created_at, dataset_version_id, run_id, metrics, status, demo, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"v{ver}", str(dest), "YOLOv8n", time.time(), ds["id"], run_id, json.dumps(metrics),
                 "candidate", demo, note))
            mid = cur.lastrowid
        update_run(run_id, status="completed", finished_at=time.time(), model_id=mid, message="Done. Candidate model created.")
    except Exception as e:
        update_run(run_id, status="failed", finished_at=time.time(), error=traceback.format_exc()[-1500:],
                   message=f"Failed: {e}")
        raise


if __name__ == "__main__":
    main(int(sys.argv[1]))
