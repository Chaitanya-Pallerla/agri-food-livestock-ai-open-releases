"""Step 1: find recent studies in agriculture, food and livestock/aquaculture that use any listed technology (OpenAlex).
Adds unseen works to data/queue.json; works already processed are listed in data/seen.json."""
import datetime as dt
import re
import sys
import time

from common import CONFIG, BudgetExhausted, abstract_from_index, classify, get, key_of, load, save

OA = "https://api.openalex.org/works"
REVIEW = re.compile(r"\b(review|survey|overview|meta-analysis|bibliometric|perspective)\b")
FIELDS = ("id,doi,title,publication_date,type,abstract_inverted_index,best_oa_location,primary_location,locations,"
          "authorships,ids")


def boolean(phrases):
    return " OR ".join(f'"{p}"' if " " in p or "-" in p else p for p in phrases)


def run(days=None):
    S = CONFIG["search"]
    days = int(days or S["window_days"])
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    seen = set(load("seen.json", []))
    queue = {q["key"]: q for q in load("queue.json", [])}
    added = 0
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            query = f"({boolean(dphr)}) AND ({boolean(tphr)})"
            cursor, got = "*", 0
            while cursor and got < S["per_query_limit"]:
                try:
                    r = get(OA, params={"filter": f"title_and_abstract.search:{query},from_publication_date:{since},type:article|preprint",
                                        "select": FIELDS, "per-page": 200, "cursor": cursor})
                except BudgetExhausted as e:
                    save("queue.json", list(queue.values()))
                    print("OpenAlex daily budget used up; stopping here and continuing next run.", str(e)[:120])
                    return
                if r is None or r.status_code != 200:
                    print("  query failed:", dom, "|", tech, r.status_code if r is not None else "no response")
                    break
                j = r.json()
                for w in j.get("results", []):
                    got += 1
                    k = key_of(w)
                    if k in seen or k in queue:
                        continue
                    title = w.get("title") or ""
                    if w.get("type") == "review" or REVIEW.search(title.lower()):
                        continue
                    abstract = abstract_from_index(w.get("abstract_inverted_index"))
                    doms, techs = classify(title + " " + abstract, title=title)
                    if not doms or not techs:
                        continue
                    queue[k] = dict(key=k, openalex=w["id"], doi=(w.get("doi") or "").replace("https://doi.org/", ""),
                                    title=title, date=w.get("publication_date"), abstract=abstract,
                                    authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])][:12],
                                    venue=((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
                                    pdf=[l.get("pdf_url") for l in ([w.get("best_oa_location")] + (w.get("locations") or [])) if l and l.get("pdf_url")],
                                    landing=[l.get("landing_page_url") for l in (w.get("locations") or []) if l and l.get("landing_page_url")],
                                    domains=doms, technologies=techs)
                    added += 1
                cursor = j.get("meta", {}).get("next_cursor")
                time.sleep(0.15)
            print(f"  {dom[:12]:12} x {tech[:40]:40} hits {got}")
            if added >= S["max_new_per_run"]:
                break
        if added >= S["max_new_per_run"]:
            break
    save("queue.json", list(queue.values()))
    print(f"search: {added} new studies queued since {since}; queue size {len(queue)}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
