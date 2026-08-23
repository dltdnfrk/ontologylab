# Task 7 review-repair commit verifier

Date: 2026-08-23
Verifier: omo senpi-task `st_01a030a5`
Mode: evidence-only reverification; no test, stage, commit, or product/test edit.

## Verdict: CONFIRMED

The corrected frozen perimeter is:

`1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`

`task-7-review-repair-commit.md` records that value. `.omo/start-work/ledger.jsonl` event 396 supersedes the prior `1eac91b2b3a58bbd61a013c9b42fba9832b03621b76e53118a023cd543ec2ea7` correction, specifies `LC_ALL=C` path ordering, and records that the product commit is unchanged.

## Confirmed facts

| Check | Observed | Result |
|---|---|---|
| Commit | `362b0a679483139e51d8e37748674a867d6a9b2f` | match |
| Parent count and parent | one: `5a6378964bfc41fe2a679453a88235c548a59f4b` | match |
| Subject | `fix(extraction): preserve exact receipt identity` | match |
| Tree | `dce1386961684e924108ded625e56dab4031384d` | match |
| Changed path set | exact expected 21 paths | match |
| Committed blobs vs code/security final freezes | 21/21 SHA-256 match | match |
| `LC_ALL=C` sorted perimeter | `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b` | match |
| Index | `git diff --cached --quiet` exit 0 | empty |
| Owned worktree vs commit | `git diff --quiet <commit> -- <21 paths>` exit 0 | equal |
| Forbidden changed paths | metadata-only changed-path scan found 0 `.omo`, `docs`, `graphify-out`, `uv.lock`, or six denylist paths | absent |
| Six denylist paths in commit tree | metadata-only `git ls-tree` count 0; contents not read or hashed | absent |
| `origin/main` | remote and local-tracking ref `4ee5465b9727a2ca3c00e7eea0f3893e2301c148` | unchanged |
| Push/non-containment | target is not an ancestor of `origin/main` (exit 1); `origin/main` is an ancestor of target (exit 0); `origin/main...HEAD` is `0 51` | no push of target observed |

## Recomputed committed blob SHA-256

```
ontologylab/citation.py	6050d74cb87cffca1143056ae5341ab455eab7bd33bdf9cad2674ce717d4ed80
ontologylab/citation_bind.py	b045f72bfb8623c75668b81a2f936c6f0629bb1cd3753ec3bf5092782fcc9e8c
ontologylab/citation_store.py	da42b2da42205cb57c92ba87fb675cec007f97244cb081bec675b81d250e3ce4
ontologylab/citation_types.py	1b3209c242ef87e38cd0e8046ad11ac2060c3ad0b4391af9c434990bae60ae78
ontologylab/grounded_review.py	745004019c0dcbdf84a6cf86875f2d9338e1410b124cd048d1d74bbacf2e5ca0
ontologylab/grounded_review_members.py	187df60da17791aceda2a96b73e005aa08253e0cff9856bd0505ab74bd89566a
ontologylab/grounded_review_schema.py	9fc80b3b50e8391fd1dd4e9425ebf900710f5a9e91a59021c1076266902f30c5
ontologylab/grounded_review_store.py	bccd4f7d629b65af32dd36ebf748f0a313fd26f5ecdde441ce5cacc45053cd0d
ontologylab/h1_classify_cite.py	1ad78d2c47a5939f5db94c14dfba7cbf95e6c3005bf27734e2345da76f76d1c6
ontologylab/h1_existing.py	1c5f63d5aa71f3aff935a976352710a5cfe08d904ec50b6a990c513c2cea2e98
ontologylab/h1_existing_review.py	bd36a80dc55871c389fb1da8210c54a314c36acfaa4a0928536aca786820c98a
ontologylab/h1_finalize.py	b7f803229239d9e5df8674779b82d1f950b71e723146005cdf86244f85aca2ad
ontologylab/h1_materialize.py	f477b557f0896ec3f4ee3b15d2095dd9d8635b8446e78711e07a5c00491e73d0
ontologylab/h1_materialize_review.py	d23dec0f34a08b9e4a6f9c1c365b0e7428e3a002303a1b82d5b35656f2379cee
tests/step7_sec2_support.py	5463a6729acf94b051bfb724d043ce745db6fd1927c8dbd9244ef1f32f2a12de
tests/step7_valid_stale.py	10e71ed154ae6dee93263f244f7049dc8ae072cdece11e01482eaa8ffdc01d34
tests/test_step7_citation_bind.py	38f21a3ecd46f437993d735be80ef759d25945e91746bac65bc49295ddb8ffc2
tests/test_step7_review_repair.py	892fa15e8f810a78b795e09df19b206e4a74c58ffde47b6ac6f6b85f40f1a886
tests/test_step7_security_members.py	c8f7e4cc499bc36c6afeeaf1cc284332b8f09eb1e174c6171bf892650a89078c
tests/test_step7_security_repair_2.py	d64ee3a90c17f8ba22e48868113262d0b34082fa337798601c4288cd0df813af
tests/test_step7_tampered_non_approval.py	40cf516b905082769a3d9d40f154c7ece1ce172ccb85cb7270c7e596dc30a3dd
```

## Independent recomputation

For each of the 21 expected paths, the SHA-256 was computed from exact `git show 362b0a679483139e51d8e37748674a867d6a9b2f:<path>` bytes. The `path<TAB>sha256\n` records were sorted with `LC_ALL=C sort` and hashed:

- `shasum -a 256`: `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`
- independent Python `hashlib.sha256` over the identical 2050-byte, 21-line LF-terminated record stream: `1bd10421c5075045e550c2b4015270dd251409c4157622e87c79fc21dc47126b`
- records reconstructed in `git diff-tree --no-commit-id --name-only -r <commit>` order produce the same digest; byte-for-byte comparison with the `LC_ALL=C` stream passed.

### Prior verifier error

The prior `1eac...` result used bare `sort`, which used the workstation's locale collation rather than the required `LC_ALL=C` ordering. That ordering differs for the period/underscore path names in this perimeter. It was not the specified recipe.

No tests ran. This report is the only write in this correction; the Git index and tracked worktree remain unaltered.
