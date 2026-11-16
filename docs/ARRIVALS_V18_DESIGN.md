# Upcoming-arrival display v18

This is a UI-only refinement to the student-site experimental forecast panel. No backend GPS, ETA modeling, source collection, or Nginx modifications.

## Current-source UI
- Show **minutes and New York clock time together** in each source forecast row.
- Distinguish only the **earliest valid upcoming arrival for the selected stop** with a purple accent and **NEXT** marker; never invent additional cycles.
- The existing "Show more" control preserves the maximum of 8 source-supplied slots per supported stop.
- Arrival forecasts remain labeled *Experimental* and *Unverified*. This is not the independently calibrated ETA engine.
- Remove the now-obsolete "Clock times" checkbox, since both values are visible simultaneously.

## GPS-delay safety
- Normal source eligibility remains **45 seconds**.
- On GPS delay or a transient API failure while the browser is online, a previously received source snapshot can remain visible **only up to 120 seconds after its original source-generated timestamp**.
- Retain a minimal snapshot in per-tab session storage, with a hard upper age bound; this prevents the card resetting to empty immediately on a page refresh during a short delay.
- Stale rows use subdued amber styling, a **STALE / Not live** caption, no NEXT emphasis, and a frozen **last predicted** minute value. The accompanying clock time is the original arrivalAt, not a new prediction.
- Once the source snapshot expires, the arrival card disappears and GPS's independent delayed/offline/after-hours status remains truthful.
- If live GPS returns without valid source estimates, the old arrival cache is cleared. Do not display stale student estimates while the officially sourced API is selected.
- No historical marker or old GPS position is promoted back to live.

## Tests
- Browser regression covers countdown plus clock, earliest-only highlight, extra arrivals, Marshak directional labels, NAC missing estimates, delayed transitions, tab reload, 2-minute expiry, and phone/desktop widths.
- All existing route, last GPS, service notice, accessibility, mobile and offline browser tests must remain green.
