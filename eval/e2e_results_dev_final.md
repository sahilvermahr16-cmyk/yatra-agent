# yatra-agent — end-to-end results

Run on 2026-10-13 20:09, live APIs, gpt-4o-mini. **2/2 cases passed.**

Every case is checked against its own expectation and against general rules: errors carry 'handled_by', a report is written, the plan ends with the fixed tail, the right number of days, every day has a timeline with no overlaps, sightseeing ends by 19:00 (or a note says the day is long), no place twice, and a budget outside the limit is explained.

| Case | What it tests | Result | Status | Details |
|---|---|---|---|---|
| E-01 | normal city trip | PASS | done | Jaipur; 6 places; Rs 9,000 (21 s) |
| E-02 | a state instead of a city | PASS | done | Jaipur; 8 places; Rs 14,900 (34 s) |

## Goals

- **E-01**: 2 days in Jaipur, we love forts
- **E-02**: 3 days in Rajasthan, I like palaces
