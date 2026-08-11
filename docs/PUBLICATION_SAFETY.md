# Public-read publication safety

> `ACCEPTED` for repository governance: the user explicitly authorized changing
> this GitHub repository from private to public-read. This authority covers
> visibility only; it does not select a license, publish a package, create a
> release, or authorize disclosure of private operational source material.

## Pre-publication observations

`PROPOSED`: these observations select the publication design but are not the
final fixed-commit publication receipt. They must be repeated after the scoped
commits are pushed to the still-private source repository.

- `detect-secrets 1.5.0` found only commit/tree digests and a phrase describing
  secret isolation; manual review found no credential value.
- `gitleaks 8.30.1` scanned the reachable 36-commit history and current
  worktree with `.gitleaks.toml`; both reported zero findings. The allowlist is
  limited to the synthetic M4B `crash_point=` parameter under `scripts/` and
  `tests/`.
- Every commit reachable from `main` uses a GitHub
  `users.noreply.github.com` author address. Two sealed M3 environment
  descriptors contain a personal-name macOS site-packages path. They contain
  no credential or operational host, but publishing main history discloses
  that user-name path. `ACCEPTED` for this publication profile: retain the
  frozen measurement descriptor and state this disclosure instead of claiming
  that main contains no user path.
- A non-main research branch has distinct commits containing private
  operational references and non-noreply corporate author metadata. Its six
  Actions runs and recent repository events also expose branch names and head
  SHAs to repository viewers.

The scans reduce risk; they do not prove that no sensitive inference is
possible.

## Main-only publication isolation

`ACCEPTED` for repository governance: do not change the existing repository
directly from private to public. GitHub documents that a visibility change can
expose Actions history and repository activity, while deleting a branch does
not guarantee immediate removal of cached or SHA-addressable sensitive
history. Preserve the existing repository under the private archive name
`agent-coding-paradigm-private-archive`.

Create an empty private staging repository, clone only local `main` with
`--single-branch`, and push exactly
`refs/heads/main:refs/heads/main`. Do not use `--all`, `--mirror`, `--tags`, or
an include-all-branches import. Before visibility changes, require:

- exactly one remote head named `main` and zero tags;
- every commit unique to the private research branch absent from the staging
  repository API and isolated clone;
- zero gitleaks findings for the staging worktree and reachable history;
- both repository workflows successful for the fixed candidate SHA;
- `licenseInfo = null` and no GitHub-generated initialization commit.

Only after those gates pass may staging change to public and take the canonical
name `gj3447/agent-coding-paradigm`. Keep separate local remotes named `origin`
for the public repository and `private-archive` for the preserved private
repository. GitHub's relevant procedures are the
[visibility guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility),
[repository rename guide](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository),
and [existing-code push guide](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

## Public-use boundary

No license has been selected. Public visibility permits GitHub reading and
forking under GitHub's platform behavior, but this repository grants no
additional reuse permission. External source entries are reference-only and
retain their own licenses. Private operational payloads are absent from the
synthetic consumer corpus rather than redacted in place.
