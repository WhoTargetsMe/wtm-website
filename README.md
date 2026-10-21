# whotargetsme-website

Static mirror of the whotargets.me marketing site (Who Targets Me), frozen
on 21 October 2026 and served from GitHub Pages.

## Why this exists

The site previously ran on a Bitnami WordPress instance on AWS Lightsail.
The PHP2Shell vulnerabilities (CVE-2026-109618 / CVE-2026-109619, October
2026) made internet-facing PHP untenable, and Bitnami Lightsail images
stopped receiving updates in May 2026. Rather than lift-and-shift WordPress
to new hosting, the site was frozen as-is while a replacement is built.

## How it was built

1. `wget` mirror of the live WordPress site.
2. `build_freeze_site.py` (included here for provenance) which:
   - fetches every referenced `/wp-includes` and `/wp-content` asset
     under clean, query-stripped object paths
   - salvages pages saved only under `?p=` junk permalinks by following
     each file's canonical URL
   - materialises every page in every URL form the site must answer
     (`/slug/`, `/slug`, `/en/slug/`) because the WordPress install
     served the same content at root and `/en/` paths
3. Deployed as-is: no build step, served straight from `main`.

The raw wget mirror and the migration artifacts (database dump, WordPress
WXR export, uploads archive) are **not** in this repository — they contain
non-public data and live in private storage.

## Serving

- GitHub Pages, publishing source: `main` branch at `/`
- Custom domain: `whotargets.me` (apex, via A records to GitHub Pages)
- `www` redirects to the apex via GitHub Pages automatic domain redirects
- `.nojekyll` disables Jekyll processing — files are served as-is

## What happens next

This freeze is a stopgap. The plan is to replace it with a SvelteKit
static build managed through Decap CMS (git-based editing), deployed to
Pages from this same repository — so the domain and DNS never change.

## Known limitations of the freeze

- Forms do not work (contact forms were PHP)
- Feeds, search and wp-admin are not available
- A handful of images that were already broken (404) on the original
  site are equally broken here
- The featured-reports section of wtm-trends, which read the WordPress
  REST API, is empty during the freeze
