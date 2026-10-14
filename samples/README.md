# Sample runs

Three runs of the agent, each saved with `--out`. Every run has three files:

| File | What it is | Open it for |
|---|---|---|
| `.log` | The console transcript: everything printed on screen | the plan, each step, the days, the budget check, step by step |
| `.md` | The final report, easy to read on GitHub | the final output |
| `.json` | The same report as data; `trace` lists every tool call (tool, attempts, time taken) and every LLM call | the exact tool calls |

## The three runs

| Run | Goal | What it shows |
|---|---|---|
| 1. [`run1_normal`](run1_normal.md) | 3 days in Jodhpur next weekend, must see Mehrangarh Fort, love stepwells and street food, under 20k for two | A normal trip. The planner's first plan was incomplete, so code sent it back once (self-correction); Wikipedia had no places for "street food", so food spots came from OpenStreetMap |
| 2. [`run2_weather_failure`](run2_weather_failure.md) | 2 days in Jaipur this weekend, must visit Amber Fort, love forts and bazaars, around 12000 | **Induced failure** (`--inject-failure weather_timeout`): the weather API times out 3 times; the agent plans without weather and says so |
| 3. [`run3_budget_replan`](run3_budget_replan.md) | 4 days in Udaipur for 2 people, must see City Palace, love lakes, max 15000 total | **Over budget**: the first draft costs Rs 27,000; the replanner switches to a budget hotel and budget meals, Rs 14,000 |

Commands:

```bash
python run.py "3 days in Jodhpur next weekend, must see Mehrangarh Fort, love stepwells and street food, under 20k for two" --out samples/run1_normal
python run.py "2 days in Jaipur this weekend, must visit Amber Fort, love forts and bazaars, around 12000" --inject-failure weather_timeout --out samples/run2_weather_failure
python run.py "4 days in Udaipur for 2 people, must see City Palace, love lakes, max 15000 total" --out samples/run3_budget_replan
```

## Where to look

| What the assignment asks for | Where |
|---|---|
| **Planning** (before acting) | `.log`, panel "3 · Plan before acting": [run 1, line 12](run1_normal.log#L12); the self-correction is at [line 33](run1_normal.log#L33). In the report: "The plan (written before any tool ran)" |
| **Tool calls** | `.log`, panel "4 · Execute the plan" ([run 1, line 36](run1_normal.log#L36)): one line per step, ok or miss. Every call with its attempts and time: `trace` in the `.json` |
| **Failure and recovery** | [run 2, line 44](run2_weather_failure.log#L44): "handled: weather timeout … after 3 attempt(s) → continued without a forecast"; the `.json` has the same in `errors` with `handled_by` |
| **Replanning** | [run 3, line 57](run3_budget_replan.log#L57): panel "7 · Replan, round 1", Rs 27,000 → Rs 14,000, then the budget check again |
| **Final output** | the `.md` reports (day-by-day plan, cost, notes, assumptions, sources), or the end of each `.log` |

The runs were made on 13–14 October 2026, so "this weekend" and "next weekend" are dates in October 2026. Live data (weather, places, hotels) changes, so a new run will not be identical.
