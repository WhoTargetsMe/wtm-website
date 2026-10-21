#!/usr/bin/env python3
"""
Build a clean serving tree for the whotargets.me site freeze.

Input : whotargetme-mirror/       (raw wget download, left untouched)
Output: data/site-freeze-build/  (tree ready to upload to an S3 bucket
                                  with an index.html index document)

Why the transformations:
1. Assets: pages reference /wp-includes and /wp-content files with ?ver=
   query strings. S3 query strings are not part of the object key, so a
   browser asking for styles.css?ver=6.1.6 needs the object styles.css.
   Some assets were saved by wget under mangled names (with the query
   string embedded); we fetch every referenced asset under its clean
   path from the still-live origin instead.
2. Salvage: wget saved many posts only as en/index.html?p=NNN.html
   (junk permalink form). Each file's <link rel=canonical> points at its
   real URL; we copy each to its canonical path.
3. Normalisation: the live site serves the same page at /slug (302 from
   root), /slug/ and /en/slug/. A bucket with an index document only
   resolves /slug/ to slug/index.html, so we materialise every page in
   every form: slug/ (dir + index.html), slug.html, slug (extensionless,
   for no-slash links).
4. Cross-tree duplication: root pages and /en/ pages are the same content
   (root /about/ 302s to /en/about/), and inbound links from wtm-trends
   use the /en/ form while internal links use the root form. Both trees
   must contain every top-level page.
"""
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional

MIRROR = Path("/Volumes/projects/whotargetsme/whotargetme-mirror")
BUILD = Path("/Volumes/projects/whotargetsme/data/site-freeze-build")
ORIGIN = "https://whotargets.me"

# junk that must never reach the bucket
EXCLUDE_DIRS = {"wp-json"}
QUERY_NAME_RE = re.compile(r"\?")

ASSET_RE = re.compile(
    r"https://whotargets\.me/((?:wp-(?:includes|content))/[^\s\"'\)\?<>]+)",
    re.IGNORECASE,
)
CANONICAL_RE = re.compile(
    r"<link\s+rel=[\"']canonical[\"']\s+href=[\"']([^\"']+)[\"']"
)


def copy_clean_tree():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    def ignore(dirpath, names):
        ignored = set()
        if Path(dirpath).name in EXCLUDE_DIRS:
            ignored.update(names)
        for n in names:
            if QUERY_NAME_RE.search(n):
                ignored.add(n)
        return ignored

    shutil.copytree(MIRROR, BUILD / "site", ignore=ignore)
    # the bucket root must be the site root, not a nested "site/" dir
    for entry in (BUILD / "site").iterdir():
        shutil.move(str(entry), str(BUILD / entry.name))
    (BUILD / "site").rmdir()


def html_files(tree: Path):
    for f in tree.rglob("*.html"):
        if "wp-content" not in f.parts:
            yield f


def fetch_missing_assets():
    referenced = set()
    for f in html_files(BUILD):
        text = f.read_text(errors="replace")
        for match in ASSET_RE.finditer(text):
            referenced.add(match.group(1))
    fetched, failed = 0, []
    for rel in sorted(referenced):
        target = BUILD / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(f"{ORIGIN}/{rel}", timeout=30) as r:
                target.write_bytes(r.read())
            fetched += 1
        except Exception as e:  # noqa: BLE001
            failed.append((rel, str(e)[:60]))
    print(f"assets referenced: {len(referenced)}, fetched now: {fetched}, failed: {len(failed)}")
    for rel, err in failed:
        print(f"  FAILED {rel} ({err})")


def salvage_query_pages():
    """Copy every ?p=-style file to its canonical path as <path>.html."""
    salvaged, skipped = 0, 0
    for f in MIRROR.rglob("*"):
        if not f.is_file() or not QUERY_NAME_RE.search(f.name):
            continue
        if any(part in EXCLUDE_DIRS for part in f.parts):
            continue
        text = f.read_text(errors="replace")
        m = CANONICAL_RE.search(text)
        if not m:
            skipped += 1
            continue
        path = m.group(1).removeprefix(f"{ORIGIN}/").strip("/")
        if not path or path.endswith((".css", ".js", ".xml")):
            skipped += 1
            continue
        target = BUILD / f"{path}.html"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
            salvaged += 1
    print(f"salvaged {salvaged} pages via canonical, skipped {skipped}")


def page_source(dir_path: Path, slug: str) -> Optional[Path]:
    """Return the existing page file for slug in dir_path, if any."""
    for candidate in (dir_path / f"{slug}.html", dir_path / slug / "index.html"):
        if candidate.exists():
            return candidate
    return None


def duplicate_top_level_between_trees():
    """Mirror top-level root pages into en/ and vice versa (same content)."""
    root, en = BUILD, BUILD / "en"
    en.mkdir(exist_ok=True)
    duped = 0
    for base, other in ((root, en), (en, root)):
        for f in sorted(base.glob("*.html")):
            slug = f.name.removesuffix(".html")
            if slug == "index" or other.joinpath(f"{slug}.html").exists():
                continue
            other.joinpath(f"{slug}.html").write_bytes(f.read_bytes())
            duped += 1
        for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name not in ("en", "wp-content")):
            src = page_source(d.parent, d.name)
            if not src or page_source(other, d.name):
                continue
            dst = other / f"{d.name}.html"
            dst.write_bytes(src.read_bytes())
            duped += 1
    print(f"cross-tree duplicated pages: {duped}")


def normalise_page_forms():
    """For every X.html anywhere: ensure X/index.html exists.

    Note: the no-slash URL form (/about) needs an S3 object at key "about"
    alongside prefix "about/index.html". A local file "about" cannot
    coexist with a directory "about/" on the filesystem, so those
    extensionless objects are created during the upload step instead.
    """
    made_dir = 0
    for f in list(html_files(BUILD)):
        slug = f.name.removesuffix(".html")
        if slug == "index":
            continue
        dir_index = f.parent / slug / "index.html"
        if not dir_index.exists():
            dir_index.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dir_index)
            made_dir += 1
    print(f"normalised: {made_dir} slug/ dirs (extensionless handled at upload)")


def finish():
    # /en/ serves the English homepage too
    en_index = BUILD / "en" / "index.html"
    if not en_index.exists():
        shutil.copyfile(BUILD / "index.html", en_index)

    (BUILD / "error.html").write_text(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Who Targets Me</title></head>
<body style="font-family:sans-serif;max-width:40em;margin:4em auto;padding:0 1em">
<h1>Who Targets Me</h1>
<p>That page isn't available right now.</p>
<p><a href="/">Back to whotargets.me</a></p>
</body></html>
"""
    )
    total = sum(1 for _ in BUILD.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in BUILD.rglob("*") if f.is_file())
    print(f"final tree: {total} files, {size / 1e6:.1f} MB")


def report_link_forms():
    """Info only: which link styles pages actually use (for sanity checking)."""
    text = (BUILD / "index.html").read_text(errors="replace")
    for label, pattern in (
        ("page/N pagination", r'href="[^"]*/page/\d+/?"'),
        ("category links", r'href="[^"]*category/[^"]*"'),
    ):
        hits = re.findall(pattern, text)
        sample = sorted(set(hits))[:3]
        print(f"{label}: {len(hits)} on homepage {sample if sample else ''}")


def main():
    copy_clean_tree()
    fetch_missing_assets()
    salvage_query_pages()
    duplicate_top_level_between_trees()
    normalise_page_forms()
    finish()
    report_link_forms()
    print("done:", BUILD)


if __name__ == "__main__":
    sys.exit(main())
