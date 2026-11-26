# S4Sight v3 (Django REST Framework edition)

A web application that helps laboratory staff read microscope slides. It runs on one laboratory computer, with no internet
needed after the one-time install. It reads four tests:

| Test | Specimen | What it looks for | Result |
|---|---|---|---|
| TB smear, Ziehl-Neelsen | Sputum | Acid-fast bacilli | negative, scanty, 1+, 2+, 3+ (WHO/IUATLD) |
| TB smear, fluorescence (auramine) | Sputum | Acid-fast bacilli | negative, scanty, 1+, 2+, 3+ |
| **Stool parasites** (new) | Stool: saline or iodine wet mount, Kato-Katz, concentration | Roundworms (Ascaris, hookworm, Trichuris, Strongyloides larva, Enterobius), tapeworms (Taenia, Hymenolepis nana, Diphyllobothrium), flukes (Schistosoma mansoni, Fasciola, Clonorchis/Opisthorchis) | what was seen and how many, positive or negative |
| **STI swab** (new) | Vaginal, cervical or urethral swab: Gram stain, saline wet mount, KOH | Gram-negative intracellular diplococci (gonorrhoea), yeast cells and pseudohyphae (candidiasis), Trichomonas, clue cells, pus cells | what was seen, positive or negative, with plain-language report lines |

A technician photographs microscope fields (with the computer's webcam, picture files, or **a paired phone**), an AI model
(YOLOv8) marks what it finds, the technician checks the marks, and then either **verifies the result** or, if not sure,
**sets the sample aside for an expert**. One person's verification is enough.

**A person always makes the final call.** This is a research tool, not a validated diagnostic device.

### What is new in v3

* **Stool and STI tests** beside TB, each with its own AI model, cut-offs and training pictures.
* **Simpler screens.** Home shows one big button per test. A sample goes through three steps: *Photograph*, *Check*,
  *Verify*. Stool and STI results are a checklist with + and − buttons and a short description of what each egg or organism
  looks like. Rarely used pages (training pictures, AI models, performance, settings) are under *More tools*.
* **One person verifies.** The technician presses **Verify result**, and the result is final. No second reader is required.
* **Not sure? Set it aside.** **Not sure: ask an expert** sends the sample, with the technician's best guess and reason, to the
  **Expert queue**. The technician carries on with the next sample. An expert (senior reader or lab lead, not the person who
  set it aside) opens it, sees the photos and marks, and **verifies** it or **sends it back** with a note (for example
  "retake photo 3 in focus").
* For TB, Xpert and culture results are now **optional** records (they still give the rifampicin result, the PPV/NPV
  figures, and a flag when a positive smear has a negative Xpert). The stricter v2 rules are kept in
  `core/services/confirm.py` as `status_v2_strict` for laboratories that want them back.
* The old two-vote review of single low-confidence boxes is gone: those boxes show in orange ("needs a look") on the sample.

**There are no real AI models for stool or STI yet.** They need real, consented, expert-labelled photos. Until then the
technician records findings on the checklist by eye, which works fully, and *Training pictures, Generate demo pictures*
can make computer-drawn practice images to try the training steps (models trained on them are marked DEMO).

Built with Django 5, Django REST Framework, SQLite, YOLOv8 (Ultralytics) and a plain-JavaScript interface.

## See it like the demo video

After installing (below), double-click **`load_demo_windows.bat`** (Mac/Linux: `./load_demo.sh`, or
`python manage.py load_demo`). It activates the bundled **DEMO models** from the `demo/` folder for TB (Ziehl-Neelsen),
stool parasites and STI swabs (candidiasis), so each test shows AI marks and a suggested result. These models were
trained only on computer-drawn pictures: they are labelled DEMO everywhere and must not be used for diagnosis. A demo
model is never activated over a real model for the same test unless you add `--force`. Real models are trained from
your own labelled photos under *More tools, Training pictures* and *AI models*.

## Install and run

### Windows

1. Install **Python 3.12** from https://www.python.org/downloads/ . On the first installer screen tick **"Add python.exe to PATH"**.
2. Right-click the zip, **Extract All**, and open the extracted `smearsight_drf` folder.
3. Double-click **`install_windows.bat`**. It needs internet and takes 5 to 20 minutes the first time (a large download, about 1 to 2 GB).
   If the window shows an error, it explains the usual causes and keeps a log in `install_log.txt`. Running it again continues where it stopped.
4. When it finishes, S4Sight starts and your browser opens at http://localhost:8000.
5. Next time: double-click **`start_windows.bat`**. Keep the black window open while you work; closing it stops the app.

### Mac / Linux

    ./install.sh        # first time only (then it starts the app)
    ./start.sh          # every other time

Then open http://localhost:8000.

### What is new in v2

* **Select a phone as the camera.** Pair a phone once, then choose it from *Capture from* when you start a slide. Photos taken on the
  phone appear on the computer by themselves.
* **Fluorescence microscopy** (auramine O) beside Ziehl-Neelsen, with its own model, quality checks and grading scales.
* **PPV and NPV** next to sensitivity and specificity, a cut-off table for every model, and editable acceptance targets.
* **Confirming positives**: scanty, 1+, 2+ and 3+ each get a required confirmation path (blind re-read, Xpert, culture).
* **Health check and feedback** for monitoring after go-live.

### Upgrading from v1 (keeps your data)

1. Close S4Sight. Extract the v2 zip **over** the old folder (same place; the `data` folder is not in the zip, so it is kept).
2. Double-click **`upgrade_windows.bat`** (Mac/Linux: `./upgrade.sh`). It first copies your database to `data/backups/before_v2_<time>.sqlite3`,
   installs the one new package, updates the database and prints counts. Existing slides, images and models become Ziehl-Neelsen ones.
3. Start the app as usual. To go back, close the app and copy the backup file over `data/smearsight.sqlite3`.

### Using S4Sight on a phone (the usual way)

The phone sits in the eyepiece adapter and does the whole job: start the sample, take the photos, check the marks and
verify (or set aside for an expert). The lab computer only runs S4Sight in the background and keeps the data.

1. On the computer, double-click **`start_for_phones_windows.bat`** (Mac/Linux: `./start_for_phones.sh`). It asks for an
   access PIN; choose 4 or more digits. Keep the window open.
2. Connect the phone to the **same private Wi-Fi** (WPA2, not a guest network).
3. On the computer, click **Open on a phone** (Home page or menu) and scan the QR code with the phone. Type the PIN once
   (it is remembered for 12 hours).
4. In the phone browser menu choose **Add to Home screen**. S4Sight then opens like an app.
5. Choose your name under the S4Sight bar at the top. Use the tabs at the bottom: **Home, New, Expert, Results, More**.

On the phone:
* **Take photo** opens the phone camera; after each photo the camera button (bottom right, with the next photo number)
  takes the next field. Photos are shrunk on the phone to 1600 px before sending (faster on Wi-Fi, and GPS and camera
  details are removed).
* If a photo is **blurry, too dark or washed out**, S4Sight says so at once with a tip. Press **Retake it** to take it
  again, or **Keep it**. **Remove this photo** takes off any photo while the sample is still being read.
* A finger on the photo scrolls the page. Tap a box to count or remove it. To draw a box the AI missed, press
  **Add a missed one** first, then drag.

Photos taken through the phone camera may also stay in the phone's gallery; delete them there if your policy requires.

### Photograph on the phone, mark on the computer

Every photo the phone saves is stored on the lab computer at once, so the same sample can be finished on the big screen:

1. On the phone, after the last photo, press **Done taking photos: check on the computer**, then start the next sample.
2. On the computer, **Home** shows **From the microscope**: every sample still being read, with its newest photo, updated
   by itself every few seconds. Samples the phone has finished show **Ready to check** at the top (and a short message
   pops up). A sample that is still being photographed shows **Photographing now**; if it is open on the computer, new
   photos appear there too.
3. Open the sample on the computer and mark accurately:
   * **Zoom**: mouse wheel (zooms where the mouse points), the **+ / −** buttons or keys, **Fit** or key **0** for the whole photo.
   * **Move around** a zoomed photo: hold **Space** and drag, or drag with the middle mouse button.
   * **Large view** (button or key **L**, **Esc** to leave): the photo fills the screen.
   * **Next / previous photo**: the arrow buttons or the **←** **→** keys.
   * Stool and STI: keys **1-9** choose what you are marking (the order of the list), then drag a box around it.
     Outlines stay thin and boxes are easier to pick when zoomed in, so small eggs, yeast and diplococci can be marked precisely.
   * Tests without an AI yet can be marked by hand in the same way; the marks fill in the checklist counts.
4. Verify, or ask an expert. Tick **Use these photos and marks to train the AI** to keep the marks as training labels.

Either device can verify; if the phone verifies or sets the sample aside while the computer has it open, the computer
updates too.

### Using a phone only as a camera for the computer (optional)

If a person reads at the computer screen and a phone only takes the pictures, use the pairing below. A paired phone can
send photos and nothing else (it never sees results).

1. Start the app so phones can reach it: `start_windows.bat --lan --pin 1234` (or `./start.sh --lan --pin 1234`). The phone and
   the computer must be on the same Wi-Fi. Use a private network (WPA2), not a public or guest one.
2. In **Analyze slide**, open the **Capture from** list and choose **Pair a new phone**. A 6-digit code and a QR code appear (valid 10 minutes, one use).
3. On the phone, scan the QR code (or open the address shown and type the code). The phone is paired and shows its name on the computer. You do **not** share the PIN.
4. Choose the phone in **Capture from**, start the slide, and take photos on the phone. A phone serves one open slide at a time.
   If a photo is blurry or washed out, the phone asks for a retake before anything is stored.
5. Remove a phone at any time under **Settings, Phones used as cameras** (you can also rename it there). A removed phone can no longer send anything.

What the phone is allowed to do: send photos to the one slide chosen for it, nothing else. It cannot read slides, results or other images.
Photos are shrunk to 1600 px and re-saved without GPS or camera details (EXIF). Pairing is rate-limited. The phone page uses the
ordinary camera app (no camera permission prompt in the browser, no https needed). A copy may remain in the phone's own gallery;
delete it there if your policy requires.

Traffic on the lab Wi-Fi is plain http. For more protection use a private network and a PIN, or put a TLS reverse proxy (Caddy, nginx) in front.

## Workflow

Daily work (technician):

1. Choose your name under **Who is working?** at the top of the menu.
2. On **Home**, press the test: TB (ZN), TB (fluorescence), Stool parasites or STI swab. Type the lab sample number (never the
   patient's name) and press **Start**. Stain, magnification and site are remembered under *More options*.
3. **Photograph** fields with *Take photo*, *Add picture files*, or the paired phone.
4. **Check**: tap a box to count or remove it, drag on the picture to add one the AI missed (for stool and STI, first tap
   what it is). For TB choose the grade; for stool and STI use + and − on the checklist.
5. **Verify result**, or **Not sure: ask an expert** with a reason. A reason is also asked when your result differs from the AI.

Expert (senior reader or lab lead): open **Expert queue** (the number shows how many wait), open the oldest, then
**Verify as expert** or **Send back to the bench** with a note.

Building and improving the AI (under *More tools*):

1. **Training pictures**: choose the test, upload field pictures (tick the consent box only if consent or an ethics waiver
   covers training use), import a YOLO-format zip, or press *Generate demo pictures*. Ticking *Use these photos and marks to
   train the AI* when verifying a sample also adds it.
2. Label pictures by drawing boxes (for stool and STI, choose what each box is). One person's labels are enough; a second
   person can optionally confirm them.
3. **Freeze a picture set.** Pictures are split into train, validation and test by sample, so one sample is never in both.
4. **AI models**: trains YOLOv8n on the CPU and evaluates on the held-out test samples. For real data put `yolov8n.pt` in
   `data/models/base/` to start from pretrained weights; otherwise training starts from scratch.
5. An expert **approves** the candidate. Approval is blocked if its sensitivity is lower than the active model's for the same
   test. Older models can be rolled back to.
6. **Performance**: time per sample, sensitivity, specificity, **PPV and NPV** against reference results with 95% confidence
   intervals, by test and site, checked against your targets. CSV export (includes stool and STI findings).

### Upgrading from v2 (keeps your data)

Same steps as below: extract over the old folder, run `upgrade_windows.bat` (or `./upgrade.sh`). The database gets the new
columns; existing slides, images and models stay TB ones. Positive TB slides that were waiting for a second reader are now
simply verified.

All data is in the `data/` folder (database, images, datasets, models). Use *Settings and audit, Download full backup*, or copy that folder.

## Fluorescence microscopy

Choose **Fluorescence (auramine O)** when you start a slide, and pick 200x/250x or 400x. Fluorescence needs its own model (train it on
fluorescence images; a Ziehl-Neelsen model does not transfer). Quality checks differ: no "too dark" flag (the background is dark), and a
"washed out" flag instead; blur limits are lower. Grading follows the IUATLD/WHO scale for the chosen magnification:

| Report | 200x/250x (300 fields) | 400x (40 fields) |
|---|---|---|
| Scanty | 1 to 29 in the whole length | 1 to 19 in the length |
| 1+ | 30 to 299 in the length | 20 to 199 in the length |
| 2+ | 10 to 100 per field | 5 to 50 per field |
| 3+ | more than 100 per field | more than 50 per field |

The scale leaves a gap between "1+" and "2+" for some counts. The app resolves such counts upward to 2+ and flags the slide for lab-lead confirmation.
Ziehl-Neelsen at 1000x still uses 100 fields. Fewer fields than the scale requires are marked *provisional*.

## Cut-offs, PPV and NPV

* **Detection cut-off** (per modality, in Settings): a detection counts when its confidence is at or above it (default 0.50); between the review
  value (0.60) and the floor (0.25) detections go to expert review. Senior readers and the lab lead can change the cut-off.
* **Cut-off table** (Model training, *Cut-offs* on a trained model): for thresholds from 0.25 to 0.90 it shows image-level sensitivity, specificity, **PPV** and
  **NPV** on the held-out test set, each with a 95% interval and a mark when all targets are met. *Use* sets the cut-off for that modality.
* **Targets** (Settings, lab lead only): defaults are placeholders (sensitivity 0.80, specificity 0.95, PPV 0.90, NPV 0.90). Replace them with your programme's
  own criteria. A target counts as **met** only when the lower 95% limit is at or above it; "point" means the estimate is at target but the interval is wide.
* **PPV and NPV depend on prevalence.** The Performance page shows the observed values and values adjusted to the prevalence you enter (default 10%),
  with a range from the confidence limits. Do not compare PPV across sites with different prevalence.
* They are calculated only from slides with an Xpert or culture result, so enter those results (also for negative slides) or the figures stay empty.

## Confirming scanty, 1+, 2+ and 3+ positives (v2 rules, off by default in v3)

Since v3 one person's verification is final, and Xpert/culture are optional. The stricter v2 policy below is kept as
`status_v2_strict` in `core/services/confirm.py`; to switch it back on, make `status()` call it.

| Grade | Required | Recommended |
|---|---|---|
| 3+ | Blind re-read by a second reader | Xpert (also gives rifampicin resistance) |
| 2+ | Blind re-read by a second reader | Xpert |
| 1+ | Blind re-read, then Xpert or culture | Re-stain with ZN if a fluorescence slide |
| Scanty | Blind re-read, then Xpert or culture | Re-stain with ZN; repeat the smear |
| Any fluorescence positive | Xpert or culture | |

* The **blind re-read** page (*Awaiting confirmation* on the dashboard, then *Re-read*) shows only images; the second reader counts bacilli and the app
  compares the grades. Different result category, or two or more grade steps apart, is **discordant** and goes to a third reader (referee);
  a one-step difference is minor.
* Record Xpert or culture on the slide. Culture outranks Xpert. A "trace" or invalid Xpert is treated as unclear, not confirmed.
  A smear-positive, Xpert-negative result is flagged for investigation (false positive, non-tuberculous mycobacteria, or sample problem).
* A senior reader or lead can close a slide as *accepted* with a written reason when confirmation is not possible.
* Blind reading is a screen convention; the list pages still show grades to people with access.

## For developers

* REST API under `/api/` (Django REST Framework ViewSets and serializers, JSON, with the browsable API in a browser):
  `slides`, `images`, `detections`, `review`, `datasets`, `training`, `models`, plus `state`, `performance`, `summary`,
  `audit`, `export/slides.csv`, `backup.zip`; v2 adds `devices`, `devices/pairing`, `slides/<id>/capture-device`, `slides/<id>/capture-status`,
  `slides/<id>/confirmation`, `slides/<id>/blind`, `models/<id>/cutoffs`, `settings`, `feedback`, `capture-events`, `health` and, for phones, `/phone` and `/api/phone/*`. Errors are always `{"detail": "readable message"}`.
* Django admin at `/admin/` to inspect or fix records: run `python manage.py createsuperuser` once (inside the virtual environment).
* Reader identity is the `X-Reader` request header (the interface sends it). Optional access PIN via `--pin` or `SMEARSIGHT_PIN`.
* Training runs as a separate process: `python manage.py train_worker <run_id>`.
* Tests: `python manage.py test core` (uses a temporary data folder, includes a real two-epoch training run).
* Settings through environment variables: `SMEARSIGHT_DATA` (data folder), `SMEARSIGHT_PIN`, `SMEARSIGHT_TZ`,
  `SMEARSIGHT_BLUR_MIN`, `SMEARSIGHT_DARK_MAX`, `SMEARSIGHT_BRIGHT_MIN`, `SMEARSIGHT_BLUR_MIN_FM`, `SMEARSIGHT_HAZE_MAX_FM`.

      smearsight_site/   Django project (settings, urls)
      core/              models, serializers, API views, services (grading, imaging, datasets, inference), train_worker command
      static/            the web interface
      data/              created on first run

## Monitoring after go-live

* `http://<computer>:8000/healthz` returns `{"ok":true}` with no login (for a simple uptime check). `/api/health` (PIN-protected) adds free disk space, database status, active models, phones paired/online and uploads in the last 24 hours, and lists problems (for example less than 2 GB free, or more than 20% of phone uploads failing).
* Settings, *Health and monitoring*, shows the same checks and the recent capture log (uploads, retakes asked, failures, with phone and time). *Usability feedback* lists the ratings and comments left on phones and computers (1 to 5 stars). Use *Settings* for cut-offs and targets.
* Watch in the first weeks: share of photos that ask for a retake, failed uploads per phone, unconfirmed positives, and the star ratings.

## Troubleshooting

* **"Python was not found"**: install Python 3.12 and tick *Add python.exe to PATH*.
* **Install fails or stops**: run the installer again. Try a phone hotspot if a network blocks downloads. You need about 3 GB of free disk space.
  If it still fails on PyTorch or Ultralytics, install Python 3.12, delete the `.venv` folder, and run the installer again.
* **"DLL load failed" or an error mentioning torch when training or analysing (Windows)**: install the free "Microsoft Visual C++ Redistributable (x64)" from Microsoft, then start the app again.
* **"Port 8000 already in use"**: `start_windows.bat --port 8010`, then open http://localhost:8010.
* **Phone cannot connect**: the phone and computer must be on the same Wi-Fi (not a guest network that isolates devices), the app must be started with `--lan`, and Windows may ask to allow Python through the firewall: allow it on private networks.
* **Code rejected**: codes work once, for 10 minutes; after 5 wrong tries from one phone address pairing waits 5 minutes. Make a new code.
* **Phone says 'not selected'**: on the computer choose that phone in *Capture from* for the open slide.

## Honest limits

* **Stool and STI have no trained AI yet** and the demo pictures are drawn by the computer. Real use needs real, consented,
  expert-labelled photos for each test, then training and an evaluation at your laboratory.
* Gram stain finds gonorrhoea reliably in men with urethral discharge, but misses many infections in women; the report says
  so. Trichomonas is best seen moving in a fresh wet mount, which a still photo cannot show. A single negative stool misses
  many infections; test up to three samples.
* v3 was checked with automatic tests. The new screens have not yet been tried by technicians; run the user-testing protocol.

* **v2 was tested with automatic checks and emulated phones, not real ones.** Six phone profiles (iPhone SE/13, Pixel 7, Galaxy S9+/A55, Moto G4) were emulated in Chromium
  (the iPhone profiles are not real Safari). Test on your own phones, and run the user-testing protocol with your technicians, before relying on it.
* Demo models for both stains are trained on computer-drawn images only; their PPV/NPV show the software works and say nothing clinical.
* The PPV/NPV targets and the confirmation policy are placeholders from published guidance, to be set by the programme. WHO (2025) recommends molecular
  testing, not smear, as the initial test, so use S4Sight as a smear-reading aid and for monitoring.
* Demo images are computer-drawn. A model trained on them (marked DEMO everywhere) proves the software works, nothing more.
  Real performance needs real, consented, expert-labelled slides and a prospective evaluation against culture or Xpert.
* Grading follows the WHO/IUATLD scale for 100 fields; fewer fields are marked *provisional*.
* The app stores no patient names. Use anonymous lab codes.
* Sensitivity and specificity shown are only as good as the reference results entered, and small samples give wide intervals.
* The blur, dark and bright image flags use untuned default thresholds. Check them against a few of your own photos and adjust with the
  environment variables above. Flagged images are excluded from training.
