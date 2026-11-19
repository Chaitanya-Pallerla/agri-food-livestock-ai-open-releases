# Open AI releases in agriculture, food and livestock

A living list of research studies in **agriculture**, **food science** and **livestock and aquaculture** that apply AI
(large language models, vision-language models, agents, embodied and physical AI, robotics, computer vision, machine
learning and sixteen emerging technologies) **and publicly release their code, data or model weights**, with links.

**{{N}} studies** with at least one open release · {{VERIFIED}} checked by hand · {{AUTO}} found automatically ·
last updated **{{TODAY}}** (updated automatically every 5 days).

| Domain | Studies | Code | Data | Model weights |
|---|---:|---:|---:|---:|
{{TABLE}}

Browse: [by technology](docs/by-technology.md) · download as [CSV](data/studies.csv) or [JSON](data/studies.json)

**Technologies covered:** {{TECHS}}

## Latest additions

{{LATEST}}

## How the list is built

Every 5 days a GitHub Action runs three scripts, with no manual step:

1. **Search** ([scripts/search.py](scripts/search.py)) queries [OpenAlex](https://openalex.org) for studies published in the
   last three weeks whose title or abstract matches a domain term *and* a technology term from
   [config/terms.json](config/terms.json). Reviews and surveys are excluded.
2. **Detect releases** ([scripts/detect.py](scripts/detect.py)) looks for the study's *own* code, data or weights in the
   abstract and the open-access full text, in Hugging Face models and datasets tagged with the paper's arXiv id, in Zenodo
   records linked to its DOI and, as a last resort, in GitHub repositories whose README quotes the paper title. Links to
   well-known third-party tools, and promises such as "available on request" or "will be released", are ignored. Every
   link is opened; GitHub links are checked through the GitHub API (stars, licence, last update), and links broken by PDF
   line breaks are repaired against the owner's real repositories. Studies without a release are checked again after
   30, 90 and 180 days, because code is often published late.
3. **Build** ([scripts/build.py](scripts/build.py)) writes this page, one page per domain and the CSV/JSON files.

**Status column.** *verified* entries (the first {{VERIFIED}}) come from three literature reviews in which every release
statement was read by hand; *auto* entries were found by the scripts and may occasionally be wrong. Only openly
accessible full texts are read, so releases mentioned only inside paywalled papers can be missed. {{NOREL}} screened
studies have no open release so far and are re-checked over time.

## Contributing

Spotted a missing study, a wrong link or a release that is not the study's own? Open an issue or a pull request
editing `data/studies.json`; to change what is searched, edit `config/terms.json`.

## Licence

Code: MIT. Data (the lists in `data/` and `docs/`): CC BY 4.0. Each linked resource keeps its own licence.
