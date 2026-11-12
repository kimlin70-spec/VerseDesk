"""Move seasonal passages in tools/verse_plan.tsv to fitting dates (by swapping).

usage: python3 -I tools/seasonal.py [tools/verse_plan.tsv]   (rewrites the file in place)
then:  python3 -I tools/build_verses.py

Each rule is (regex for a reference, target date). The first plan entry matching the regex
is swapped with the entry currently on the target date: Advent prophecies and the nativity
in December, Matthew 2 on Epiphany (01-06), the Passion and Easter from 03-24 to 04-07
(Easter moves every year; the plan keeps one date per verse, so this is an approximation).
Fixed special days never move. Afterwards neighbouring days from the same book are
separated by swapping with free days. Running it again on an arranged plan changes nothing.
"""
import re
import sys
from pathlib import Path

FIXED = {"01-01", "01-02", "02-14", "02-29", "03-01", "03-20", "05-05", "05-08", "08-15",
         "10-31", "11-25", "12-24", "12-25", "12-31"}

RULES = [
    # Advent: prophecy -> annunciation -> incarnation -> the angels, then Christmastide
    (r"^Isaiah 7:14", "12-01"),
    (r"^Micah 5:2", "12-03"),
    (r"^Isaiah 9:2\b", "12-05"),
    (r"^Luke 1:37", "12-08"),
    (r"^Luke 1:38", "12-10"),
    (r"^Matthew 1:2[0-3]", "12-13"),
    (r"^Galatians 4:4", "12-16"),
    (r"^John 1:14", "12-19"),
    (r"^Luke 2:1[3-4]", "12-22"),
    (r"^Luke 2:19", "12-26"),
    (r"^Luke 2:52", "12-29"),
    (r"^Matthew 2:(1|2|9|10|11)\b", "01-06"),  # Epiphany
    # Passion and Easter (Easter falls between 22 March and 25 April)
    (r"^Isaiah 53:", "03-24"),
    (r"^Luke 22:4[1-4]", "03-26"),
    (r"^Luke 23:34", "03-27"),
    (r"^John 19:30", "03-30"),
    (r"^Matthew 28:[1-7]\b", "04-02"),
    (r"^Luke 24:", "04-03"),
    (r"^John 20:", "04-04"),
    (r"^John 11:25", "04-05"),
    (r"^1 Corinthians 15:(20|5[4-7])", "04-07"),
]


def book(ref):
    return ref.rsplit(" ", 1)[0]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "verse_plan.tsv"
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [l for l in lines if l.startswith("#")]
    rows = [l.split("\t")[:2] for l in lines if l and not l.startswith("#")]
    plan = {d: r for d, r in rows}
    dates = [d for d, _ in rows]
    placed = set()
    for pattern, target in RULES:
        assert target not in FIXED, target
        src = next((d for d in dates if d not in FIXED and d not in placed and re.search(pattern, plan[d])), None)
        if src is None:
            continue
        if src != target:
            plan[src], plan[target] = plan[target], plan[src]
            print(f"{plan[target]}: {src} -> {target} (swapped with {plan[src]})")
        placed.add(target)
    # break up neighbours from the same book by swapping with a free (non-fixed, non-seasonal) day
    locked = FIXED | placed

    def clashes(i):
        return sum(1 for j in (i - 1, i + 1) if 0 <= j < len(dates) and book(plan[dates[j]]) == book(plan[dates[i]]))

    for _ in range(3):
        for i in range(1, len(dates)):
            a, b = dates[i - 1], dates[i]
            if book(plan[a]) != book(plan[b]):
                continue
            victim = b if b not in locked else a
            if victim in locked:
                continue
            vi = dates.index(victim)
            for ci, c in enumerate(dates):
                if c in locked or abs(ci - vi) <= 1:
                    continue
                before = clashes(vi) + clashes(ci)
                plan[victim], plan[c] = plan[c], plan[victim]
                if clashes(vi) + clashes(ci) < before:
                    break
                plan[victim], plan[c] = plan[c], plan[victim]
    adj = [(a, b) for a, b in zip(dates, dates[1:]) if book(plan[a]) == book(plan[b])]
    print(f"same book on consecutive days: {len(adj)} {adj}")
    path.write_text("\n".join(header + [f"{d}\t{plan[d]}" for d in dates]) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
