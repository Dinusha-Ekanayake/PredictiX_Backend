"""Sri Lankan personnel names, emails, phones and employee IDs.

The corpus is split by community roughly in line with national demographics
(~74% Sinhala, ~15% Tamil, ~10% Moor) so a warehouse roster reads like a real
Sri Lankan one rather than a single-community list.
"""

from __future__ import annotations

import random
import unicodedata

# ── Name corpus ───────────────────────────────────────────────────────────────
SINHALA_MALE = [
    "Kasun", "Nuwan", "Chathura", "Dinusha", "Sampath", "Ruwan", "Tharindu",
    "Lahiru", "Isuru", "Chamara", "Prasad", "Nimal", "Sunil", "Ajith", "Roshan",
    "Gayan", "Dhanushka", "Supun", "Malinda", "Buddhika", "Thilina", "Kanchana",
    "Udara", "Sanjaya", "Amila", "Hasitha", "Janaka", "Pubudu", "Shantha",
    "Asanka", "Charith", "Nalin", "Rangana", "Sameera", "Chaminda", "Duminda",
    "Hiran", "Kavinda", "Dilshan", "Eranga", "Harsha", "Indika", "Jagath",
    "Kalana", "Lasantha", "Manoj", "Naveen", "Oshadha", "Pasindu", "Randika",
    "Saliya", "Thushara", "Upul", "Vimukthi", "Wasantha", "Yohan", "Anuruddha",
    "Bandula", "Chanaka", "Damith", "Gihan", "Heshan", "Kelum", "Milinda",
    "Nishantha", "Pradeep", "Rasika", "Sujeewa", "Tharaka", "Viraj",
]
SINHALA_FEMALE = [
    "Nayomi", "Chathurika", "Dilrukshi", "Sanduni", "Ishara", "Piumi", "Hasini",
    "Tharushi", "Nimasha", "Kaushalya", "Anusha", "Madushika", "Erandi",
    "Gayathri", "Sewwandi", "Rashmi", "Dinithi", "Amaya", "Nethmi", "Thilini",
    "Upeksha", "Yasodha", "Kumari", "Shalini", "Iresha", "Nadeesha", "Hiruni",
    "Sachini", "Dulani", "Maheshi", "Chandima", "Dilhani", "Geethani",
    "Harshani", "Janani", "Lakmali", "Menaka", "Niroshi", "Pavithra", "Ruwani",
    "Samanthi", "Tharangi", "Udeshika", "Vindya", "Wasana", "Nilanthi",
]
SINHALA_SURNAMES = [
    "Perera", "Fernando", "Silva", "Jayawardena", "Bandara", "Rajapaksa",
    "Wickramasinghe", "Gunawardena", "Dissanayake", "Senanayake", "Ekanayake",
    "Wijesinghe", "Herath", "Ratnayake", "Amarasinghe", "Kumarasinghe",
    "Weerasinghe", "Abeywickrama", "Samaraweera", "Karunaratne", "Liyanage",
    "Mendis", "Peiris", "Gunasekara", "Jayasuriya", "Munasinghe", "Pathirana",
    "Ranasinghe", "Seneviratne", "Tennakoon", "Vithanage", "Wanigasekara",
    "Alwis", "Chandrasiri", "Edirisinghe", "Galappaththi", "Hettiarachchi",
    "Illangakoon", "Kodikara", "Madushanka", "Nanayakkara", "Opatha",
    "Rathnayaka", "Samarasinghe", "Thilakaratne", "Udawatta", "Wijeratne",
]

TAMIL_MALE = [
    "Arun", "Kumaran", "Ravi", "Suresh", "Mohan", "Vijay", "Ganesh", "Thevan",
    "Selvam", "Anand", "Balan", "Chandran", "Dinesh", "Elango", "Karthik",
    "Murali", "Nirmal", "Rajan", "Sivakumar", "Thiru", "Vasanth", "Prakash",
    "Sasikumar", "Jeyakumar", "Manoharan", "Yogeswaran",
]
TAMIL_FEMALE = [
    "Kavitha", "Priya", "Nirmala", "Shanthi", "Malathi", "Vasanthi",
    "Rajeswari", "Ananthi", "Thilaga", "Sujatha", "Vijayalakshmi", "Kalaivani",
    "Meenakshi", "Sathyabama",
]
TAMIL_SURNAMES = [
    "Rajendran", "Sivalingam", "Thangarajah", "Kandasamy", "Balasubramaniam",
    "Selvarajah", "Ponnambalam", "Nadarajah", "Vairamuthu", "Chandrasekaran",
    "Muthukumar", "Ratnasingham", "Sivanathan", "Arumugam", "Krishnapillai",
]

MOOR_MALE = [
    "Mohamed", "Ahamed", "Farhan", "Rizwan", "Nazeer", "Aslam", "Imran",
    "Fazal", "Rauf", "Nizam", "Shafi", "Hussain", "Irfan", "Zahir", "Rifky",
]
MOOR_FEMALE = [
    "Fathima", "Ayesha", "Nasreen", "Zainab", "Rukshana", "Shameena", "Hafsa",
    "Rizna", "Sabreena", "Nadhira",
]
MOOR_SURNAMES = [
    "Marikkar", "Farook", "Hameed", "Zubair", "Cassim", "Rahman", "Saleem",
    "Haniffa", "Ismail", "Jiffry", "Wahab", "Nawaz",
]

# (first-name pools, surname pool, demographic weight)
_COMMUNITIES = [
    ((SINHALA_MALE, SINHALA_FEMALE), SINHALA_SURNAMES, 74),
    ((TAMIL_MALE, TAMIL_FEMALE), TAMIL_SURNAMES, 15),
    ((MOOR_MALE, MOOR_FEMALE), MOOR_SURNAMES, 11),
]
_WEIGHTS = [w for _, _, w in _COMMUNITIES]


def make_person(rng: random.Random) -> tuple[str, str]:
    """Return (first_name, surname) sampled with realistic community weights."""
    (male, female), surnames, _ = rng.choices(_COMMUNITIES, weights=_WEIGHTS, k=1)[0]
    # Sri Lankan warehouse/driver workforces skew male; support and admin
    # functions are more balanced. A single ~72/28 split across the roster is a
    # fair approximation without overclaiming precision we don't have.
    pool = male if rng.random() < 0.72 else female
    return rng.choice(pool), rng.choice(surnames)


# ── Derived identifiers ───────────────────────────────────────────────────────
def _slug(text: str) -> str:
    """Lowercase ASCII, letters only — safe for an email local part."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in norm if ch.isalpha()).lower()


class EmailAllocator:
    """Allocates ``<user>.<dept_acronym>@lankalogix.com`` addresses, uniquely.

    The requested house style is first-name plus department acronym
    (``dinusha.elec@lankalogix.com``). Across ~1,300 staff first names collide
    constantly, so collisions fall back the way a real IT department would:
    add the surname initial, then a numeric suffix.
    """

    def __init__(self, domain: str) -> None:
        self._domain = domain
        self._taken: set[str] = set()

    def allocate(self, first: str, surname: str, acronym: str) -> str:
        base = _slug(first)
        initial = _slug(surname)[:1]
        for candidate in (base, f"{base}{initial}"):
            email = f"{candidate}.{acronym}@{self._domain}"
            if email not in self._taken:
                self._taken.add(email)
                return email
        n = 2
        while True:
            email = f"{base}{initial}{n}.{acronym}@{self._domain}"
            if email not in self._taken:
                self._taken.add(email)
                return email
            n += 1

    def reserve(self, email: str) -> str:
        """Claim a fixed address (demo/super-admin accounts) so it can't clash."""
        self._taken.add(email)
        return email


def make_phone(rng: random.Random) -> str:
    """Sri Lankan mobile number, ``+94 7X XXX XXXX``.

    07x prefixes in service: 070/071/072/074/075/076/077/078.
    """
    prefix = rng.choice(["70", "71", "72", "74", "75", "76", "77", "78"])
    return f"+94 {prefix} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


def make_employee_id(warehouse_short: str, seq: int) -> str:
    return f"LLX-{warehouse_short}-{seq:05d}"
