"""The tests S4Sight can read, and what can be found in each.

A "test type" (stored as `modality` on slides, images, datasets and models, for compatibility with v2)
decides: which stains and magnifications are offered, what the model looks for (its classes), how the
result is reported, and which tips the technician sees.

  zn   TB, Ziehl-Neelsen (bright-field)       graded:   negative / scanty / 1+ / 2+ / 3+
  fm   TB, fluorescence (auramine)            graded:   negative / scanty / 1+ / 2+ / 3+
  stl  Stool parasites (wet mount, Kato-Katz) findings: which eggs/larvae were seen, and how many
  sti  STI genital swab (Gram, wet mount)     findings: which organisms/cells were seen

Each test type has its own model, its own cut-offs and its own training data. A model for one does not
work for another.

The descriptions under "look" are short reminders for the bench, not a substitute for a bench atlas.
"""

PANELS = {
    "zn": {
        "name": "TB smear (Ziehl-Neelsen)", "short": "TB ZN", "group": "tb", "kind": "graded",
        "specimen": "Sputum", "icon": "lungs",
        "stains": ["Ziehl-Neelsen", "Kinyoun"], "magnifications": ["1000x"],
        "classes": [
            {"id": "afb", "name": "Acid-fast bacilli (AFB)", "group": "TB", "diagnostic": True,
             "look": "Thin red, slightly curved rods on a blue background."},
        ],
        "tips": ["Read at 1000x with oil. A full reading is 100 fields.",
                 "Use the same light setting for every field."],
    },
    "fm": {
        "name": "TB smear (fluorescence)", "short": "TB FM", "group": "tb", "kind": "graded",
        "specimen": "Sputum", "icon": "lungs",
        "stains": ["Auramine O", "Auramine-rhodamine"], "magnifications": ["200x", "250x", "400x"],
        "classes": [
            {"id": "afb", "name": "Acid-fast bacilli (AFB)", "group": "TB", "diagnostic": True,
             "look": "Bright yellow-green rods on a dark background."},
        ],
        "tips": ["Work in a dim room. A full reading is 300 fields at 200-250x or 40 fields at 400x.",
                 "Focus on the bright specks first, then take the picture."],
    },
    "stl": {
        "name": "Stool parasites", "short": "Stool", "group": "stool", "kind": "findings",
        "specimen": "Stool", "icon": "stool",
        "stains": ["Saline wet mount", "Iodine wet mount", "Kato-Katz", "Formol-ether concentration"],
        "magnifications": ["100x", "400x"],
        "classes": [
            # roundworms (nematodes)
            {"id": "ascaris", "name": "Ascaris lumbricoides egg", "group": "Roundworms", "diagnostic": True,
             "look": "Round to oval, thick brown shell with a bumpy outer coat. 45-75 um."},
            {"id": "hookworm", "name": "Hookworm egg", "group": "Roundworms", "diagnostic": True,
             "look": "Oval, thin clear shell, inside a ball of 4-8 cells with clear space around it. 60-75 um."},
            {"id": "trichuris", "name": "Trichuris trichiura egg (whipworm)", "group": "Roundworms", "diagnostic": True,
             "look": "Barrel or lemon shape, brown, a clear plug at each end. 50-55 um."},
            {"id": "strongyloides", "name": "Strongyloides stercoralis larva", "group": "Roundworms", "diagnostic": True,
             "look": "A moving worm-like larva (not an egg) in fresh stool. About 250 um long."},
            {"id": "enterobius", "name": "Enterobius vermicularis egg (pinworm)", "group": "Roundworms", "diagnostic": True,
             "look": "Clear shell, flat on one side (D shape). Best found with the tape test."},
            # tapeworms (cestodes)
            {"id": "taenia", "name": "Taenia egg (beef or pork tapeworm)", "group": "Tapeworms", "diagnostic": True,
             "look": "Round, thick brown shell with fine radial stripes, 6 hooks inside. 30-35 um."},
            {"id": "h_nana", "name": "Hymenolepis nana egg (dwarf tapeworm)", "group": "Tapeworms", "diagnostic": True,
             "look": "Round to oval, thin clear shell, 6 hooks inside, thread-like filaments at the poles. 30-47 um."},
            {"id": "diphyllobothrium", "name": "Diphyllobothrium egg (fish tapeworm)", "group": "Tapeworms", "diagnostic": True,
             "look": "Oval, yellow-brown, a lid at one end and a small knob at the other. 58-75 um."},
            # flukes (trematodes)
            {"id": "s_mansoni", "name": "Schistosoma mansoni egg", "group": "Flukes", "diagnostic": True,
             "look": "Large oval egg with a sharp spine on the side. 115-175 um."},
            {"id": "fasciola", "name": "Fasciola hepatica egg (liver fluke)", "group": "Flukes", "diagnostic": True,
             "look": "Very large oval, yellow-brown, a small lid at one end. 130-150 um."},
            {"id": "clonorchis", "name": "Clonorchis / Opisthorchis egg (liver fluke)", "group": "Flukes", "diagnostic": True,
             "look": "Small light-bulb shape with a lid that sits on 'shoulders'. 27-35 um."},
        ],
        "tips": ["Look at 100x for eggs, check at 400x. Scan the whole cover slip.",
                 "One negative stool does not rule out worms. Test up to 3 samples on different days."],
        "notes_negative": "No eggs or larvae seen. One stool sample can miss infection; repeat up to 3 times if symptoms continue.",
    },
    "sti": {
        "name": "STI swab (genital)", "short": "STI", "group": "sti", "kind": "findings",
        "specimen": "Vaginal, cervical or urethral swab", "icon": "swab",
        "stains": ["Gram stain", "Saline wet mount", "KOH preparation"],
        "magnifications": ["1000x", "400x"],
        "classes": [
            {"id": "gndc", "name": "Gram-negative intracellular diplococci", "group": "Gonorrhoea", "diagnostic": True,
             "look": "Pink pairs of bean-shaped cocci INSIDE pus cells (Gram stain, 1000x oil)."},
            {"id": "candida_yeast", "name": "Yeast cells (budding)", "group": "Candidiasis", "diagnostic": True,
             "look": "Oval cells 3-6 um, often budding. Purple on Gram stain, clear in KOH."},
            {"id": "candida_hyphae", "name": "Pseudohyphae", "group": "Candidiasis", "diagnostic": True,
             "look": "Long chains of stretched yeast cells, sometimes branching."},
            {"id": "trichomonas", "name": "Trichomonas vaginalis", "group": "Trichomoniasis", "diagnostic": True,
             "look": "Pear-shaped, a bit bigger than a pus cell, jerky movement with flagella (fresh saline wet mount)."},
            {"id": "clue_cell", "name": "Clue cells", "group": "Bacterial vaginosis", "diagnostic": True,
             "look": "Epithelial cells covered with small bacteria so the cell edge looks fuzzy."},
            {"id": "pus_cell", "name": "Pus cells (white cells)", "group": "Other", "diagnostic": False,
             "look": "Round cells with a lobed nucleus. Many pus cells suggest inflammation."},
        ],
        "tips": ["Gram stain at 1000x oil for diplococci and yeast. Look at a fresh saline wet mount at 400x for Trichomonas.",
                 "A negative smear in a woman does not rule out gonorrhoea; send a molecular test if it is available."],
        "notes_negative": "No organisms seen.",
    },
}

ORDER = ["zn", "fm", "stl", "sti"]
GRADED_GRADES = ["negative", "scanty", "1+", "2+", "3+"]
FINDING_RESULTS = ["negative", "positive"]


def keys():
    return list(ORDER)


def get(modality):
    return PANELS.get(modality) or PANELS["zn"]


def is_valid(modality):
    return modality in PANELS


def is_graded(modality):
    return get(modality)["kind"] == "graded"


def class_ids(modality):
    return [c["id"] for c in get(modality)["classes"]]


def class_index(modality):
    """class id -> YOLO class number for this test type (the order in the catalog)."""
    return {c: i for i, c in enumerate(class_ids(modality))}


def class_name(modality, cid):
    for c in get(modality)["classes"]:
        if c["id"] == cid:
            return c["name"]
    return cid


def default_label(modality):
    return class_ids(modality)[0]


def results_for(modality):
    return GRADED_GRADES if is_graded(modality) else FINDING_RESULTS


def public():
    """What the web page needs to draw forms and checklists."""
    return {k: {kk: vv for kk, vv in PANELS[k].items()} for k in ORDER}


# ------------------------------------------------------------------ reporting findings
def clean_findings(modality, findings):
    """Keep only known class ids with whole, non-negative counts."""
    out = {}
    valid = set(class_ids(modality))
    for k, v in (findings or {}).items():
        if k in valid:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[k] = min(n, 100000)
    return out


def findings_result(modality, findings):
    """'positive' if any diagnostic finding was seen, else 'negative'."""
    diag = {c["id"] for c in get(modality)["classes"] if c["diagnostic"]}
    return "positive" if any(n > 0 and k in diag for k, n in (findings or {}).items()) else "negative"


def interpret(modality, findings, stain=""):
    """Short plain-language report lines for a findings test."""
    p = get(modality)
    findings = findings or {}
    lines = []
    groups = {}
    for c in p["classes"]:
        n = findings.get(c["id"], 0)
        if n > 0:
            groups.setdefault(c["group"], []).append(f"{c['name']} ({n} seen)")
    for g, items in groups.items():
        lines.append(f"{g}: " + "; ".join(items))
    if modality == "sti":
        if findings.get("gndc"):
            lines.append("Gram-negative intracellular diplococci: consistent with gonorrhoea. Treat per national guideline.")
        if findings.get("candida_yeast") or findings.get("candida_hyphae"):
            lines.append("Yeast or pseudohyphae seen: consistent with candidiasis.")
        if findings.get("trichomonas"):
            lines.append("Trichomonas vaginalis seen.")
        if findings.get("clue_cell"):
            lines.append("Clue cells seen: suggests bacterial vaginosis (check with Amsel or Nugent criteria).")
        if not findings.get("gndc"):
            lines.append("No diplococci seen. In women this does not rule out gonorrhoea (smear misses many infections).")
    if findings_result(modality, findings) == "negative" and p.get("notes_negative"):
        lines.append(p["notes_negative"])
    return lines
