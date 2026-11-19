"""Step 2: find each queued study's own released code, data or model weights and check every link.

Sources, in order: links in the abstract; links in the open-access full text (references cut); Hugging Face models and
datasets tagged with the paper's arXiv id; Zenodo records related to the DOI; and, if nothing else is found, GitHub
repositories whose README quotes the paper title. Rules learned from manual checking: skip well-known third-party tools,
skip promises ("will be released", "on request"), and repair URLs broken by PDF line breaks against the owner's real repos."""
import datetime as dt
import difflib
import io
import re
import sys
import time

from common import get, gh_headers, load, plain, save

TODAY = dt.date.today().isoformat()
HOST = (r"(?:github\.com|gitlab\.[a-z0-9.-]+|bitbucket\.org|huggingface\.co|zenodo\.org|doi\.org/10\.5281|figshare\.com|osf\.io|"
        r"kaggle\.com|codeocean\.com|data\.mendeley\.com|[a-z0-9-]+\.github\.io)")
URL = re.compile(r"(?:https?://\s?)?(?:www\.)?" + HOST + r"/?[^\s,;)\]>\"'<]*", re.I)
OWN = re.compile(r"\b(our|we|this (study|work|paper|article)|code|source code|implementation|data ?set|data are|data is|"
                 r"weights|checkpoints?|model is|models are|available|availability|released?|repository|open[- ]source)\b", re.I)
PROMISE = re.compile(r"(upon (reasonable )?request|on request|will be (made )?(publicly )?(available|released|open)|upon (publication|acceptance)|"
                     r"after (publication|acceptance)|we plan to release|to be released)", re.I)
THIRD = re.compile(r"(github\.com/(ultralytics|facebookresearch/(segment-anything|sam2|esm|detectron2|dinov2)|huggingface/|openai/|"
                   r"meta-llama|haotian-liu|QwenLM|ollama|langchain-ai|run-llama|hiyouga/LLaMA-Factory|unslothai|vllm-project|"
                   r"ggerganov|tatsu-lab|lm-sys|microsoft/(LoRA|DeepSpeed)|google-research/(bert|vision_transformer)|IDEA-Research|"
                   r"WongKinYiu|open-mmlab|pytorch|tensorflow|keras-team|scikit-learn|milvus-io|chroma-core|deepseek-ai|"
                   r"mlfoundations|salesforce/LAVIS|OpenGVLab|THUDM|InternLM|kermitt2/grobid|jmorganca)|"
                   r"huggingface\.co/(meta-llama|google|openai|Qwen|mistralai|microsoft|bert-base|sentence-transformers|"
                   r"BAAI|facebook|deepseek-ai|THUDM|internlm|OpenGVLab|liuhaotian|lmsys|TheBloke|nomic-ai|docs|spaces/mteb|blog)|"
                   r"huggingface\.co/?$|github\.com/?$|kaggle\.com/?$|zenodo\.org/?$)", re.I)


def clean(u):
    u = re.sub(r"\s+", "", u).rstrip(".,;:")
    u = re.sub(r"(\.(git|The|We|In|Index|References|Keywords|CCS|Ethics|Acknowledg\w*|Supplementary|Declarations))$", "", u)
    u = re.sub(r"^(?:https?://)?", "https://", u)
    m = re.match(r"(https://(?:github\.com|gitlab\.[a-z0-9.-]+)/[^/]+/[^/#?]+)", u)   # repository root, not deep file paths
    return m.group(1) if m and "/-/" not in m.group(1) else (u.split("/-/")[0] if "/-/" in u else u)


def kind_of(url, ctx):
    u, c = url.lower(), ctx.lower()
    kinds = set()
    if "huggingface.co/datasets" in u or any(h in u for h in ("figshare", "kaggle.com/datasets", "data.mendeley", "osf.io")):
        kinds.add("data")
    elif "huggingface.co/" in u and "/spaces/" not in u:
        kinds.add("weights")
    elif any(h in u for h in ("github.com", "gitlab.", "bitbucket.org", "codeocean")):
        kinds.add("code")
    if re.search(r"\b(data ?sets?|data are|benchmark|corpus|annotations?)\b", c):
        kinds.add("data")
    if re.search(r"\b(weights|checkpoints?|trained models?|pre-?trained models?)\b", c):
        kinds.add("weights")
    if re.search(r"\b(code|implementation|source)\b", c) and "github" in u:
        kinds.add("code")
    return sorted(kinds or {"code"})


def github_check(url):
    """Existence, stars, licence and last update of a GitHub repo; repairs names broken by lost hyphens."""
    m = re.match(r"https://github\.com/([^/\s]+)/([^/\s#?]+)", url)
    if not m:
        return None
    owner, name = m.group(1), re.sub(r"\.git$", "", m.group(2))
    r = get(f"https://api.github.com/repos/{owner}/{name}", headers=gh_headers())
    if r is not None and r.status_code == 200:
        j = r.json()
        return dict(url=j["html_url"], ok=True, stars=j.get("stargazers_count"), license=(j.get("license") or {}).get("spdx_id"),
                    updated=(j.get("pushed_at") or "")[:10])
    r = get(f"https://api.github.com/users/{owner}/repos", params={"per_page": 100}, headers=gh_headers())
    if r is not None and r.status_code == 200:
        names = [x["name"] for x in r.json()]
        best = [x for x in names if len(name) >= 6 and x.lower().startswith(name.lower().rstrip("_-."))][:1]
        best = best or difflib.get_close_matches(name, names, n=1, cutoff=0.82)
        if not best:
            norm = {plain(x): x for x in names}
            best = [norm[plain(name)]] if plain(name) in norm else []
        if best:
            return github_check(f"https://github.com/{owner}/{best[0]}")
    return dict(url=url, ok=False)


def url_check(url):
    if "github.com" in url:
        return github_check(url) or dict(url=url, ok=False)
    r = get(url, timeout=30)
    return dict(url=url, ok=bool(r is not None and r.status_code < 400))


def text_links(text):
    out = []
    flat = re.sub(r"\s+", " ", text)
    for m in URL.finditer(flat):
        u = clean(m.group(0))
        if THIRD.search(u) or re.fullmatch(r"https://(github\.com|gitlab\.[a-z0-9.-]+|huggingface\.co)/[^/]+/?", u):
            continue
        ctx = flat[max(0, m.start() - 260):m.end() + 80]
        if not OWN.search(ctx[:280]) or PROMISE.search(ctx):
            continue
        if not any(x["url"] == u for x in out):
            out.append(dict(url=u, kinds=kind_of(u, ctx), source="paper text"))
    return out


def pdf_text(urls):
    import pymupdf
    for u in urls[:3]:
        r = get(u, timeout=60, stream=True)
        if r is None or r.status_code != 200:
            continue
        data = r.raw.read(30_000_000, decode_content=True)
        if data[:4] != b"%PDF":
            continue
        try:
            doc = pymupdf.open(stream=io.BytesIO(data), filetype="pdf")
            t = "\n".join(p.get_text() for p in doc.pages(0, min(doc.page_count, 40)))
        except Exception:
            continue
        j = max(t.rfind("\nReferences"), t.rfind("\nREFERENCES"), t.rfind("\nBibliography"))
        return t[:j] if j > len(t) * 0.4 else t
    return ""


def arxiv_id(item):
    m = re.search(r"arxiv\.(\d{4}\.\d{4,5})", (item.get("doi") or "").lower())
    if m:
        return m.group(1)
    for u in item.get("landing", []) + item.get("pdf", []):
        m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", u or "")
        if m:
            return m.group(1)
    return None


def hf_links(aid):
    out = []
    for kind, path in (("weights", "models"), ("data", "datasets")):
        r = get(f"https://huggingface.co/api/{path}", params={"filter": f"arxiv:{aid}", "limit": 5})
        if r is not None and r.status_code == 200:
            for x in r.json():
                rid = x.get("id") or x.get("modelId")
                if rid and not THIRD.search("huggingface.co/" + rid):
                    out.append(dict(url=f"https://huggingface.co/{'datasets/' if path == 'datasets' else ''}{rid}",
                                    kinds=[kind], source="Hugging Face (arXiv tag)", ok=True))
    return out


def zenodo_links(doi):
    if not doi:
        return []
    r = get("https://zenodo.org/api/records", params={"q": f'related.identifier:"{doi}"', "size": 5})
    out = []
    if r is not None and r.status_code == 200:
        for h in r.json().get("hits", {}).get("hits", []):
            rtype = ((h.get("metadata") or {}).get("resource_type") or {}).get("type", "")
            kinds = ["code"] if rtype == "software" else ["data"] if rtype == "dataset" else ["data"]
            out.append(dict(url=h.get("links", {}).get("self_html") or f"https://zenodo.org/records/{h.get('id')}",
                            kinds=kinds, source="Zenodo (linked to DOI)", ok=True))
    return out


def github_search(title, authors=()):
    words = re.findall(r"[A-Za-z0-9-]+", title)
    if len(words) < 5 or not gh_headers().get("Authorization"):
        return []
    r = get("https://api.github.com/search/repositories", params={"q": f'"{title[:120]}" in:readme', "per_page": 3},
            headers=gh_headers())
    time.sleep(2.2)  # search API: 30 requests per minute
    out = []
    if r is not None and r.status_code == 200:
        for x in r.json().get("items", [])[:3]:
            if not plausible_repo(x, title, authors):
                continue
            out.append(dict(url=x["html_url"], kinds=["code"], source="GitHub README cites the title", ok=True,
                            stars=x.get("stargazers_count"), license=(x.get("license") or {}).get("spdx_id"),
                            updated=(x.get("pushed_at") or "")[:10]))
    return out


def plausible_repo(repo, title, authors):
    """A repo found by search counts only if its name shares a distinctive title word (e.g. 'AgroGPT') or its owner
    matches an author's surname; this rejects repositories that merely cite the paper."""
    name = plain(repo.get("name", ""))
    owner = plain((repo.get("owner") or {}).get("login", ""))
    words = [plain(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", title)]
    stop = {"with", "from", "using", "based", "model", "models", "large", "language", "learning", "deep", "framework",
            "approach", "system", "analysis", "towards", "toward", "agricultural", "agriculture", "food", "data", "dataset"}
    distinct = [w for w in words if w not in stop and len(w) >= 4]
    surnames = [plain(a.split(",")[0].split()[-1]) for a in authors if a and a.strip()]
    if any(w and (w in name or name in w) for w in distinct if len(name) >= 4):
        return True
    return any(sn and len(sn) >= 3 and sn in owner for sn in surnames)


def find_releases(item, full=True):
    links = text_links(item.get("abstract", ""))
    if full and item.get("pdf"):
        links += [x for x in text_links(pdf_text(item["pdf"])) if x["url"] not in {y["url"] for y in links}]
    checked = []
    for x in links:
        c = url_check(x["url"])
        if c and c.get("ok"):
            checked.append(dict(x, **c))
        elif c:
            checked.append(dict(x, ok=False))
    aid = arxiv_id(item)
    if aid:
        checked += [x for x in hf_links(aid) if x["url"] not in {y["url"] for y in checked}]
    checked += [x for x in zenodo_links(item.get("doi")) if x["url"] not in {y["url"] for y in checked}]
    if any(x.get("ok") for x in checked):
        checked = [x for x in checked if x.get("ok")]
    if not any(x.get("ok") for x in checked):
        checked += github_search(item.get("title", ""), item.get("authors", []))
    return checked


def run(limit=None):
    queue = load("queue.json", [])
    studies = {s["key"]: s for s in load("studies.json", [])}
    seen = set(load("seen.json", []))
    norel = {s["key"]: s for s in load("no_release.json", [])}
    limit = int(limit or 10**9)
    done = 0
    for item in list(queue)[:limit]:
        rel = find_releases(item)
        item["releases"] = rel
        item["checked"] = TODAY
        item["status"] = "auto-detected"
        item.pop("abstract", None)
        if any(x.get("ok") for x in rel):
            studies[item["key"]] = item
            norel.pop(item["key"], None)
        else:
            norel[item["key"]] = dict(key=item["key"], title=item["title"], doi=item.get("doi"), date=item.get("date"),
                                      authors=item.get("authors", [])[:3], venue=item.get("venue", ""),
                                      domains=item.get("domains", []), technologies=item.get("technologies", []),
                                      checks=1, last=TODAY, landing=item.get("landing", [])[:2], pdf=item.get("pdf", [])[:2])
        seen.add(item["key"])
        queue.remove(item)
        done += 1
        if done % 25 == 0:
            save("queue.json", queue); save("studies.json", list(studies.values()))
            save("seen.json", sorted(seen)); save("no_release.json", list(norel.values()))
            print(f"  processed {done}")
    # studies without a release are checked again 30, 90 and 180 days later (code is often released late)
    rechecked = 0
    for k, s in list(norel.items()):
        age = (dt.date.today() - dt.date.fromisoformat(s["last"])).days
        if s["checks"] < 4 and age >= {1: 30, 2: 60, 3: 90}.get(s["checks"], 999) and rechecked < 300:
            rel = find_releases(dict(s, abstract=""), full=False)
            s["checks"] += 1; s["last"] = TODAY; rechecked += 1
            if any(x.get("ok") for x in rel):
                studies[k] = dict(s, releases=rel, checked=TODAY, status="auto-detected (late release)")
                norel.pop(k)
    save("queue.json", queue); save("studies.json", list(studies.values()))
    save("seen.json", sorted(seen)); save("no_release.json", list(norel.values()))
    print(f"detect: processed {done}, rechecked {rechecked}; studies with releases {len(studies)}, without {len(norel)}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
