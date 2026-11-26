"""Run the active model on an image and time it."""
import threading
import time

from ..models import MLModel
from .config import CONF_FLOOR

_lock = threading.Lock()
_cache = {}        # model id -> (YOLO model, imgsz); one entry per active model (bright-field and fluorescence)


def active_model(modality="zn"):
    return MLModel.objects.filter(status="active", modality=modality).order_by("-approved_at", "-id").first()


def active_models():
    from . import panels
    return {mod: active_model(mod) for mod in panels.ORDER}


def _load(m):
    from ultralytics import YOLO   # imported lazily: starting the web app does not need torch
    with _lock:
        if m.id not in _cache:
            model = YOLO(m.path)
            imgsz = int((m.metrics or {}).get("imgsz", 512))
            _cache[m.id] = (model, imgsz)
            # warm-up so the first real slide is not slower than the rest
            import numpy as np
            model.predict(np.zeros((imgsz, imgsz, 3), np.uint8), imgsz=imgsz, conf=0.9, verbose=False, device="cpu")
        return _cache[m.id]


def forget():
    with _lock:
        _cache.clear()


def detect(image_path, m=None, modality="zn"):
    """Returns (detections, inference_ms, total_ms). Boxes are normalised YOLO centre format."""
    m = m or active_model(modality)
    if not m:
        return None
    model, imgsz = _load(m)
    t0 = time.perf_counter()
    res = model.predict(image_path, imgsz=imgsz, conf=CONF_FLOOR, iou=0.5, max_det=300, verbose=False, device="cpu")[0]
    total_ms = (time.perf_counter() - t0) * 1000
    sp = res.speed
    inference_ms = float(sp.get("preprocess", 0) + sp.get("inference", 0) + sp.get("postprocess", 0))
    from . import panels
    valid = set(panels.class_ids(m.modality))
    fallback = panels.default_label(m.modality)
    names = getattr(model, "names", None) or {}
    dets = []
    if res.boxes is not None and len(res.boxes):
        xywhn = res.boxes.xywhn.cpu().numpy()
        conf = res.boxes.conf.cpu().numpy()
        cls = res.boxes.cls.cpu().numpy() if res.boxes.cls is not None else [0] * len(conf)
        for (cx, cy, w, h), c, k in zip(xywhn, conf, cls):
            label = names.get(int(k), fallback) if isinstance(names, dict) else fallback
            dets.append({"cx": float(cx), "cy": float(cy), "w": float(w), "h": float(h), "conf": float(c),
                         "label": label if label in valid else fallback})
    return dets, inference_ms, total_ms
