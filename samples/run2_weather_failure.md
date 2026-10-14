# Trip plan: Jaipur

**Goal:** 2 days in Jaipur this weekend, must visit Amber Fort, love forts and bazaars, around 12000

**Status:** Plan ready

## Summary

- **Where:** Jaipur, Rajasthan
- **When:** Sat 17 Oct 2026 to Sun 18 Oct 2026 (2 days, 1 nights)
- **Travellers:** 1
- **Cost:** Rs 9,000 for the group (limit Rs 12,000) → **within**

## The plan (written before any tool ran)

_2 days in Jaipur around the Amber Fort, forts, and bazaars._

1. `resolve_destination` — Find Jaipur on the map; every later step searches around it.
2. `weather` — The trip starts in 4 days, so the forecast can guide outdoor plans.
3. `locate_place` "Amber Fort" — You must see the Amber Fort.
4. `find_places` "fort" — You want to see forts; 'fort' is what such a place is called.
5. `find_places` "bazaar" — You want to see bazaars; 'bazaar' is what such a place is called.
6. `find_places` "tourist attraction" — Fill the free time with Jaipur's best-known sights.
7. `build_itinerary` — Put the places into days, most important first.
8. `find_stays_and_food` — Find a stay near each next day's sights and places to eat near the day's route.
9. `estimate_costs` — Price the stay, food, travel and tickets.
10. `check_budget` — Compare the cost with your budget.

## What the agent did

| Step | Tool | Result |
|---|---|---|
| 1 | resolve_destination | ✅ city -> base city Jaipur (26.920, 75.788) |
| 2 | weather | ⚠️ forecast unavailable; continuing without weather |
| 3 | locate_place | ✅ Amber Fort found, 9.7 km from Jaipur |
| 4 | find_places | ✅ 'fort': 6 found, 5 new (Jaigarh Fort, Nahargarh Fort, Shila Devi...) |
| 5 | find_places | ✅ 'bazaar': 1 found, 1 new (Badi Chaupar) |
| 6 | find_places | ✅ 'tourist attraction': 6 found, 4 new (Hawa Mahal, Jal Mahal, Jantar Mantar, Jaipur...) |

**Failures handled:**

- `weather` timeout: injected failure (--inject-failure): simulated timeout (after 3 attempt(s)) → continued without a forecast

## Day by day

### Day 1: Sat 17 Oct

| Time | Plan | Takes |
|---|---|---|
| 07:35 | Arrive in Jaipur |  |
| 07:35 | → by road 6.7 km | ~35 min |
| 08:10 | [Drop the bags at Rajputana Haveli](https://www.openstreetmap.org/node/4483166712) (check-in is later) | 15 min |
| 08:25 | → by road 7.1 km | ~35 min |
| 09:00 | [Breakfast at Cafe Coffee Day](https://www.openstreetmap.org/node/10744673403) (cafe, 0.1 km) | 45 min |
| 09:45 | → walk 0.2 km | ~5 min |
| 09:50 | **[Amber Fort](https://en.wikipedia.org/wiki/Amber_Fort)** (must visit) | 2 h 30 min |
| 12:20 | → walk 0.5 km | ~10 min |
| 12:30 | [Lunch at Garh rooftop cafe and restaurant](https://www.openstreetmap.org/node/13201142301) (restaurant, 0.4 km) | 1 h |
| 13:30 | Rest (a break in the middle of the day) | 1 h |
| 14:30 | → walk 0.5 km | ~10 min |
| 14:40 | **[Jaigarh Fort](https://en.wikipedia.org/wiki/Jaigarh_Fort)** (for: forts) | 2 h 30 min |
| 17:10 | → walk 0.1 km | ~5 min |
| 17:15 | **[Shila Devi](https://en.wikipedia.org/wiki/Shila_Devi)** (for: forts) | 1 h |
| 18:15 | Free time (rest, or look around Shila Devi) | 1 h 5 min |
| 19:20 | → walk 0.5 km | ~10 min |
| 19:30 | [Dinner at Dayaram Ji Jagadamba Restaurant](https://www.openstreetmap.org/node/14159517634) (restaurant, 0.4 km) | 1 h |
| 20:30 | → by road 7.6 km | ~35 min |
| 21:05 | [Check in at Rajputana Haveli](https://www.openstreetmap.org/node/4483166712) (hotel, near tomorrow's places) |  |


_Why these places: Amber Fort (must visit); Jaigarh Fort (you wanted forts); Shila Devi (you wanted forts). All within 0.1 km of each other._

### Day 2: Sun 18 Oct

| Time | Plan | Takes |
|---|---|---|
| 08:40 | [Check out of Rajputana Haveli](https://www.openstreetmap.org/node/4483166712) (leave the bags at the desk) |  |
| 08:40 | → by road 2.3 km | ~20 min |
| 09:00 | [Breakfast at The Tattoo Cafe](https://www.openstreetmap.org/node/5249299221) (cafe, <0.1 km) | 45 min |
| 09:45 | → walk <0.1 km | ~5 min |
| 09:50 | **[Badi Chaupar](https://en.wikipedia.org/wiki/Badi_Chaupar)** (for: bazaars) | 1 h |
| 10:50 | → by road 2.4 km | ~20 min |
| 11:10 | **[Nahargarh Fort](https://en.wikipedia.org/wiki/Nahargarh_Fort)** (for: forts) | 2 h 30 min |
| 13:40 | → walk 0.1 km | ~5 min |
| 13:45 | [Lunch at Once Upon at Gath](https://www.openstreetmap.org/node/13607613087) (restaurant, <0.1 km) | 1 h |
| 14:45 | Rest (a break in the middle of the day) | 1 h |
| 15:45 | → by road 5.5 km | ~30 min |
| 16:15 | **[Kanak Vrindavan](https://en.wikipedia.org/wiki/Kanak_Vrindavan)** (for: forts) | 1 h |
| 17:15 | Free time (rest, or look around Kanak Vrindavan) | 1 h 55 min |
| 19:10 | → by road 2.1 km | ~20 min |
| 19:30 | [Dinner at RESTAURANT , JAIPUR](https://www.openstreetmap.org/node/5227030921) (restaurant, 1.6 km) | 1 h |
| 20:30 | → by road 2.0 km | ~20 min |
| 20:50 | [Collect the bags from Rajputana Haveli](https://www.openstreetmap.org/node/4483166712) | 15 min |
| 21:05 | End of the trip |  |


_Why these places: Badi Chaupar (you wanted bazaars); Nahargarh Fort (you wanted forts); Kanak Vrindavan (you wanted forts). All within 4.8 km of each other._

**If you have more time:** Maota Lake, Hawa Mahal, Jal Mahal, Jantar Mantar, Jaipur, City Palace, Jaipur

## Cost and budget

| Item | Amount |
|---|---|
| Hotel (mid, 1 room(s)) | Rs 3,000 |
| Food (mid) | Rs 2,400 |
| Local travel (cab) | Rs 3,000 |
| Entry tickets | Rs 600 |
| **Total** | **Rs 9,000** |

## Notes

- Group size not given, so 1 traveller was assumed.
- Budget of Rs 12,000 was treated as a maximum, because the words 'around 12000' did not say whether it can be exceeded.
- The weather forecast could not be fetched, so the plan has no weather adjustments. Please check the forecast before you go.
- Because you chose Amber Fort, other historic sights were preferred among the popular ones.

## Assumptions

- Prices are assumed (there is no free live price API for India): hotel Rs 3,000 per room per night (mid), food Rs 1,200 per person per day (mid), cab Rs 1,500 per day (config.py).
- Each sight is assumed to cost Rs 100 per person to enter; 2 people share a room and 4 share a cab.
- Sights come from Wikipedia within 25 km of the base city; 'popular' means most read on Wikipedia in the last 60 days.
- Must-visit places farther than 60 km from the base city are not planned.
- Weather comes from the Open-Meteo forecast, which reaches 16 days ahead.
- At most 3 places are planned per day.
- Stays and places to eat come from OpenStreetMap, which has no prices or ratings: a stay is chosen for the planned price level and for being near the next day's places, not for its quality.
- A hotel 3-8 km outside the centre is assumed to cost 25% less.
- The traveller reaches the city early on day 1, goes to the first night's hotel and leaves the bags at the desk (15 min; check-in is later), and is at breakfast by 09:00. On the last day the bags stay at the hotel desk after check-out and are collected in the evening. Arrival and departure travel to the city are not planned.
- Each day runs from 09:00 (breakfast, 45 min); sightseeing ends by 19:00, and a place that would end later moves to 'If you have more time'. Lunch (60 min) comes between 11:30 and 14:30, followed by 1 h of rest; the evening meal is at 19:30.
- Visit lengths are assumed by kind of place (fort, fortress, zoo 2 h 30 min; palace 2 h; museum, gallery, market 1 h 30 min; temple, mandir, lake 1 h; cenotaph, stepwell, baori 45 min; clock tower, gate, statue 30 min; other places 1 h). Travel: up to 1 km is walked at 4.5 km/h; longer trips go by road at 20 km/h plus 10 min to find a ride, with roads 1.3x the straight-line distance.

## Sources

- Open-Meteo geocoding and forecast: https://open-meteo.com
- Wikipedia (places, descriptions, page views): https://en.wikipedia.org
- OpenStreetMap via the Overpass API (stays and places to eat): https://www.openstreetmap.org
- Wikivoyage: https://en.wikivoyage.org/wiki/Jaipur
