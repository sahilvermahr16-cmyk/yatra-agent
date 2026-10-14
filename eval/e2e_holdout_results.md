# yatra-agent — end-to-end HOLDOUT results

Run on 2026-10-13 20:18, live APIs, gpt-4o-mini. **10/10 cases passed.**

Every case is checked against its own expectation and against general rules: errors carry 'handled_by', a report is written, the plan ends with the fixed tail, the right number of days, every day has a timeline with no overlaps, sightseeing ends by 19:00 (or a note says the day is long), no place twice, and a budget outside the limit is explained.

| Case | What it tests | Result | Status | Details |
|---|---|---|---|---|
| H-01 | normal city trip | PASS | done | Hyderabad; 9 places; Rs 15,000 (34 s) |
| H-02 | a state instead of a city | PASS | done | Thiruvananthapuram; 6 places; Rs 9,000 (76 s) |
| H-03 | must-visit place far from the city | PASS | done | Pune; 5 places; Rs 8,900 (37 s) |
| H-04 | tight budget: the replanner should bring it down | PASS | done | Shimla; 6 places; Rs 13,500 / limit Rs 12,000; 3 replan round(s); self-corrections: llm_self_check_retry, llm_self_check_retry (32 s) |
| H-05 | no budget given: a guide only, no replanning | PASS | done | Rishikesh; 6 places; Rs 9,000; self-corrections: llm_self_check_retry (47 s) |
| H-06 | ambiguous instruction: no destination | PASS | needs_city |  (2 s) |
| H-07 | destination outside India | PASS | needs_city |  (7 s) |
| H-08 | Hinglish goal | PASS | done | Kolkata; 9 places; Rs 15,000 / limit Rs 15,000; self-corrections: llm_self_check_retry (41 s) |
| H-09 | induced failure: weather API times out (`--inject-failure weather_timeout`) | PASS | done | Bhopal; 6 places; Rs 9,000; handled: weather (timeout: injected failure (--inject-failure): simulated timeout (after 3 attempt(s))) (33 s) |
| H-10 | induced failure: Wikipedia place search times out (`--inject-failure places_timeout`) | PASS | done | Madurai; 0 places; Rs 14,100; handled: places (timeout: injected failure (--inject-failure): simulated timeout (after 3 attempt(s))), places (timeout: injected failure (--inject-failure): simulated timeout (after 3 attempt(s))) (11 s) |

## Goals

- **H-01**: 3 days in Hyderabad, love history and biryani
- **H-02**: 2 days in Kerala, backwaters and beaches
- **H-03**: 2 days in Pune, must see the Golden Temple
- **H-04**: 3 days in Shimla for 3 people, max 12000 total
- **H-05**: a weekend in Rishikesh
- **H-06**: I want a relaxing vacation, you choose
- **H-07**: 4 days in Bangkok, street food
- **H-08**: kolkata 3 din ghumna h 15k tak, purani imaratein pasand h
- **H-09**: 2 days in Bhopal, must see Upper Lake
- **H-10**: 3 days in Madurai, temples
