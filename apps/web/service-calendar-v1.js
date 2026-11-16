/**
 * CCNY shuttle service-day advisories, not real-time dispatch confirmation.
 * Academic calendar entries were checked against CCNY Registrar PDFs.
 * The 2026-11-11 exception is a dated rider report, not a CCNY announcement.
 * None of these rules implies a GPS failure or suppresses observed live buses.
 */
export const CALENDAR_URL = 'https://www.ccny.cuny.edu/registrar/academic-calendar';
export const SHUTTLE_URL = 'https://www.ccny.cuny.edu/about/gettingthere';
const FALL_2026 = 'https://www.ccny.cuny.edu/sites/default/files/2026-09/Fall%202026%20Academic%20Calendar.pdf';
const WINTER_2027 = 'https://www.ccny.cuny.edu/sites/default/files/2026-09/Winter%20Session%202027%20Academic%20Calendar.pdf';
const SPRING_2027 = 'https://www.ccny.cuny.edu/sites/default/files/2026-08/Spring%202027%20Academic%20Calendar.pdf';

// Confirmed academic calendar designations, NOT independently confirmed shuttle dispatch.
// Only explicit no-class/closed dates are treated as expected service gaps.
const EXCEPTIONS = new Map([
  ['2026-09-07', ['College closed', FALL_2026]],
  ['2026-09-21', ['No classes scheduled', FALL_2026]],
  ['2026-10-12', ['College closed', FALL_2026]],
  // Veterans Day is a student report, NOT listed as a closure on the Fall 2026 calendar.
  ['2026-11-11', ['Veterans Day', SHUTTLE_URL, 'reported']],
  ['2026-11-25', ['No classes scheduled', FALL_2026]],
  ['2026-11-26', ['Thanksgiving · college closed', FALL_2026]],
  ['2026-11-27', ['Thanksgiving · college closed', FALL_2026]],
  ['2026-12-24', ['College closed', FALL_2026]],
  ['2026-12-25', ['College closed', FALL_2026]],
  ['2026-12-31', ['College closed', FALL_2026]],
  ['2027-01-01', ['College closed', WINTER_2027]],
  ['2027-01-18', ['College closed', WINTER_2027]],
  ['2027-02-12', ['College closed', SPRING_2027]],
  ['2027-02-15', ['College closed', SPRING_2027]],
  ['2027-03-10', ['No classes scheduled', SPRING_2027]],
  ['2027-05-17', ['No classes scheduled', SPRING_2027]],
  ['2027-05-31', ['College closed', SPRING_2027]],
]);

const RECESSES = [
  ['2026-12-22', '2027-01-03', 'Between semesters · shuttle service not normally scheduled', SHUTTLE_URL],
  ['2027-01-04', '2027-01-27', 'Winter intersession · shuttle normally does not operate', SHUTTLE_URL],
  ['2027-04-21', '2027-04-29', 'Spring recess', SPRING_2027],
];

export function nyDateParts(now = new Date()) {
  if (!(now instanceof Date) || !Number.isFinite(now.getTime())) throw new TypeError('Valid Date required');
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit', weekday:'short',
  });
  const fields = Object.fromEntries(formatter.formatToParts(now).map(p=>[p.type,p.value]));
  return { date:`${fields.year}-${fields.month}-${fields.day}`, weekday:fields.weekday };
}

export function serviceNotice(now = new Date(), hasFreshLiveBuses = false) {
  // A real, fresh moving or standing bus is stronger evidence than a planned closure.
  if (hasFreshLiveBuses) return null;
  const {date,weekday} = nyDateParts(now);
  const day = EXCEPTIONS.get(date);
  if (day) {
    const [reason,url,kind] = day;
    if (kind === 'reported') return {
      kind:'reported',title:'No shuttle service reported',
      detail:`${reason} · Rider report, not confirmed by CCNY Facilities.`,
      sourceLabel:'CCNY shuttle policy',url,date,
    };
    return {
      kind:'calendar',title:'No shuttle service expected',
      detail:`${reason} · Based on the CCNY academic calendar.`,
      sourceLabel:'CCNY calendar',url,date,
    };
  }
  const recess = RECESSES.find(([start,end])=>date>=start && date<=end);
  if (recess) return {
    kind:'recess',title:'Shuttle service not normally scheduled',
    detail:`${recess[2]} · Check for special service announcements.`,
    sourceLabel:'CCNY schedule',url:recess[3],date,
  };
  if (weekday === 'Sat' || weekday === 'Sun') return {
    kind:'weekend',title:'No regular weekday shuttle scheduled',
    detail:'The published shuttle schedule is Monday–Friday on class days. Check for exceptions.',
    sourceLabel:'CCNY shuttle policy',url:SHUTTLE_URL,date,
  };
  return null;
}
