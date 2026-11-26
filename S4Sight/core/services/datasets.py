"""Freezing dataset versions (split by slide) and importing YOLO-format data."""
import io
import random
import shutil
import zipfile
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Q

from ..models import Annotation, DatasetImage, DatasetVersion, Image
from . import panels
from .config import DATASETS_DIR
from .imaging import BadImage, save_image


def eligible_images(include_single_read=True, include_synthetic=True, modality="zn"):
    """Images that may enter a training set: consent confirmed, not excluded, good enough quality,
    and labelled. Since v3 one person's checked labels are enough (include_single_read=True); pass
    False to use only labels that a second person also verified."""
    statuses = ["verified", "labelled"] if include_single_read else ["verified"]
    qs = Image.objects.filter(consent=True, status__in=statuses, modality=modality).filter(
        Q(quality_flag__isnull=True) | Q(quality_flag="") | Q(synthetic=True))
    if not include_synthetic:
        qs = qs.filter(synthetic=False)
    return qs


def group_key(im):
    return f"s{im.slide_id}" if im.slide_id else f"i{im.id}"


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


def preview(include_single_read=True, include_synthetic=True, modality="zn"):
    imgs = list(eligible_images(include_single_read, include_synthetic, modality).annotate(
        n=Count("annotations", filter=Q(annotations__label__in=panels.class_ids(modality)))))
    pos = sum(1 for i in imgs if i.n)
    return {"images": len(imgs), "positive_images": pos, "negative_images": len(imgs) - pos,
            "groups": len({group_key(i) for i in imgs}), "synthetic": sum(1 for i in imgs if i.synthetic)}


@transaction.atomic
def freeze(name, seed, include_single_read, include_synthetic, reader, modality="zn"):
    imgs = list(eligible_images(include_single_read, include_synthetic, modality).prefetch_related("annotations"))
    if len(imgs) < 12:
        raise ValueError(f"Only {len(imgs)} eligible images for {panels.get(modality)['name']}. "
                         "Label at least 12 images first (or generate demo images).")
    idx = panels.class_index(modality)
    ann, groups = {}, {}
    for im in imgs:
        a = [x for x in im.annotations.all() if x.label in idx]
        ann[im.id] = a
        g = group_key(im)
        groups[g] = groups.get(g, False) or bool(a)
    split_of = _split_groups(groups, seed)
    counts = {"train": 0, "val": 0, "test": 0}
    ver = DatasetVersion.objects.create(
        name=name, seed=seed, modality=modality, includes_synthetic=any(i.synthetic for i in imgs), created_by=reader,
        config={"include_single_read": include_single_read, "include_synthetic": include_synthetic,
                "modality": modality})
    root = DATASETS_DIR / f"v{ver.id}"
    for s in ("train", "val", "test"):
        (root / "images" / s).mkdir(parents=True, exist_ok=True)
        (root / "labels" / s).mkdir(parents=True, exist_ok=True)
    members = []
    for im in imgs:
        sp = split_of[group_key(im)]
        counts[sp] += 1
        shutil.copy(im.path, root / "images" / sp / f"{im.id}.jpg")
        lines = [f"{idx[a.label]} {a.cx:.6f} {a.cy:.6f} {a.w:.6f} {a.h:.6f}" for a in ann[im.id]]
        (root / "labels" / sp / f"{im.id}.txt").write_text("\n".join(lines))
        members.append(DatasetImage(version=ver, image=im, split=sp))
    DatasetImage.objects.bulk_create(members)
    names = "".join(f"  {i}: {c}\n" for c, i in sorted(idx.items(), key=lambda x: x[1]))
    (root / "data.yaml").write_text(
        f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}")
    ver.path, ver.n_train, ver.n_val, ver.n_test = str(root), counts["train"], counts["val"], counts["test"]
    ver.save()
    return ver, len(groups)


def import_yolo_zip(data: bytes, reader, site, consent, modality="zn"):
    """Zip with images/ and labels/ folders (YOLO txt). Class numbers follow the order of the test type's
    classes in core/services/panels.py (TB: 0 = AFB). Imported images are marked labelled."""
    ids = panels.class_ids(modality)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    labels = {Path(n).stem: n for n in names if n.lower().endswith(".txt") and "label" in n.lower()}
    added = skipped = 0
    with transaction.atomic():
        for n in names:
            if not n.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                info = save_image(zf.read(n), modality)
            except BadImage:
                skipped += 1
                continue
            if Image.objects.filter(sha256=info["sha256"], slide__isnull=True, modality=modality).exists():
                skipped += 1
                continue
            im = Image.objects.create(
                filename=Path(n).name, path=info["path"], width=info["width"], height=info["height"],
                sha256=info["sha256"], blur_score=info["blur_score"], quality_flag=info["quality_flag"],
                status="labelled", source="import", added_by=reader, site=site, consent=bool(consent),
                last_labelled_by="import", modality=modality)
            lab = labels.get(Path(n).stem)
            if lab:
                for line in zf.read(lab).decode("utf-8", "ignore").splitlines():
                    p = line.split()
                    if len(p) >= 5 and p[0].isdigit() and int(p[0]) < len(ids):
                        cx, cy, w, h = (float(x) for x in p[1:5])
                        Annotation.objects.create(image=im, label=ids[int(p[0])], cx=cx, cy=cy, w=w, h=h,
                                                  reader="import")
            added += 1
    return {"added": added, "skipped": skipped}
