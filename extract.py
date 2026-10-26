"""Example parser: extract one specific PDF layout into program.json.

This reads a 6-week Push/Pull/Legs PDF where each page is one training day laid
out as a table. It's tied to that PDF's layout; for another PDF, write a parser
like this one, write program.json by hand, or ask Claude Code to convert the
PDF (see README).

The table columns sit at fixed x positions, so words are bucketed into columns
by x, and rows are split using the working-sets column (every exercise row has
a value there) as the anchor.
"""

import json
import re
import sys

import pymupdf

# (column name, x upper bound) - a word belongs to the first column whose bound
# exceeds the word's horizontal centre.
COLUMNS = [
    ("label", 180),
    ("exercise", 370),
    ("warmup_sets", 450),
    ("working_sets", 530),
    ("reps", 620),
    ("load", 700),
    ("rpe", 790),
    ("rest", 890),
    ("sub1", 1030),
    ("sub2", 1180),
    ("notes", 10_000),
]
TABLE_TOP = 170
TABLE_BOTTOM = 900
# Rows whose comma-separated reps are parts of one set ("5, 15" = 5 slow reps
# then 15 more), not one target per set; rewritten as "5+15".
WITHIN_SET_REPS = {
    "Eccentric-Accentuated Cable Lateral Raise, Constant-Tension Cable Lateral Raise",
}


def column_for(x):
    for name, bound in COLUMNS:
        if x < bound:
            return name
    return COLUMNS[-1][0]


def join_words(words):
    """Join words in reading order, fixing hyphenated line breaks."""
    words = sorted(words, key=lambda w: (round(w[1] / 5), w[0]))
    text = " ".join(w[4] for w in words)
    text = re.sub(r"(\w)- (\w)", r"\1-\2", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_page(page):
    words = page.get_text("words")
    full_text = page.get_text()
    week = int(re.search(r"WEEK (\d+)", full_text).group(1))
    day = re.search(r"((?:Push|Pull|LEGs|Legs) #\d)", full_text).group(1)
    day = day.replace("LEGs", "Legs")

    # Drop the "Mandatory Rest Day" banner, which overlaps the last row.
    banner = {(w[5], w[6]) for w in words if w[4] == "Mandatory"}
    words = [w for w in words if (w[5], w[6]) not in banner]

    table = [w for w in words if TABLE_TOP < w[1] < TABLE_BOTTOM]
    anchors = sorted(
        {round((w[1] + w[3]) / 2) for w in table if column_for((w[0] + w[2]) / 2) == "working_sets"}
    )
    # Row boundaries halfway between consecutive anchors.
    bounds = [TABLE_TOP]
    bounds += [(a + b) / 2 for a, b in zip(anchors, anchors[1:])]
    bounds.append(TABLE_BOTTOM)

    rows = []
    for top, bottom in zip(bounds, bounds[1:]):
        cells = {name: [] for name, _ in COLUMNS}
        for w in table:
            ymid = (w[1] + w[3]) / 2
            if top <= ymid < bottom:
                cells[column_for((w[0] + w[2]) / 2)].append(w)
        row = {name: join_words(ws) for name, ws in cells.items() if name != "label"}
        if row["exercise"] in WITHIN_SET_REPS:
            row["reps"] = row["reps"].replace(", ", "+")
        rows.append(row)
    return {"week": week, "day": day, "page": page.number + 1, "exercises": rows}


def main(path="ppl_program.pdf", out="program.json", name="PPL"):
    doc = pymupdf.open(path)
    days = [parse_page(p) for p in doc]
    with open(out, "w") as f:
        json.dump({"name": name, "days": days}, f, indent=2)
    print(f"Wrote {len(days)} days to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
