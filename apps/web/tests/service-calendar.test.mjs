import test from 'node:test';
import assert from 'node:assert/strict';
import {serviceNotice,nyDateParts} from '../service-calendar-v1.js';

const noon=(date)=>new Date(date+'T17:00:00Z'); // 12 noon New York standard time

test('Veterans Day 2026 is a dated attributed report, not a confirmed campus closure',()=>{
  const notice=serviceNotice(noon('2026-11-11'));
  assert.equal(notice.kind,'reported');
  assert.match(notice.detail,/not independently confirmed/);
  assert.match(notice.detail,/Veterans Day/);
  assert.equal(serviceNotice(noon('2026-11-12')),null);
});
test('official Thanksgiving no-class and closure dates appear',()=>{
  assert.equal(serviceNotice(noon('2026-11-25')).kind,'calendar');
  assert.match(serviceNotice(noon('2026-11-26')).detail,/Thanksgiving/);
  assert.equal(serviceNotice(noon('2026-11-27')).kind,'calendar');
});
test('winter calendar and spring recess are covered',()=>{
  assert.equal(serviceNotice(noon('2027-01-18')).kind,'calendar');
  assert.equal(serviceNotice(noon('2027-04-24')).kind,'recess');
  assert.equal(serviceNotice(noon('2027-05-17')).kind,'calendar');
});
test('weekend is advisory, not a GPS outage diagnosis',()=>{
  assert.equal(serviceNotice(noon('2026-11-14')).kind,'weekend');
  assert.equal(serviceNotice(noon('2026-11-16')),null);
});
test('source time uses New York calendar date even when UTC has rolled over',()=>{
  assert.equal(nyDateParts(new Date('2026-11-12T02:00:00Z')).date,'2026-11-11');
  assert.equal(serviceNotice(new Date('2026-11-12T02:00:00Z')).kind,'reported');
});
test('fresh buses override any calendar assumption',()=>{
  assert.equal(serviceNotice(noon('2026-11-11'),true),null);
  assert.equal(serviceNotice(noon('2026-11-26'),true),null);
});
test('never assume every public holiday closes CCNY',()=>{
  assert.equal(serviceNotice(noon('2027-02-17')),null);
});
