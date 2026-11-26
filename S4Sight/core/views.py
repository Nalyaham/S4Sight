"""API views (Django REST Framework). Slides, images, expert review and pages."""
import hashlib
import time
import zipfile

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from . import models as M
from . import serializers as S
from .api_common import (ApiError, api_exception_handler, audit, counted, fail, reader_name, reader_role)  # noqa: F401
from .middleware import token
from .services import confirm, datasets, grading, imaging, inference, panels, settings_store, synth
from .services.acquisition import add_field_images
from .services.config import STATIC_DIR, pin
from .services.network import lan_enabled, lan_ip

VERSION = "3.0"
EXPERT_ROLES = ("senior", "lead")
DEMO_BANNER = "DEMO model: trained on synthetic pictures. Not for diagnostic use."
LIBRARY = Q(consent=True) | Q(source__in=["upload", "import", "synthetic"])


# ================================================================== pages
LOGIN_HTML = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>S4Sight</title>
<body style="font-family:system-ui;background:#0F2A33;display:grid;place-items:center;height:100vh;margin:0">
<form method=post action=/login style="background:#fff;padding:32px;border-radius:12px;width:280px;display:grid;gap:14px">
<h2 style="margin:0">S4Sight</h2><label>Access PIN<input name=pin type=password autofocus
style="width:100%;box-sizing:border-box;padding:12px;font-size:16px;margin-top:6px"></label>
<button style="padding:12px;font-size:16px;background:#0B6E78;color:#fff;border:0;border-radius:8px">Enter</button>{msg}</form>"""


@csrf_exempt
def login_view(request):
    if request.method == "POST":
        if pin() and request.POST.get("pin") == pin():
            r = HttpResponseRedirect("/")
            r.set_cookie("ss_auth", token(), httponly=True, samesite="Lax", max_age=60 * 60 * 12)
            return r
        return HttpResponse(LOGIN_HTML.replace("{msg}", "<p style='color:#B42318;margin:0'>Wrong PIN.</p>"), status=401)
    return HttpResponse(LOGIN_HTML.replace("{msg}", ""))


def index_view(request):
    resp = FileResponse(open(STATIC_DIR / "index.html", "rb"), content_type="text/html")
    resp["Cache-Control"] = "no-cache"
    return resp


# ================================================================== state + readers
def model_with_metrics(m):
    return S.MLModelSerializer(m).data if m else None


@api_view(["GET"])
def state(request):
    return Response({
        "readers": S.ReaderSerializer(M.Reader.objects.all(), many=True).data,
        "active_model": model_with_metrics(inference.active_model("zn")),
        "active_models": {k: model_with_metrics(v) for k, v in inference.active_models().items()},
        "thresholds": settings_store.thresholds("zn"),
        "thresholds_by_modality": {m: settings_store.thresholds(m) for m in panels.ORDER},
        "targets": settings_store.targets(), "prevalence": settings_store.prevalence(),
        "modalities": grading.MODALITIES, "stains": grading.STAINS, "magnifications": grading.MAGNIFICATIONS,
        "panels": panels.public(), "panel_order": panels.ORDER, "expert_roles": list(EXPERT_ROLES),
        "pin_enabled": bool(pin()), "lan_enabled": lan_enabled(), "version": VERSION, "demo_banner": DEMO_BANNER,
        "set_aside": M.Slide.objects.filter(status="set_aside").count(),
        "open_slides": M.Slide.objects.filter(status="open").count(),
        "open_review": M.ReviewItem.objects.filter(status__in=["open", "disputed"]).count()})


@api_view(["POST"])
def add_reader(request):
    s = S.ReaderIn(data=request.data)
    s.is_valid(raise_exception=True)
    name, role = s.validated_data["name"].strip(), s.validated_data["role"]
    if not name:
        fail("Name is required.")
    M.Reader.objects.update_or_create(name=name, defaults={"role": role})
    audit(reader_name(request), "reader.save", f"{name} ({role})")
    return Response({"ok": True})


# ================================================================== slides
def slide_fields(slide):
    imgs = list(slide.images.order_by("field_no", "id"))
    latest = {}
    for a in M.Analysis.objects.filter(slide=slide).order_by("id"):
        latest[a.image_id] = a                      # last one wins
    dets = {}
    for d in M.Detection.objects.filter(image__slide=slide).order_by("-conf"):
        dets.setdefault(d.image_id, []).append(d)
    out = []
    for im in imgs:
        row = S.ImageSerializer(im).data
        an = latest.get(im.id)
        row["analysis"] = S.AnalysisSerializer(an).data if an else None
        row["detections"] = S.DetectionSerializer(dets.get(im.id, []), many=True).data if an else []
        out.append(row)
    return out


def _per_field(fields, keep):
    """For each analysed field: {class_id: count} of the detections that `keep` accepts."""
    out = []
    for f in fields:
        if not f["analysis"]:
            continue
        c = {}
        for x in f["detections"]:
            if keep(x):
                c[x["label"]] = c.get(x["label"], 0) + 1
        out.append(c)
    return out


def slide_detail(slide):
    slide.refresh_from_db()
    d = dict(S.SlideSerializer(slide).data)
    fields = slide_fields(slide)
    pos = settings_store.thresholds(slide.modality)["positive"]

    def is_counted(x):
        return x["status"] in ("kept", "added") or (x["status"] == "pending" and x["conf"] >= pos)
    d["fields"] = fields
    edited = _per_field(fields, is_counted)
    ai = _per_field(fields, lambda x: x["status"] != "added" and x["conf"] >= pos)
    if panels.is_graded(slide.modality):
        d["suggested"] = grading.grade_slide([sum(c.values()) for c in edited], slide.modality, slide.magnification)
        d["ai_only"] = grading.grade_slide([sum(c.values()) for c in ai], slide.modality, slide.magnification)
    else:
        d["suggested"] = grading.result_from_findings(edited, slide.modality)
        d["ai_only"] = grading.result_from_findings(ai, slide.modality)
        if slide.status == "confirmed":
            d["report"] = panels.interpret(slide.modality, slide.findings)
    d["kind"] = panels.get(slide.modality)["kind"]
    d["test_name"] = panels.get(slide.modality)["name"]
    d["standard_fields"] = grading.standard_fields(slide.modality, slide.magnification)
    d["capture_device"] = S.device_brief(slide.capture_device) if slide.capture_device_id else None
    d["confirmation"] = confirm.status(slide, list(slide.confirmations.order_by("id")))
    end = slide.confirmed_at or slide.set_aside_at or timezone.now()
    if slide.status == "confirmed" and slide.set_aside_at:
        end = slide.set_aside_at                    # technician's own time; the expert's wait is not counted
    d["elapsed_seconds"] = (end - slide.started_at).total_seconds()
    d["model"] = ({"id": slide.model.id, "name": slide.model.name, "demo": slide.model.demo} if slide.model else None)
    d["model_missing"] = slide.model is None and inference.active_model(slide.modality) is None
    return d


def get_or_404(model, pk, what="Item"):
    try:
        return model.objects.get(pk=pk)
    except (model.DoesNotExist, ValueError):
        fail(f"{what} not found", 404)


class SlideViewSet(viewsets.GenericViewSet):
    queryset = M.Slide.objects.all()
    serializer_class = S.SlideIn

    def list(self, request):
        qs = M.Slide.objects.exclude(status="synthetic").annotate(
            n_fields=Count("images"), last_photo_at=Max("images__added_at"), last_image_id=Max("images__id"))
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        if request.query_params.get("include_demo", "1") in ("0", "false"):
            qs = qs.filter(demo=False)
        limit = int(request.query_params.get("limit", 50) or 50)
        return Response(S.SlideSerializer(qs.order_by("-started_at")[:limit], many=True).data)

    def create(self, request):
        s = S.SlideIn(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        code = v["code"].strip()
        if not code:
            fail("Sample ID is required (use an anonymous lab code, never a patient name).")
        if M.Slide.objects.filter(code=code).exists():
            fail(f"Sample {code} already exists.", 409)
        modality = v["microscopy"] or grading.modality_for_stain(v["stain"])
        if modality not in grading.MODALITIES:
            fail("Choose a test: " + ", ".join(f"{k} ({n})" for k, n in grading.MODALITIES.items()) + ".")
        stain = v["stain"] if v["stain"] in grading.STAINS[modality] else grading.STAINS[modality][0]
        mag = v["magnification"] if v["magnification"] in grading.MAGNIFICATIONS[modality] else grading.MAGNIFICATIONS[modality][-1]
        dev = None
        if v["device_id"]:
            dev = M.CaptureDevice.objects.filter(pk=v["device_id"], revoked=False).first()
            if not dev:
                fail("That phone is not paired (or was revoked).", 404)
        sl = M.Slide.objects.create(code=code, site=v["site"].strip(), stain=stain, magnification=mag,
                                    modality=modality, status="open", started_by=reader_name(request),
                                    capture_device=dev)
        if dev:                                    # one phone serves one open slide at a time
            M.Slide.objects.filter(capture_device=dev, status="open").exclude(pk=sl.pk).update(capture_device=None)
        audit(reader_name(request), "slide.start", f"{code} {modality} {mag}" + (f" phone={dev.name}" if dev else ""))
        return Response(slide_detail(sl))

    def retrieve(self, request, pk=None):
        return Response(slide_detail(get_or_404(M.Slide, pk, "Slide")))

    @action(detail=True, methods=["post"], url_path="fields")
    def fields(self, request, pk=None):
        reader = reader_name(request)
        slide = get_or_404(M.Slide, pk, "Slide")
        if slide.status != "open":
            fail("This sample is already verified or waiting for an expert. Start a new sample.", 409)
        files = request.FILES.getlist("files")
        if not files:
            fail("No images were sent.")
        results, model_missing = add_field_images(slide, [(f.name, f.read()) for f in files], reader)
        audit(reader, "slide.fields", f"{slide.code} +{sum(1 for r in results if 'image_id' in r)} fields")
        detail = slide_detail(slide)
        detail["upload_results"] = results
        detail["model_missing"] = model_missing
        return Response(detail)

    @action(detail=True, methods=["post"], url_path="photos-done")
    def photos_done(self, request, pk=None):
        """The phone at the microscope says 'all photos taken': the sample shows on the computer as ready
        to check and mark. done=false takes it back (more photos are coming)."""
        slide = get_or_404(M.Slide, pk, "Sample")
        if slide.status != "open":
            fail("This sample is already verified or waiting for an expert.", 409)
        done = str(request.data.get("done", True)).lower() not in ("0", "false", "no")
        if done and not slide.images.exists():
            fail("Take at least one photo first.")
        M.Slide.objects.filter(pk=slide.pk).update(photos_done_at=timezone.now() if done else None,
                                                   photos_done_by=reader_name(request) if done else None)
        audit(reader_name(request), "slide.photos_done" if done else "slide.photos_more", slide.code)
        return Response(slide_detail(slide))

    @action(detail=True, methods=["delete"], url_path=r"fields/(?P<image_id>\d+)")
    def remove_field(self, request, pk=None, image_id=None):
        """Take a photo off a sample that is still being read (blurry, wrong field, taken twice).
        Once the sample is verified or set aside its photos are part of the record and stay."""
        slide = get_or_404(M.Slide, pk, "Sample")
        if slide.status != "open":
            fail("Photos can only be removed while the sample is still being read.", 409)
        im = M.Image.objects.filter(pk=image_id, slide=slide).first()
        if not im:
            fail("That photo is not on this sample.", 404)
        if im.dataset_members.exists():
            fail("This photo is already in a frozen picture set, so it stays.", 409)
        path, fno = im.path, im.field_no
        with transaction.atomic():
            M.ReviewItem.objects.filter(image=im).delete()
            im.delete()                                  # detections and analyses go with it (cascade)
            for i, other in enumerate(slide.images.order_by("field_no", "id"), start=1):
                if other.field_no != i:
                    M.Image.objects.filter(pk=other.pk).update(field_no=i)
        if not M.Image.objects.filter(path=path).exists():   # files are shared by content, so delete only if unused
            try:
                from pathlib import Path
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        audit(reader_name(request), "slide.field_remove", f"{slide.code} photo {fno}")
        return Response(slide_detail(slide))

    # ---------------------------------------------------------- v3: verify, set aside, expert
    @staticmethod
    def _result(slide, v):
        """(final_grade, findings) from the request, checked against the test type."""
        if panels.is_graded(slide.modality):
            g = v.get("final_grade")
            if g not in grading.GRADES:
                fail("Choose the grade: " + ", ".join(grading.GRADES) + ".")
            return g, {}
        findings = panels.clean_findings(slide.modality, v.get("findings") or {})
        return panels.findings_result(slide.modality, findings), findings

    def _finalize(self, slide, s, reader, v, verification, grade, findings):
        """Shared by the technician's own verification and the expert's."""
        if v["add_to_dataset"] and not v["consent_confirmed"]:
            fail("Confirm that consent / ethics approval covers training use before adding images.")
        now = timezone.now()
        slide.status, slide.confirmed_at, slide.verification = "confirmed", now, verification
        if not slide.set_aside_at:
            slide.session_seconds = (now - slide.started_at).total_seconds()
        slide.final_grade, slide.findings, slide.confirmed_by = grade, findings, reader
        slide.override_reason = (v.get("override_reason") or "").strip() or None
        slide.manual_seconds = v.get("manual_seconds")
        slide.ai_grade, slide.ai_bacilli, slide.ai_fields = (
            s["ai_only"]["grade"], s["ai_only"]["total"], s["ai_only"]["fields"])
        slide.ai_findings = s["ai_only"].get("findings") or {}
        slide.capture_device = None
        slide.save()
        added = 0
        if v["add_to_dataset"]:
            pos = settings_store.thresholds(slide.modality)["positive"]
            for f in s["fields"]:
                M.Annotation.objects.filter(image_id=f["id"]).delete()
                boxes = [M.Annotation(image_id=f["id"], label=d["label"], cx=d["cx"], cy=d["cy"], w=d["w"], h=d["h"],
                                      reader=reader)
                         for d in f["detections"]
                         if d["status"] in ("kept", "added") or (d["status"] == "pending" and d["conf"] >= pos)]
                M.Annotation.objects.bulk_create(boxes)
                M.Image.objects.filter(id=f["id"]).update(consent=True, status="labelled", last_labelled_by=reader,
                                                          modality=slide.modality)
                added += 1
        return added

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        """The technician (or anyone reading the sample) verifies the result. One person is enough."""
        reader = reader_name(request)
        c = S.ConfirmIn(data=request.data)
        c.is_valid(raise_exception=True)
        v = c.validated_data
        slide = get_or_404(M.Slide, pk, "Slide")
        with transaction.atomic():
            s = slide_detail(slide)
            if s["status"] == "set_aside":
                fail("This sample is waiting for an expert. An expert verifies it from the Expert queue.", 409)
            if s["status"] != "open":
                fail("This sample is already verified.", 409)
            if not s["fields"]:
                fail("Add at least one photo before verifying.")
            grade, findings = self._result(slide, v)
            sug = s["suggested"]["grade"]
            if slide.model_id and sug and grade != sug and not v["override_reason"].strip():
                fail("Your result differs from the suggestion. Please give a short reason.")
            added = self._finalize(slide, s, reader, v, "self", grade, findings)
            audit(reader, "slide.verify",
                  f"{slide.code} result={grade} {findings or ''} ai={s['ai_only']['grade']} dataset+={added}")
        return Response(slide_detail(slide))

    @action(detail=True, methods=["post"], url_path="set-aside")
    def set_aside(self, request, pk=None):
        """'I am not sure': the technician puts the sample aside for an expert, with their best guess."""
        reader = reader_name(request)
        a = S.SetAsideIn(data=request.data)
        a.is_valid(raise_exception=True)
        v = a.validated_data
        slide = get_or_404(M.Slide, pk, "Slide")
        with transaction.atomic():
            s = slide_detail(slide)
            if s["status"] != "open":
                fail("Only a sample that is still being read can be set aside.", 409)
            if not s["fields"]:
                fail("Add at least one photo so the expert can see what you saw.")
            if not v["reason"].strip():
                fail("Say briefly why you are not sure (for example: cannot tell the egg type).")
            guess, findings = None, {}
            if panels.is_graded(slide.modality):
                guess = v.get("final_grade") if v.get("final_grade") in grading.GRADES else None
            else:
                findings = panels.clean_findings(slide.modality, v.get("findings") or {})
                guess = panels.findings_result(slide.modality, findings)
            now = timezone.now()
            slide.status, slide.set_aside_at, slide.set_aside_by = "set_aside", now, reader
            slide.set_aside_reason, slide.tech_result, slide.tech_findings = v["reason"].strip(), guess, findings
            slide.session_seconds = (now - slide.started_at).total_seconds()
            slide.capture_device = None
            slide.save()
            audit(reader, "slide.set_aside", f"{slide.code} guess={guess} reason={v['reason'].strip()[:200]}")
        return Response(slide_detail(slide))

    @action(detail=True, methods=["post"], url_path="expert-verify")
    def expert_verify(self, request, pk=None):
        """An expert (senior reader or lab lead) decides a sample that was set aside."""
        reader = reader_name(request)
        c = S.ExpertIn(data=request.data)
        c.is_valid(raise_exception=True)
        v = c.validated_data
        slide = get_or_404(M.Slide, pk, "Slide")
        if reader_role(reader) not in EXPERT_ROLES:
            fail("Only an expert (senior reader or lab lead) can verify a set-aside sample. "
                 "Choose your name at the bottom of the menu.", 403)
        if reader == slide.set_aside_by:
            fail("You set this sample aside, so a different expert must verify it.", 409)
        with transaction.atomic():
            s = slide_detail(slide)
            if s["status"] != "set_aside":
                fail("This sample is not waiting for an expert.", 409)
            grade, findings = self._result(slide, v)
            slide.expert_note = v["note"].strip() or None
            added = self._finalize(slide, s, reader, v, "expert", grade, findings)
            if not slide.override_reason and slide.tech_result and grade != slide.tech_result:
                M.Slide.objects.filter(pk=slide.pk).update(
                    override_reason=f"Expert changed the technician's result {slide.tech_result} to {grade}.")
            audit(reader, "slide.expert_verify",
                  f"{slide.code} result={grade} {findings or ''} technician={slide.tech_result} dataset+={added}")
        return Response(slide_detail(slide))

    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, pk=None):
        """The expert sends the sample back to the bench (for example: photos too blurry, re-stain)."""
        reader = reader_name(request)
        r = S.ReturnIn(data=request.data)
        r.is_valid(raise_exception=True)
        slide = get_or_404(M.Slide, pk, "Slide")
        if reader_role(reader) not in EXPERT_ROLES:
            fail("Only an expert can send a sample back.", 403)
        if slide.status != "set_aside":
            fail("This sample is not waiting for an expert.", 409)
        note = r.validated_data["note"].strip()
        if not note:
            fail("Tell the technician what to do (for example: retake field 3 in focus).")
        M.Slide.objects.filter(pk=slide.pk).update(status="open", set_aside_at=None, expert_note=f"{reader}: {note}")
        audit(reader, "slide.return", f"{slide.code}: {note[:200]}")
        return Response(slide_detail(slide))

    @action(detail=True, methods=["patch"], url_path="reference")
    def reference(self, request, pk=None):
        r = S.ReferenceIn(data=request.data)
        r.is_valid(raise_exception=True)
        slide = get_or_404(M.Slide, pk, "Slide")
        slide.reference_result = r.validated_data["reference_result"] or None
        slide.reference_method = r.validated_data["reference_method"]
        slide.save(update_fields=["reference_result", "reference_method"])
        audit(reader_name(request), "slide.reference", f"{slide.id} {slide.reference_result} {slide.reference_method}")
        return Response(slide_detail(slide))


class DetectionViewSet(viewsets.GenericViewSet):
    queryset = M.Detection.objects.all()
    serializer_class = S.DetectionIn

    def partial_update(self, request, pk=None):
        d = S.DetectionIn(data=request.data)
        d.is_valid(raise_exception=True)
        det = get_or_404(M.Detection, pk, "Detection")
        det.status = d.validated_data["status"]
        det.save(update_fields=["status"])
        audit(reader_name(request), "detection.edit", f"{det.id} -> {det.status}")
        return Response(S.DetectionSerializer(det).data)


# ================================================================== images + labelling
def _bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class ImageViewSet(viewsets.GenericViewSet):
    queryset = M.Image.objects.all()
    serializer_class = S.AnnotationsIn

    def _with_boxes(self, qs):
        return qs.annotate(n_boxes=Count("annotations"))

    def list(self, request):
        q = request.query_params
        qs = M.Image.objects.all()
        if int(q.get("in_library", 1)):
            qs = qs.filter(LIBRARY)
        if q.get("status"):
            qs = qs.filter(status=q["status"])
        if q.get("modality") in panels.PANELS:
            qs = qs.filter(modality=q["modality"])
        if q.get("slide_id"):
            qs = qs.filter(slide_id=q["slide_id"])
        if int(q.get("quality", 0)):
            qs = qs.exclude(quality_flag__isnull=True).exclude(quality_flag="")
        if q.get("positive") == "yes":
            qs = qs.filter(id__in=M.Annotation.objects.values("image_id"))
        elif q.get("positive") == "no":
            qs = qs.exclude(id__in=M.Annotation.objects.values("image_id"))
        total = qs.count()
        limit, offset = int(q.get("limit", 60)), int(q.get("offset", 0))
        items = self._with_boxes(qs).order_by("-id")[offset:offset + limit]
        return Response({"total": total, "items": S.ImageSerializer(items, many=True).data})

    def retrieve(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        d = dict(S.ImageSerializer(im).data)
        d["annotations"] = S.AnnotationSerializer(im.annotations.all(), many=True).data
        return Response(d)

    def destroy(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        if im.dataset_members.exists():
            fail("This image is part of a frozen dataset version, so it is excluded instead of deleted.", 409)
        if im.slide_id:
            fail("Images attached to a slide record cannot be deleted.", 409)
        im.delete()
        audit(reader_name(request), "image.delete", pk)
        return Response({"ok": True})

    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        resp = FileResponse(open(im.path, "rb"), content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp

    @action(detail=True, methods=["get"], url_path="thumb")
    def thumb(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        size = min(max(int(request.query_params.get("size", 220)), 60), 640)
        resp = HttpResponse(imaging.thumb_bytes(im.path, size), content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp

    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):
        reader = reader_name(request)
        site, consent = request.data.get("site", ""), _bool(request.data.get("consent", 0))
        modality = request.data.get("modality", "zn")
        if modality not in grading.MODALITIES:
            fail("Unknown test type.")
        added, skipped, errors = 0, 0, []
        for f in request.FILES.getlist("files"):
            try:
                info = imaging.save_image(f.read(), modality)
            except imaging.BadImage as e:
                errors.append(f"{f.name}: {e}")
                continue
            if M.Image.objects.filter(sha256=info["sha256"], slide__isnull=True, modality=modality).exists():
                skipped += 1
                continue
            M.Image.objects.create(
                filename=f.name, path=info["path"], width=info["width"], height=info["height"], sha256=info["sha256"],
                blur_score=info["blur_score"], quality_flag=info["quality_flag"], status="unlabelled", source="upload",
                added_by=reader, site=site, consent=consent, modality=modality)
            added += 1
        audit(reader, "images.upload", f"added={added} skipped={skipped} consent={int(consent)}")
        return Response({"added": added, "skipped": skipped, "errors": errors})

    @action(detail=True, methods=["post"], url_path="consent")
    def consent(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        M.Image.objects.filter(pk=im.pk).update(consent=True)
        audit(reader_name(request), "image.consent", pk)
        return Response({"ok": True})

    @action(detail=True, methods=["put"], url_path="annotations")
    def annotations(self, request, pk=None):
        reader = reader_name(request)
        a = S.AnnotationsIn(data=request.data)
        a.is_valid(raise_exception=True)
        im = get_or_404(M.Image, pk, "Image")
        clip = lambda x: min(max(x, 0), 1)       # noqa: E731
        valid, default = panels.class_ids(im.modality), panels.default_label(im.modality)
        boxes = []
        for b in a.validated_data["boxes"]:
            cx, cy, w, h = clip(b["cx"]), clip(b["cy"]), clip(b["w"]), clip(b["h"])
            label = b.get("label") or default
            if label not in valid:
                fail(f"'{label}' is not something this test looks for.")
            if w * h >= 1e-4:
                boxes.append((label, cx, cy, w, h))
        with transaction.atomic():
            im.annotations.all().delete()
            M.Annotation.objects.bulk_create([M.Annotation(image=im, label=lb, cx=cx, cy=cy, w=w, h=h, reader=reader)
                                              for lb, cx, cy, w, h in boxes])
            st = "labelled" if (boxes or a.validated_data["negative"]) else "unlabelled"
            im.status, im.last_labelled_by = st, (reader if st != "unlabelled" else None)
            im.save(update_fields=["status", "last_labelled_by"])
            audit(reader, "image.label", f"{im.id} boxes={len(boxes)} negative={a.validated_data['negative']}")
        return self.retrieve(request, pk)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        reader = reader_name(request)
        im = get_or_404(M.Image, pk, "Image")
        if im.status != "labelled":
            fail("Only labelled images can be verified.", 409)
        if im.last_labelled_by == reader:
            fail("A different reader must verify this image (two readers are required).", 409)
        im.status = "verified"
        im.save(update_fields=["status"])
        audit(reader, "image.verify", pk)
        return Response({"ok": True})

    @action(detail=True, methods=["post"], url_path="exclude")
    def exclude(self, request, pk=None):
        im = get_or_404(M.Image, pk, "Image")
        im.status = "excluded"
        im.save(update_fields=["status"])
        audit(reader_name(request), "image.exclude", pk)
        return Response({"ok": True})

    @action(detail=True, methods=["post"], url_path="detections")
    def detections(self, request, pk=None):
        b = S.BoxIn(data=request.data)
        b.is_valid(raise_exception=True)
        im = get_or_404(M.Image, pk, "Image")
        if im.slide_id and im.slide.status != "open":
            fail("This sample is already verified or waiting for an expert.", 409)
        an = M.Analysis.objects.filter(image=im).order_by("-id").first()
        if not an:
            if not im.slide_id:
                fail("Mark pictures that are not on a sample in Training pictures.")
            # no AI for this test (yet): the person marks by hand; an empty analysis holds the marks
            an = M.Analysis.objects.create(slide=im.slide, image=im, model=None)
        v = dict(b.validated_data)
        label = v.pop("label", "") or panels.default_label(im.modality)
        if label not in panels.class_ids(im.modality):
            fail(f"'{label}' is not something this test looks for.")
        det = M.Detection.objects.create(analysis=an, image=im, conf=1.0, status="added", label=label, **v)
        audit(reader_name(request), "detection.add", f"image {im.id}")
        return Response(S.DetectionSerializer(det).data)


@api_view(["GET"])
def dataset_stats(request):
    modality = request.query_params.get("modality", "zn")
    lib = M.Image.objects.filter(LIBRARY, modality=modality)
    flagged = lib.exclude(quality_flag__isnull=True).exclude(quality_flag="")
    return Response({
        "total": lib.count(),
        "unlabelled": lib.filter(status="unlabelled").count(),
        "labelled": lib.filter(status="labelled").count(),
        "verified": lib.filter(status="verified").count(),
        "excluded": lib.filter(status="excluded").count(),
        "quality_flagged": flagged.count(),
        "synthetic": M.Image.objects.filter(synthetic=True, modality=modality).count(), "modality": modality,
        "consent_pending": M.Image.objects.filter(consent=False, source__in=["upload", "import"], modality=modality).count(),
        "preview": datasets.preview(False, True, modality)})


@api_view(["POST"])
def make_synthetic(request):
    s = S.SyntheticIn(data=request.data)
    s.is_valid(raise_exception=True)
    n, seed = max(8, min(s.validated_data["count"], 400)), s.validated_data["seed"]
    modality = s.validated_data["modality"]
    reader, made = reader_name(request), 0
    for k in range(0, n, 4):
        code = f"SYN{modality.upper()}-{seed}-{k // 4 + 1:03d}"
        if M.Slide.objects.filter(code=code).exists():
            continue
        with transaction.atomic():
            sl = M.Slide.objects.create(code=code, site="Synthetic", status="synthetic", demo=True, modality=modality,
                                        stain=grading.STAINS[modality][0], magnification=grading.MAGNIFICATIONS[modality][-1],
                                        notes="synthetic demo slide")
            for j in range(min(4, n - k)):
                img, boxes = synth.make_labelled(modality, seed * 100000 + k + j)
                info = imaging.save_image(synth.encode_jpeg(img), modality)
                if M.Image.objects.filter(slide=sl, sha256=info["sha256"]).exists():
                    continue
                im = M.Image.objects.create(
                    slide=sl, filename=f"{code}-f{j + 1}.jpg", path=info["path"], width=info["width"],
                    height=info["height"], sha256=info["sha256"], blur_score=info["blur_score"], quality_flag=None,
                    status="verified", synthetic=True, source="synthetic", added_by=reader, site="Synthetic",
                    field_no=j + 1, consent=True, last_labelled_by="synthetic-generator", modality=modality)
                M.Annotation.objects.bulk_create([
                    M.Annotation(image=im, label=lb, cx=cx, cy=cy, w=w, h=h, reader="synthetic-generator")
                    for (lb, cx, cy, w, h) in boxes])
                made += 1
    audit(reader, "synthetic.generate", f"{made} demo images")
    return Response({"made": made})


@api_view(["POST"])
def import_yolo(request):
    f = request.FILES.get("file")
    if not f:
        fail("Choose a .zip file first.")
    modality = request.data.get("modality", "zn")
    if modality not in grading.MODALITIES:
        fail("Unknown test type.")
    try:
        res = datasets.import_yolo_zip(f.read(), reader_name(request), request.data.get("site", ""),
                                       _bool(request.data.get("consent", 0)), modality)
    except zipfile.BadZipFile:
        fail("That file is not a zip archive.")
    audit(reader_name(request), "import.yolo", f"added={res['added']} skipped={res['skipped']}")
    return Response(res)


# ================================================================== expert review
def _resolve(item, votes, roles):
    if item.status == "disputed":
        # only a senior/lead vote cast AFTER the dispute arose can settle it
        for v in votes:
            if v.id > (item.disputed_after or 0) and roles.get(v.reader) in ("senior", "lead") \
                    and v.vote in ("afb", "not_afb"):
                return v.vote
        return None
    a = sum(1 for v in votes if v.vote == "afb")
    n = sum(1 for v in votes if v.vote == "not_afb")
    u = sum(1 for v in votes if v.vote == "unsure")
    if a >= 2: return "afb"
    if n >= 2: return "not_afb"
    if a >= 1 and n >= 1: return "disputed"
    if u >= 2: return "unclear"
    return None


class ReviewViewSet(viewsets.GenericViewSet):
    queryset = M.ReviewItem.objects.all()
    serializer_class = S.VoteIn

    def list(self, request):
        reader = reader_name(request)
        st = request.query_params.get("status", "open")
        sts = ["open"] if st == "open" else ["disputed"] if st == "disputed" else ["open", "disputed"]
        items = M.ReviewItem.objects.filter(status__in=sts).select_related("image__slide").order_by("conf")[:120]
        out = []
        for it in items:
            votes = list(it.votes.all())
            row = dict(S.ReviewItemSerializer(it).data)
            row["slide_code"] = it.image.slide.code if it.image.slide_id else None
            row["n_votes"] = len(votes)
            row["voters"] = [v.reader for v in votes]
            row["my_vote"] = next((v.vote for v in votes if v.reader == reader), None)
            out.append(row)
        counts = {k: M.ReviewItem.objects.filter(status=k).count() for k in ("open", "disputed", "resolved")}
        return Response({"items": out, "counts": counts, "role": reader_role(reader)})

    @action(detail=True, methods=["get"], url_path="crop")
    def crop(self, request, pk=None):
        it = get_or_404(M.ReviewItem, pk)
        return HttpResponse(imaging.crop_bytes(it.image.path, it.cx, it.cy, it.w, it.h), content_type="image/jpeg")

    @action(detail=True, methods=["post"], url_path="vote")
    def vote(self, request, pk=None):
        reader = reader_name(request)
        v = S.VoteIn(data=request.data)
        v.is_valid(raise_exception=True)
        with transaction.atomic():
            it = get_or_404(M.ReviewItem, pk)
            if it.status not in ("open", "disputed"):
                fail("This item is already resolved.", 409)
            try:
                with transaction.atomic():
                    new = M.ReviewVote.objects.create(item=it, reader=reader, vote=v.validated_data["vote"])
            except IntegrityError:
                fail("You have already voted on this item.", 409)
            votes = list(it.votes.order_by("id"))
            roles = dict(M.Reader.objects.values_list("name", "role"))
            res = _resolve(it, votes, roles)
            if res == "disputed":
                it.status, it.disputed_after = "disputed", new.id
                it.save(update_fields=["status", "disputed_after"])
            elif res:
                it.status, it.resolution = "resolved", res
                it.save(update_fields=["status", "resolution"])
                if it.detection_id and res in ("afb", "not_afb"):
                    M.Detection.objects.filter(id=it.detection_id).update(status="kept" if res == "afb" else "removed")
            audit(reader, "review.vote", f"item {it.id} {v.validated_data['vote']} -> {res or 'waiting'}")
        return Response({"resolution": res, "item": S.ReviewItemSerializer(it).data})
