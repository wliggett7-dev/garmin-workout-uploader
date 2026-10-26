"""Upload a program's workouts to Garmin Connect and schedule them on the calendar.

    .venv/bin/python upload.py --start 2026-10-26              # upload + schedule
    .venv/bin/python upload.py --start 2026-10-26 --dry-run    # preview only
    .venv/bin/python upload.py --start 2026-10-26 --days mon wed fri
    .venv/bin/python upload.py --no-schedule --weeks 1

Workouts go onto the calendar in program order, one per training day, starting
on --start. The first run asks for your Garmin email and password (and a code if
Garmin sends one); login tokens are then saved in .garminconnect/ so later runs
don't ask again. Re-running is safe: workouts are matched by name and updated in
place, and a workout already on the calendar for its date isn't added twice.
"""

import argparse
import datetime as dt
import getpass
from pathlib import Path

from garminconnect import Garmin

from build import add_program_args, build_workout, load, report_guesses, workout_name

TOKENSTORE = Path(".garminconnect")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def login():
    if TOKENSTORE.exists():
        client = Garmin()
    else:
        email = input("Garmin email: ")
        password = getpass.getpass("Garmin password: ")
        client = Garmin(email, password, prompt_mfa=lambda: input("MFA code: "))
    client.login(str(TOKENSTORE))
    return client


def existing_workouts(client):
    """Map workout name -> id for the workouts already in your library."""
    found, start = {}, 0
    while True:
        page = client.get_workouts(start, 100, my_workouts_only=True)
        for w in page:
            found[w["workoutName"]] = w["workoutId"]
        if len(page) < 100:
            return found
        start += 100


def scheduled_pairs(client, first, last):
    """(workoutId, date) pairs already on the calendar between two dates."""
    items = client.get_scheduled_workouts_by_period(first.isoformat(), last.isoformat())
    pairs = set()
    for item in items:
        workout_id = item.get("workoutId") or (item.get("workout") or {}).get("workoutId")
        date = item.get("date") or item.get("calendarDate") or item.get("scheduleDate")
        if workout_id and date:
            pairs.add((workout_id, str(date)[:10]))
    return pairs


def training_dates(start, count, weekdays):
    """The first `count` dates on or after `start` that fall on a training weekday."""
    allowed = {WEEKDAYS.index(d) for d in weekdays}
    dates, date = [], start
    while len(dates) < count:
        if date.weekday() in allowed:
            dates.append(date)
        date += dt.timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_program_args(parser)
    parser.add_argument("--start", type=dt.date.fromisoformat, help="date of the first workout (YYYY-MM-DD)")
    parser.add_argument(
        "--days",
        nargs="+",
        type=str.lower,
        choices=WEEKDAYS,
        default=WEEKDAYS[:6],
        help="weekdays you train (default: mon tue wed thu fri sat)",
    )
    parser.add_argument("--no-schedule", action="store_true", help="upload only, don't touch the calendar")
    parser.add_argument("--weeks", type=int, nargs="+", help="only upload these program weeks")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen without logging in")
    args = parser.parse_args()
    if not args.no_schedule and not args.start:
        parser.error("--start is required unless --no-schedule is given")

    program = load(args)
    days = program["days"]
    # Dates come from the whole program so --weeks doesn't shift them.
    dates = [None] * len(days) if args.no_schedule else training_dates(args.start, len(days), args.days)
    plan = [(d, date) for d, date in zip(days, dates) if not args.weeks or d["week"] in args.weeks]
    # Build everything first so a bad program fails before anything is uploaded.
    payloads = [build_workout(program, day).to_dict() for day, _ in plan]

    if args.dry_run:
        for day, date in plan:
            when = f"{date:%a %Y-%m-%d}" if date else "unscheduled"
            print(f"{when:16} {workout_name(program, day)}")
        report_guesses()
        return

    client = login()
    library = existing_workouts(client)
    scheduled = [date for _, date in plan if date]
    calendar = scheduled_pairs(client, min(scheduled), max(scheduled)) if scheduled else set()

    for (day, date), payload in zip(plan, payloads):
        name = workout_name(program, day)
        if name in library:
            workout_id = library[name]
            client.update_workout(workout_id, payload)
            action = "updated"
        else:
            workout_id = client.upload_workout(payload)["workoutId"]
            action = "uploaded"
        line = f"{action:8} {name}"
        if date:
            if (workout_id, date.isoformat()) in calendar:
                line += f"  (already on {date:%a %b %d})"
            else:
                client.schedule_workout(workout_id, date.isoformat())
                line += f"  -> {date:%a %b %d}"
        print(line)
    report_guesses()


if __name__ == "__main__":
    main()
