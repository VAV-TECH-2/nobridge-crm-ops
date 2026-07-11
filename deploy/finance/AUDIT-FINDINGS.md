# Audit findings — CRM crash-safety + Nobridge Finance correctness
Date: 2026-06-04 (audit) → 2026-06-05 (remediation). Verified against the LIVE migrated data on `finance-db`.
**Status: all in-scope issues fixed, deployed, and verified — see [RESOLUTION](#resolution--fixed--deployed--verified-2026-06-05) at the bottom.** CRM untouched throughout.

## PART A — CRM crash-safety: PASS ✅
The Finance integration cannot crash the CRM, with live evidence:
- **Caddy routing isolated + precise.** `caddy validate` = Valid. Every Twenty path (`/`, `/graphql`, `/metadata`, `/rest`, `/healthz`, `/auth/google`→302, `/assets`, `/fonts`, `/images`) reaches the CRM (200/302); none hit the gate. `/financexyz` → 200 (Twenty) proves the `/finance` matcher is not over-broad. `/finance` = 401 (no auth) / 200 (auth). Asset Cache-Control headers preserved.
- **Full isolation.** Separate Docker networks (`twenty_default` 4 containers / `nobridge-finance_default` 2); no port collision (3000 vs 3100; finance-db not host-exposed); separate DBs/volumes/creds.
- **Resources healthy.** 5.0 GiB RAM free; Finance app 39 MiB, finance-db 33 MiB (caps 1 g / 512 m). Disk 45 GB free. No OOM kills.
- **Reversible + isolated.** front-build/stock-compose/Caddyfile backups all present. CRM's `clienttype-sync` timer healthy; backup timer isolated. All 4 Twenty containers healthy; no server errors in 2h.
- Open item (browser-only): visually confirm CRM real-time/websocket updates — Caddy forwards WS automatically through the `handle{}` wrap; app healthy since restart, so expected fine.

## PART B — Finance correctness

### Verified CORRECT (recomputed from raw rows, matches API exactly)
- **Currency normalization works**: one-time costs USD $3,176.65 + IDR 25,347,160/16800 = **$4,685.41** = API `oneTimeCostsTotal`. ✓
- **One-time income IS counted** (52.5 M IDR/16800 = $3,125 = `incomeTotal`). ✓ (the auditor's "missing income" flag was a false positive)
- **Budget metrics exact**: budget 500 M IDR/16800 = $29,761.90; `budgetLeft` = 29,761.90 − 23,621.81 = **$6,140.10** ✓; `budgetRunway` = 6,140.10 / (2,411.41 − 520.83) = **3.25 mo** ✓; `requiredIncome` = **$1,890.58** ✓.
- **Amount-history has no gaps in the data**: every recurring cost's earliest AmountChange == its startDate.
- **All 15 GET endpoints return 200** (dashboard ×6 periods, analysis ×2, entries ×3, fixed-future-income, categories, settings/budget, settings/ai-key).
- Conclusion: the summation/expansion/normalization engine is sound. The issues below are specific **metric definitions**, not a broken engine.

### CONFIRMED ISSUES (severity · reproduction · location · real-vs-design)
1. **HIGH — Runway logic is inverted** (`lib/analytics/calculations.ts:277-279`).
   `runway = burn>income ? null : max(0, totalNet/burn)`. It returns **null (UI: "Income covers burn") exactly when you're UNsustainable**. Live: burn $2,411/mo vs income $521/mo → runway=null, but you're clearly burning capital. Currently **masked** because a budget is set (the UI shows the *correct* budgetRunway 3.25 mo instead) — but it's wrong and would show if the budget is cleared. Fix: mirror budgetRunway's `netBurn = burn − income` approach; null only when income ≥ burn.
2. **MEDIUM — Projections treat one-time income as recurring** (`:482, :504-515`). Forward projection uses a 6-month *trailing average* of income; your one-time $3,125 Jan client payment becomes a projected **$521/mo income forever** (analysis shows `projected_income: 521` for all 6 future months). Overstates future income — there is no recurring income.
3. **MEDIUM — One-time costs averaged over a fixed /6 window** (`:261, :533, :592`). Monthly burn / expense-breakdown divide trailing one-time costs by 6 regardless of how many months of activity exist → **understates burn for <6-month-old data**.
4. **MEDIUM — Partial current month vs full last month** in `momGrowth` & `costMoMChange` (`:287-332`). Recurring is counted as a full occurrence on day 1 of the month while one-time is month-to-date → MoM figures skew early each month (apples-to-oranges).
5. **MEDIUM (design) — Single current exchange rate for ALL history** (`:12-19, :187`). Every IDR amount (any date) is converted at today's 16,800. Your data is **IDR-heavy** (payroll = 71% of costs, all IDR), so historical USD totals move with today's rate — no point-in-time accuracy. Needs your decision (rate-history table vs accept).
6. **LOW — `nextPaymentDate` tick race** (`lib/recurring/advance.ts:61-88`). Concurrent dashboard loads (e.g., two browser tabs) can double-advance the *displayed* next-payment date (no row lock). Cosmetic — does not affect any financial total.
7. **LOW — Non-USD/IDR currencies treated as USD** (`:18`). `normalizeToUSD` only special-cases IDR; a third currency would be summed as USD. Only matters if one ever appears (classifier emits only USD/IDR).
8. **LOW (latent) — amount-history gap** (`:121-138`). If a recurring entry's earliest AmountChange postdates its startDate, the pre-first-rate period is uncounted. NOT present in current data, but possible for a future AI-created entry.

### NOT verified here (would require writes / a browser — recommend a manual pass or a follow-up with throwaway test data)
Write paths (create / update-amount / delete / stop), the AI classify flow (also needs an API key set), and modal/toggle UI (currency toggle, billing-schedule, amount-history). The GET side + a code read of the write handlers looked correct, but exercising them mutates data, which this read-only audit avoided.

### Definition questions needing your intent (for the fix plan)
- What should **runway** measure — months of *budget* left, months of *cash/capital* left (and where does that number come from), or both?
- Do you want **point-in-time exchange-rate accuracy** for historical IDR (store the rate per period), or is "value everything at today's rate" acceptable?
- Should **one-time income** (and one-time costs) be excluded from forward **projections**, or modeled differently?

## RESOLUTION — fixed + deployed + verified (2026-06-05)
Remediation shipped in two batches (Finance-only; CRM untouched throughout — re-verified healthy after each deploy). Decisions you gave: runway = months until **Budget** runs out; exchange rate = **store history** (point-in-time); projections = **recurring only**; #3 = **actual months of activity**; #4 = **keep month-to-date**.

| # | Severity | Status | Fix shipped |
|---|---|---|---|
| 1 | HIGH | ✅ FIXED (Batch 1, commit `cea22bb`) | Runway now mirrors budgetRunway: `netBurn = burn − income`; `runway = (budget set && netBurn>0 && budgetLeft>0) ? budgetLeft/netBurn : null`. Live = **3.25 mo** (was `null`). `app/page.tsx` no longer mislabels unsustainable as "Income covers burn". |
| 2 | MEDIUM | ✅ FIXED (Batch 1) | Projections use **current monthly recurring** income/expenses (+ fixed-future buckets in live mode), not a trailing average. Base projected_income now **0** (no phantom $521); live mode shows real signed future income (Jul $26,250, Aug $3,125). |
| 3 | MEDIUM | ✅ FIXED (Batch 2, commit `8b046c3`) | One-time figures averaged over **actual months of activity** (17 mo here): analysis breakdown + revenue concentration use `/monthsOfActivity`; trailing burn uses `min(6, monthsOfActivity)`. Verified: Software/SaaS $726→**$387**, Subscriptions $51→**$18**, Travel $7→**$2**, revenue Client $521→**$184**. |
| 4 | MEDIUM | ⏸️ KEPT BY DESIGN | Per your call, MoM stays month-to-date (current partial vs full last month). Unchanged. |
| 5 | MEDIUM | ✅ FIXED (Batch 2) | New `ExchangeRate` snapshot table + `rateOn(date)` (latest snapshot ≤ date, fallback earliest). Every IDR amount now converts at its period rate. `POST /api/settings/exchange-rate` records a snapshot on each refresh. Seeded one epoch snapshot @16,800 so current numbers are preserved exactly (regression-verified: all dashboards byte-identical pre/post). |
| 6 | LOW | ✅ FIXED (Batch 1) | `tickStaleNextPaymentDates` uses a guarded `updateMany({where:{id, nextPaymentDate}})` — a concurrent second tick is a no-op instead of double-advancing. |
| 7 | LOW | ⏸️ OUT OF SCOPE | Only USD/IDR exist (classifier emits only those). Documented; no code change. |
| 8 | LOW | ✅ FIXED (Batch 1) | `expandWithHistory` clamps the first amount-version segment start to `itemStartDate`, so a pre-first-rate gap can't go uncounted. |

**Regression evidence (Batch 2):** captured every GET endpoint before/after deploy (`metrics-pre.txt` / `metrics-post.txt` on the VM). Diff = exactly the four #3 deltas above + their recomputed percentages; everything else (all dashboard totals, runway, burn, projections, cash-flow, MoM, health score) byte-identical save one 4×10⁻¹² float-rounding artifact in `this_year` topExpenseCategories. **Point-in-time conversion confirmed; #3 averaging confirmed.**

**Post-deploy health:** CRM `healthz`/`/`/`/graphql` = 200, all 4 Twenty containers healthy, zero server errors. Finance gate 401→200; all 16 GET endpoints 200; no app/prisma errors. `ExchangeRate` table = 1 seed row (16,800 @ epoch).

### Still recommended (not blocking)
- **Write-path / UI manual pass** (#5 from "NOT verified"): create/update-amount/delete/stop, AI classify (needs the API key you can now set in Settings), and modal/toggle UI. Exercising these mutates data, so the audit left them to a manual check.
- When you click **Refresh rate** in Settings, it now also writes a dated snapshot — from then on, IDR amounts entered after that date value at the newer rate automatically.
