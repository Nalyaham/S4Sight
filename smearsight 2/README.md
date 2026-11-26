# SmearSight: TB smear reading assistant

A web application that runs on one laboratory computer (no internet needed after setup). A technician photographs
microscope fields of a Ziehl-Neelsen smear, a YOLOv8 model marks suspected acid-fast bacilli (AFB), the technician
checks and corrects the boxes, and the app suggests a WHO/IUATLD grade. The app also stores images for a dataset,
supports two-reader labelling, retrains the model, and records time per slide so you can measure the benefit.

**A person always makes the final call.** SmearSight is a research tool, not a validated diagnostic device.

## Run it

Requires Python 3.10 or newer. First run needs internet once, to install packages.

    Linux / macOS:   ./run.sh
    Windows:         double-click run.bat      (or:  py -m venv .venv  &  .venv\Scripts\pip install -r requirements.txt  &  .venv\Scripts\python run.py)

Then open http://localhost:8000.

Using phones as the camera: run `python run.py --lan --pin 1234`, connect the phone to the same Wi-Fi, and open the
address the app prints. In **Analyze slide** the *Take photo* button opens the phone camera. Always set a PIN
when using `--lan`; anyone on the network could otherwise open the app.

All data lives in the `data/` folder (database, images, datasets, models). Copy it, or use Settings, Download full backup.

## Workflow

1. **Dataset**: upload field images (tick the consent box only if consent or an ethics waiver covers training use),
   import a YOLO-format zip, or press *Generate demo images* to try the app with synthetic pictures.
2. Label images by drawing boxes. A *different* reader verifies them. Only verified images are used for training.
3. **Freeze a version.** Images are split into train/validation/test by slide, so one slide is never in both training and test.
4. **Model training**: trains YOLOv8n on the CPU and evaluates on the held-out test slides.
   Put `yolov8n.pt` in `data/models/base/` to start from pretrained weights (recommended with real data); otherwise training starts from scratch.
5. A senior reader or the lab lead **approves** the candidate. Approval is blocked if its sensitivity is lower than the active model's, and
   older models can be rolled back to.
6. **Analyze slide**: photograph fields, tap boxes to count or uncount them, drag to add missed bacilli, confirm a final grade.
   A reason is required when you override the suggestion. Doing this builds the time-per-slide statistics.
7. **Expert review**: detections with confidence below 0.60 queue for two readers to vote on; disagreements go to a senior reader.
8. **Performance**: time per slide (app vs your manual time), sensitivity and specificity against culture or Xpert results (with 95% confidence intervals), by site, CSV export.

## Honest limits

* The demo images are computer-drawn. A model trained on them (marked DEMO everywhere) proves the software works, nothing more.
  Real performance needs real, consented, expert-labelled slides, and a prospective evaluation against culture or Xpert.
* Grading follows the WHO/IUATLD scale for 100 fields; fewer fields are marked *provisional*.
* The app does not store patient names. Use anonymous lab codes.
* Sensitivity and specificity shown in the app are only as good as the reference results you enter, and small samples give wide intervals.
* Photos from phones vary in focus and lighting; the app flags blurry, dark or bright images, but those thresholds are untuned defaults (adjust with SMEARSIGHT_BLUR_MIN, SMEARSIGHT_DARK_MAX, SMEARSIGHT_BRIGHT_MIN after checking a few of your own photos). Flagged images are excluded from training.

## Layout

    app/            FastAPI backend (main.py), database, grading, dataset freezing, inference, training worker
    static/         the web interface (plain JavaScript, no internet needed)
    tests/          python -m pytest tests
    data/           created on first run
