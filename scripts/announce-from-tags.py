#!/usr/bin/env python3
"""Builds the Discord data for ALL published files of a mod version from the release tags.

  announce-from-tags.py MODS_JSON MOD VERSION OUTDIR [--type release] [--repo-dir DIR]

MODS_JSON  mods.yml as JSON (yq -o json . mods.yml)
VERSION    the mod version without loader and MC part, e.g. 1.1.1 (all tags v1.1.1-* are used)
OUTDIR     gets one JSON file per tag, the input for discord-announce.py
--repo-dir an existing clone with all branches and tags (otherwise the GitHub repo is cloned;
           GH_TOKEN is used if set, for private repos)

Per tag: Modrinth and CurseForge links from the tag message (written by publish.yml), changelog
section from changelog.txt at the tag (as Markdown), game versions from mods.yml or minecraft_version.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)-(Forge|NeoForge|Fabric)-mc(.+)$")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def changelog_md(text, version):
    """Section VERSION of changelog.txt as Markdown ("Fixes" -> "**Fixes**", " - x" -> "- x")."""
    lines = text.splitlines()
    dash = lambda l: re.match(r"^-+\s*$", l) is not None
    sec = []
    for n in range(len(lines) - 1):
        if lines[n].strip() == version and dash(lines[n + 1]):
            for k in range(n + 2, len(lines)):
                if k + 1 < len(lines) and dash(lines[k + 1]):
                    break                      # next version heading
                sec.append(lines[k])
            break
    md, heads = [], 0
    for l in sec:
        if not l.strip():
            continue
        if re.match(r"^\s*[-*•]\s+", l):
            md.append(re.sub(r"^\s*[-*•]\s+", "- ", l))
        elif re.match(r"^[A-Z][A-Za-z ]*:?\s*$", l):
            if heads:
                md.append("")
            heads += 1
            md.append(f"**{l.strip()}**")
        else:
            md.append(l)
    return "\n".join(md)


def branch_of(repo, tag, loader):
    """Version branch of a tag: the branch with this loader that contains the tag with the fewest commits after it."""
    best = None
    for b in git(repo, "branch", "-r", "--contains", tag).splitlines():
        b = b.strip()
        if "->" in b or not b.startswith("origin/") or not b.endswith(f"-{loader}"):
            continue
        after = int(git(repo, "rev-list", "--count", f"{tag}..{b}").strip())
        if best is None or after < best[0]:
            best = (after, b[len("origin/"):])
    return best[1] if best else ""


def main(argv):
    args, rtype, repo = [], "release", None
    it = iter(argv)
    for a in it:
        if a == "--type":
            rtype = next(it)
        elif a == "--repo-dir":
            repo = next(it)
        else:
            args.append(a)
    if len(args) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    mods_json, mod, version, outdir = args
    cfg = json.load(open(mods_json))[mod]
    tmp = None
    if not repo:
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        token = os.environ.get("GH_TOKEN", "")
        auth = f"x-access-token:{token}@" if token else ""
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                        f"https://{auth}github.com/{cfg['repo']}.git", repo], check=True)
    os.makedirs(outdir, exist_ok=True)
    tags = git(repo, "tag", "-l", f"v{version}-*").split()
    if not tags:
        print(f"no tags v{version}-* in {cfg['repo']}", file=sys.stderr)
        return 1
    for tag in tags:
        full = tag[1:]
        m = VERSION_RE.match(full)
        if not m:
            continue
        msg = git(repo, "cat-file", "-p", tag)
        mr = re.search(r"Modrinth: (\S+)", msg)
        cf = re.search(r"CurseForge: (\S+)", msg)
        branch = branch_of(repo, tag, m.group(2))
        props = git(repo, "show", f"{tag}:gradle.properties")
        mc = re.search(r"^\s*minecraft_version\s*=\s*(\S+)", props, re.M)
        tag_gv = re.search(r"Game versions: (.+)", msg)          # written by publish.yml since 2026-11-13
        gv = (tag_gv.group(1).split() if tag_gv else None) \
            or ((cfg.get("branches") or {}).get(branch) or {}).get("game_versions") \
            or [mc.group(1) if mc else m.group(3)]
        try:
            changelog = changelog_md(git(repo, "show", f"{tag}:changelog.txt"), full)
        except subprocess.CalledProcessError:
            changelog = ""
        data = {"mod": mod, "branch": branch, "version": full, "title": f"{m.group(1)} ({m.group(2)} {m.group(3)})",
                "type": rtype, "game_versions": [str(v) for v in gv], "modrinth_id": str(cfg.get("modrinth", "")),
                "curseforge_id": str(cfg.get("curseforge", "")), "modrinth_url": mr.group(1) if mr else "",
                "curseforge_url": cf.group(1) if cf else "", "repo": cfg["repo"], "changelog": changelog}
        with open(os.path.join(outdir, f"{tag}.json"), "w") as f:
            json.dump(data, f, indent=1)
        print(f"{tag:32} {branch:16} {','.join(data['game_versions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
