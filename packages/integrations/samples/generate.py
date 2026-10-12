"""Generate a synthetic med-spa EMR export (fake people, no PHI) for dev and demos.

Headers deliberately look like a real export, not like our canonical fields, so
the sample exercises mapping suggestion. Regenerate with:

    uv run python packages/integrations/samples/generate.py
"""

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "medspa"
FIRST = [
    "Ava",
    "Mia",
    "Emma",
    "Olivia",
    "Sophia",
    "Isabella",
    "Chloe",
    "Grace",
    "Lily",
    "Zoe",
    "Hannah",
    "Nora",
    "Ella",
    "Leah",
    "Maya",
    "Ruby",
    "Jade",
    "Claire",
    "Eva",
    "Ivy",
    "James",
    "Liam",
    "Noah",
    "Ethan",
    "Mason",
]
LAST = [
    "Smith",
    "Johnson",
    "Brown",
    "Garcia",
    "Miller",
    "Davis",
    "Martinez",
    "Lopez",
    "Wilson",
    "Anderson",
    "Taylor",
    "Moore",
    "Jackson",
    "Lee",
    "Harris",
    "Clark",
    "Lewis",
    "Walker",
    "Young",
    "King",
]
SERVICES = [
    ("Botox", "Injectables", 450),
    ("Dermal Filler", "Injectables", 750),
    ("HydraFacial", "Facials", 225),
    ("Chemical Peel", "Facials", 180),
    ("Laser Hair Removal", "Laser", 300),
    ("IPL Photofacial", "Laser", 400),
    ("Microneedling", "Skin", 350),
    ("IV Vitamin Drip", "Wellness", 199),
]
PROVIDERS = ["Dr. Rivera", "Sarah Kim, NP", "Jessica Park, RN"]


def main(seed: int = 7, patients: int = 240) -> None:
    rng = random.Random(seed)
    today = datetime.now().replace(minute=0, second=0, microsecond=0)
    OUT.mkdir(exist_ok=True)
    p_rows, a_rows, t_rows = [], [], []
    appt_id = inv_id = 1000
    for i in range(1, patients + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        female = first not in {"James", "Liam", "Noah", "Ethan", "Mason"}
        dob = date(rng.randint(1958, 2003), rng.randint(1, 12), rng.randint(1, 28))
        p_rows.append(
            {
                "Client ID": f"C{i:05d}",
                "First Name": first,
                "Last Name": last,
                "Email Address": f"{first}.{last}{i}@example.com".lower(),
                "Mobile": f"({rng.randint(201, 989)}) 555-{rng.randint(1000, 9999)}",
                "DOB": dob.strftime("%m/%d/%Y"),
                "Gender": "Female" if female else "Male",
                "SMS Opt In": "Yes" if rng.random() < 0.8 else "No",
                "Referral Source": rng.choice(["Instagram", "Google", "Friend", "Walk-in", ""]),
            }
        )
        # Visit history: some patients are regulars, many went quiet months ago.
        favourite = rng.choice(SERVICES[:4] if female else SERVICES[4:])
        last_visit_days_ago = rng.choice([rng.randint(5, 80), rng.randint(130, 500), rng.randint(200, 700)])
        visits = rng.randint(1, 8)
        for v in range(visits):
            when = today - timedelta(days=last_visit_days_ago + v * rng.randint(60, 120), hours=rng.randint(0, 6))
            svc = favourite if rng.random() < 0.7 else rng.choice(SERVICES)
            appt_id += 1
            status = rng.choices(["Checked Out", "No Show", "Cancelled"], weights=[90, 5, 5])[0]
            a_rows.append(
                {
                    "Appointment ID": f"A{appt_id}",
                    "Client ID": f"C{i:05d}",
                    "Date": when.strftime("%m/%d/%Y %I:%M %p"),
                    "Service": svc[0],
                    "Category": svc[1],
                    "Provider": rng.choice(PROVIDERS),
                    "Status": status,
                }
            )
            if status == "Checked Out":
                inv_id += 1
                t_rows.append(
                    {
                        "Invoice ID": f"INV{inv_id}",
                        "Client ID": f"C{i:05d}",
                        "Appointment ID": f"A{appt_id}",
                        "Date": when.strftime("%m/%d/%Y %I:%M %p"),
                        "Item": svc[0],
                        "Category": svc[1],
                        "Provider": a_rows[-1]["Provider"],
                        "Total": f"${svc[2] * rng.uniform(0.9, 1.3):,.2f}",
                    }
                )
        if rng.random() < 0.15:  # a few already have something booked
            appt_id += 1
            a_rows.append(
                {
                    "Appointment ID": f"A{appt_id}",
                    "Client ID": f"C{i:05d}",
                    "Date": (today + timedelta(days=rng.randint(2, 30))).strftime("%m/%d/%Y %I:%M %p"),
                    "Service": favourite[0],
                    "Category": favourite[1],
                    "Provider": rng.choice(PROVIDERS),
                    "Status": "Confirmed",
                }
            )
    for name, rows in (("patients", p_rows), ("appointments", a_rows), ("transactions", t_rows)):
        with open(OUT / f"{name}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
