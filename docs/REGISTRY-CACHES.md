# External registry caches

Registry-derived identifiers are local, authoritative inputs to normalization.
Model-supplied identifiers are retained only when they equal a cache result.
The generated SQLite and JSON files live under `--data-dir` and should not be
committed.

## PubChem name to CAS

Download PubChem's public-domain Compound Extras synonym dump,
`CID-Synonym-filtered.gz`, from:

<https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/>

Build the cache without network access from ontologylab:

```bash
ontologylab registry import pubchem /path/to/CID-Synonym-filtered.gz \
  --data-dir ./data
```

The accepted format is PubChem's headerless UTF-8, two-column,
tab-separated format: one `CID<TAB>synonym` pair per line. Both gzip and plain
files are accepted by content. The importer checks this shape, numeric CIDs,
CAS check digits, conflicting CAS values, and ambiguous normalized synonyms;
it never infers columns from an unfamiliar file. The cache is built in a
temporary SQLite file and atomically replaces the prior cache only after a
successful import. Metadata records source name, SHA-256, UTC import date,
counts, format, source URL, and public-domain status.

## Mode-of-action starter data

A successful first PubChem import installs `registry-moa.json` under the same
data directory. Runtime resolution reads only that local file. Its metadata
marks it as a hand-seeded, dated, expandable starter set, initially containing:

| Active | CAS | Classification |
|---|---|---|
| boscalid | 188425-85-6 | FRAC 7 |
| azoxystrobin | 131860-33-8 | FRAC 11 |
| chlorantraniliprole | 500008-45-7 | IRAC 28 |
| glyphosate | 1071-83-6 | HRAC 9 |

The installer never replaces an existing local table, so users may extend it.
Each mapping requires `active`, a check-digit-valid `cas_number`, `scheme`
(`FRAC`, `IRAC`, or `HRAC`), and `code`. Normalization looks up MoA by the CAS
resolved from the PubChem cache, not by the proposal's bare name.

## EPPO

EPPO remains import-first as documented by CLI help:

```bash
ontologylab registry import eppo /path/to/export.csv --data-dir ./data
```
