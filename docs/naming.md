# Naming: general vs niche

Two separate names matter and they do different jobs.

| layer | name | job |
|---|---|---|
| repo / pip package | `ramet` | findable, memorable, doesn't box you in |
| concept inside the README | "many synthetic identities against one service" | tells a reader what it is in one line |

## Why `ramet`

A **ramet** is real botanical vocabulary: a single clonal colony can produce
many ramets — genetically identical units, each a separate individual.

That is precisely the mechanism this code implements. One seed produces one
identity, deterministically, and the library manages many of them side by
side with separate network routes and separate records. The name states the
pattern without stating an industry, which is what makes it survive a change
of target.

Two syllables, hard consonants, no `-kit` / `-hub` / `-forge` / `-ops`
suffix. Reads like a library, not a startup.

## The general/niche split

**General layer** — true for any target, no assumptions:

```
probe/schema.py    follow_missing, probe_fields, parse_har
homepage           "APIs without docs can be mapped from their own errors"
```

This is the part that would survive being extracted into its own package,
because nothing in it requires more than one identity. If someone only wants
schema discovery, `probe/schema.py` is self-contained.

**Niche layer** — only earns its keep with many identities:

```
core/identity.py   seed -> deterministic identity
core/netpool.py    one proxy per identity, IP budget
core/schedule.py   jitter, quiet hours
runner.py          loop identities -> submit
core/store.py      ip_history, per-identity event log
```

This is not a weakness to be hidden. It is the actual product. The README
says so in its second paragraph instead of claiming neutrality.

## Naming rules applied

- No industry word in the package name: `domain`, `registrar`, `kyc`,
  `account` are all out of the title.
- No evasion word: `stealth`, `ghost`, `phantom`, `anon` — those attract the
  wrong reader and date badly.
- No `-kit` / `-hub` / `-forge` / `-stack`. Those suffixes signal a repo that
  doesn't know what it is.
- The name describes the *mechanism* (many keyed instances), not the *market*.

## If you rename again

Do it once, do it fully:

```bash
grep -rc "ramet" --include="*.py" --include="*.md" --include="*.toml" .
python3 -m pytest          # 57 must pass
PYTHONPATH=packages python3 -m ramet.cli doctor
```

Anything less and you end up with a repo whose title says one thing and whose
imports say another.
