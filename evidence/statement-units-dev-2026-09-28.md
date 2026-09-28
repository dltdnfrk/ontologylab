# Statement-units development coverage

**Development-only.** development-only, these papers were seen by earlier trials, not a precision or recall claim.

`rules_version = units-v1`; `cue_version = cues-v1`.

| PMCID | eligible sentences | units | explicit | unresolved | gold in units | gold in arm slots | null rows with cues |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PMC12632097 | 191 | 191 | 7 | 12 | 6/6 | 2/6 | 3/3 |
| PMC12546283 | 90 | 90 | 8 | 5 | 7/7 | 4/7 | 4/4 |
| PMC12563837 | 116 | 116 | 3 | 30 | 7/7 | 0/7 | 1/4 |
| PMC12713700 | 156 | 156 | 12 | 11 | 8/8 | 0/8 | 3/3 |
| PMC11298438 | 189 | 189 | 0 | 22 | 6/6 | 0/6 | 3/3 |
| totals | 742 | 742 | 30 | 80 | 34/34 | 6/34 | 14/17 |

Eligible sentences include uncued positives. Unresolved units are ambiguous containers, not guessed claims. Gold asserting spans are historical development rows, not a recall denominator.
