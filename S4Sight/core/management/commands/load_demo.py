"""Load the bundled DEMO models so a fresh install looks like the S4Sight demo.

    python manage.py load_demo            (or double-click load_demo_windows.bat / ./load_demo.sh)

The models in demo/ were trained only on computer-drawn pictures: TB (Ziehl-Neelsen), stool parasites and STI swabs
(candidiasis). They show that the workflow works (AI marks, suggested result, verification) but say nothing about
real slides, and they are marked DEMO everywhere in the app. A demo model is activated only if no model is active
for that test yet, unless --force is given. Running this twice does nothing the second time.
"""
import json
import shutil

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AuditLog, MLModel
from core.services import inference, panels
from core.services.config import BASE_DIR, MODELS_DIR

DEMOS = [("zn", "tb_demo_model"), ("stl", "stl_demo_model"), ("sti", "sti_demo_model")]


class Command(BaseCommand):
    help = "Install the bundled DEMO models (TB, stool, STI), as shown in the S4Sight demo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="activate the demo models even if another model is active for that test")

    def handle(self, *args, **opts):
        installed = []
        for mod, stem in DEMOS:
            src, meta = BASE_DIR / "demo" / f"{stem}.pt", BASE_DIR / "demo" / f"{stem}.json"
            name, test = f"{mod}-demo", panels.get(mod)["name"]
            if not src.exists():
                self.stdout.write(f"{test}: no demo model in the demo folder, skipped.")
                continue
            existing = MLModel.objects.filter(name=name).first()
            active = MLModel.objects.filter(status="active", modality=mod).first()
            if existing and existing.status == "active":
                self.stdout.write(f"{test}: demo model already active. Nothing to do.")
                continue
            if active and not opts["force"]:
                self.stdout.write(f"{test}: a model is already active ({active.name}), so the demo model was not "
                                  "activated. Use --force to replace it.")
                continue
            dest = MODELS_DIR / f"model_{mod}_demo.pt"
            shutil.copy(src, dest)
            metrics = json.loads(meta.read_text()) if meta.exists() else {}
            metrics["demo_note"] = "Trained only on computer-drawn pictures. Not for diagnostic use."
            if active:
                MLModel.objects.filter(pk=active.pk).update(status="archived")
            if existing:
                MLModel.objects.filter(pk=existing.pk).update(status="active", path=str(dest), approved_at=timezone.now())
            else:
                MLModel.objects.create(name=name, path=str(dest), modality=mod, status="active", demo=True,
                                       metrics=metrics, approved_by="demo loader", approved_at=timezone.now(),
                                       notes="Bundled demo model (computer-drawn training pictures only).")
            AuditLog.objects.create(reader="demo loader", action="model.demo_load", detail=f"{name} activated")
            installed.append(test)
        inference.forget()
        if installed:
            self.stdout.write(self.style.SUCCESS(
                "Demo models installed and active for: " + ", ".join(installed) + ". "
                "Start S4Sight: the AI marks are shown with a DEMO label."))
