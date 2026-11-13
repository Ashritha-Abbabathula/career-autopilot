"""Which postings count: India location, tech role, entry-level or intern."""
import re

LOCATION_RX = re.compile(r"bengaluru|bangalore|hyderabad|\bindia\b|\bremote\b.*\bindia\b", re.I)
CITY_RX = re.compile(r"bengaluru|bangalore|hyderabad", re.I)
TECH_RX = re.compile(
    r"engineer|developer|sde|software|scientist|research|machine learning|\bml\b|\bai\b|"
    r"data|robot|embedded|firmware|autonomy|perception|intern|analyst", re.I)
NOT_TECH_RX = re.compile(r"sales|marketing|recruit|account exec|customer success|legal|finance|"
                         r"people ops|human resources|designer|content", re.I)
SENIOR_RX = re.compile(r"senior|\bsr\.?\b|staff|principal|lead|manager|director|head of|architect|\bvp\b|"
                       r"distinguished|fellow|\b(?:iii|iv|v)\b|\b[3-9]\+? years", re.I)
INTERN_RX = re.compile(r"\bintern(?:ship)?\b|\btrainee\b|\bco-?op\b", re.I)
ENTRY_RX = re.compile(r"new grad|graduate|\bassociate\b|\bjunior\b|\bsde[- ]?(?:1|i)\b|"
                      r"engineer[- ](?:1|i)\b|\bentry\b|early career|campus|fresher", re.I)


def in_india(location: str) -> bool:
    return bool(LOCATION_RX.search(location or ""))


def in_target_city(location: str) -> bool:
    return bool(CITY_RX.search(location or ""))


def is_tech(title: str) -> bool:
    return bool(TECH_RX.search(title)) and not NOT_TECH_RX.search(title)


def level_of(title: str) -> str:
    """'intern', 'entry', 'mid' or 'senior' from the title alone (a rough guess)."""
    if INTERN_RX.search(title):
        return "intern"
    if SENIOR_RX.search(title):
        return "senior"
    if ENTRY_RX.search(title):
        return "entry"
    return "mid"
