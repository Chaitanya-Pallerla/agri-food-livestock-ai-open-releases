"""Step 2b: re-apply the current rules to every automatically found entry (rules improve over time).

Drops third-party links, re-checks repositories found by GitHub search with the stricter author/name test, re-checks the
domain with the current terms, and moves entries with no remaining release to data/no_release.json. Hand-verified
entries are never changed."""
import re

from common import classify, get, load, plain, save
from detect import THIRD, plausible_repo


def abstract_for(s):
    if s.get("abstract"):
        return s["abstract"]
    doi = s.get("doi")
    if not doi:
        return ""
    r = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"})
    if r is not None and r.status_code == 200:
        res = r.json().get("resultList", {}).get("result", [])
        if res and res[0].get("abstractText"):
            return re.sub(r"<[^>]+>", " ", res[0]["abstractText"])
    r = get(f"https://api.crossref.org/works/{doi}")
    if r is not None and r.status_code == 200:
        return re.sub(r"<[^>]+>", " ", r.json().get("message", {}).get("abstract", "") or "")
    return ""


def run():
    S = load("studies.json", [])
    norel = {s["key"]: s for s in load("no_release.json", [])}
    keep, moved, dropped_links = [], 0, 0
    for s in S:
        if s.get("status", "").startswith("verified"):
            keep.append(s)
            continue
        rel = []
        for r in s.get("releases", []):
            u = r.get("url", "")
            if THIRD.search(u):
                dropped_links += 1
                continue
            if r.get("source", "").startswith("GitHub README"):
                if any(x.get("source", "").startswith("GitHub README") for x in rel):   # one search hit per study
                    dropped_links += 1
                    continue
                m = re.match(r"https://github\.com/([^/]+)/([^/#?]+)", u)
                if not m or not plausible_repo({"name": m.group(2), "owner": {"login": m.group(1)}}, s["title"], s.get("authors", [])):
                    dropped_links += 1
                    continue
            rel.append(r)
        s["releases"] = rel
        if "abstract" not in s:
            s["abstract"] = abstract_for(s)[:1500]
        doms, techs = classify(s["title"] + " " + s["abstract"], title=s["title"])
        if doms:
            s["domains"], s["technologies"] = doms, techs or s.get("technologies", [])
        if not doms or not any(r.get("ok") for r in rel):
            moved += 1
            if doms:
                norel[s["key"]] = dict(key=s["key"], title=s["title"], doi=s.get("doi"), date=s.get("date"),
                                       authors=s.get("authors", [])[:3], venue=s.get("venue", ""), domains=doms,
                                       technologies=techs, checks=1, last=s.get("checked"), landing=s.get("landing", [])[:2],
                                       pdf=s.get("pdf", [])[:2])
            continue
        keep.append(s)
    save("studies.json", keep)
    save("no_release.json", list(norel.values()))
    print(f"clean: removed {dropped_links} doubtful links; {moved} entries no longer qualify; {len(keep)} studies remain")


if __name__ == "__main__":
    run()
