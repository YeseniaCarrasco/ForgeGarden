"""Volunteer schedule for the Forge Garden calendar.

Three kinds of opportunities appear on the calendar:
  * drop-in  - open volunteer hours; just show up.
  * sign-up  - a shift one volunteer must claim (requires login).
  * event    - a garden event shown for reference; no volunteers needed.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DROP_IN = "drop-in"
SIGN_UP = "sign-up"
EVENT = "event"

KIND_LABELS = {
    DROP_IN: "Drop-in hours (just show up)",
    SIGN_UP: "Sign-up required (log in)",
    EVENT: "Garden event (no volunteers needed)",
}


def fmt_time(t, suffix=True):
    """10:20 -> '10:20am', 13:00 -> '1pm'."""
    hour = t.hour % 12 or 12
    text = f"{hour}:{t.minute:02d}" if t.minute else f"{hour}"
    if suffix:
        text += "am" if t.hour < 12 else "pm"
    return text


def fmt_range(start, end=None):
    """Format a time range, dropping the first am/pm when both match: '1–2pm'."""
    if end is None:
        return fmt_time(start)
    same_half = (start.hour < 12) == (end.hour < 12)
    return f"{fmt_time(start, suffix=not same_half)}–{fmt_time(end)}"


@dataclass(frozen=True)
class Opportunity:
    key: str
    title: str
    kind: str
    start: time
    end: time | None
    description: str

    @property
    def time_label(self):
        return fmt_range(self.start, self.end)

    @property
    def display_end(self):
        """End time used to size the block on the week grid."""
        if self.end:
            return self.end
        return (datetime.combine(date.min, self.start) + OPEN_ENDED_BLOCK).time()


COMPOST_ROUTE = Opportunity(
    "compost", "Compost Route", SIGN_UP, time(10, 20), None,
    "One volunteer runs the compost route each day. First time running it? "
    "You'll choose a training day when you sign up.",
)
GLEAN_TEAM = Opportunity(
    "glean", "Glean Team", DROP_IN, time(13, 0), time(14, 0),
    "Pick excess fruit from neighborhood trees whose owners have asked us to "
    "harvest them.",
)
GARDEN_WORK = Opportunity(
    "garden", "Garden Work", DROP_IN, time(14, 30), time(16, 0),
    "Help with work around the garden.",
)
FARMSTAND_HARVEST = Opportunity(
    "harvest", "Farmstand Harvest", DROP_IN, time(9, 30), time(11, 30),
    "Harvest the veggies and fruit that are ready for that day's farmstand.",
)
FARMSTAND = Opportunity(
    "farmstand", "Farmstand", EVENT, time(11, 30), time(13, 30),
    "11:30am–12:30pm is student hour; 12:30–1:30pm is open to everyone, "
    "including community members.",
)
NOURISH_PREP = Opportunity(
    "nourish", "Nourish Night Prep", DROP_IN, time(16, 30), time(18, 0),
    "Help prep food for Nourish Night, where students can get a free "
    "plant-based meal.",
)

# Weekly opportunities keyed by date.weekday() (Monday = 0).
WEEKLY = {
    0: [NOURISH_PREP],
    1: [GLEAN_TEAM, GARDEN_WORK],
    4: [FARMSTAND_HARVEST, FARMSTAND],
}
DAILY = [COMPOST_ROUTE]

# Human-readable overview, shown below the calendar.
SCHEDULE_SUMMARY = [
    ("Every day", DAILY),
    ("Mondays", WEEKLY[0]),
    ("Tuesdays", WEEKLY[1]),
    ("Fridays", WEEKLY[4]),
]

# Week grid settings: the grid runs 9am-6pm in 10-minute rows. Opportunities
# with only a start time (the compost route) are drawn as 40-minute blocks.
GRID_START = time(9, 0)
GRID_END = time(18, 0)
SLOT_MINUTES = 10
SLOTS_PER_HOUR = 60 // SLOT_MINUTES
GRID_ROWS = (GRID_END.hour - GRID_START.hour) * SLOTS_PER_HOUR
OPEN_ENDED_BLOCK = timedelta(minutes=40)


def opportunities_for(day):
    """All opportunities on a given date, in start-time order."""
    return sorted(DAILY + WEEKLY.get(day.weekday(), []), key=lambda o: o.start)


def week_start(day):
    """The Sunday on or before the given date (weeks run Sunday-Saturday)."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_label(start):
    """'November 8–14, 2026', 'Nov 29 – Dec 5, 2026', or across years in full."""
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start:%B} {start.day}–{end.day}, {end.year}"
    if start.year == end.year:
        return f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    return f"{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"


def _grid_line(t):
    """CSS grid line where a time falls (line 1 = GRID_START)."""
    minutes = (t.hour - GRID_START.hour) * 60 + t.minute - GRID_START.minute
    return minutes // SLOT_MINUTES + 1


def hour_labels():
    """(label, grid-row) pairs for the time axis, one per hour."""
    return [
        (fmt_time(time(h)), f"{_grid_line(time(h))} / span {SLOTS_PER_HOUR}")
        for h in range(GRID_START.hour, GRID_END.hour)
    ]


def layout_day(day):
    """Place a day's opportunities on the week grid.

    Blocks in lane 0 span the whole day column. When blocks overlap, each
    later one goes in its own lane and is drawn on top, covering the right
    three-quarters of the column. Returns (blocks, grid_columns), where
    grid_columns is the CSS grid-template-columns value for the day column.
    """
    lane_ends = []
    blocks = []
    for opp in opportunities_for(day):
        start, end = opp.start, opp.display_end
        for lane, lane_end in enumerate(lane_ends):
            if lane_end <= start:
                lane_ends[lane] = end
                break
        else:
            lane_ends.append(end)
            lane = len(lane_ends) - 1
        blocks.append({
            "opp": opp,
            "row": f"{_grid_line(start)} / {_grid_line(end)}",
            "col": "1 / -1" if lane == 0 else f"{lane + 1} / -1",
            "stacked": lane > 0,
        })
    lanes = max(len(lane_ends), 1)
    columns = " ".join(["minmax(0, 1fr)"] + ["minmax(0, 3fr)"] * (lanes - 1))
    return blocks, columns


def long_date(day):
    """date(2026, 11, 20) -> 'Friday, November 20, 2026'."""
    return f"{day:%A, %B} {day.day}, {day.year}"
