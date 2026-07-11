# Onboarding — Nobridge CRM workspace (Mac & Windows)

New teammate (or new machine)? This gets you from zero to a fully working
workspace on **macOS or Windows**. Expect ~30 minutes plus clone time.

> AI assistants: after setup, read `CLAUDE.md` → `README.md` in that order.
> This file is only the machine-setup recipe.

---

## 0. The three-repo layout (understand this first)

One folder, three git repos. The root repo deliberately **ignores** the two
nested ones — each syncs with its own GitHub remote:

| Path | GitHub repo | Remote name | What it is |
|---|---|---|---|
| `CRM/` (this folder) | `VAV-TECH-2/nobridge-crm-ops` (public) | `origin` | Ops workspace: deploy config, Python tooling, docs |
| `CRM/twenty/` | `VAV-TECH-2/CRM` (public) | **`vt2`** (canonical) | Twenty CRM frontend fork — prod branch `ui/icon-box-sizing` |
| `CRM/.crm-automations/dashboard/` | `VAV-TECH-2/nobridge-ops-dashboard` (private) | `origin` | node.nobridge.co ops dashboard source |

**Secrets are NOT in git** (the root repo is public). They arrive as a
password-protected zip from the team lead — step 4.

---

## 1. Install prerequisites

### Both OSes
- **Git** (Mac: `xcode-select --install` gives you git; Windows: [Git for Windows](https://gitforwindows.org/) — install with defaults, this includes **Git Bash**)
- **GitHub CLI** (`gh`) — then `gh auth login`
- **Python 3.12+** (Mac: `brew install python` or python.org; Windows: python.org installer, tick "Add to PATH") — then `pip install requests pyjwt openpyxl`
- **OpenSSH client** (built into both; Windows: Settings → Optional Features if missing)
- Optional, rarely needed: Node 24 + Yarn 4 (only for local frontend builds — CI normally builds), Docker Desktop (only for local image builds — normally never), `az` CLI (VM start/stop)

### Windows only
- **7-Zip** (recommended) — for extracting the password-protected secrets bundle from the script; File Explorer works too.
- Run once (the setup script also does this):
  ```
  git config --global core.longpaths true
  ```
  The `twenty/` repo has paths up to 238 chars; without this, clone/checkout can fail on Windows.

---

## 2. Clone the workspace

Put it at the same relative place on every machine:

- **Mac:** `~/Desktop/Nobridge Software/CRM`
- **Windows:** `%USERPROFILE%\Desktop\Nobridge Software\CRM`

```bash
# Mac / Git Bash — note the quotes, the folder name has a space
mkdir -p ~/Desktop/"Nobridge Software"
cd ~/Desktop/"Nobridge Software"
git clone https://github.com/VAV-TECH-2/nobridge-crm-ops.git CRM
cd CRM
```

## 3. Run the bootstrap script (clones the nested repos)

```bash
# Mac / Git Bash
bash scripts/setup.sh
```
```powershell
# Windows PowerShell alternative
powershell -File scripts\setup.ps1
```

This clones `twenty/` (~600 MB) and `.crm-automations/dashboard/` into place,
sets Windows git config, and verifies the layout. Re-running is safe.

> **Windows: expected warning during the twenty clone.** Git may warn about
> `packages/twenty-website/public/illustrations/pricing/Price` vs `price` —
> two upstream directories that differ only by letter case. Windows (and Mac)
> filesystems can only materialize one of them. **This is harmless and
> affects only a marketing-site asset. Never "fix", rename, or commit
> anything about it.**

## 4. Restore the secrets bundle

Get `nobridge-crm-secrets-<date>.zip` from the team lead (password arrives
separately). Then:

```bash
# Mac / Git Bash
bash scripts/restore-secrets.sh /path/to/nobridge-crm-secrets-<date>.zip
```
```powershell
# Windows
powershell -File scripts\restore-secrets.ps1 C:\path\to\nobridge-crm-secrets-<date>.zip
```

This places the live API token and credential-bearing scripts into
`.crm-sales-engine/`. They are gitignored — **git will never show them, and
that is correct. Do not add them.** Delete the zip afterwards.

You also need, outside this folder (ask the team lead):
- **VM SSH key** → `~/.ssh/id_rsa` (Mac) / `%USERPROFILE%\.ssh\id_rsa` (Windows). Without it, nothing that touches the VM works.
- Sales Engine source → `Desktop/Nobridge Software/sales-engine-vm` and Finance source → `Desktop/Nobridge Software/Nobridge Finance/nobridge-finance` (separate repos — see README §7).

## 5. Verify

```bash
ssh azureuser@20.189.126.94 "echo ok && sudo docker ps --format '{{.Names}}'"
gh repo view VAV-TECH-2/CRM
curl -I https://crm.nobridge.co && curl -I https://fin.nobridge.co && curl -I https://node.nobridge.co
```

All three URLs should answer, and SSH should list the twenty/finance containers.

---

## 6. Daily sync workflow (how we don't step on each other)

- **Start of every work session — pull all three repos:**
  ```bash
  git pull                                            # root, in CRM/
  git -C twenty pull vt2 ui/icon-box-sizing           # frontend
  git -C .crm-automations/dashboard pull              # dashboard
  ```
- **End of session — push what you changed** (root: `git push`; twenty: `git push vt2 ui/icon-box-sizing`; dashboard: `git push`).
- Frontend changes deploy via CI: push to `vt2` → Actions `ui-build.yaml` builds the bundle → scp to VM (README §3). **Coordinate in chat before deploying to prod.**
- Small team, trunk-based: commit straight to the main branches, pull before push. If you get a conflict you don't understand, stop and ask — several files here drive production.

## 7. Cross-OS rules (why your diff won't be full of noise)

- **Line endings are handled by `.gitattributes`** (everything LF except `*.ps1`). Do **not** set `core.autocrlf` — leave git config alone and the repo files win on both OSes.
- **All `.sh` scripts are bash. On Windows, run them from Git Bash**, never PowerShell/cmd.
- **Never pipe a script into SSH from PowerShell** — PowerShell adds a UTF-8 BOM that corrupts the first line on the server. Write the script to a file, `scp` it, then run it (README §9).
- **Paths in docs:** Mac docs say `~/Desktop/Nobridge Software/CRM`, Windows equivalent is `%USERPROFILE%\Desktop\Nobridge Software\CRM`. Old notes may say `Desktop\CRM` — that's the pre-2026-07 layout; map it to the current path.
- Filename hygiene for new files: no `: * ? " < > |`, no trailing dots/spaces, and never create two paths differing only by case (breaks every teammate's checkout).

## 8. Before you touch ANYTHING that mutates production

Read `README.md` §4 (Directory Guide) and §9 (gotchas). Highlights:
- Twenty is **pinned to v2.7.3 — never boot `latest`** (it migrates the DB forward and prod then crash-loops).
- Many `.crm-*` scripts write to the live CRM. LIVE vs HISTORICAL vs scratch is documented per directory.
- `deploy/vm-rollback.sh` **destroys all VM data**. Last resort only.
