"""HTML landing page for portfolio API demos."""

GITHUB = "dawit-Tegegnwork"


def render_landing(
    title: str,
    tagline: str,
    synthetic_notice: str,
    repo_slug: str,
    *,
    health_path: str = "/health",
    docs_path: str = "/docs",
    extra_links: list[tuple[str, str]] | None = None,
    quick_steps: list[str] | None = None,
) -> str:
    extra = "".join(f'<a href="{href}">{label}</a>' for href, label in (extra_links or []))
    steps = "".join(f"<li>{s}</li>" for s in (quick_steps or []))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;line-height:1.6}}
main{{max-width:820px;margin:0 auto;padding:2.5rem 1.25rem}}
.notice{{background:#1e293b;border:1px solid #334155;color:#cbd5e1;padding:1rem;border-radius:8px;margin:1rem 0}}
.links a{{display:inline-block;margin:.35rem .75rem .35rem 0;color:#38bdf8;font-weight:600}}
ol{{padding-left:1.25rem}} code{{background:#334155;padding:.1rem .35rem;border-radius:4px}}
</style></head><body><main>
<h1>{title}</h1><p>{tagline}</p>
<div class="notice"><strong>Synthetic data only.</strong> {synthetic_notice}</div>
<div class="links">
<a href="{docs_path}">API docs</a><a href="{health_path}">Health check</a>{extra}
<a href="https://github.com/{GITHUB}/{repo_slug}">GitHub</a>
</div>
<h2>Quick test (3 minutes)</h2><ol>{steps}</ol>
</main></body></html>"""
