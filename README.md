# garmin-workout-uploader

Turns workout plans, such as a PDF from a coach or a program you bought, into Garmin Connect strength workouts and schedules them on your Garmin calendar, so each day's session shows up on your watch.

On the watch you get each exercise with its sets and rep targets, rest timers between sets, warm-up steps, supersets, drop sets, timed holds and AMRAP sets. Each step's notes carry the program's own exercise name, rep range, RPE, form cues and substitutions.

Your program stays private: PDFs, your program file and your login are all gitignored.

## How it works


1. **Get your plan into `program.json`**, a simple format described below.
2. **`build.py`** turns each day into a Garmin strength workout and matches exercise names to Garmin's exercise catalog.
3. **`upload.py`** logs in to Garmin Connect, uploads the workouts and puts them on your calendar.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

To try it without a plan of your own, use the example:

```
.venv/bin/python upload.py --program examples/full_body.json --map examples/exercise_map.json \
    --start 2026-11-02 --days mon thu --dry-run
```

## Step 1: Turn your PDF into program.json

Every workout PDF is laid out differently...

- **With a script.** `extract.py` is a working example that reads one specific 6-week Push/Pull/Legs PDF by the position of its table columns. Use it as a starting point for your own layout.
- **By hand.** For a short plan, write the JSON yourself. See [examples/full_body.json](examples/full_body.json).

Tip: don't open PDFs in VS Code's text editor. It can save them back as text and corrupt them.

### program.json format

```json
{
  "name": "Full Body",
  "days": [
    {
      "week": 1,
      "day": "Day A",
      "exercises": [
        {
          "exercise": "Barbell Back Squat",
          "warmup_sets": "2-3",
          "working_sets": 3,
          "reps": "5",
          "rpe": "8",
          "rest": "~3-4 min",
          "notes": "Brace hard.",
          "sub1": "Hack Squat",
          "sub2": "Leg Press"
        }
      ]
    }
  ]
}
```

Days are listed in the order you'll do them. Workouts are named `<name> W<week> <day>`, e.g. "Full Body W1 Day A".

| Field | Required | Meaning |
|---|---|---|
| `exercise` | yes | Exercise name, e.g. `"DB Bench Press"`. Prefix `A1.` / `A2.` on two consecutive exercises to make a superset. |
| `working_sets` | yes | Number of working sets, e.g. `3`. |
| `reps` | yes | Reps per set. See the formats below. |
| `rest` | no | Rest after each set: `"2 min"`, `"~3-4 min"` or `"90s"`. A range uses the top. |
| `warmup_sets` | no | e.g. `"2-3"`. Shown as one open warm-up step. |
| `rpe`, `notes`, `sub1`, `sub2` | no | Shown in the step notes on the watch. |

Formats for `reps`:

| Format | Meaning |
|---|---|
| `"10"`, `"8-12"` | Same target every set; a range uses the top. |
| `"8, 5, 12"` | A different target for each set. |
| `"10+5"` | One set done in parts with no rest, e.g. a drop set. To switch exercises partway, map the name to a list in the exercise map. |
| `"AMRAP"` | As many reps as possible; press lap when done. |
| `"30s HOLD"`, `"45s"` | A timed set. |

`build.py` checks the file and lists every problem it finds, with the exact day and exercise.

## Step 2: Check the workouts and exercise matches

```
.venv/bin/python build.py
```

This writes every workout to `workouts/` as JSON and lists any exercise names that didn't exactly match Garmin's catalog, along with the closest match it picked. It understands common gym shorthand (DB, RDL, pec deck, skull crusher, ...). If a guess is wrong, add it to `exercise_map.json`:

```json
{
  "Kroc Row": "Dumbbell Row",
  "Squeeze Pressdown + Overhead Extension": ["Triceps Press-down", "Cable Overhead Triceps Extension"]
}
```

Values must be Garmin exercise names exactly as they appear in the Garmin Connect workout editor. Use a list for a set that switches exercise partway through, like a `"8 + 8"` set of two exercises.

## Step 3: Upload and schedule

```
.venv/bin/python upload.py --start 2026-10-26 --dry-run   # preview the schedule
.venv/bin/python upload.py --start 2026-10-26             # upload + schedule
```

Workouts go onto your calendar one per training day, in program order, starting on `--start`. Options:

- `--days mon wed fri` sets the days you train (default: Monday to Saturday).
- `--weeks 1 2` uploads only those program weeks.
- `--no-schedule` uploads to your workout library without touching the calendar.
- `--program` / `--map` use different files (default: `program.json` / `exercise_map.json`).

The first run asks for your Garmin email and password, and for a code if Garmin sends one. Login tokens are saved in `.garminconnect/` (gitignored), so later runs don't ask again.

Re-running is safe: workouts are matched by name and updated in place, and a workout already on the calendar for its date isn't added again. So if you change your program, just run it again.

Then sync your watch from the Garmin Connect app, and each day's workout appears under Training → Workouts and on your calendar.

## How sets appear on the watch

- **Rest:** a countdown at the top of the range (4:00 for "~3-4 min"). Press lap to skip ahead.
- **Warm-ups:** one open step per exercise ("2-3 warm-up sets"). Press lap when done.
- **Rep targets:** the top of the range. The full range is in the step notes.

Built with [python-garminconnect](https://github.com/cyberjunky/python-garminconnect).
