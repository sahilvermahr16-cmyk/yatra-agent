# How yatra-agent works

The details behind the [README](../README.md): architecture, tools, planning and self-correction, failures, output, evaluation, assumptions and limitations.

---

## 1. Architecture

![Architecture and control flow](architecture.png)

A **LangGraph** state machine (`graph.py`) with one shared state (`state.py`). Every data shape is a Pydantic model (`schemas.py`). The guiding split: **the LLM decides only what needs language understanding or judgment; code does all lookups, arithmetic, dates and scheduling**, so every number in the plan can be tested.

| # | Node | LLM or code | What it does |
|---|---|---|---|
| 1 | `extract` | LLM | Goal → `TripRequest`: destination, dates, travellers, budget words, must-visit places, kinds of place, interests. The LLM copies the user's own words for dates and budget; code checks them against the goal and retries once |
| 2 | `normalize` | code | Calendar dates, nights, travellers, budget ceiling / floor in rupees for the whole group; every default becomes a note |
| 3 | `planner` | LLM | An ordered tool plan with a reason per step. Code checks it (one step per wish, the right order, weather only inside the forecast range); one retry with the problems listed; else a default plan |
| 4 | `executor` | code | Runs the data steps in order through one handler per tool; a failure or an unmet wish becomes a note, never a crash |
| 5a | `itinerary` | code | Picks places by priority (must-visit → kinds of place → interests → popular), groups nearby ones into days, puts indoor places on rainy days |
| 5b | `stays` | code | One OpenStreetMap query: a hotel each night near the next day's places, breakfast, lunch, a 1-hour rest, dinner or street food; times every day; a place that would end after 19:00 moves to "if you have more time" |
| 6 | `budget_check` | code | Prices the plan (assumed price table) and compares it with the ceiling / floor |
| 7 | `replanner` | LLM + code | Code lists only the changes that are allowed and what each saves; the LLM chooses; code applies them, re-picks the hotel, meals and timeline from the saved OpenStreetMap data, and sends the plan back to `budget_check` (at most 3 rounds) |
| 8 | `reporter` | code | Builds the `TripReport` (JSON) and the Markdown report |

Routes: no destination → straight to the reporter (`needs_city`); the city cannot be placed → reporter (`needs_city` or `gave_up`); outside the budget (over the ceiling or under the floor) with a change still possible → replanner → budget_check again; within the budget, nothing left to change or 3 rounds used → reporter.

---

## 2. Tools

All live, free and keyless. Every call goes through one wrapper (`tools/http.py`): a timeout, retries on timeouts / 5xx / 429 (not on other 4xx), a trace event, and failure injection. `tools/calls.py` turns each failure into an error record that says how the agent carried on (`handled_by`).

| Tool | Service | Used for |
|---|---|---|
| Geocoding | Open-Meteo geocoding API | Place name → coordinates. Only towns in India with exactly that name; the travel guide's coordinates break ties ("Udaipur" in Rajasthan, not Tripura) |
| Weather | Open-Meteo forecast API | Daily forecast, up to 16 days ahead; rainy days get indoor places |
| Travel guide | Wikivoyage API + Wikimedia page views | Is it a city or a state? A state's cities, and the most-read one as the base city |
| Places | Wikipedia API (search near the city, page views) | Must-visit places, places of a kind ("stepwells"), and the best-known sights |
| Stays and food | OpenStreetMap Overpass API (4 public servers, tried in turn) | Hotels, guest houses, hostels, cafes, restaurants, food stalls near the plan |
| Cost calculator | local code, `config.PRICE_TABLE` | Hotel, food, local travel and tickets at budget / mid / luxury level (simulated: see [§7](#7-assumptions-mock-data-and-simulated-tools)) |

Diagnostics that need no LLM: `python -m tools.geocode Jaipur Mysore`, `python -m tools.destination Rajasthan`, `python -m tools.osm` (compares the Overpass servers).

---

## 3. Planning and self-correction

- **The plan comes first.** The planner sees the request and the tool descriptions and returns an ordered list of steps, each with the tool, its query, the wish it serves and why. It is printed before any tool runs.
- **Code checks the plan** (`plan_checks.py`): every must-visit place has a lookup, every wish has a search, the weather step appears only if the dates are within the forecast range, and the plan ends with build_itinerary → find_stays_and_food → estimate_costs → check_budget. If anything is wrong, the LLM gets the list of problems and one retry; if it is still wrong, a default plan built in code is used (`planner_fallback` in the trace).
- **The extractor checks itself** the same way: dates and budget must be the user's own words and must agree with each other (`llm_self_check_retry`); output that does not fit the schema is retried once (`llm_parse_retry`).
- **Unexpected results are handled, not only errors**: a search with no results becomes an honest note and the time goes to popular sights; a must-visit place more than 60 km away is not planned and the note says where it is ("Taj Mahal is in Agra; plan a separate trip"); a city name that matches only a village or an airport is not taken.
- **Budget loop**: outside the budget → code lists the changes that would move the cost the right way, each with its exact effect (a lower or higher hotel or food level, public transport or a cab, a hotel outside the centre, dropping a paid sight — popular ones first, never a must-visit place — and never a level the user named) → the LLM chooses → code applies them and prices the plan again. If nothing brings it within, the report says how far off it is and what was tried.

Every one of these shows up as a line in the console (yellow "self-correction") and as an event in the JSON trace.

---

## 4. Failures: induced and real

| Failure | What the agent does | Where you see it |
|---|---|---|
| Weather API down (`--inject-failure weather_timeout`) | 3 attempts, then plans without weather and says so | Panel 4 "miss", "handled: weather timeout … → continued without a forecast", a note in the report (`samples/run2_weather_failure`) |
| Wikipedia search down (`places_timeout`) | Each failed search becomes a note; the days stay free rather than invented | Panel 4, report notes |
| OpenStreetMap busy or down (`osm_timeout`, and often for real) | Each of 4 servers is asked once (a quick refusal once more after 3 s); then the days are still timed but name no hotel or restaurant | "handled: osm …" with every server's reason |
| Geocoding down (`geocode_timeout`) | Stops cleanly with status `gave_up` and the reason | Report status and errors |
| Ambiguous goal ("you choose") | Stops before planning with `needs_city` and says the goal needs a city or state | Report status and notes |
| Place outside India ("Paris") | Not matched to an Indian village; `needs_city` with "does not seem to be in India" | Report notes |
| LLM output that does not fit, or disagrees with the goal | One retry with the error or the problems; then a fallback or a clean stop | Trace events, yellow lines in the console |

---

## 5. Output

Console (with `rich`): panels 1–8 show the goal as read, the completed request, the plan, every step, the days, the budget check, each replanning round and the final notes, then the trip day by day:

```
Day 1 · Wed 14 Oct · Mainly clear, 24–33°C, rain 8%
08:05  Arrive in Udaipur
08:05  → by road 4.0 km                                            ~25 min
08:30  Drop the bags at Shrikant Palace (check-in is later)          15 min
09:00  Breakfast at Foodiz (cafe, 0.4 km)                            45 min
09:55  City Palace, Udaipur (must visit)                                2 h
12:00  Lake Palace (for: lakes)                                         2 h
14:05  Lunch at Sunset Terrace (restaurant, 0.3 km)                     1 h
15:05  Rest (a break in the middle of the day)                          1 h
16:10  Shiv Niwas Palace (popular sight)                                2 h
19:30  Dinner at Palki Khana (restaurant, 0.3 km)                       1 h
20:35  Check in at Shrikant Palace (hostel, near tomorrow's places)
```

- `PREFIX.json` — the `TripReport`: request, destination, plan, step results, weather, itinerary with timelines, cost, verdict, replanning rounds, notes, errors (each with `handled_by`), assumptions, sources and the full trace (every tool call with attempts and duration).
- `PREFIX.md` — the same as a readable report.
- `PREFIX.log` — the console transcript.

---

## 6. Testing and evaluation

| What | Command | Result |
|---|---|---|
| Unit tests (no network; the LLM is faked where needed) | `python -m pytest -q` | 241 passed |
| Extract step on its own (real LLM) | `python eval/run_extract_eval.py` (`--holdout`, `--holdout2`, `--dates-final`, `--budget`) | 50/57 cases fully right across five sets (88%) |
| Whole agent, dev set (real LLM and APIs) | `python eval/run_e2e.py` | first run 12/14 → 14/14 after three fixes |
| Whole agent, holdout set (run once) | `python eval/run_e2e.py --holdout` | 10/10 (95% interval 72–100%) |

The end-to-end runner checks each case against its own expectation (status, base city, budget ceiling, replanning, notes, handled errors) **and** against rules every run must follow: every error has `handled_by`, the plan ends with the fixed tail, the right number of days, every day has a timeline with no overlaps, sightseeing ends by 19:00, no place twice, a budget outside the limit is explained.

The full record — every round, the root cause of each failure with the command that proved it, and what the checks cannot see — is in [`eval/results_log.md`](../eval/results_log.md). Raw results: `eval/e2e_results_first.md`, `eval/e2e_results_dev_final.md`, `eval/e2e_holdout_results.md`.

---

## 7. Assumptions, mock data and simulated tools

There is no free live API for Indian hotel, food or taxi prices, visit durations or city travel times, so these are **assumptions in `config.py`**, listed in the Assumptions section of every report:

- **Cost calculator (simulated tool).** Per night / per day prices for budget, mid and luxury levels (`PRICE_TABLE`), Rs 300 per person per day for public transport, Rs 100 per sight, 2 people per room, 4 per cab. A hotel 3–8 km outside the centre is assumed 25% cheaper. The plan is priced at mid level unless the user names a level.
- **Timing.** Breakfast at 09:00, sightseeing until 19:00, lunch between 11:30 and 14:30, a 1-hour rest after lunch, dinner at 19:30. Visit length by kind of place (fort 2.5 h, palace 2 h, museum or market 1.5 h, temple or lake 1 h, cenotaph or stepwell 45 min). Up to 1 km is walked; longer trips go at 20 km/h plus 10 minutes to find a ride.
- **Arrival.** The traveller reaches the city early on day 1 and leaves the bags at the hotel desk; travel to and from the city is not planned.
- **Defaults when the goal does not say**: 2 days, 1 traveller, the trip starts tomorrow; a bare budget figure is a maximum; no budget means the cost is shown as a guide only.
- **"Popular"** means most read on Wikipedia over the last 60 days; OpenStreetMap has no prices or ratings, so a stay is chosen for its level and location, not its quality.

---

## 8. Limitations

The main ones (details and the rest in [`eval/results_log.md`](../eval/results_log.md) and the write-up):

- Prices and times are assumptions, not live data.
- The free OpenStreetMap servers are often busy in the Indian evening; the plan then names no hotels or restaurants (and says so).
- A state's base city is the most-read one, whatever the interests (Kerala + "backwaters" → Thiruvananthapuram, not Alappuzha).
- One base city per trip; no travel between cities, no origin city, no train or flight.
- Some budget phrasings are read less reliably ("about 15k": 3 of 6 right; a miss is treated as a maximum, the safe side).
- Wikipedia coverage decides which sights exist; small towns may get few places.
- Known issue: when no cafe is found near a day's first place, the timeline still shows the ride to that place before "Breakfast near your stay" (Day 3 of `samples/run1_normal`). The breakfast should come first.
