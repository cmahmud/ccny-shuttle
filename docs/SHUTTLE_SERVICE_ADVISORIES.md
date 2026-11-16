# CCNY date-based shuttle advisory notices

The compact tracker shows a small, nonblocking message above stop selection on dates when CCNY shuttle service is normally not scheduled. **This is not a dispatch feed or independent proof that the shuttles are not operating.** Live GPS is never overwritten or hidden by these notices; fresh confirmed source-reported vehicles suppress the calendar assumption.

### Sources

- Official service policy: https://www.ccny.cuny.edu/about/gettingthere — shuttle typically operates Monday–Friday 6:30 AM–10 PM on class days, not holidays/cancelled classes/intersessions.
- 2026 Fall Academic Calendar: https://www.ccny.cuny.edu/sites/default/files/2026-09/Fall%202026%20Academic%20Calendar.pdf
- 2027 Winter Academic Calendar: https://www.ccny.cuny.edu/sites/default/files/2026-09/Winter%20Session%202027%20Academic%20Calendar.pdf
- 2027 Spring Academic Calendar: https://www.ccny.cuny.edu/sites/default/files/2026-08/Spring%202027%20Academic%20Calendar.pdf

### Important Veterans Day exception

November 11, 2026 is a date-specific **rider-reported nonoperation**. The published Fall 2026 CCNY Registrar calendar does **not explicitly list November 11 as a campus closure**. The banner deliberately says "No shuttle service reported" and "Rider report, not confirmed by CCNY Facilities" rather than asserting CCNY officially closed. Remove or upgrade that one-day exception only after independent confirmation from Facilities; the entry expires automatically at New York midnight.

### Precedence and safety

- Live, fresh observed bus positions override expected closure notices.
- Dated academic closure/no-class notices take precedence over weekend/recess notices.
- Winter intersession and between-term gaps are labelled **normally not scheduled**, not guaranteed cancellation.
- Weekend notice describes the regular *weekday* shuttle; other campus transport or exceptions may exist.
- On all other dates, the banner stays hidden. A GPS outage alone never creates a holiday explanation.
- All date matching is done in `America/New_York`, never device-local or server UTC.
- There is no network polling for notices, no new backend API, and no new operating costs. The schedule is a small static JS module reviewed for each semester; it does not claim automatically synced CCNY closures.
- If the academic calendar changes, update `apps/web/service-calendar-v1.js` after confirming the change. Exceptional closures can be added with their own source and expiration date.
