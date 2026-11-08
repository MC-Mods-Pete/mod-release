#!/usr/bin/env python3
"""Posts one Discord message per mod for a Publish run (called by the announce job in publish.yml).

Input: a folder with one JSON file per published target (written by the publish jobs):
  {mod, branch, version, title, type, game_versions[], modrinth_id, curseforge_id, modrinth_url,
   curseforge_url, repo, changelog}
Environment: DISCORD_WEBHOOK (without it nothing is posted, only printed), DRY=1 prints the payload.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.request

COLORS = {"release": 0x2ECC71, "beta": 0xF1C40F, "alpha": 0xE74C3C}
UA = {"User-Agent": "MC-Mods-Pete/mod-release"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def vkey(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


def total_downloads(proj, cf_id):
    """(label, number): Modrinth + CurseForge downloads, CurseForge via api.cfwidget.com (public, no key).
    If only one side is readable, the label says which. None if nothing is readable."""
    sources, total = [], 0
    if isinstance(proj.get("downloads"), int):
        total += proj["downloads"]; sources.append("Modrinth")
    if cf_id:
        try:
            cf = get_json(f"https://api.cfwidget.com/{cf_id}")
            total += int(cf["downloads"]["total"]); sources.append("CurseForge")
        except Exception as e:
            print(f"! CurseForge downloads not readable: {e}")
    if not sources:
        return None
    return ("Total Downloads" if len(sources) == 2 else f"Downloads ({sources[0]})"), total


def label(item):
    """'Fabric 26.1.2' from the title '1.1.1 (Fabric 26.1.2)'."""
    m = re.search(r"\(([^)]*)\)\s*$", item["title"])
    return m.group(1) if m else item["branch"]


def mc_text(versions):
    vs = sorted(set(versions), key=vkey)
    return ", ".join(vs) if vs else "?"


def cut(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def file_line(i):
    """**Fabric 26.1.2** (26.1–26.3) · [CurseForge](…) · [Modrinth](…)"""
    lab = label(i)
    mc = lab.split()[-1]
    gv = sorted(set(i["game_versions"]), key=vkey)
    line = f"**{lab}**" + (f" ({gv[0]}–{gv[-1]})" if gv and gv != [mc] else "")
    for name, key in (("CurseForge", "curseforge_url"), ("Modrinth", "modrinth_url")):
        if i.get(key):
            line += f" · [{name}]({i[key]})"
    return line



def embed_for(mod, items):
    # sorted by Minecraft version, then loader: Fabric 1.20.1, Forge 1.20.1, NeoForge 1.21.1, Fabric 26.1.2, …
    items.sort(key=lambda i: (vkey(label(i).split()[-1]), label(i).split()[0]))
    first = items[0]
    short = first["title"].split(" (")[0]
    proj = {}
    try:
        proj = get_json(f"https://api.modrinth.com/v2/project/{first['modrinth_id']}")
    except Exception as e:  # the message still works without it
        print(f"! Modrinth project not readable: {e}")
    name = proj.get("title") or mod
    mr_project = f"https://modrinth.com/mod/{proj.get('slug') or first['modrinth_id']}"
    cf_project = next((i["curseforge_url"].split("/files/")[0] for i in items if i.get("curseforge_url")), "")

    # one line per file, in the message text (fields allow only 1024 characters, the text 4096)
    lines = [file_line(i) for i in items]
    while len(lines) > 1 and sum(len(x) + 1 for x in lines) > 3000:
        lines = lines[:-2] + [f"… and {len(items) - len(lines) + 2} more files"]
    files_text = "**Files**\n" + "\n".join(lines)
    info = ["━━━━━━━"]
    downloads = total_downloads(proj, first.get("curseforge_id"))
    if downloads:
        info.append(f"**{downloads[0]}**: {downloads[1]:,}")
    info.append(f"**Type**: {first['type'].upper()}")
    info_text = "\n".join(info)
    changelog = cut(first["changelog"].strip() or "No changelog.", 4000 - len(files_text) - len(info_text))
    fields = []
    links = []
    if cf_project:
        links.append(f"[CurseForge]({cf_project})")
    links.append(f"[Modrinth]({mr_project})")
    links.append(f"[Source Code](https://github.com/{first['repo']})")
    fields.append({"name": "Links", "value": " | ".join(links), "inline": False})

    files = "file" if len(items) == 1 else "files"
    embed = {
        "title": cut(f"New {name} {first['type'].upper()}: {short}", 256),
        "url": mr_project,
        # blank line before the separator, otherwise Markdown appends it to the last list item
        "description": f"{changelog}\n\n{info_text}\n\n{files_text}",
        "color": COLORS.get(first["type"], COLORS["release"]),
        "fields": fields,
        "footer": {"text": f"{len(items)} {files} · CurseForge and Modrinth"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if proj.get("icon_url"):
        embed["thumbnail"] = {"url": proj["icon_url"]}
    return embed


def main(folder):
    items = []
    for f in sorted(glob.glob(os.path.join(folder, "**", "*.json"), recursive=True)):
        items.append(json.load(open(f)))
    if not items:
        print("nothing was published, no message")
        return 0
    by_mod = {}
    for i in items:
        by_mod.setdefault(i["mod"], []).append(i)
    hook = os.environ.get("DISCORD_WEBHOOK", "")
    for mod, its in sorted(by_mod.items()):
        payload = {"embeds": [embed_for(mod, its)], "allowed_mentions": {"parse": []}}
        if os.environ.get("DRY") or not hook:
            if not hook:
                print("::notice::secret DISCORD_WEBHOOK not set, message only printed")
            print(json.dumps(payload, indent=2))
            continue
        req = urllib.request.Request(hook + ("&" if "?" in hook else "?") + "wait=true",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={**UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"posted {mod} ({len(its)} files): HTTP {r.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "announce"))
