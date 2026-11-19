"""Step 1: find recent studies in agriculture, food and livestock/aquaculture that use any listed technology.

Free, regularly updated sources (each is optional; if one fails or is over budget the others still run):
  Crossref      - nearly every DOI-registered paper; filtered by *index date*, so late-indexed papers are not missed
  arXiv         - preprints (where most code releases first appear)
  Europe PMC    - PubMed plus bioRxiv/medRxiv preprints, with full-text links
  OpenAlex      - broad index with abstracts and open-access PDF links (set OPENALEX_API_KEY)
  Semantic Scholar - broad index with abstracts (used only if SEMANTIC_SCHOLAR_API_KEY is set)
Unseen studies are merged (by DOI, arXiv id or title) into data/queue.json."""
import datetime as dt
import html
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

from common import CONFIG, BudgetExhausted, abstract_from_index, classify, get, load, plain, save

REVIEW = re.compile(r"\b(review|survey|overview|meta-analysis|bibliometric|perspective)\b")
S = CONFIG["search"]


def boolean(phrases, quote='"'):
    return " OR ".join(f'{quote}{p}{quote}' if " " in p or "-" in p else p for p in phrases)


def top(phrases, n):
    """The n most specific phrases (longest first) - keyword APIs limit query length."""
    return sorted(set(phrases), key=lambda p: -len(p))[:n]


class Collector:
    def __init__(self):
        self.seen = set(load("seen.json", []))
        self.queue = {q["key"]: q for q in load("queue.json", [])}
        self.index = {}
        for k, q in self.queue.items():
            for idk in self.ids(q):
                self.index[idk] = k
        self.added = 0
        self.by_source = {}

    @staticmethod
    def ids(q):
        out = []
        if q.get("doi"):
            out.append("doi:" + q["doi"].lower())
        if q.get("arxiv"):
            out.append("arxiv:" + q["arxiv"])
        if q.get("title"):
            out.append("title:" + plain(q["title"])[:80])
        return out

    def add(self, source, rec):
        title = html.unescape(re.sub(r"<[^>]+>", "", rec.get("title") or "")).strip()
        if not title or REVIEW.search(title.lower()):
            return
        rec["title"] = title
        rec["abstract"] = html.unescape(re.sub(r"<[^>]+>", " ", rec.get("abstract") or "")).strip()
        doi = (rec.get("doi") or "").lower().replace("https://doi.org/", "")
        if not doi and rec.get("arxiv"):
            doi = f"10.48550/arxiv.{rec['arxiv']}"
        rec["doi"] = doi
        key = doi or "title:" + plain(title)[:80]
        if key in self.seen:
            return
        doms, techs = classify(title + " " + rec["abstract"], title=title)
        if not doms or not techs:
            return
        hit = next((self.index[i] for i in self.ids(rec) if i in self.index), None)
        if hit:                                   # merge: keep the richest abstract and all full-text links
            q = self.queue[hit]
            if len(rec["abstract"]) > len(q.get("abstract", "")):
                q["abstract"] = rec["abstract"]
            q["pdf"] = list(dict.fromkeys(q.get("pdf", []) + [u for u in rec.get("pdf", []) if u]))
            q["landing"] = list(dict.fromkeys(q.get("landing", []) + [u for u in rec.get("landing", []) if u]))
            q["sources"] = sorted(set(q.get("sources", [])) | {source})
            q["domains"] = sorted(set(q["domains"]) | set(doms))
            order = list(CONFIG["technologies"])
            q["technologies"] = sorted(set(q["technologies"]) | set(techs), key=order.index)
            if rec.get("arxiv") and not q.get("arxiv"):
                q["arxiv"] = rec["arxiv"]
            return
        q = dict(key=key, doi=doi, arxiv=rec.get("arxiv"), title=title, date=rec.get("date"), abstract=rec["abstract"],
                 authors=rec.get("authors", [])[:12], venue=rec.get("venue", ""), pdf=[u for u in rec.get("pdf", []) if u],
                 landing=[u for u in rec.get("landing", []) if u], domains=doms, technologies=techs, sources=[source])
        self.queue[key] = q
        for i in self.ids(q):
            self.index[i] = key
        self.added += 1
        self.by_source[source] = self.by_source.get(source, 0) + 1

    def full(self):
        return self.added >= S["max_new_per_run"]


# ------------------------------------------------------------------ sources
def crossref(c, since):
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            q = " ".join(top(dphr, 4) + top(tphr, 3))
            r = get("https://api.crossref.org/works", params={
                "query.bibliographic": q,
                "filter": f"from-index-date:{since},type:journal-article,type:proceedings-article,type:posted-content",
                "rows": 200, "select": "DOI,title,abstract,author,issued,container-title,link,URL"})
            if r is None or r.status_code != 200:
                continue
            for it in r.json().get("message", {}).get("items", []):
                parts = (it.get("issued") or {}).get("date-parts") or [[None]]
                c.add("Crossref", dict(doi=it.get("DOI"), title=(it.get("title") or [""])[0], abstract=it.get("abstract", ""),
                                       authors=[f"{a.get('given', '')} {a.get('family', '')}".strip() for a in it.get("author", [])],
                                       date="-".join(str(x) for x in parts[0] if x), venue=(it.get("container-title") or [""])[0],
                                       pdf=[l["URL"] for l in it.get("link", []) if "pdf" in (l.get("content-type") or "")],
                                       landing=[it.get("URL")]))
            time.sleep(0.3)
            if c.full():
                return


def arxiv(c, since):
    start = since.replace("-", "") + "0000"
    end = dt.date.today().strftime("%Y%m%d") + "2359"
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            dq = " OR ".join(f'abs:"{p}"' for p in top(dphr, 10))
            tq = " OR ".join(f'abs:"{p}"' for p in top(tphr, 6))
            r = get("http://export.arxiv.org/api/query", params={
                "search_query": f"({dq}) AND ({tq}) AND submittedDate:[{start} TO {end}]", "max_results": 200})
            time.sleep(3.1)                                          # arXiv asks for one request every 3 s
            if r is None or r.status_code != 200 or "Rate exceeded" in r.text[:200]:
                continue
            try:
                entries = ET.fromstring(r.content).findall("a:entry", ns)
            except ET.ParseError:
                continue
            for e in entries:
                aid = re.sub(r"v\d+$", "", e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1])
                c.add("arXiv", dict(arxiv=aid, doi=e.findtext("x:doi", "", ns), title=" ".join(e.findtext("a:title", "", ns).split()),
                                    abstract=" ".join(e.findtext("a:summary", "", ns).split()),
                                    authors=[a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
                                    date=e.findtext("a:published", "", ns)[:10], venue="arXiv",
                                    pdf=[f"https://arxiv.org/pdf/{aid}"], landing=[f"https://arxiv.org/abs/{aid}"]))
            if c.full():
                return


def europepmc(c, since):
    today = dt.date.today().isoformat()
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            q = f'({boolean(top(dphr, 12))}) AND ({boolean(top(tphr, 8))}) AND CREATION_DATE:[{since} TO {today}]'
            cursor = "*"
            for _ in range(3):
                r = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={
                    "query": q, "format": "json", "resultType": "core", "pageSize": 200, "cursorMark": cursor})
                if r is None or r.status_code != 200:
                    break
                j = r.json()
                res = j.get("resultList", {}).get("result", [])
                for it in res:
                    urls = (it.get("fullTextUrlList") or {}).get("fullTextUrl", [])
                    venue = ((it.get("journalInfo") or {}).get("journal") or {}).get("title") or it.get("source", "")
                    c.add("Europe PMC", dict(doi=it.get("doi"), title=it.get("title"), abstract=it.get("abstractText", ""),
                                             authors=[a.get("fullName", "") for a in (it.get("authorList") or {}).get("author", [])],
                                             date=it.get("firstPublicationDate"), venue=venue,
                                             pdf=[u["url"] for u in urls if u.get("documentStyle") == "pdf" and u.get("availabilityCode") in ("OA", "F")],
                                             landing=[u["url"] for u in urls if u.get("documentStyle") == "html"]))
                nxt = j.get("nextCursorMark")
                if not nxt or nxt == cursor or len(res) < 200:
                    break
                cursor = nxt
            time.sleep(0.2)
            if c.full():
                return


def openalex(c, since):
    fields = "id,doi,title,publication_date,type,abstract_inverted_index,best_oa_location,primary_location,locations,authorships"
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            query = f"({boolean(dphr)}) AND ({boolean(tphr)})"
            cursor, got = "*", 0
            while cursor and got < S["per_query_limit"]:
                r = get("https://api.openalex.org/works", params={
                    "filter": f"title_and_abstract.search:{query},from_publication_date:{since},type:article|preprint",
                    "select": fields, "per-page": 200, "cursor": cursor})
                if r is None or r.status_code != 200:
                    break
                j = r.json()
                for w in j.get("results", []):
                    got += 1
                    if w.get("type") == "review":
                        continue
                    locs = [w.get("best_oa_location")] + (w.get("locations") or [])
                    c.add("OpenAlex", dict(doi=w.get("doi"), title=w.get("title"),
                                           abstract=abstract_from_index(w.get("abstract_inverted_index")),
                                           authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])],
                                           date=w.get("publication_date"),
                                           venue=((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
                                           pdf=[l.get("pdf_url") for l in locs if l and l.get("pdf_url")],
                                           landing=[l.get("landing_page_url") for l in locs if l and l.get("landing_page_url")]))
                cursor = j.get("meta", {}).get("next_cursor")
                time.sleep(0.15)
            if c.full():
                return


def semanticscholar(c, since):
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if not key:
        print("  Semantic Scholar: no API key set, skipped")
        return
    for dom, dphr in CONFIG["domains"].items():
        for tech, tphr in CONFIG["technologies"].items():
            q = "(" + " | ".join(f'"{p}"' for p in top(dphr, 12)) + ") + (" + " | ".join(f'"{p}"' for p in top(tphr, 8)) + ")"
            r = get("https://api.semanticscholar.org/graph/v1/paper/search/bulk", headers={"x-api-key": key}, params={
                "query": q, "publicationDateOrYear": f"{since}:",
                "fields": "title,abstract,externalIds,authors,publicationDate,venue,openAccessPdf"})
            time.sleep(1.1)
            if r is None or r.status_code != 200:
                continue
            for p in r.json().get("data", []) or []:
                ext = p.get("externalIds") or {}
                c.add("Semantic Scholar", dict(doi=ext.get("DOI"), arxiv=ext.get("ArXiv"), title=p.get("title"),
                                               abstract=p.get("abstract") or "", authors=[a.get("name", "") for a in p.get("authors", [])],
                                               date=p.get("publicationDate"), venue=p.get("venue", ""),
                                               pdf=[(p.get("openAccessPdf") or {}).get("url")]))
            if c.full():
                return


SOURCES = [("Crossref", crossref), ("arXiv", arxiv), ("Europe PMC", europepmc), ("OpenAlex", openalex),
           ("Semantic Scholar", semanticscholar)]


def run(days=None, only=None):
    days = int(days or S["window_days"])
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    c = Collector()
    for name, fn in SOURCES:
        if only and name.lower().replace(" ", "") not in only.lower().replace(" ", ""):
            continue
        t0 = time.time()
        try:
            fn(c, since)
        except BudgetExhausted:
            print(f"  {name}: daily budget used up, skipped this run")
        except Exception as e:                                   # one failing source must not stop the others
            print(f"  {name}: failed ({type(e).__name__}: {str(e)[:100]})")
        print(f"  {name}: {c.by_source.get(name, 0)} new studies ({time.time() - t0:.0f} s)")
        save("queue.json", list(c.queue.values()))
        if c.full():
            break
    print(f"search: {c.added} new studies queued since {since}; queue size {len(c.queue)}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else None,
        sys.argv[2] if len(sys.argv) > 2 else None)
