"""Print each day's HTML report to PDF, for OneDrive and email (OneDrive previews PDFs; it will not render HTML).

Usage: python pipeline/pdf.py [YYYY-MM-DD ...]   (default: every report without a PDF, plus latest)
Needs: pip install playwright && python -m playwright install --with-deps chromium
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"

PRINT_CSS = """
@page { size: A4; margin: 14mm 12mm 16mm; }
nav.scroll, .filter { display: none !important; }
.top { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.card, .item, .today li, tr { break-inside: avoid; }
h2 { break-after: avoid; }
details, .allq, .mini, .stats .mini, .links { display: none !important; }
.printonly { display: block !important; }
.cards { grid-template-columns: 1fr 1fr !important; gap: 8px !important; }
.card { padding: 8px 10px !important; font-size: 11.5px; line-height: 1.4; }
.card h3 { font-size: 14px !important; } .card .sig li { margin: 1px 0; }
body { font-size: 13px; } .item p { margin: 2px 0; }
a { color: inherit; }
"""


async def render(paths: list[Path]) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(**({"executable_path": __import__("os").environ["CHROME_PATH"], "args": ["--no-sandbox"]} if __import__("os").environ.get("CHROME_PATH") else {}))
        page = await browser.new_page(viewport={"width": 1100, "height": 1400})
        for html in paths:
            await page.goto(html.resolve().as_uri(), wait_until="networkidle")
            await page.emulate_media(media="print", color_scheme="light")
            await page.evaluate("document.documentElement.dataset.theme='light';"
                                "")
            await page.add_style_tag(content=PRINT_CSS)
            out = html.with_suffix(".pdf")
            await page.pdf(path=str(out), format="A4", print_background=True,
                           display_header_footer=True, header_template="<span></span>",
                           footer_template='<div style="font:9px sans-serif;width:100%;text-align:center;color:#555">'
                                           'Parliamentary briefing · page <span class="pageNumber"></span> of '
                                           '<span class="totalPages"></span></div>')
            print(f"pdf: {out.name} ({out.stat().st_size // 1024} KB)")
        await browser.close()


def main(dates: list[str]) -> int:
    reports = sorted(REPORTS.glob("20??-??-??.html"))
    if dates:
        todo = [REPORTS / f"{d}.html" for d in dates if (REPORTS / f"{d}.html").exists()]
    else:
        todo = [r for r in reports if not r.with_suffix(".pdf").exists()] or reports[-1:]
        if reports and reports[-1] not in todo:
            todo.append(reports[-1])  # always refresh the newest
    if not todo:
        print("no reports to print")
        return 0
    asyncio.run(render(todo))
    shutil.copy(reports[-1].with_suffix(".pdf"), REPORTS / "latest.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
