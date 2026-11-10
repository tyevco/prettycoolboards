"""Check every link in the built VitePress site (.vitepress/dist).

- internal links (relative, or absolute under /prettycoolboards/ or https://tyevco.github.io/prettycoolboards/):
  the target file exists in dist (clean URLs: x -> x.html or x/index.html) and the #anchor exists in it
- github.com/tyevco/prettycoolboards/(blob|tree)/main/<path>: the path exists in git HEAD
- other external links: fetched (HEAD, then GET), with a browser user agent
usage: python tools/check_links.py <repo> [--no-external]   (after npm run docs:build)
"""
import concurrent.futures as cf
import html.parser
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

REPO = sys.argv[1]
DIST = os.path.join(REPO, ".vitepress", "dist")
BASE = "/prettycoolboards/"
SITE = "https://tyevco.github.io/prettycoolboards/"
GH = "https://github.com/tyevco/prettycoolboards/"


class P(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        for k in ("href", "src"):
            if k in a and a[k] and tag in ("a", "img", "link", "script", "source"):
                if tag == "link" and a.get("rel") in ("preconnect", "dns-prefetch"):
                    continue
                self.links.append((tag, a[k]))


pages = {}
for root, _, files in os.walk(DIST):
    for f in files:
        if f.endswith(".html"):
            p = os.path.join(root, f)
            pp = P()
            pp.feed(open(p, encoding="utf-8", errors="replace").read())
            pages[os.path.relpath(p, DIST).replace(os.sep, "/")] = pp


def resolve(path):
    """dist-relative path for a site path (no base), or None"""
    path = urllib.parse.unquote(path).lstrip("/")
    cands = [path, path + ".html", path.rstrip("/") + "/index.html", path + "index.html"] if path else ["index.html"]
    for c in cands:
        if os.path.isfile(os.path.join(DIST, c)):
            return c
    return None


tracked = set(subprocess.run(["git", "-C", REPO, "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True, text=True).stdout.split("\n"))
tracked_dirs = {os.path.dirname(t) for t in tracked} | {"/".join(t.split("/")[:i]) for t in tracked for i in range(1, t.count("/") + 1)}

problems, external = [], {}
for page, pp in sorted(pages.items()):
    for tag, href in pp.links:
        if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        url = urllib.parse.urlsplit(href)
        if url.scheme in ("http", "https"):
            full = href
            if full.startswith(SITE):
                tgt = "/" + full[len(SITE):]
                url = urllib.parse.urlsplit(BASE.rstrip("/") + tgt)
            elif full.startswith(GH):
                m = re.match(re.escape(GH) + r"(blob|tree)/main/([^#?]*)", full)
                if m:
                    p = urllib.parse.unquote(m.group(2)).rstrip("/")
                    if p not in tracked and p not in tracked_dirs:
                        problems.append((page, href, "not in git HEAD"))
                    continue
                external.setdefault(href.split("#")[0], []).append(page)
                continue
            else:
                external.setdefault(href.split("#")[0], []).append(page)
                continue
        # internal
        if url.path == "" and url.fragment:
            tgt_page = page
        else:
            path = url.path
            if path.startswith(BASE):
                path = path[len(BASE):]
            elif path.startswith("/"):
                if not path.startswith(("/assets", "/vp-icons")):
                    problems.append((page, href, "absolute path outside the base"))
                continue
            else:
                path = os.path.normpath(os.path.join(os.path.dirname(page), path)).replace(os.sep, "/")
                if path == ".":
                    path = ""
            tgt_page = resolve(path)
            if tgt_page is None:
                problems.append((page, href, "missing target"))
                continue
        if url.fragment and tgt_page.endswith(".html"):
            frag = urllib.parse.unquote(url.fragment)
            ids = pages[tgt_page].ids if tgt_page in pages else set()
            if frag not in ids:
                problems.append((page, href, f"missing anchor in {tgt_page}"))

print(f"{len(pages)} pages, {len(problems)} internal/repo problems, {len(external)} external URLs")
for p in problems:
    print("BROKEN", *p, sep=" | ")
json.dump({"problems": problems, "external": external}, open(os.path.join(DIST, "..", "linkcheck.json"), "w"), indent=1)

if "--no-external" in sys.argv:
    sys.exit(1 if problems else 0)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
      "Accept": "text/html,application/pdf,*/*"}


def fetch(u):
    for method in ("HEAD", "GET"):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=UA, method=method), timeout=25)
            return r.status, ""
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 404, 405, 429, 400, 501):
                continue
            return e.code, ""
        except Exception as e:
            if method == "HEAD":
                continue
            return None, type(e).__name__ + ": " + str(e)[:80]
    return None, "?"


with cf.ThreadPoolExecutor(12) as ex:
    res = dict(zip(external, ex.map(fetch, external)))
bad = {u: r for u, r in res.items() if not (r[0] and 200 <= r[0] < 400)}
print(f"external: {len(res)} checked, {len(bad)} not OK")
for u, (code, err) in sorted(bad.items()):
    print("EXT", code, err, u, "<-", ", ".join(sorted(set(external[u])))[:160])
json.dump({"problems": problems, "external_bad": {u: [r[0], r[1], external[u]] for u, r in bad.items()}},
          open(os.path.join(DIST, "..", "linkcheck.json"), "w"), indent=1)

sys.exit(1 if problems else 0)
