"""Hard search filters — user constraints that a high match score can NEVER override.

Pipeline order: discover → normalize → dedupe → HARD FILTERS → score → prioritize → queue.
A job that fails a hard filter is persisted (so it is never re-processed as "new") but is never
qualified or queued automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services import detection as det
from app.services.profile_service import salary_bounds_monthly_usd
from app.services.text_utils import contains_term, normalize_company, normalize_text

LATAM_COUNTRIES = ["mexico", "colombia", "argentina", "chile", "peru", "brazil", "venezuela", "ecuador", "uruguay", "costa rica",
                   "guatemala", "dominican", "bolivia", "paraguay", "panama", "honduras", "el salvador", "nicaragua", "cuba", "puerto rico"]
EU_COUNTRIES = ["spain", "portugal", "france", "germany", "italy", "netherlands", "belgium", "ireland", "poland", "austria", "sweden",
                "denmark", "finland", "greece", "czech", "romania", "hungary", "croatia", "slovakia", "slovenia", "bulgaria", "lithuania",
                "latvia", "estonia", "luxembourg", "malta", "cyprus"]
WORLDWIDE = {"worldwide", "anywhere", "global", "remote"}


@dataclass
class FilterResult:
    status: str  # passed | review | rejected
    reasons: list[str] = field(default_factory=list)  # why rejected / why review
    notes: list[str] = field(default_factory=list)    # informational (e.g. salary unknown, allowed)

    def as_list(self) -> list[str]:
        return self.reasons + [f"Note: {n}" for n in self.notes]


def _user_places(profile, locations: list[str]) -> list[str]:
    places = [normalize_text(x) for x in locations if x]
    for v in (profile.country, profile.location, profile.work_authorization):
        if v:
            places.append(normalize_text(v))
    return places


def region_compatible(region: str, places: list[str]) -> bool:
    r = region.lower()
    blob = " ".join(places)
    words = set(blob.split())
    if r == "us":
        return "united states" in blob or bool(words & {"usa", "us"})
    if r == "latam":
        return "latam" in blob or "latin america" in blob or any(c in blob for c in LATAM_COUNTRIES)
    if r == "eu":
        return " eu" in f" {blob}" or "europe" in blob or any(c in blob for c in EU_COUNTRIES)
    if r == "uk":
        return "united kingdom" in blob or " uk" in f" {blob}" or "england" in blob
    return r in blob


def evaluate_hard_filters(job, profile, settings: dict) -> FilterResult:
    cfg = settings.get("job_search") or {}
    rejects: list[str] = []
    reviews: list[str] = []
    notes: list[str] = []
    text = "\n".join(x for x in [job.title, job.description, job.requirements, job.location] if x)
    text_norm = normalize_text(text)

    # --- salary (normalized to monthly USD with the existing salary service)
    bounds = salary_bounds_monthly_usd(profile, settings.get("usd_rates") or {})
    lo, hi = job.salary_monthly_usd_min, job.salary_monthly_usd_max
    if lo is None and hi is None:
        policy = cfg.get("salary_unknown_policy", "allow")
        if policy == "reject":
            rejects.append("Salary not published (your policy: reject unknown salary).")
        elif policy == "review":
            reviews.append("Salary not published — review before applying (your policy).")
        else:
            notes.append("Salary not published.")
    else:
        top = hi if hi is not None else lo
        bottom = lo if lo is not None else hi
        if bounds["min"] is not None and top < bounds["min"]:
            rejects.append(f"Salary ~${top:,.0f}/mo is below your minimum (${bounds['min']:,.0f}/mo).")
        if bounds["max"] is not None and bottom > bounds["max"]:
            rejects.append(f"Salary ~${bottom:,.0f}/mo is above your configured maximum (${bounds['max']:,.0f}/mo).")

    # --- work arrangement & location
    arrangements = set(profile.work_arrangements or [])
    rt = job.remote_type or "unknown"
    if arrangements and rt != "unknown" and rt not in arrangements:
        rejects.append(f"Work arrangement '{rt}' is not in your preferences ({', '.join(sorted(arrangements))}).")
    locations = [x for x in (cfg.get("locations") or []) if x]
    places = _user_places(profile, locations)
    if places:
        for region in det.detect_location_restrictions(text):
            if not region_compatible(region, places):
                rejects.append(f"Restricted to candidates in {region}.")
    if locations and rt in ("onsite", "hybrid") and job.location:
        loc = normalize_text(job.location)
        if not any(normalize_text(x) in loc or loc in normalize_text(x) for x in locations if normalize_text(x) not in WORLDWIDE):
            rejects.append(f"Location '{job.location}' is not one of your locations.")

    # --- employment type / seniority
    types = profile.employment_types or []
    if types and job.employment_type and job.employment_type not in types:
        rejects.append(f"Employment type '{job.employment_type}' is not one you accept.")
    levels = cfg.get("seniority") or []
    if levels and job.seniority and job.seniority not in levels:
        rejects.append(f"Seniority '{job.seniority}' is not in your allowed levels.")

    # --- exclusions
    comp = normalize_company(job.company)
    for ex in cfg.get("excluded_companies") or []:
        exn = normalize_company(ex)
        if exn and comp and (exn == comp or contains_term(comp, exn)):
            rejects.append(f"Company '{job.company}' is excluded.")
    if job.category and job.category in set(settings.get("excluded_categories") or []):
        rejects.append(f"Job type '{det.CATEGORY_LABELS.get(job.category, job.category)}' is excluded.")
    for ind in profile.excluded_industries or []:
        if ind and contains_term(normalize_text(text + " " + (job.company or "")), ind):
            rejects.append(f"Matches excluded industry '{ind}'.")

    # --- required keywords (ALL must appear)
    missing = [k for k in (cfg.get("required_keywords") or []) if k and not contains_term(text_norm, k)]
    if missing:
        rejects.append(f"Missing required keyword(s): {', '.join(missing)}.")

    status = "rejected" if rejects else "review" if reviews else "passed"
    return FilterResult(status, rejects + reviews, notes)
