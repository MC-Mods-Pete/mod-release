#!/usr/bin/env python3
"""Compares the Minecraft versions a jar declares with the game versions that will be published.

  check-game-versions.py JAR "VERSION VERSION ..."      (versions separated by spaces or newlines)

Reads the Minecraft dependency from the jar (fabric.mod.json "depends.minecraft", or the "minecraft"
dependency in META-INF/mods.toml / META-INF/neoforge.mods.toml), expands it against the list of
Minecraft releases from Mojang and compares:

  error    a published version is NOT allowed by the jar (players would get a jar that does not load)
  error    the jar allows a version that is not published, inside a closed range (e.g. 1.20.3 for
           ">=1.20.2 <=1.20.6"): add it to game_versions in mods.yml or narrow the range in the jar
  warning  the range is open to the top (">=26.1", "[26.3,)") and newer releases exist that are not
           published: deliberate if they are untested, otherwise add them to mods.yml

Exit 1 on errors. Without network or metadata it only warns (exit 0).
Environment: MC_VERSIONS_MANIFEST (URL or file, default Mojang's version_manifest_v2.json).
"""
import json
import os
import re
import sys
import tomllib
import urllib.request
import zipfile

MANIFEST = os.environ.get("MC_VERSIONS_MANIFEST",
                          "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")


def note(kind, msg):
    print(f"::{kind}::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"{kind}: {msg}")


def vt(v):
    """'1.20.2' -> (1, 20, 2); missing parts count as 0, so 1.21 == 1.21.0."""
    parts = [int(x) for x in re.findall(r"\d+", v.split("-")[0].split("+")[0])]
    return tuple(parts + [0] * (4 - len(parts)))


def releases():
    if os.path.isfile(MANIFEST):
        data = json.load(open(MANIFEST))
    else:
        req = urllib.request.Request(MANIFEST, headers={"User-Agent": "MC-Mods-Pete/mod-release"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    return [v["id"] for v in data["versions"] if v.get("type") == "release"]


# ---------------------------------------------------------------- Fabric (fabric.mod.json)

def fabric_term(term, v):
    term = term.strip()
    if term in ("", "*"):
        return True
    m = re.match(r"^(>=|<=|>|<|=|~|\^)?\s*(.+)$", term)
    op, ver = m.group(1) or "", m.group(2)
    if re.search(r"(^|\.)[xX*]($|\.)", ver):            # 1.21.x
        prefix = [p for p in ver.split(".") if p not in ("x", "X", "*")]
        return list(vt(v)[:len(prefix)]) == [int(p) for p in prefix]
    a, b = vt(v), vt(ver)
    if op == ">=": return a >= b
    if op == "<=": return a <= b
    if op == ">": return a > b
    if op == "<": return a < b
    if op == "~":                                        # ~1.21 = >=1.21 <1.22, ~1.21.1 = >=1.21.1 <1.22
        n = len(re.findall(r"\d+", ver))
        upper = list(b[:max(n - 1, 1)]); upper[-1] += 1
        return a >= b and a < tuple(upper + [0] * (4 - len(upper)))
    if op == "^":
        return a >= b and a[0] == b[0]
    return a == b


def fabric_allows(dep, v):
    alts = dep if isinstance(dep, list) else [dep]       # list = OR, spaces inside = AND
    return any(all(fabric_term(t, v) for t in alt.split()) for alt in alts)


def fabric_open(dep):
    alts = dep if isinstance(dep, list) else [dep]
    return any(not re.search(r"(<|~|\^|^\d[\d.]*$|\.x$)", alt.strip()) for alt in alts)


# ---------------------------------------------------------------- Forge/NeoForge (mods.toml, Maven ranges)

def maven_ranges(rng):
    return re.findall(r"[\[(][^\])]*[\])]", rng) or [rng.strip()]


def maven_allows(rng, v):
    for r in maven_ranges(rng):
        if not r or r[0] not in "[(":
            if vt(v) == vt(r):                           # bare version: exactly this one
                return True
            continue
        lo, _, hi = r[1:-1].partition(",")
        lo, hi = lo.strip(), hi.strip()
        if "," not in r:                                 # [1.20.1] = exactly
            if vt(v) == vt(lo):
                return True
            continue
        ok = True
        if lo:
            ok &= vt(v) >= vt(lo) if r[0] == "[" else vt(v) > vt(lo)
        if hi:
            ok &= vt(v) <= vt(hi) if r[-1] == "]" else vt(v) < vt(hi)
        if ok:
            return True
    return False


def maven_open(rng):
    return any(r[0] in "[(" and r[1:-1].partition(",")[2].strip() == "" and "," in r for r in maven_ranges(rng))


# ---------------------------------------------------------------- jar

def jar_requirement(jar):
    """('fabric', dep) or ('maven', range) or (None, None)."""
    with zipfile.ZipFile(jar) as z:
        names = set(z.namelist())
        if "fabric.mod.json" in names:
            data = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
            dep = (data.get("depends") or {}).get("minecraft")
            return ("fabric", dep) if dep else (None, None)
        for name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
            if name in names:
                data = tomllib.loads(z.read(name).decode("utf-8", "replace"))
                for deps in (data.get("dependencies") or {}).values():
                    for d in deps if isinstance(deps, list) else []:
                        if d.get("modId") == "minecraft" and d.get("versionRange"):
                            return "maven", d["versionRange"]
    return None, None


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    jar, published = argv[0], sorted(set(argv[1].split()), key=vt)
    kind, req = jar_requirement(jar)
    if not kind:
        note("warning", f"no Minecraft dependency found in {os.path.basename(jar)}, game versions not checked")
        return 0
    if "${" in json.dumps(req):
        note("error", f"unresolved placeholder in the jar's Minecraft dependency: {req}")
        return 1
    try:
        known = releases()
    except Exception as e:
        note("warning", f"Minecraft version list not reachable ({e}), game versions not checked")
        return 0
    allows = (lambda v: fabric_allows(req, v)) if kind == "fabric" else (lambda v: maven_allows(req, v))
    is_open = fabric_open(req) if kind == "fabric" else maven_open(req)
    in_jar = sorted((v for v in known if allows(v)), key=vt)
    print(f"jar requires minecraft {json.dumps(req) if kind == 'fabric' else req}")
    print(f"  allows:    {', '.join(in_jar) or '-'}")
    print(f"  published: {', '.join(published) or '-'}")
    errors = 0
    wrong = [v for v in published if not allows(v)]
    if wrong:
        note("error", f"published but not allowed by the jar: {', '.join(wrong)}. "
                      f"Remove them from game_versions in mods.yml or widen the range in the jar.")
        errors += 1
    missing = [v for v in in_jar if v not in published]
    top = max((vt(v) for v in published), default=(0,))
    above = [v for v in missing if is_open and vt(v) > top]
    inside = [v for v in missing if v not in above]
    if inside:
        note("error", f"allowed by the jar but not published: {', '.join(inside)}. "
                      f"Add them to game_versions in mods.yml or narrow the range in the jar.")
        errors += 1
    if above:
        note("warning", f"the jar's range is open to the top and also allows {', '.join(above)}, "
                        f"which will not be published. Add them to mods.yml if they are tested.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
