"""Tests for v3: stool and STI tests, one-person verification, set aside for an expert."""
import io
from pathlib import Path

from django.test import TestCase
from rest_framework.test import APIClient

from core import models as M
from core.services import grading, panels, synth

H = lambda n: {"HTTP_X_READER": n}      # noqa: E731
TECH, SENIOR, LEAD = "Lab technician", "Senior reader", "Laboratory lead"


def photo(modality="stl", seed=11):
    img, _ = synth.make_labelled(modality, seed)
    b = io.BytesIO(synth.encode_jpeg(img))
    b.name = "field.jpg"
    return b


class CatalogTests(TestCase):
    def test_four_tests_with_their_own_classes(self):
        self.assertEqual(panels.ORDER, ["zn", "fm", "stl", "sti"])
        stool = {c["group"] for c in panels.get("stl")["classes"]}
        self.assertEqual(stool, {"Roundworms", "Tapeworms", "Flukes"})
        sti = panels.class_ids("sti")
        for k in ("gndc", "candida_yeast", "candida_hyphae"):
            self.assertIn(k, sti)
        self.assertEqual(panels.class_index("zn"), {"afb": 0})
        self.assertTrue(panels.is_graded("fm"))
        self.assertFalse(panels.is_graded("stl"))

    def test_findings_result_and_report(self):
        self.assertEqual(panels.findings_result("sti", {"pus_cell": 9}), "negative")      # pus cells alone are not a diagnosis
        self.assertEqual(panels.findings_result("sti", {"gndc": 1}), "positive")
        rep = " ".join(panels.interpret("sti", {"gndc": 2, "candida_yeast": 4}))
        self.assertIn("gonorrhoea", rep)
        self.assertIn("candidiasis", rep)
        neg = " ".join(panels.interpret("sti", {}))
        self.assertIn("does not rule out gonorrhoea", neg)
        self.assertIn("repeat up to 3 times", " ".join(panels.interpret("stl", {})))
        self.assertEqual(panels.clean_findings("stl", {"ascaris": "3", "bogus": 2, "taenia": 0, "hookworm": -1}), {"ascaris": 3})

    def test_result_from_findings(self):
        r = grading.result_from_findings([{"ascaris": 2}, {}, {"ascaris": 1, "s_mansoni": 1}], "stl")
        self.assertEqual((r["grade"], r["findings"], r["fields"]), ("positive", {"ascaris": 3, "s_mansoni": 1}, 3))
        self.assertTrue(any("Roundworms" in x for x in r["report"]))
        self.assertEqual(grading.result_from_findings([{}, {}], "stl")["grade"], "negative")
        self.assertIsNone(grading.result_from_findings([], "sti")["grade"])

    def test_demo_pictures_have_valid_marks(self):
        for mod in ("stl", "sti", "zn", "fm"):
            labels = set()
            for seed in range(12):
                img, boxes = synth.make_labelled(mod, seed)
                self.assertEqual(img.shape[2], 3)
                for lb, cx, cy, w, h in boxes:
                    self.assertIn(lb, panels.class_ids(mod))
                    self.assertTrue(0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1, (mod, lb, cx, cy, w, h))
                    labels.add(lb)
            self.assertTrue(labels, mod)
        self.assertGreaterEqual(len({b[0] for s in range(30) for b in synth.make_field_stool(s)[1]}), 4)


class WorkflowTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def new(self, code, mod="stl", **extra):
        r = self.c.post("/api/slides", {"code": code, "microscopy": mod, **extra}, format="json", **H(TECH))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def add_photo(self, sid, mod="stl", seed=11):
        r = self.c.post(f"/api/slides/{sid}/fields", {"files": photo(mod, seed)}, format="multipart", **H(TECH))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def post(self, sid, what, who, **body):
        return self.c.post(f"/api/slides/{sid}/{what}", body, format="json", **H(who))

    def test_new_tests_get_their_own_stains(self):
        s = self.new("S-1")
        self.assertEqual((s["modality"], s["stain"], s["kind"]), ("stl", "Saline wet mount", "findings"))
        t = self.new("T-1", "sti", stain="Saline wet mount")          # shared stain name must keep the chosen test
        self.assertEqual((t["modality"], t["stain"]), ("sti", "Saline wet mount"))
        self.assertEqual(self.new("T-2", "sti", stain="Kato-Katz")["stain"], "Gram stain")
        self.assertEqual(self.c.post("/api/slides", {"code": "X", "microscopy": "xyz"}, format="json").status_code, 400)

    def test_technician_verifies_stool_with_findings(self):
        s = self.new("S-2")
        self.assertEqual(self.post(s["id"], "confirm", TECH, findings={"ascaris": 1}).status_code, 400)   # no photo yet
        self.add_photo(s["id"])
        r = self.post(s["id"], "confirm", TECH, findings={"ascaris": 3, "trichuris": 1, "bogus": 2})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d["status"], d["final_grade"], d["verification"], d["confirmed_by"]), ("confirmed", "positive", "self", TECH))
        self.assertEqual(d["findings"], {"ascaris": 3, "trichuris": 1})
        self.assertTrue(any("Roundworms" in x for x in d["report"]))
        self.assertEqual(self.post(s["id"], "confirm", TECH, findings={}).status_code, 409)               # only once
        csv = self.c.get("/api/export/slides.csv").content.decode()
        self.assertIn("Ascaris lumbricoides egg=3", csv)

    def test_sti_pus_cells_only_is_negative(self):
        s = self.new("T-3", "sti")
        self.add_photo(s["id"], "sti")
        d = self.post(s["id"], "confirm", TECH, findings={"pus_cell": 6}).json()
        self.assertEqual(d["final_grade"], "negative")

    def test_tb_needs_a_real_grade(self):
        s = self.new("Z-1", "zn")
        self.add_photo(s["id"], "zn")
        self.assertEqual(self.post(s["id"], "confirm", TECH, final_grade="positive").status_code, 400)
        self.assertEqual(self.post(s["id"], "confirm", TECH).status_code, 400)
        self.assertEqual(self.post(s["id"], "confirm", TECH, final_grade="scanty").json()["final_grade"], "scanty")

    def test_set_aside_then_expert_verifies(self):
        s = self.new("S-3")
        self.assertEqual(self.post(s["id"], "set-aside", TECH, reason="cannot tell").status_code, 400)  # no photo
        self.add_photo(s["id"])
        self.assertEqual(self.post(s["id"], "set-aside", TECH, reason=" ").status_code, 400)            # no reason
        r = self.post(s["id"], "set-aside", TECH, reason="Cannot tell what this is", findings={"taenia": 1})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d["status"], d["tech_result"], d["tech_findings"], d["set_aside_by"]),
                         ("set_aside", "positive", {"taenia": 1}, TECH))
        tech_seconds = d["session_seconds"]
        st = self.c.get("/api/state").json()
        self.assertEqual(st["set_aside"], 1)
        sm = self.c.get("/api/summary").json()
        self.assertEqual((sm["set_aside_n"], sm["set_aside"][0]["code"]), (1, "S-3"))
        self.assertEqual([x["code"] for x in self.c.get("/api/slides?status=set_aside").json()], ["S-3"])
        # while it waits the technician cannot verify it or add photos
        self.assertEqual(self.post(s["id"], "confirm", TECH, findings={}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/slides/{s['id']}/fields", {"files": photo(seed=12)}, format="multipart").status_code, 409)
        # only an expert can decide
        self.assertEqual(self.post(s["id"], "expert-verify", TECH, findings={}).status_code, 403)
        r = self.post(s["id"], "expert-verify", SENIOR, findings={"h_nana": 2}, note="Thin shell with filaments: H. nana")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d["status"], d["verification"], d["confirmed_by"], d["findings"]), ("confirmed", "expert", SENIOR, {"h_nana": 2}))
        self.assertEqual(d["session_seconds"], tech_seconds)                  # bench time, not the wait for the expert
        self.assertIn("H. nana", d["expert_note"])
        self.assertEqual(self.c.get("/api/state").json()["set_aside"], 0)
        self.assertEqual(self.post(s["id"], "expert-verify", LEAD, findings={}).status_code, 409)      # already done
        # result changed from the technician's guess? Both were positive, so no override note is needed here
        self.assertIsNone(M.Slide.objects.get(pk=s["id"]).override_reason)

    def test_expert_change_of_result_is_recorded(self):
        s = self.new("Z-2", "zn")
        self.add_photo(s["id"], "zn")
        self.post(s["id"], "set-aside", TECH, reason="Not sure if these are AFB", final_grade="scanty")
        d = self.post(s["id"], "expert-verify", LEAD, final_grade="negative").json()
        self.assertEqual((d["final_grade"], d["tech_result"]), ("negative", "scanty"))
        self.assertIn("scanty to negative", d["override_reason"])

    def test_expert_cannot_verify_own_set_aside(self):
        s = self.new("S-4")
        self.add_photo(s["id"])
        self.post(s["id"], "set-aside", SENIOR, reason="Unusual egg")
        self.assertEqual(self.post(s["id"], "expert-verify", SENIOR, findings={}).status_code, 409)
        self.assertEqual(self.post(s["id"], "expert-verify", LEAD, findings={}).status_code, 200)

    def test_send_back_to_the_bench(self):
        s = self.new("S-5")
        self.add_photo(s["id"])
        self.post(s["id"], "set-aside", TECH, reason="Smear or photo quality is poor")
        self.assertEqual(self.post(s["id"], "return", TECH, note="x").status_code, 403)
        self.assertEqual(self.post(s["id"], "return", LEAD, note="").status_code, 400)
        r = self.post(s["id"], "return", LEAD, note="Retake photo 1 in focus")
        self.assertEqual((r.json()["status"], r.json()["set_aside_at"]), ("open", None))
        self.assertIn("Retake photo 1", r.json()["expert_note"])
        self.add_photo(s["id"], seed=13)
        d = self.post(s["id"], "confirm", TECH, findings={}).json()
        self.assertEqual((d["status"], d["final_grade"], d["verification"]), ("confirmed", "negative", "self"))

    def test_marks_with_several_classes(self):
        s = self.new("S-6")
        self.add_photo(s["id"])
        sl = M.Slide.objects.get(pk=s["id"])
        im = sl.images.get()
        an = M.Analysis.objects.create(slide=sl, image=im, inference_ms=5, total_ms=6)
        M.Detection.objects.create(analysis=an, image=im, cx=.3, cy=.3, w=.1, h=.1, conf=.9, label="ascaris")
        M.Detection.objects.create(analysis=an, image=im, cx=.6, cy=.6, w=.1, h=.1, conf=.8, label="ascaris")
        low = M.Detection.objects.create(analysis=an, image=im, cx=.8, cy=.2, w=.1, h=.1, conf=.3, label="taenia")
        d = self.c.get(f"/api/slides/{s['id']}").json()
        self.assertEqual((d["suggested"]["grade"], d["suggested"]["findings"]), ("positive", {"ascaris": 2}))
        self.c.patch(f"/api/detections/{low.id}", {"status": "kept"}, format="json")
        r = self.c.post(f"/api/images/{im.id}/detections", {"cx": .5, "cy": .5, "w": .1, "h": .1, "label": "s_mansoni"}, format="json")
        self.assertEqual(r.json()["label"], "s_mansoni")
        self.assertEqual(self.c.post(f"/api/images/{im.id}/detections", {"cx": .5, "cy": .5, "w": .1, "h": .1, "label": "afb"}, format="json").status_code, 400)
        d = self.c.get(f"/api/slides/{s['id']}").json()
        self.assertEqual(d["suggested"]["findings"], {"ascaris": 2, "taenia": 1, "s_mansoni": 1})
        self.assertEqual(d["ai_only"]["findings"], {"ascaris": 2})                # the AI alone did not find the rest
        # verifying with "add to training" stores the marks with their labels
        sl.model = M.MLModel.objects.create(name="stl-demo", path="x", modality="stl", status="active")
        sl.save()
        r = self.post(s["id"], "confirm", TECH, findings={"ascaris": 2, "taenia": 1, "s_mansoni": 1}, add_to_dataset=True, consent_confirmed=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(M.Annotation.objects.filter(image=im).values_list("label", flat=True)), ["ascaris", "ascaris", "s_mansoni", "taenia"])
        self.assertEqual(M.Slide.objects.get(pk=s["id"]).ai_findings, {"ascaris": 2})

    def test_marking_by_hand_without_ai(self):
        s = self.new("S-8")
        self.add_photo(s["id"])
        im = M.Image.objects.get(slide_id=s["id"])
        self.assertFalse(M.Analysis.objects.filter(image=im).exists())          # no model for stool yet
        for lb in ("hookworm", "hookworm", "trichuris"):
            r = self.c.post(f"/api/images/{im.id}/detections", {"cx": .4, "cy": .4, "w": .05, "h": .05, "label": lb}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
        d = self.c.get(f"/api/slides/{s['id']}").json()
        self.assertEqual((d["suggested"]["grade"], d["suggested"]["findings"]), ("positive", {"hookworm": 2, "trichuris": 1}))
        self.assertEqual(d["ai_only"]["findings"], {})                          # nothing came from an AI
        r = self.post(s["id"], "confirm", TECH, findings={"hookworm": 2, "trichuris": 1}, add_to_dataset=True, consent_confirmed=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(M.Annotation.objects.filter(image=im).values_list("label", flat=True)), ["hookworm", "hookworm", "trichuris"])
        self.assertEqual(self.c.post(f"/api/images/{im.id}/detections", {"cx": .5, "cy": .5, "w": .05, "h": .05, "label": "taenia"}, format="json").status_code, 409)

    def test_reason_needed_when_result_differs_from_ai(self):
        s = self.new("S-7")
        self.add_photo(s["id"])
        sl = M.Slide.objects.get(pk=s["id"])
        sl.model = M.MLModel.objects.create(name="stl-demo", path="x", modality="stl", status="active")
        sl.save()
        im = sl.images.get()
        an = M.Analysis.objects.create(slide=sl, image=im, inference_ms=5, total_ms=6)
        M.Detection.objects.create(analysis=an, image=im, cx=.3, cy=.3, w=.1, h=.1, conf=.9, label="hookworm")
        self.assertEqual(self.post(s["id"], "confirm", TECH, findings={}).status_code, 400)
        self.assertEqual(self.post(s["id"], "confirm", TECH, findings={}, override_reason="It is an air bubble").status_code, 200)


class PhoneUseTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_remove_a_photo_while_reading(self):
        s = self.c.post("/api/slides", {"code": "P-1", "microscopy": "stl"}, format="json", **H(TECH)).json()
        for seed in (21, 22, 23):
            self.c.post(f"/api/slides/{s['id']}/fields", {"files": photo(seed=seed)}, format="multipart", **H(TECH))
        ids = list(M.Image.objects.filter(slide_id=s["id"]).order_by("field_no").values_list("id", flat=True))
        path = M.Image.objects.get(pk=ids[1]).path
        r = self.c.delete(f"/api/slides/{s['id']}/fields/{ids[1]}", **H(TECH))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([f["field_no"] for f in r.json()["fields"]], [1, 2])            # renumbered, no gap
        self.assertFalse(Path(path).exists(), "the unused picture file should be deleted")
        self.assertEqual(self.c.delete(f"/api/slides/{s['id']}/fields/{ids[1]}").status_code, 404)
        other = self.c.post("/api/slides", {"code": "P-2", "microscopy": "stl"}, format="json").json()
        self.assertEqual(self.c.delete(f"/api/slides/{other['id']}/fields/{ids[0]}").status_code, 404)   # not its photo
        self.c.post(f"/api/slides/{s['id']}/confirm", {"findings": {}}, format="json", **H(TECH))
        self.assertEqual(self.c.delete(f"/api/slides/{s['id']}/fields/{ids[0]}").status_code, 409)       # verified: kept

    def test_phone_hands_the_sample_to_the_computer(self):
        phone, computer = APIClient(), APIClient()
        s = phone.post("/api/slides", {"code": "H-1", "microscopy": "sti"}, format="json", **H(TECH)).json()
        self.assertEqual(phone.post(f"/api/slides/{s['id']}/photos-done", {}, format="json").status_code, 400)   # no photo yet
        for seed in (31, 32):
            phone.post(f"/api/slides/{s['id']}/fields", {"files": photo("sti", seed)}, format="multipart", **H(TECH))
        # the computer sees the photos straight away, with the newest one for its live list
        row = [x for x in computer.get("/api/slides?status=open").json() if x["id"] == s["id"]][0]
        self.assertEqual(row["n_fields"], 2)
        self.assertEqual(row["last_image_id"], M.Image.objects.filter(slide_id=s["id"]).order_by("-id").first().id)
        self.assertIsNotNone(row["last_photo_at"])
        self.assertIsNone(row["photos_done_at"])
        r = phone.post(f"/api/slides/{s['id']}/photos-done", {"done": True}, format="json", **H(TECH))
        self.assertEqual((r.status_code, r.json()["photos_done_by"]), (200, TECH))
        st = computer.get(f"/api/slides/{s['id']}/capture-status").json()
        self.assertEqual((st["n_fields"], st["photos_done_by"], st["status"]), (2, TECH, "open"))
        self.assertIsNotNone(st["photos_done_at"])
        phone.post(f"/api/slides/{s['id']}/photos-done", {"done": False}, format="json")
        self.assertIsNone(computer.get(f"/api/slides/{s['id']}").json()["photos_done_at"])
        # the computer verifies; the phone can no longer hand it over
        computer.post(f"/api/slides/{s['id']}/confirm", {"findings": {"candida_yeast": 3}}, format="json", **H(SENIOR))
        self.assertEqual(phone.post(f"/api/slides/{s['id']}/photos-done", {}, format="json").status_code, 409)
        self.assertEqual(computer.get(f"/api/slides/{s['id']}/capture-status").json()["status"], "confirmed")

    def test_app_link_needs_the_network(self):
        d = self.c.get("/api/app-link", HTTP_HOST="localhost:8000").json()      # this computer, started without --lan
        self.assertIsNone(d["url"])
        self.assertTrue(d["network"]["warnings"])
        d = self.c.get("/api/app-link", HTTP_HOST="192.168.1.20:8000").json()   # opened from the network already
        self.assertEqual(d["url"], "http://192.168.1.20:8000/")
        self.assertIn("<svg", d["qr_svg"])

    def test_phone_files_are_served(self):
        for p in ("/static/manifest.json", "/static/icon.svg"):
            self.assertEqual(self.c.get(p).status_code, 200, p)


class DemoModelTests(TestCase):
    def test_load_demo_installs_once_and_respects_a_real_model(self):
        from django.core.management import call_command
        call_command("load_demo", stdout=io.StringIO())
        for mod in ("zn", "stl", "sti"):                                    # TB, stool and STI demo models
            m = M.MLModel.objects.get(name=f"{mod}-demo")
            self.assertEqual((m.status, m.modality, m.demo), ("active", mod, True))
            self.assertTrue(Path(m.path).exists())
        call_command("load_demo", stdout=io.StringIO())                       # second run: nothing new
        self.assertEqual(M.MLModel.objects.filter(name="zn-demo").count(), 1)
        st = APIClient().get("/api/state").json()
        self.assertEqual((st["active_models"]["zn"]["name"], st["active_models"]["zn"]["demo"]), ("zn-demo", True))
        self.assertEqual((st["active_models"]["stl"]["name"], st["active_models"]["sti"]["name"]), ("stl-demo", "sti-demo"))
        # a real model that is already active is never replaced without --force
        M.MLModel.objects.filter(name="zn-demo").update(status="archived")
        M.MLModel.objects.create(name="zn-real", path="x", modality="zn", status="active")
        call_command("load_demo", stdout=io.StringIO())
        self.assertEqual(M.MLModel.objects.get(status="active", modality="zn").name, "zn-real")
        call_command("load_demo", "--force", stdout=io.StringIO())
        self.assertEqual(M.MLModel.objects.get(status="active", modality="zn").name, "zn-demo")


class TrainingDataTests(TestCase):
    def test_stool_freeze_writes_every_class(self):
        c = APIClient()
        self.assertEqual(c.post("/api/synthetic", {"count": 40, "seed": 3, "modality": "stl"}, format="json").json()["made"], 40)
        self.assertEqual(c.get("/api/dataset/stats?modality=zn").json()["total"], 0)
        r = c.post("/api/datasets/freeze", {"modality": "stl", "name": "stool"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        ver = M.DatasetVersion.objects.get()
        y = (Path(ver.path) / "data.yaml").read_text()
        for i, cid in enumerate(panels.class_ids("stl")):
            self.assertIn(f"  {i}: {cid}\n", y)
        used = set()
        for p in Path(ver.path).glob("labels/*/*.txt"):
            for line in p.read_text().splitlines():
                used.add(int(line.split()[0]))
        self.assertTrue(used and max(used) < len(panels.class_ids("stl")))
        self.assertGreater(len(used), 1, "several classes should reach the training files")

    def test_labels_are_checked_per_test(self):
        c = APIClient()
        up = c.post("/api/images/upload", {"files": photo("sti"), "modality": "sti", "consent": 1}, format="multipart")
        self.assertEqual(up.json()["added"], 1, up.content)
        iid = M.Image.objects.get().id
        bad = c.put(f"/api/images/{iid}/annotations", {"boxes": [{"cx": .5, "cy": .5, "w": .1, "h": .1, "label": "ascaris"}]}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = c.put(f"/api/images/{iid}/annotations", {"boxes": [{"cx": .5, "cy": .5, "w": .1, "h": .1, "label": "gndc"}]}, format="json")
        self.assertEqual(ok.json()["annotations"][0]["label"], "gndc")
        from core.services import datasets
        M.Image.objects.filter(pk=iid).update(quality_flag=None)        # drawn demo pictures can trip the blur check
        self.assertIn(iid, [i.id for i in datasets.eligible_images(modality="sti")])      # one person's labels count

    def test_import_maps_class_numbers(self):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("images/a.jpg", photo("stl", 5).getvalue())
            z.writestr("labels/a.txt", "0 0.5 0.5 0.1 0.1\n8 0.2 0.2 0.1 0.1\n99 0.1 0.1 0.1 0.1\n")
        buf.seek(0)
        buf.name = "d.zip"
        r = APIClient().post("/api/import/yolo", {"file": buf, "modality": "stl", "consent": 1}, format="multipart")
        self.assertEqual(r.json()["added"], 1, r.content)
        self.assertEqual(sorted(M.Annotation.objects.values_list("label", flat=True)), ["ascaris", "s_mansoni"])
