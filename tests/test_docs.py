"""The pages in docs/ link only to what GitHub Pages publishes with them.

GitHub Pages serves docs/ alone, so a relative link that leaves it, or one to a folder without
an index, works on GitHub and breaks on the published site.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)\)")
PAGES = sorted(DOCS.rglob("*.md"))


def anchors(page: Path) -> set[str]:
    """The anchors of a page's headings, as GitHub and GitHub Pages both make them.

    Args:
        page: A Markdown page.

    Returns:
        The anchors, without the ``#``.
    """
    found = set()
    for line in page.read_text().splitlines():
        heading = re.match(r"#+\s+(.*)", line)
        if heading:
            text = re.sub(r"[^\w\- ]", "", heading.group(1).strip().lower())
            found.add(text.replace(" ", "-"))
    return found


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.relative_to(DOCS).as_posix())
def test_a_page_links_only_within_docs(page):
    for text, target in LINK.findall(page.read_text()):
        if re.match(r"https?:|mailto:", target):
            continue
        # GitHub Pages turns a link to a page into its address only when it is on one line.
        assert "\n" not in text, f"the link to {target} is broken over two lines: keep it on one"
        path, _, anchor = target.partition("#")
        linked = (page.parent / path).resolve() if path else page
        assert linked.is_relative_to(DOCS), (
            f"{target} leaves docs/, which GitHub Pages does not publish: link to "
            "https://github.com/trash-iine/optopus-studio/blob/main/... instead"
        )
        assert linked.is_file(), f"{target} is not a file: link to a page, or a folder's README.md"
        if anchor and linked.suffix == ".md":
            assert anchor in anchors(linked), f"{target}: {linked.name} has no such heading"


def test_the_japanese_guide_has_every_page_of_the_guide():
    english = {page.name for page in (DOCS / "guide").glob("*.md")}
    japanese = {page.name for page in (DOCS / "ja" / "guide").glob("*.md")}
    assert english == japanese
