# yatra-agent — end-to-end results

Run on 2026-10-13 18:44, live APIs, gpt-4o-mini. **12/14 cases passed.**

Every case is checked against its own expectation and against general rules: errors carry 'handled_by', a report is written, the plan ends with the fixed tail, the right number of days, every day has a timeline with no overlaps, sightseeing ends by 19:00 (or a note says the day is long), no place twice, and a budget outside the limit is explained.

| Case | What it tests | Result | Status | Details |
|---|---|---|---|---|
| E-01 | normal city trip | PASS | done | Jaipur; 6 places; Rs 9,000; handled: osm (44 s) |
| E-02 | a state instead of a city | PASS | done | Jaipur; 8 places; Rs 14,900 (33 s) |
| E-03 | must-visit place far from the city | PASS | done | Jaipur; 5 places; Rs 8,900 (30 s) |
| E-04 | tight budget: the replanner should bring it down | PASS | done | Udaipur; 12 places; Rs 14,000 / limit Rs 15,000; 1 replan round(s); handled: osm (38 s) |
| E-05 | impossible budget: say so honestly | PASS | done | Panaji; 9 places; Rs 11,700 / limit Rs 2,000; 3 replan round(s); self-corrections: llm_self_check_retry (37 s) |
| E-06 | no budget given: a guide only, no replanning | PASS | done | Varanasi; 9 places; Rs 15,000; self-corrections: llm_self_check_retry (35 s) |
| E-07 | ambiguous instruction: no destination | PASS | needs_city |  (2 s) |
| E-08 | destination outside India | FAIL: status done, expected needs_city | done | Pariswani; 7 places; Rs 14,800 (24 s) |
| E-09 | Hinglish goal | PASS | done | Jaipur; 5 places; Rs 8,900 / limit Rs 10,000; handled: osm (37 s) |
| E-10 | dates beyond the 16-day forecast | FAIL: no note containing 'forecast' | done | Jodhpur; 6 places; Rs 20,400; handled: osm (37 s) |
| E-11 | induced failure: weather API times out (`--inject-failure weather_timeout`) | PASS | done | Amritsar; 6 places; Rs 9,000; handled: weather (27 s) |
| E-12 | induced failure: Wikipedia place search times out (`--inject-failure places_timeout`) | PASS | done | Mysore Airport; 0 places; Rs 8,400; handled: places (12 s) |
| E-13 | induced failure: OpenStreetMap times out (days still timed) (`--inject-failure osm_timeout`) | PASS | done | Agra; 5 places; Rs 8,900; handled: osm (21 s) |
| E-14 | induced failure: geocoding times out (recover from Wikivoyage or stop cleanly) (`--inject-failure geocode_timeout`) | PASS | gave_up | self-corrections: llm_self_check_retry; handled: geocode (10 s) |

## Goals

- **E-01**: 2 days in Jaipur, we love forts
- **E-02**: 3 days in Rajasthan, I like palaces
- **E-03**: 2 days in Jaipur, must see the Taj Mahal
- **E-04**: 4 days in Udaipur for 2 people, must see City Palace, love lakes, max 15000 total
- **E-05**: 4 days in Goa for two people, under 2000 total
- **E-06**: 3 days in Varanasi
- **E-07**: plan a trip somewhere nice in the mountains for 3 days
- **E-08**: 3 days in Paris, love museums
- **E-09**: jaipur 2 din ghumna h 10k me, khana pina pasand h
- **E-10**: 4 days in Jodhpur from 20 December
- **E-11**: 2 days in Amritsar, must visit the Golden Temple
- **E-12**: 2 days in Mysore, love palaces
- **E-13**: 2 days in Agra, must see Agra Fort
- **E-14**: 2 days in Kochi
