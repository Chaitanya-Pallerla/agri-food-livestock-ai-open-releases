"""Step 3: write README.md, one page per domain, a by-technology page and data/studies.csv from data/studies.json."""
import csv
import datetime as dt
import html
import os
import re
from collections import Counter

from common import CONFIG, DATA, ROOT, load

TODAY = dt.date.today().isoformat()
SLUG = {d: re.sub(r"[^a-z0-9]+", "-", d.lower()).strip("-") for d in CONFIG["domains"]}


def esc(s):
    return html.unescape(str(s or "")).replace("|", "\\|").replace("\n", " ").strip()


def link_cell(s):
    parts = []
    for r in s.get("releases", []):
        if not r.get("url"):
            parts.append("not linked in paper")
            continue
        host = re.sub(r"^https?://(www\.)?", "", r["url"]).split("/")[0]
        label = {"github.com": "GitHub", "huggingface.co": "Hugging Face", "zenodo.org": "Zenodo", "doi.org": "DOI"}.get(host, host)
        star = f" ★{r['stars']}" if r.get("stars") else ""
        parts.append(f"[{label}]({r['url']}){star}" + ("" if r.get("ok", True) else " (not accessible)"))
    return "<br>".join(parts) or "—"


def kinds(s):
    k = set(x for r in s.get("releases", []) for x in r.get("kinds", []))
    return ["✅" if t in k else "" for t in ("code", "data", "weights")]


def row(s):
    c, d, w = kinds(s)
    title = esc(s["title"])
    t = f"[{title}](https://doi.org/{s['doi']})" if s.get("doi") else title
    who = esc((s.get("authors") or [""])[0]).split(",")[0]
    year = s.get("year") or (s.get("date") or "")[:4]
    status = "✔ verified" if s.get("status", "").startswith("verified") else "auto"
    return f"| {year} | {t} | {who} | {esc(', '.join(s.get('technologies', [])) or '—')} | {c} | {d} | {w} | {link_cell(s)} | {status} |"


HEAD = ("| Year | Study | First author | Technologies | Code | Data | Weights | Links | Status |\n"
        "|---|---|---|---|:-:|:-:|:-:|---|---|")


def main():
    S = load("studies.json", [])
    S.sort(key=lambda s: (s.get("date") or "", s.get("title") or ""), reverse=True)
    norel = load("no_release.json", [])
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    # per-domain pages
    for dom in CONFIG["domains"]:
        rows = [s for s in S if dom in s.get("domains", [])]
        with open(os.path.join(ROOT, "docs", SLUG[dom] + ".md"), "w", encoding="utf-8") as f:
            f.write(f"# {dom}: AI studies with open code, data or model weights\n\n")
            f.write(f"{len(rows)} studies, newest first. Last updated {TODAY}. [Back to overview](../README.md)\n\n")
            f.write(HEAD + "\n" + "\n".join(row(s) for s in rows) + "\n")
    # by technology
    with open(os.path.join(ROOT, "docs", "by-technology.md"), "w", encoding="utf-8") as f:
        f.write(f"# Open releases by technology\n\nLast updated {TODAY}. [Back to overview](../README.md)\n\n")
        for tech in CONFIG["technologies"]:
            rows = [s for s in S if tech in s.get("technologies", [])]
            f.write(f"## {tech} ({len(rows)})\n\n")
            if rows:
                f.write(HEAD + "\n" + "\n".join(row(s) for s in rows) + "\n\n")
            else:
                f.write("No study with an open release yet.\n\n")
    # CSV
    with open(os.path.join(DATA, "studies.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "title", "doi", "first_author", "venue", "domains", "technologies", "code", "data", "weights",
                    "links", "status", "checked"])
        for s in S:
            k = set(x for r in s.get("releases", []) for x in r.get("kinds", []))
            w.writerow([s.get("year") or (s.get("date") or "")[:4], html.unescape(s.get("title") or ""), s.get("doi"),
                        (s.get("authors") or [""])[0], html.unescape(s.get("venue") or ""), "; ".join(s.get("domains", [])),
                        "; ".join(s.get("technologies", [])), "code" in k, "data" in k, "weights" in k,
                        " ; ".join(r["url"] for r in s.get("releases", []) if r.get("url")), s.get("status"), s.get("checked")])
    # README
    cnt = Counter(d for s in S for d in s.get("domains", []))
    k3 = lambda s, t: t in set(x for r in s.get("releases", []) for x in r.get("kinds", []))
    latest = [s for s in S if s.get("checked") == max((x.get("checked") or "") for x in S)] if S else []
    tbl = "\n".join(
        f"| [{d}](docs/{SLUG[d]}.md) | {cnt[d]} | {sum(1 for s in S if d in s['domains'] and k3(s, 'code'))} | "
        f"{sum(1 for s in S if d in s['domains'] and k3(s, 'data'))} | {sum(1 for s in S if d in s['domains'] and k3(s, 'weights'))} |"
        for d in CONFIG["domains"])
    techs = Counter(t for s in S for t in s.get("technologies", []))
    tech_line = ", ".join(f"{t} ({n})" for t, n in techs.most_common())
    readme = open(os.path.join(ROOT, "README.template.md"), encoding="utf-8").read()
    readme = (readme.replace("{{TODAY}}", TODAY).replace("{{N}}", str(len(S))).replace("{{TABLE}}", tbl)
              .replace("{{VERIFIED}}", str(sum(1 for s in S if s.get("status", "").startswith("verified"))))
              .replace("{{AUTO}}", str(sum(1 for s in S if not s.get("status", "").startswith("verified"))))
              .replace("{{NOREL}}", str(len(norel))).replace("{{TECHS}}", tech_line)
              .replace("{{LATEST}}", HEAD + "\n" + "\n".join(row(s) for s in latest[:25])))
    open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8").write(readme)
    print(f"build: {len(S)} studies with releases; pages written")


if __name__ == "__main__":
    main()
