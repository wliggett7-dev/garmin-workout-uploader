"""Turn a program file into Garmin Connect strength workouts.

Run directly to check the program and write every workout to workouts/ as JSON
for review:

    .venv/bin/python build.py [--program program.json] [--map exercise_map.json]
"""

import argparse
import json
import re
from pathlib import Path

from garminconnect.workout import (
    ConditionType,
    ExecutableStep,
    StepType,
    StrengthWorkout,
    TargetType,
    WorkoutSegment,
    create_repeat_group,
    create_strength_rest_step,
)

from exercise_map import GUESSES, garmin_exercises, load_map

# Garmin truncates longer step notes.
MAX_DESCRIPTION = 500
# Rough time per working set, for Garmin's duration estimate.
SECONDS_PER_SET = 45

NO_TARGET = {
    "workoutTargetTypeId": TargetType.NO_TARGET,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
END_REPS = {
    "conditionTypeId": ConditionType.REPS,
    "conditionTypeKey": "reps",
    "displayOrder": 10,
    "displayable": True,
}
END_TIME = {
    "conditionTypeId": ConditionType.TIME,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
END_LAP = {
    "conditionTypeId": ConditionType.LAP_BUTTON,
    "conditionTypeKey": "lap.button",
    "displayOrder": 1,
    "displayable": True,
}


REPS_PATTERN = re.compile(
    r"^(AMRAP|\d+\s*s(ec)?\s*(HOLD)?|\d+(-\d+)?(\s*[+,]\s*\d+(-\d+)?)*)$", re.IGNORECASE
)
REST_PATTERN = re.compile(r"^~?\s*\d+(-\d+)?\s*(min|mins|s|sec|secs)?$", re.IGNORECASE)
SETS_PATTERN = re.compile(r"^\d+(-\d+)?$")
EXERCISE_DEFAULTS = {
    "warmup_sets": "0",
    "rpe": "",
    "rest": "0",
    "sub1": "",
    "sub2": "",
    "notes": "",
}


def upper_bound(text):
    """Top of a range like "3-5" or "~3-4 min" (the last number in the text)."""
    return int(re.findall(r"\d+", text)[-1])


def rest_seconds(text):
    """Rest in seconds; a bare number like "2" or "~3-4" means minutes."""
    if re.search(r"\ds", text.replace(" ", "")) and "min" not in text:
        return upper_bound(text)
    return upper_bound(text) * 60


def is_timed(reps):
    """Reps like "30s" or "30s HOLD" mean a set done for time."""
    return bool(re.match(r"^\d+\s*s", reps, re.IGNORECASE))


def load_program(path="program.json"):
    """Load a program file, fill in optional fields and check every value.

    Raises ValueError listing every problem found.
    """
    with open(path) as f:
        program = json.load(f)
    if isinstance(program, list):  # Older format: just the list of days.
        program = {"name": "Program", "days": program}

    errors = []
    if not isinstance(program.get("days"), list) or not program["days"]:
        raise ValueError(f'{path}: needs a non-empty "days" list')
    program.setdefault("name", "Program")

    for i, day in enumerate(program["days"]):
        where = f"days[{i}]"
        if not isinstance(day.get("week"), int) or day["week"] < 1:
            errors.append(f'{where}: "week" must be a whole number of at least 1')
        if not isinstance(day.get("day"), str) or not day["day"].strip():
            errors.append(f'{where}: "day" must be a name like "Push #1"')
        where = f"{where} (week {day.get('week')}, {day.get('day')})"
        if not isinstance(day.get("exercises"), list) or not day["exercises"]:
            errors.append(f'{where}: needs a non-empty "exercises" list')
            continue
        for j, row in enumerate(day["exercises"]):
            for key, default in EXERCISE_DEFAULTS.items():
                row[key] = str(row.get(key) or default).strip()
            for key in ("exercise", "working_sets", "reps"):
                row[key] = str(row.get(key, "")).strip()
            label = f"{where} exercise {j + 1} '{row['exercise']}'"
            if not row["exercise"]:
                errors.append(f'{where} exercise {j + 1}: "exercise" name is missing')
            if not row["working_sets"].isdigit() or int(row["working_sets"]) < 1:
                errors.append(f'{label}: "working_sets" must be a whole number like 3, got "{row["working_sets"]}"')
            if not REPS_PATTERN.match(row["reps"]):
                errors.append(
                    f'{label}: "reps" of "{row["reps"]}" not understood '
                    '(examples: "10", "8-12", "10+5", "8, 5, 12", "AMRAP", "30s HOLD")'
                )
            if not REST_PATTERN.match(row["rest"]):
                errors.append(f'{label}: "rest" of "{row["rest"]}" not understood (examples: "2 min", "~3-4 min", "90s")')
            if not SETS_PATTERN.match(row["warmup_sets"]):
                errors.append(f'{label}: "warmup_sets" must be a number or range like "2-3", got "{row["warmup_sets"]}"')
    if errors:
        raise ValueError(f"{path} has {len(errors)} problem(s):\n  " + "\n  ".join(errors))
    return program


class StepCounter:
    """Hands out the unique, increasing stepOrder Garmin requires."""

    def __init__(self):
        self.n = 0

    def next(self):
        self.n += 1
        return self.n


def describe(row):
    parts = [f"{row['exercise']}: {row['reps']} reps"]
    if row["rpe"] not in ("", "N/A"):
        parts[0] += f" @ RPE {row['rpe']}"
    if row["notes"]:
        parts.append(row["notes"])
    subs = [s for s in (row["sub1"], row["sub2"]) if s and s != "N/A"]
    if subs:
        parts.append("Subs: " + " / ".join(subs))
    text = " ".join(parts)
    return text if len(text) <= MAX_DESCRIPTION else text[: MAX_DESCRIPTION - 1] + "…"


def exercise_step(order, entry, end_condition, value, description, step_type=None):
    return ExecutableStep(
        stepOrder=order,
        stepType=step_type
        or {"stepTypeId": StepType.INTERVAL, "stepTypeKey": "interval", "displayOrder": 3},
        endCondition=end_condition,
        endConditionValue=value,
        targetType=NO_TARGET,
        description=description,
        category=entry["category"],
        exerciseName=entry["exercise"],
    )


def warmup_step(order, entry, row):
    return exercise_step(
        order,
        entry,
        END_LAP,
        None,
        f"{row['warmup_sets']} warm-up sets for {row['exercise']}",
        step_type={"stepTypeId": StepType.WARMUP, "stepTypeKey": "warmup", "displayOrder": 1},
    )


def set_steps(steps, row, entries, reps):
    """Exercise step(s) making up one set, for a reps string like "10", "10+5", "AMRAP"."""
    desc = describe(row)
    if reps == "AMRAP":
        return [exercise_step(steps.next(), entries[0], END_LAP, None, desc)]
    if is_timed(reps):
        return [exercise_step(steps.next(), entries[0], END_TIME, float(upper_bound(reps)), desc)]
    # "8 + 8" (two exercises) or "10+5" (dropset): one set done in parts.
    pieces = [p for p in reps.split("+") if p.strip()]
    result = []
    for i, piece in enumerate(pieces):
        entry = entries[min(i, len(entries) - 1)]
        result.append(exercise_step(steps.next(), entry, END_REPS, float(upper_bound(piece)), desc))
    return result


def exercise_blocks(steps, rows):
    """Steps for one exercise row, or an A1/A2 superset given as two rows."""
    first = rows[0]
    entries = [garmin_exercises(r["exercise"]) for r in rows]
    blocks = []

    if first["warmup_sets"] not in ("", "0"):
        blocks.append(warmup_step(steps.next(), entries[0][0], first))

    sets = int(first["working_sets"])
    rest = rest_seconds(rows[-1]["rest"])
    reps = first["reps"]

    if "," in reps:
        # "8, 5, 12": a different rep target for each set, so unroll the sets.
        for set_reps in [r.strip() for r in reps.split(",")][:sets]:
            blocks += set_steps(steps, first, entries[0], set_reps)
            if rest:
                blocks.append(create_strength_rest_step(rest, steps.next()))
        return blocks

    group_order = steps.next()
    inner = []
    for row, entry in zip(rows, entries):
        inner += set_steps(steps, row, entry, row["reps"])
    if rest:
        inner.append(create_strength_rest_step(rest, steps.next()))
    blocks.append(create_repeat_group(sets, inner, group_order))
    return blocks


def group_rows(rows):
    """Pair A1./A2. superset rows; every other row stands alone."""
    groups = []
    for row in rows:
        if row["exercise"].startswith("A2.") and groups and groups[-1][0]["exercise"].startswith("A1."):
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def estimate_seconds(day):
    total = 0
    for row in day["exercises"]:
        sets = int(row["working_sets"])
        total += sets * (SECONDS_PER_SET + rest_seconds(row["rest"]))
        if row["warmup_sets"] not in ("", "0"):
            total += upper_bound(row["warmup_sets"]) * 90
    return total


def workout_name(program, day):
    return f"{program['name']} W{day['week']} {day['day']}"


def build_workout(program, day):
    steps = StepCounter()
    workout_steps = []
    for rows in group_rows(day["exercises"]):
        workout_steps += exercise_blocks(steps, rows)
    return StrengthWorkout(
        workoutName=workout_name(program, day),
        description=f"{program['name']} - Week {day['week']}, {day['day']}",
        estimatedDurationInSecs=estimate_seconds(day),
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType=StrengthWorkout.model_fields["sportType"].default_factory(),
                workoutSteps=workout_steps,
            )
        ],
    )


def add_program_args(parser):
    parser.add_argument("--program", default="program.json", help="program file (default: program.json)")
    parser.add_argument("--map", default="exercise_map.json", help="exercise map file (default: exercise_map.json)")


def load(args):
    """Load the map and program named on the command line, exiting on problems."""
    try:
        load_map(args.map)
        return load_program(args.program)
    except (OSError, ValueError) as e:
        raise SystemExit(f"Error: {e}")


def report_guesses():
    if GUESSES:
        print(f"\n{len(GUESSES)} exercise(s) had no exact Garmin match; closest guesses used:")
        for program_name, garmin_name in GUESSES.items():
            print(f"  {program_name}  ->  {garmin_name}")
        print("To change one, add it to your exercise map file (see README).")


def main():
    parser = argparse.ArgumentParser(description="Check a program and write its Garmin workouts to workouts/")
    add_program_args(parser)
    program = load(parser.parse_args())
    out = Path("workouts")
    out.mkdir(exist_ok=True)
    for day in program["days"]:
        workout = build_workout(program, day)
        name = re.sub(r"[^\w-]+", "_", workout_name(program, day)).strip("_")
        (out / f"{name}.json").write_text(json.dumps(workout.to_dict(), indent=2))
    print(f"Wrote {len(program['days'])} workouts to {out}/")
    report_guesses()


if __name__ == "__main__":
    main()
