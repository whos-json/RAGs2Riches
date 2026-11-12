# Guided UX for non-technical users

Date: 2026-11-12. Status: build order steps 1 to 6 are implemented in `app/static/index.html` (home, 4-step form, live progress, answer page, past-deal check, overview, help, upload, feedback, print styles). Still open: usability testing with real salespeople (section 9) and a user-chosen visual theme.

Goal: a salesperson who has never seen the tool should get a trustworthy answer in under two minutes, without knowing what an LLM, a median or a "comparable" is, and should always know what to do next.

Source key: **[I]** = my recommendation. **[C]** = checked against this repo's code. Nothing here was taken from a fetched source.

---

## 1. Principles ("lead the user")

1. **One question per screen, one obvious next button.** Every screen has exactly one primary action, worded as a verb phrase ("See what to expect"), never "Submit" or "Run evaluation". **[I]**
2. **Start from the user's goal, not the system's parts.** The home screen asks "What would you like to do?" and offers three big choices. The workflow diagram, event log, provider and model fields are not on the main path. **[I]**
3. **Say where you are.** A visible "Step 2 of 4" strip, with a Back button that never loses typed data. **[I]**
4. **Never leave a blank.** Every empty, loading, error and "we don't know" state says what happened, why, and what to do. **[I]**
5. **Answer first, evidence second, internals last.** Results open with a one-sentence plain-English answer; supporting numbers sit below; the technical trace is behind "Show me how this was worked out". **[I]**
6. **Be honest about certainty.** Always show how many past deals the answer rests on, and use words plus numbers ("Low trust: based on 3 similar deals"). **[I]**
7. **Defaults and examples do the work.** Every optional field can be skipped with "I don't know"; each field has an example. **[I]**
8. **Forgiving.** Inline, polite validation; no data lost on error; "Start again" and "Use the same details" buttons. **[I]**

---

## 2. Information architecture

```
Home ("What would you like to do?")
 |-- 1. Check a new deal ........ guided 4-step flow -> Answer page
 |-- 2. Learn from a past deal .. pick a deal -> same Answer page (+ "what really happened")
 |-- 3. See the big picture ..... portfolio overview (needs new /api/portfolio, see section 7)
 `-- Help / Settings ............ data status, re-load data, writing assistant (advanced)
```

A persistent top bar has only: product name, "Home", "Help". No jargon in navigation. **[I]**

---

## 3. Flow 1: Check a new deal (4 steps)

Progress strip: `1 The client  ->  2 The space  ->  3 Anything else  ->  4 Check and go`

| Step | Heading (plain language) | Fields (label -> API field) | Helper text / example |
|---|---|---|---|
| 1 | "Who is this for?" | Company name -> `account_name`; Type of business -> `industry` (dropdown from `/api/meta`, first option "Not sure"); Building, if known -> `property_name` | "Example: Acme Pte Ltd. We use this only to avoid counting this client's own past deals." |
| 2 | "What do they need?" | Space needed (sq ft) -> `size_sqft`; Lease length -> `lease_term_months` with a Years/Months switch; Rent per sq ft per month, if known -> `gross_signing_rent_psf` | "Roughly is fine. A 3,000 sq ft office is about 280 sq m." Show the size band as the user types: "That is a **Small** deal (up to 5,000 sq ft)." |
| 3 | "Anything else we should know?" | Notes -> `notes`; Lead agent -> `agent_name` | "Optional. Phone numbers and emails are removed before anything leaves this computer." |
| 4 | "Check your details" | Read-only summary with an Edit link per section | Button: **See what to expect** |

Rules **[I]**:
- Only step 1's company name may block progress, and only if the user is saving the deal (the engine itself works with an empty deal). Everything else shows "Skip".
- Validation messages are friendly and specific: "Lease length looks very long (over 50 years). Did you mean 5 years?" Limits come from `DealInput` in `app/schemas.py`. **[C]**
- Never show "Pydantic", "422" or field IDs. Map server errors to sentences (section 6).

### Progress while working

Replace the workflow diagram on the main path with a four-line checklist that ticks off live, using the existing `node_start` and `node_end` events **[C]**:

| Engine node | Shown to the user as |
|---|---|
| `validate_input` | "Reading your details" |
| `sql_baseline` | "Finding deals like this one" |
| `analogue_retrieval` | "Picking the closest matches" |
| `llm_synthesis` | "Writing your summary" |
| `assemble_scorecard` | "Putting it together" |

Show a Cancel button throughout. Typical run time is short with the built-in writer; say "This usually takes a few seconds" and switch to "Still working, a local writing model can take up to a minute" after 8 seconds.

---

## 4. The Answer page

Order is fixed, top to bottom **[I]**:

1. **Headline** (one sentence, built from real fields, never from the LLM).
   Example: "Deals like this typically earn about **SGD 20,000** (most between 8,000 and 48,000). We found **12** similar deals."
2. **How much to trust this** badge: High, Medium or Low with the reason ("Based on 12 similar deals, 9 with a recorded fee"). Source: `estimates.confidence_level`, `baseline.n_comparables`, `baseline.n_with_fee`. **[C]**
3. **What to do next** (always present, 2 to 4 checklist items):
   - Effort: "Plan on a **light-touch** approach, about 6 hours" from `effort_allocation`. Add "This is a starting guide, not a calibrated figure." (the thresholds are uncalibrated placeholders in `workflow.py`). **[C]**
   - Resources from `recommended_resources`.
   - "Look at these 3 similar deals first" linking to the analogue cards.
   - If data is missing: "Add the missing details to sharpen this answer" linking back to the right step.
4. **Similar past deals** as cards, not a table: name, industry, size, fee, and a "How alike" word (Very / Fairly / Loosely, from `similarity`), with a "Why it matches" line (same industry, same size band, same building). Tap a card for details.
5. **Risks and how to handle them** from `closing_playbook.key_risks_and_mitigations`, split into "Watch out for" and "What to do about it" (the text is already "Risk: ... Mitigation: ..."). **[C]**
6. **What we couldn't tell you, and why** from `data_gaps` and `warnings`, each with a plain reason and a fix:
   | Engine message | Friendly version |
   |---|---|
   | No WON/LOST outcomes | "We can't say how likely you are to win. Your records only list deals that went ahead, not ones that were lost. Start recording lost deals to unlock this." |
   | Sales cycle unavailable | "We can't estimate how long this will take. Your records don't show when the conversation started." |
   | Fit score unavailable | "We can't score how good a fit this client is. Budget, authority, need and timing aren't recorded." |
   | Few comparables | "Only 3 similar deals were found, so treat the numbers as a rough guide." |
7. **Feedback strip:** "Was this useful? Yes / Not really" plus an optional "What actually happened?" (WON, LOST, DROPPED). Feeds the outcome capture that unlocks win probability later. **[I]**
8. Buttons: **Check another deal**, **Print one-page summary**, **Change details and re-check** (returns to step 4 with data kept).

Collapsed at the bottom: **Show me how this was worked out** (the existing workflow diagram, timeline, event log, step details and raw JSON). This keeps the developer view for technical users without cluttering the main path. **[I]**

### Words to avoid, and replacements

| Avoid | Say instead |
|---|---|
| Comparables / analogues | Similar past deals |
| Baseline | Typical results for similar deals |
| Median | Typical (the middle value) |
| p25 to p75 | "Most deals fall between ..." |
| LLM provider / model | Writing assistant (advanced) |
| Template narrative | Standard summary |
| Template fallback | "The writing assistant wasn't available, so a standard summary was used" |
| Ingest | Load data |
| Backtest | Try it on a past deal |
| Data gaps | What we couldn't tell you |
| Unavailable | Not enough information |
| Confidence level | How much to trust this |
| Win probability | Chance of winning (only shown when real outcomes exist) |
| SGD fee, gross | Fee, in Singapore dollars |

---

## 5. Flow 2: Learn from a past deal

Searchable list (type a client or property name) instead of a 560-item dropdown. On selection: "We'll check this deal as if it were new, leaving it out of its own comparison." The Answer page then adds a **What really happened** box showing the actual fee and how far the estimate was from it ("The estimate was 12% below the actual fee"). This builds trust in the tool for new users. Uses `actual_gross_fee_sgd` from `/api/deals`. **[C]**

---

## 6. Messages for states and errors

| State | Message |
|---|---|
| First visit, no data | "Welcome. To get started, load your leasing records. [Choose file] or [Use the sample file]." (Today the app silently starts with an empty database. **[C]**) |
| Data loading | "Loading your records... 563 deals so far." |
| Writing assistant offline | "The writing assistant isn't running, so we used the standard summary. Everything else is unaffected." |
| Server error | "Something went wrong on our side. Your details are saved. [Try again]" (never show exception names) |
| Too many requests (429) | "A few checks are already running. Please wait a moment and try again." |
| Validation (422) | Point to the exact field in plain words. |
| Nothing similar found | "We couldn't find similar deals. Try leaving out the building or choosing 'Not sure' for the business type." |

---

## 7. Backend support this design needs

| Need | Today | Work |
|---|---|---|
| Plain-language headline, ranges | `baseline` has median, p25, p75, counts **[C]** | Frontend only |
| "Why it matches" per analogue | Only a similarity score **[C]** | Return the shared features from `find_analogues` (S) |
| Portfolio overview | No endpoint | New `/api/portfolio` (see `README` roadmap) (M) |
| Outcome feedback | No storage | New table and endpoint (S) |
| First-run data loading | `/api/ingest` takes a server path only **[C]** | Add file upload to `INGEST_DIR` (S) |
| Printable summary | None | Print stylesheet (S) |

---

## 8. Accessibility and device rules

- Minimum 16px body text for the guided flow (the current UI uses 14px) and 44px touch targets. **[I]**
- Keep what already exists: skip link, labelled controls, `aria-live` regions, focus outlines, reduced-motion support. **[C]**
- Never rely on colour alone: every badge carries a word. Keep the contrast rules in `nostalgic-ui-research.md` section 4 and the `portal-era-addendum.md` palette.
- Visual style is a separate decision from this flow. Either existing direction (Windows Classic or Portal 2000) works with this structure, provided the primary action stays the single most prominent element on each screen.

---

## 9. How to test with non-technical people

Recruit 5 salespeople who have not seen the tool. Give no instructions beyond the task. Watch silently and note where they hesitate. **[I]**

| Task | Pass if |
|---|---|
| "A client wants 4,000 sq ft in Raffles Place for 3 years. Find out what fee to expect." | Reaches the Answer page unaided in under 2 minutes |
| "How sure is the tool about that number?" | Points to the trust badge and explains it in their own words |
| "Which past deal is most like this one?" | Finds the top similar-deal card |
| "What can't the tool tell you, and why?" | Finds that section and restates the reason |
| "Start again with a different size." | Uses Change details without retyping everything |

Measure time to first answer, wrong turns, and any word they ask the meaning of. Add each such word to the replacement table in section 4.

---

## 10. Build order

1. Plain-language Answer page and the 4-line progress checklist (frontend only, reuses the existing event stream).
2. Home screen and the 4-step form.
3. First-run data loading with file upload.
4. "Why it matches" on similar deals, feedback strip, print stylesheet.
5. Portfolio overview.
6. Move the current developer view behind "Show me how this was worked out".
