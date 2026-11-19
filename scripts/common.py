"""Shared helpers: HTTP with retries, config, data files and text matching."""
import json
import os
import re
import time
import unicodedata

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, "config", "terms.json"), encoding="utf-8"))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "agri-food-livestock-ai-open-releases/1.0 (+https://github.com/; open-science tracker)"}
GH_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY")


class BudgetExhausted(RuntimeError):
    """OpenAlex daily budget used up; the run stops cleanly and resumes next time."""


def get(url, params=None, headers=None, timeout=40, tries=4, stream=False):
    """GET with polite retries; returns a Response or None."""
    h = dict(UA, **(headers or {}))
    if OPENALEX_KEY and "api.openalex.org" in url:
        h["Authorization"] = f"Bearer {OPENALEX_KEY}"
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, stream=stream, allow_redirects=True)
            if r.status_code == 429 and "api.openalex.org" in url and "budget" in r.text.lower():
                raise BudgetExhausted(r.text[:200])
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (k + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(3 * (k + 1))
    return None


def gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h


def load(name, default):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(name, obj):
    p = os.path.join(DATA, name)
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def plain(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def _rx(phrases):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(p.lower()) for p in phrases) + r")(?![a-z0-9])")


DOMAIN_RX = {d: _rx(p) for d, p in CONFIG["domains"].items()}
TECH_RX = {t: _rx(p) for t, p in CONFIG["technologies"].items()}


def classify(text, title=None):
    """Domains and technologies of a study. A domain counts if one of its phrases is in the title, or if its phrases occur
    at least three times (two different phrases) in the abstract; this keeps out papers that mention 'food' or 'farm' once."""
    t = (text or "").lower()
    ti = (title or "").lower()
    doms = []
    for d, rx in DOMAIN_RX.items():
        hits = rx.findall(t)
        if (ti and rx.search(ti)) or (len(hits) >= 3 and len(set(hits)) >= 2) or (title is None and hits):
            doms.append(d)
    techs = [k for k, rx in TECH_RX.items() if rx.search(t) or (ti and rx.search(ti))]
    return doms, techs


def abstract_from_index(inv):
    if not inv:
        return ""
    pos = [(p, w) for w, ps in inv.items() for p in ps]
    return " ".join(w for _, w in sorted(pos))


def key_of(work):
    """Stable identifier: DOI if present, otherwise the OpenAlex id."""
    doi = (work.get("doi") or "").replace("https://doi.org/", "").lower()
    return doi or work["id"].rsplit("/", 1)[-1]
