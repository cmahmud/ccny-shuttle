# Automatically visible last-reported shuttle locations

**Implemented November 10, 2026.**

## Reported problem and root cause

At the end of service, the live API still retained source-timestamped last GPS fixes for buses 88 and 89 in the existing SQLite observation store. The old frontend showed the buses in a small "Not currently reporting" list but **hid both map markers by default** (the `Last (N)` toggle was off). The status banner said "No current bus positions", leaving the map devoid of historical shuttle positions.

A phone and desktop real-browser baseline reproduced the issue: two known vehicles in the list and **zero historical map markers** until the button was pressed.

## What changed

- Previously observed buses (up to **7 days** old, validated against the source's original time and geographic bounds) display gray, **numbered last-reported GPS markers by default**, separately from teal current GPS markers. The map initially frames reported vehicle markers so they are visible.
- The status footer clearly reads **last-reported GPS location(s) · NOT live** when only historical reports exist.
- Each last-reported vehicle row is a full-size keyboard/touch-accessible button with the bus number, age and **actual recorded New York time**. Tapping it centers the map at the exact original latitude/longitude and opens a popup.
- The popup provides a Google Maps link to **that specific recorded coordinate**, plus a prominent statement that the bus may have moved.
- The `Last (N)` control is an optional visibility toggle, now **enabled by default**; the user may hide the historical markers. The current-bus `Buses (N)` and stop-overview `All` shortcuts still work.
- Existing Leaflet markers are updated in place (and discarded only when their source entries become invalid), so a five-second status poll **does not close a popup** or reset the student's map view.
- When an internet request fails, the already-known last reported locations remain visible **only as history**. The browser also keeps a *tab-scoped*, sanitized `sessionStorage` snapshot for **up to 24 hours** so a user can refresh the same tab during a connectivity outage. No GPS positions are cached by the service worker; no location history is submitted from the user's device. No driver, user, credential, or current-device geolocation is stored.
- Small design refinements: stronger gray versus teal visual distinction, last-reported bus-number pins, larger tappable cards, cleaner map legend, compact responsive footer, and aligned controls across 320–430px phone widths.
- Two last-reported GPS coordinates near campus may lie within about 17 meters of one another, causing numbered pins to overlap at typical map zoom. For fixes within 40 meters, the frontend now **separates only the screen-space number labels** and draws a connector to a small dot **anchored at the exact original GPS latitude/longitude**. No derived or offset geographic positions are stored or displayed as bus coordinates.

## Limitations and safeguards

This remains **student-relayed GPS, not independently verified Samsara telemetry**. A last-reported location is never a guarantee of the present location, current shuttle service, route assignment or arrival time. Raw database observations and source timestamps remain unchanged. No new GPS samples are fabricated. The interface does not display an ETA until independently calibrated.

Only buses actually recorded in the GPS source can be listed; the project **does not have the official full inactive-fleet roster**.

## Tests

- **44** static frontend/unit checks and **64** GPS collector tests passed locally.
- Real production browser tests at desktop and 390px mobile found two previously observed vehicles, **two automatically visible history pins**, exact-time popup and tap-to-focus functionality.
- Synthetic mobile browser regression at **320, 375, 390, 430px** and desktop verifies history markers appear without toggling; visually separated last-GPS labels do not overlap, and each keeps an exact source-coordinate anchor; history can be hidden/restored; tapping a vehicle centers its marker; popups survive a 5-second GPS refresh; no horizontal overflow; and the tab's session snapshot correctly supplies *historical-only* locations after the API fails and the user reloads.
- Live original GPS collector and status server remain active. No changes to `api.syndrid.com`/OmniRoute port.

There is **no validated route-snapping or moving-bus dead-reckoning** in this release. Those changes require independently verified stop geometry and a measured accuracy benchmark; this release focuses on honestly presenting the last source GPS positions that we already possess.
