# yatra-agent — Evaluation Log

Record of every scored run: the extract step (reading the user's goal, sections 2-7) and the whole agent end to end (section 8). Updated after each fix round.
LLM: gpt-4o-mini, temperature 0, function calling. "Today" is fixed to Monday 2026-10-12 in every eval set.
Intervals are 95% Wilson confidence intervals.

**Status (2026-10-13, evening): code frozen.** Extraction was frozen first (section 7 lists its known limitations); the whole agent was then tested end to end on a dev set and once on a holdout set (section 8).

| Evaluation | Score | Unseen? |
|---|---|---|
| Extract, 5 sets | 50/57 (88%) | partly |
| End to end, dev set (first run) | 12/14 | yes |
| End to end, dev set (after 3 fixes) | 14/14 | no |
| **End to end, holdout (single run)** | **10/10 (95% CI 72-100%)** | **yes** |
| Unit tests (no network, LLM faked) | 241 passed | - |

## 1. Test sets

| Set | File | Cases | Status |
|---|---|---|---|
| Dev | eval/extract_cases.json | 15 | Used for fixing |
| Holdout 1 | eval/extract_holdout.json | 12 | Used for fixing (first run was before the dev fixes) |
| Holdout 2 | eval/extract_holdout2.json | 10 | First run was unseen; then used for fixing |
| Date holdout (final) | eval/date_holdout_final.json | 10 | Hard date phrasings only; first run was unseen |
| Budget set | eval/budget_cases.json | 10 | All five budget directions; first run was unseen |
| End-to-end dev | eval/e2e_cases.json | 14 | Whole agent, live APIs; used for fixing |
| End-to-end holdout | eval/e2e_holdout.json | 10 | Whole agent, live APIs; run once, never fixed against |
| Unit tests | tests/ | 241 | Pure code, no network (the LLM is faked where needed) |

## 2. Final scores at freeze — 2026-10-13

### Whole case correct (every expected field right)

| Set | Passed | Accuracy | 95% CI | Failed |
|---|---|---|---|---|
| Dev | 14/15 | 93% | 70–99% | EX-10 |
| Holdout 1 | 10/12 | 83% | 55–95% | HO-07, HO-12 |
| Holdout 2 | 9/10 | 90% | 60–98% | H2-01 |
| Date holdout | 8/10 | 80% | 49–94% | DF-02, DF-07 |
| Budget set | 9/10 | 90% | 60–98% | B-09 |
| **All sets** | **50/57** | **88%** | **77–94%** | |

### By field (all five sets, final run)

| Field group | Correct checks | Accuracy | 95% CI |
|---|---|---|---|
| destination | 46/46 | 100% | 92–100% |
| must_visit | 12/12 | 100% | 76–100% |
| place_types | 27/27 | 100% | 88–100% |
| interests | 23/23 | 100% | 86–100% |
| budget numbers (amount, max, per person, per day) | 73/74 | 99% | 93–100% |
| dates (start, end, days, final dates) | 77/79 | 97% | 91–99% |
| travellers | 18/19 | 95% | 75–99% |
| budget_direction | 27/30 | 90% | 74–97% |

### Progress of whole-case scores over the day

| Round | Dev | Holdout 1 | Holdout 2 | Date holdout | Budget set |
|---|---|---|---|---|---|
| Before the interests fix | 10/15 | 8/12 | 7/10 | 9/10 | — |
| After the preferences fix | 12/15 | 9/12 | 6/10 | 9/10 | — |
| After budget_hint + firmness | 12/15 | 12/12 | 8/10 | 8/10 | — |
| **Final (budget_direction schema)** | **14/15** | **10/12** | **9/10** | **8/10** | **9/10 (unseen)** |

## 3. Budget round — 2026-10-13

Problem: a single yes/no "is it a limit" could not tell the planner which way a figure limits the cost, and the LLM skipped short words like "under".

Design (schema locked before coding):

- The LLM copies **budget_phrase** (the figure with the words attached to it), then records **budget_amount**, **budget_amount_max** (range only), **budget_is_per_person**, **budget_is_per_day**, and **budget_direction**: at_most / about / at_least / range / not_stated.
- The prompt teaches one test instead of word lists: "what would the user say about a plan that costs a little more, and one that costs a little less?"
- Code checks the evidence and the structure (phrase present and in the goal, contains the figure; a range has two numbers; max only for a range) and retries once.
- Code turns the direction into rupee bounds for the whole group and trip: **total_budget** (target), **budget_ceiling**, **budget_floor**. "about" may go 10% over (config). A bare figure is treated as a maximum, with a note. The planner decides what to do with a plan above or below the bounds.

| Direction | Correct | Example phrases |
|---|---|---|
| at_most | 12/12 | under, max, no more than, can't go over, up to, tops |
| at_least | 2/2 | minimum, "more than 40k is fine" |
| range | 2/2 | between 10 and 14 thousand, 12-15k per head |
| not_stated | all | budget 20000, Rs 9000 total |
| about | 3/6 | about, around, roughly, approximately, somewhere near |

Steps in this round: budget_hint (firmness) → "under" failed (6/9 ceilings) → budget_phrase made "under" work (9/9) but broke estimates (1/4) → budget_direction schema: 90% overall, 9/10 on the unseen budget set.

## 4. Preferences round — 2026-10-13

Three levels of importance: must_visit (always included) → place_types (best example of each kind) → interests (fill the rest). Each place_type carries its own interests, so a kind of place can never be recorded without its purpose.

| Field | Before | After |
|---|---|---|
| interests | 12/23 | 22/23 → 23/23 at freeze |
| must_visit | — | 11/12 → 12/12 at freeze |
| place_types | — | 24/26 → 27/27 at freeze |

Root cause found by experiment: with json_schema mode the LLM returned empty interests; function calling plus the structural PlaceType change fixed it. Unknown interest words are dropped by a validator instead of failing the whole extraction.

## 5. Dates round — 2026-10-13

Design: the LLM only describes each date (a DateRef: exact phrase + kind); code checks the phrase against the goal and does all calendar arithmetic. One LLM retry when a date disagrees with its own phrase; anything still wrong is dropped with a note and the documented defaults apply.

| Set | Date cases | Correct | Accuracy | 95% CI | Unseen? |
|---|---|---|---|---|---|
| Holdout 2, first run | 9 | 9 | 100% | 70–100% | **Yes** |
| Date holdout, first run | 10 | 6 strict / 7 trip dates | 60% / 70% | 31–83% | **Yes** |
| Date holdout, after fixes | 10 | 9 | 90% | 60–98% | No |

Before this round (old design, LLM wrote calendar dates): weekday and weekend dates were off by about two days in every relative-date case.

| Case | Phrase | Root cause | Fix |
|---|---|---|---|
| DF-02 | "weekend after next" | DateRef cannot express two weeks ahead | Not fixed: a warning note is added (no silent error) |
| DF-07 | "first week of November" | LLM gave a month without a day | Code drops it with a note; final dates follow the defaults |
| DF-09 | "5/11" | Checker only knew month names | Numeric DD/MM accepted (Indian format, documented) |
| DF-10 | "returning next Sunday" | End weekday ignored "next" | Same "next week" rule for start and end |

## 6. Robustness features of the extract step

- Evidence first: dates and budget are copied as the user's own words; code verifies them against the goal (no word lists).
- Self-check with one LLM retry (trace event llm_self_check_retry); a parse failure is retried once (llm_parse_retry); after a second failure the run stops cleanly with status gave_up and an error record.
- Every assumption is written as a note in the report (defaults, dropped dates, how a bare budget was read).

## 7. Known limitations (for the write-up)

- **"about" budgets are unstable (3/6).** When missed, the figure is treated as a maximum with a note — the safe side (the plan never overspends). A sharper prompt line is designed but not applied.
- **A head count inside the budget phrase** ("max 60000 for two") is not taken as the group size (EX-10); 1 traveller is assumed with a note. The prompt also asks the LLM both to "count people" and to "never count"; with more time, people would be listed by the LLM and counted in code.
- **"for the two of us"** next to a figure was once read as per person (HO-07).
- "weekend after next" is read as next weekend, with a warning.
- A vague period ("first week of November") is dropped; the trip starts tomorrow, with a note.
- Numeric dates are read as DD/MM.
- Origin city, pace, things to avoid and group type (kids, elderly) are not extracted.
- Samples are small (10–15 per set), so intervals are wide; sets used for fixing are no longer unseen.

## 8. End-to-end round — 2026-10-13

Runner: `python eval/run_e2e.py` (dev) and `python eval/run_e2e.py --holdout` (once). Each case runs the full graph on live APIs (Open-Meteo, Wikivoyage, Wikipedia, OpenStreetMap, gpt-4o-mini) and is checked twice:

- **its own expectation**: status (done / needs_city / gave_up), base city or state, budget ceiling, replanning or not, notes that must appear, handled errors from an injected failure;
- **general rules every run must follow**: every error carries `handled_by`; a report is written; a stopped run says why; the plan ends with build_itinerary -> find_stays_and_food -> estimate_costs -> check_budget; the right number of days; every day has a timeline with no overlapping items; sightseeing ends by 19:00 or a note says the day is long; no place twice; a budget outside the limit is explained.

### Cases (dev set, 14)

Normal city, a state, a must-visit place far away, a tight budget, an impossible budget, no budget, an ambiguous goal, a city outside India, a Hinglish goal, dates beyond the 16-day forecast, and one induced failure each for weather, Wikipedia search, OpenStreetMap and geocoding (`--inject-failure`).

### Dev results and the fixes they led to

| Run | Score | What failed |
|---|---|---|
| First run (unseen) | 12/14 | E-08 Paris planned in "Pariswani" (J&K); E-10 no forecast note. Hidden in passes: base city "Mysore Airport"; OpenStreetMap failed in 4 of 10 live runs |
| After fixes | 14/14 | - |

| # | Problem | Root cause (with the evidence) | Fix |
|---|---|---|---|
| 1 | OpenStreetMap failed without injection | `python -m tools.osm` (new diagnostic): even a 1-search query failed on the three servers in use (HTTP 504 / 30 s timeouts), so it was server load, not our query; only maps.mail.ru answered | Four Overpass servers in turn; a quick refusal (429/5xx) is asked once more after 3 s, a timeout is not; client timeout above the server's own limit |
| 2 | Paris -> Pariswani, Mysore -> Mysore Airport | `python -m tools.geocode Paris Mysore Mysuru`: the geocoder matches the start of a name and returns non-towns; we accepted any result | Only towns (GeoNames PPL*) with exactly the searched name; the travel guide's title is tried next (Mysore -> Mysuru); if none, the guide's own coordinates decide: near an Indian match -> used with a note, far from all -> "does not seem to be in India" (needs_city) |
| 3 | No note for dates beyond the forecast | The planner correctly drops the weather step, but the note was only written by that step | The executor adds the note when the trip starts beyond the 16-day forecast |

### Holdout (single run, after the dev fixes)

**10/10.** New cities and goals (Hyderabad, Kerala, Pune + Golden Temple, Shimla on 12,000 for 3, Rishikesh with no budget, "you choose", Bangkok, a Hinglish Kolkata goal, Bhopal with the weather API down, Madurai with Wikipedia search down). No OpenStreetMap failures in these live runs. With 10 cases the 95% interval is 72-100%, so this shows the paths work, not that the agent never fails.

### Found by reading the sample runs, not by the checks

The checks test structure (status, notes, handling, timelines); they do not judge whether a place is the right one. Reading the samples after the holdout found a bug the checks could not see:

| Sample | Must visit | Was planned as | Root cause | Fix |
|---|---|---|---|---|
| Udaipur | City Palace | the city page "Udaipur" | `locate_place` took the first search hit; "City Palace, Udaipur" has only secondary coordinates (confirmed with the API), so it was dropped | Search near the city first, then "name city", then "name"; a page counts only if its title carries the name's distinctive words (not fort / palace / temple ...), never the city's own page; secondary coordinates are requested when locating |
| Jaipur | Amber Fort | the town "Amber, India" | same: first hit taken; "Amber Fort" was third | the most of the name's words wins |

The holdout score above was measured before this fix; E-03 and E-04 were re-run after it and still pass.

### Known limitations of the whole agent (for the write-up)

- **Public OpenStreetMap servers are often busy** in the Indian evening (European afternoon). The agent then plans without naming stays and meals and says so; production would need its own Overpass server or a paid places API.
- **The base city of a state ignores the interests**: Kerala + "backwaters" was based in Thiruvananthapuram (most viewed) rather than Alappuzha or Kochi.
- **"done" with no places**: if every Wikipedia search fails, the plan has free days and honest notes but the status is still done.
- **Locate edge cases not handled**: a namesake in another city found by the name-only search ("City Palace, Jaipur" if Udaipur's page were missing) would be reported as far away; a misspelt name falls back to the first result near the city.
- **OpenStreetMap data quality**: no prices or ratings; a student hostel tagged as a hostel can be chosen at the budget level.
- **A hotel change for one night** follows the rule "stay near the next day's places", which can mean moving the bags on a short trip.
- Times are assumptions (visit length by kind of place, city speed, meal times), listed in every report.

