# mod-release

Release automation for the Minecraft mods of [MC-Mods-Pete](https://github.com/MC-Mods-Pete).
One workflow builds a mod branch on GitHub Actions, uploads the jar to Modrinth and CurseForge
and sets an annotated tag `v<mod_version>` in the mod repo.

## Run

Usually via `mc-release` (pushes the branch to GitHub first, then starts the workflow).
By hand: **Actions → Publish → Run workflow**, or

```
gh workflow run publish.yml -R MC-Mods-Pete/mod-release \
  -f targets="UndeadNights@26.3-Fabric UndeadNights@26.3-NeoForge" -f type=release -f dry_run=true
```

- `targets`: `Mod@Branch`, several separated by spaces (one job each)
- `type`: `release`, `beta` or `alpha`
- `dry_run` (default `true`): build and check only, the jar is attached to the run as an artifact

## What a run checks

- `mod_version` in `gradle.properties` matches `x.y.z-Loader-mcVersion`, otherwise abort
- the tag `v<mod_version>` does not exist yet
- changelog: the section for this version from `changelog.txt`, otherwise the commits since the last tag
- JDK by Minecraft version: ≤1.16.5 → 8, 1.17–1.20.4 → 17, 1.20.5–1.21.x → 21, 26.x → 25
- game versions: `game_versions` from `mods.yml`, otherwise `minecraft_version`

## Setup

Environment **`release`** (Settings → Environments) with these secrets:

| Secret | Content |
|---|---|
| `MODRINTH_TOKEN` | Modrinth PAT, scope "Create versions" only |
| `CURSEFORGE_TOKEN` | CurseForge API token |
| `RELEASE_PAT` | Fine-grained GitHub token, owner MC-Mods-Pete, all mod repos, **Contents: read and write** (for the tags) |

A dry run works without secrets.

## Adding a mod

Add an entry to `mods.yml` (GitHub repo, Modrinth and CurseForge project IDs, optional `game_versions` per branch).
