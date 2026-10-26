"""Match program exercise names to Garmin Connect catalog exercises.

Each name is resolved in this order:
1. An entry in the exercise map file (a JSON object of program name -> Garmin
   display name, or a list of names for a set that switches exercise midway).
2. An exact Garmin catalog name, ignoring case.
3. The closest catalog name. These are guesses: they are recorded in GUESSES
   so callers can show them, and the program's own name always appears in the
   step notes on the watch.
"""

import difflib
import json
import math
import re
from collections import Counter
from pathlib import Path

from garminconnect.exercises import EXERCISES, resolve

BY_LOWER_NAME = {e["name"].lower(): e for e in EXERCISES}
# Guessed matches made so far: program name -> Garmin display name.
GUESSES = {}

# Gym names Garmin doesn't use -> the closest wording it does.
PHRASES = {
    "reverse pec deck": "rear lateral raise",
    "pec deck": "cable crossover",
    "pec stretch": "pectoral stretch",
    "pec static stretch": "pectoral stretch",
    "cable pec flye": "cable crossover",
    "cable pec fly": "cable crossover",
    "cable flye": "cable crossover",
    "cable fly": "cable crossover",
    "glute ham raise": "leg curl",
    "toe press": "calf raise",
    "skull crusher": "lying triceps extension",
    "stiff leg": "straight leg",
    "press around": "cable crossover",
    "larsen press": "bench press",
    "kroc row": "dumbbell row",
}
# Two words Garmin writes as one ("Lat Pull-down" -> "pulldown").
COMPOUNDS = {"pull down", "push up", "pull up", "press down", "pull over", "kick back", "chin up", "step up", "sit up"}
# Words naming special equipment or a stretch. A catalog entry with one of these
# only fits if the program name says so too.
SPECIAL = {"banded", "band", "suspension", "wheelchair", "swiss", "ball", "medicine", "ring", "trx", "sandbag", "stretch", "climber"}
# Gym shorthand -> the words Garmin's catalog uses.
SYNONYMS = {
    "db": "dumbbell",
    "dumbell": "dumbbell",
    "bb": "barbell",
    "kb": "kettlebell",
    "rdl": "romanian deadlift",
    "sldl": "straight leg deadlift",
    "stiff": "straight",
    "ohp": "overhead press",
    "flye": "fly",
    "flyes": "fly",
    "flys": "fly",
    "bicep": "biceps",
    "tricep": "triceps",
    "pushdown": "pressdown",
    "pec": "chest",
    "ez": "ezbar",
    "1": "single",
    "one": "single",
}
# Variant words that say how an exercise is done, not which exercise it is.
FILLER = {"a", "and", "the", "with", "on", "to", "of", "style", "only", "slow", "pause", "paused", "heavy"}


def _words(name):
    name = " ".join(re.findall(r"[a-z0-9]+", name.lower().replace("ez-bar", "ezbar")))
    for compound in COMPOUNDS:
        name = re.sub(rf"\b{compound}\b", compound.replace(" ", ""), name)
    for phrase, replacement in PHRASES.items():
        name = re.sub(rf"\b{phrase}\b", replacement, name)
    words = []
    for w in name.split():
        words += SYNONYMS.get(w, w).split()
    return words


def _stem(word):
    return word[:-1] if word.endswith("s") and word[:-1] in _VOCAB else word


_VOCAB = {w for e in EXERCISES for w in _words(e["name"])}
_CATALOG_WORDS = {e["name"].lower(): {_stem(w) for w in _words(e["name"])} for e in EXERCISES}
_DOC_FREQ = Counter(w for ws in _CATALOG_WORDS.values() for w in ws)
# Rare words ("arnold", "preacher") say more about an exercise than common ones ("dumbbell").
_IDF = {w: math.log(len(_CATALOG_WORDS) / n) + 1 for w, n in _DOC_FREQ.items()}

_overrides = {}


def load_map(path):
    """Load an exercise map file; a missing file just means no overrides."""
    global _overrides
    path = Path(path)
    _overrides = json.loads(path.read_text()) if path.exists() else {}
    for program_name, names in _overrides.items():
        for name in [names] if isinstance(names, str) else names:
            if resolve(name) is None:
                raise ValueError(f"{path}: '{name}' (for '{program_name}') is not a Garmin exercise name")


def _clean(name):
    """Drop superset labels like "A1." and notes in parentheses."""
    name = re.sub(r"^[A-Z]\d+\.\s*", "", name)
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def _score(words, catalog_name):
    """Shared-word weight, normalised so extra words on either side count against."""
    catalog = _CATALOG_WORDS[catalog_name]
    shared = sum(_IDF[w] for w in words & catalog)
    if not shared:
        return 0.0
    unknown = 3.0  # Weight for program words the catalog never uses.
    mine = sum(_IDF.get(w, unknown) for w in words)
    theirs = sum(_IDF[w] for w in catalog)
    score = shared / math.sqrt(mine * theirs)
    if (catalog & SPECIAL) - words:
        score *= 0.5
    # Tie-break on spelling similarity.
    return score + 0.01 * difflib.SequenceMatcher(None, " ".join(sorted(words)), catalog_name).ratio()


def _match(program_name):
    cleaned = _clean(program_name).lower()
    if cleaned in BY_LOWER_NAME:
        return BY_LOWER_NAME[cleaned]
    words = {_stem(w) for w in _words(cleaned)} - FILLER
    best = max(BY_LOWER_NAME, key=lambda name: _score(words, name))
    entry = BY_LOWER_NAME[best]
    GUESSES[program_name] = entry["name"]
    return entry


def garmin_exercises(program_name):
    """Return the list of Garmin catalog entries for a program exercise."""
    if program_name in _overrides:
        names = _overrides[program_name]
        return [resolve(n) for n in ([names] if isinstance(names, str) else names)]
    return [_match(program_name)]
