"""Export only the public learning portfolio; never package the Python service or data.

Standard-library only. The OCI homepage remains the single source for the animation.
Exact replacement checks fail closed if its wording changes and needs a new export.
"""

import runpy
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "observatory/static"
ASSETS = (
    "home.css", "home.js", "icon.svg", "architecture.svg", "request-flow.svg",
    "hardware-flow.svg", "service-architecture.svg",
)
REPO = "https://github.com/sivalinb/llm-serving-observatory"
SITE_ASSETS = ("portfolio.css", "academy.css", "academy.js")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Portfolio source contract changed: {old[:90]!r}")
    return text.replace(old, new, 1)


def render() -> str:
    page = (STATIC / "home.html").read_text()
    replacements = [
        ('<html lang="en">', '<html lang="en" data-deployment="portfolio">'),
        ('<a href="#concepts">The concepts</a>', '<a href="/learn/">Serving Academy</a>'),
        ('then explore the real CPU assistant and private experiment lab.',
         'explore architecture diagrams and the source. Live AI chat is pending OCI deployment.'),
        ('href="/assistant">Open assistant', 'href="#live-service">AI service status'),
        ('A learning lab + a real CPU-powered documentation assistant.<br>Designed for a small OCI Phoenix deployment.',
         'Public learning portfolio · hosted with ChatGPT Sites.<br>Live AI chat is coming with OCI deployment.'),
        ('A real service and an experimental lab, with a clear line between measured results and modeled behavior.',
         'Explore the implementation and run it locally. This public portfolio has no live model, request history or operational dashboards.'),
        ('<article class="experience assistant-experience">',
         '<article id="live-service" class="experience assistant-experience">'),
        ('<span class="experience-tag">THE REAL SERVICE</span>',
         '<span class="experience-tag">COMING WITH OCI DEPLOYMENT</span>'),
        ('<h3>Ask the documentation assistant.</h3>', '<h3>Live AI chat is not online yet.</h3>'),
        ('Get source references and streamed answers about serving concepts. Inspect your own timing and token receipt.',
         'The repository includes a real CPU-powered documentation assistant. It needs a running backend; this ChatGPT-hosted portfolio does not run the model or accept questions.'),
        ('<li>Invite-only access and personal request history</li><li>A small, real CPU model when configured</li><li>Document search even when AI answers are off</li>',
         '<li>Available in the code: invite-only access and token receipts</li><li>Deployment target: a small OCI Phoenix CPU VM</li><li>No model calls, API keys or user data collected by this portfolio</li>'),
        ('href="/assistant">Open the assistant',
         f'href="{REPO}/blob/main/docs/servingops-runbook.md" target="_blank" rel="noopener noreferrer">Read the service runbook'),
        ('Small models can be wrong. Citation IDs are checked; factual support is not guaranteed.',
         'ChatGPT Sites provides hosting here, not ChatGPT-powered answers. When deployed, small-model answers still need source verification.'),
        ('Operators use <code>/lab</code> through a local connection or SSH tunnel. The public site blocks it.',
         'The lab and dashboards are not included in this public export. Run them locally or privately on OCI.'),
        ('href="/lab" hidden', 'href="#explore" hidden'),
        ('Deployment target, not a live-status claim.',
         'Future OCI deployment target. Only the learning portfolio is hosted on ChatGPT Sites today.'),
    ]
    for old, new in replacements:
        page = replace_once(page, old, new)
    cards = []
    for name, title, summary in [
        ("request-flow", "Follow the request", "Latency boundaries, prefill, KV handoff and token accounting."),
        ("hardware-flow", "Understand memory", "CPU RAM, GPU HBM, model weights, KV cache and bandwidth."),
        ("architecture", "Explore the learning lab", "Simulated workers, real-engine adapters and the observability pipeline."),
        ("service-architecture", "Plan the OCI service", "Public HTTPS, private CPU inference and operator-only telemetry."),
    ]:
        cards.append(
            f'<article class="diagram-card"><a href="/static/{name}.svg" '
            f'target="_blank" rel="noopener noreferrer" aria-label="{title}: open full-size diagram">'
            f'<img src="/static/{name}.svg" alt="{summary}" loading="lazy" width="1200" height="800">'
            f'<h3>{title} ↗</h3></a><p>{summary}</p></article>'
        )
    diagrams = (
        '<section id="diagrams" class="section" aria-labelledby="diagrams-title">'
        '<div class="section-heading"><div><p class="eyebrow">READ THE SYSTEM</p>'
        '<h2 id="diagrams-title">Architecture, from request to hardware.</h2></div>'
        '<p>Open any diagram at full size. These document the design, not live traffic.</p></div>'
        '<div class="diagram-grid">' + ''.join(cards) + '</div></section>'
    )
    page = replace_once(page, '<section class="deployment section"', diagrams + '<section class="deployment section"')
    page = replace_once(page, '</head>', '<link rel="stylesheet" href="/static/portfolio.css">\n</head>')
    academy = (
        '<section class="academy-launch section" aria-labelledby="academy-title">'
        '<div><p class="eyebrow">LEARN END-TO-END SERVING</p>'
        '<h2 id="academy-title">Go beyond the first token.</h2>'
        '<p>20 modules connect models and tokens to batching, KV memory, GPU topology, infrastructure, '
        'security, observability, reliability, quality and cost.</p>'
        '<a class="button primary" href="/learn/">Start learning in the Serving Academy ↗</a></div>'
        '<ol><li>Foundations → define the workload and model</li><li>Engine → manage memory and execution</li>'
        '<li>Scale → place, route and grow capacity</li><li>Operate → measure, protect and recover</li>'
        '<li>Applications → evaluate outcomes and cost</li></ol>'
        '<p>Includes self-checks and four browser exercises. No GPU or cloud account required. '
        'Exercises are explanatory, not live inference.</p></section>'
    )
    page = replace_once(page, '<section class="purpose"', academy + '<section class="purpose"')
    return page


def build(destination: Path) -> None:
    """Write an allowlisted artifact and reject stale/unrecognized output files."""
    expected = {"index.html", "404.html", "learn/index.html"} | {f"static/{a}" for a in ASSETS + SITE_ASSETS}
    if destination.exists():
        unexpected = {str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()} - expected
        symlinks = [p for p in destination.rglob("*") if p.is_symlink()]
        if unexpected or symlinks or destination.is_symlink():
            raise ValueError("Output contains unexpected files or symlinks; use a clean build directory")
    page = render()  # Validate the source contract before writing any output.
    academy = runpy.run_path(str(ROOT / "scripts/render_academy.py"))["render_academy"]()
    (destination / "static").mkdir(parents=True, exist_ok=True)
    for asset in ASSETS:
        shutil.copyfile(STATIC / asset, destination / "static" / asset)
    for asset in SITE_ASSETS:
        shutil.copyfile(ROOT / "sites" / asset, destination / "static" / asset)
    (destination / "learn").mkdir(exist_ok=True)
    (destination / "learn/index.html").write_text(academy)
    (destination / "index.html").write_text(page)
    (destination / "404.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Not available · LLM Serving Observatory</title>'
        '<link rel="stylesheet" href="/static/home.css"></head><body><main class="section">'
        '<h1>This is the public learning portfolio.</h1>'
        '<p>Live AI chat is coming with OCI deployment. The private lab and API are not hosted here.</p>'
        '<a class="button primary" href="/">Return to the animated tour</a></main></body></html>'
    )


if __name__ == "__main__":
    build(ROOT / "dist")
    print("Built public portfolio in dist/ (no backend, models, data or secrets).")
