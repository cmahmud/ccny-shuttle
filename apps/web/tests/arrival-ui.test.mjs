import test from 'node:test';
import assert from 'node:assert/strict';
import {selectArrivalSlots,arrivalTimeLabel,arrivalDirectionLabel,eligibleArrivalSnapshot,STALE_ARRIVAL_GRACE_MS} from '../arrival-ui-v2.js';
const now=Date.parse('2026-11-16T16:15:00Z');
const at=m=>new Date(now+m*60000).toISOString();
const sample={source:'student_public',experimental:true,calibrated:false,
  generatedAt:new Date(now-10000).toISOString(),stops:{
    '125':[
      {vehicleId:'88',busName:'88',direction:'SB',arrivalAt:at(35),providerPredictionsEnabled:false},
      {vehicleId:'89',busName:'89',direction:'SB',arrivalAt:at(17),providerPredictionsEnabled:false},
      {vehicleId:'88',busName:'88',direction:'SB',arrivalAt:at(35),providerPredictionsEnabled:false},
      {vehicleId:'89',busName:'89',direction:'SB',arrivalAt:at(58),providerPredictionsEnabled:false},
    ]
  }};
test('use only bounded, valid, unique source slots sorted by arrival',()=>{
  const rows=selectArrivalSlots(sample,'125',now);
  assert.deepEqual(rows.map(x=>x.busName),['89','88','89']);
  assert.equal(rows[0].providerPredictionsEnabled,false);
});
test('source must be explicit and no data outside allowed source or expired',()=>{
  assert.deepEqual(selectArrivalSlots({...sample,source:'samsara'},'125',now),[]);
  assert.deepEqual(selectArrivalSlots({...sample,calibrated:true},'125',now),[]);
  assert.deepEqual(selectArrivalSlots(sample,'nac',now),[]);
  assert.deepEqual(selectArrivalSlots(sample,'125',now+60000),[]);
  assert.deepEqual(selectArrivalSlots({...sample,generatedAt:at(1)},'125',now),[]);
});
test('arrival format is conservative, relative or NY clock without invented precision',()=>{
  assert.equal(arrivalTimeLabel(at(17),false,now),'17 min');
  assert.equal(arrivalTimeLabel(at(0.2),false,now),'Due soon');
  assert.match(arrivalTimeLabel(at(17),true,now),/11:32\s*AM/);
});
test('direction text uses established stop route names',()=>{
  assert.equal(arrivalDirectionLabel('NB','marshak'),'To 145th St');
  assert.equal(arrivalDirectionLabel('SB','marshak'),'To 125th St');
  assert.equal(arrivalDirectionLabel('NB','125'),'Northbound');
});

test('stale source snapshots have a strict 120-second grace, never an extended live window', () => {
  assert.equal(STALE_ARRIVAL_GRACE_MS,120000);
  assert.deepEqual(selectArrivalSlots(sample,'125',now+70000),[]);
  const stale=selectArrivalSlots(sample,'125',now+70000,STALE_ARRIVAL_GRACE_MS);
  assert.ok(stale.length>0);
  assert.equal(eligibleArrivalSnapshot(sample,now+119999,STALE_ARRIVAL_GRACE_MS),false);
  assert.deepEqual(selectArrivalSlots(sample,'125',now+120000,STALE_ARRIVAL_GRACE_MS),[]);
  assert.equal(eligibleArrivalSnapshot({...sample,source:'other'},now,STALE_ARRIVAL_GRACE_MS),false);
});
test('source age and clock are independent of stale countdown reference', () => {
  const lastKnownAt=now-10000;
  assert.equal(arrivalTimeLabel(at(17),false,lastKnownAt),'18 min');
  assert.match(arrivalTimeLabel(at(17),true,now),/11:32\s*AM/);
});
