/** Read-only rendering helpers for experimental, student-site forecast times. */
const NY_CLOCK=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'});
export const KNOWN_ESTIMATE_STOPS=new Set(['125','135','marshak','145']);

export function selectArrivalSlots(snapshot,stop,now=Date.now()) {
  if (!snapshot || snapshot.source!=='student_public' || snapshot.experimental!==true ||
      snapshot.calibrated!==false || !KNOWN_ESTIMATE_STOPS.has(stop)) return [];
  const generated=Date.parse(snapshot.generatedAt);
  if (!Number.isFinite(generated) || generated>now+10000 || now-generated>45000) return [];
  const input=snapshot.stops?.[stop];
  if (!Array.isArray(input)) return [];
  const seen=new Set();
  return input.filter(item=>{
      if (!item || !['NB','SB'].includes(item.direction) ||
          typeof item.vehicleId!=='string' || !item.vehicleId ||
          (typeof item.busName!=='string' && item.busName!==null))return false;
      const at=Date.parse(item.arrivalAt);
      const lead=at-now;
      if (!Number.isFinite(at) || lead< -30000 || lead>7200000) return false;
      const key=[item.vehicleId,item.direction,item.arrivalAt].join('|');
      if (seen.has(key)) return false;
      seen.add(key);return true;
    })
    .sort((a,b)=>Date.parse(a.arrivalAt)-Date.parse(b.arrivalAt))
    .slice(0,8);
}

export function arrivalTimeLabel(arrivalAt,clockTimes=false,now=Date.now()) {
  const time=Date.parse(arrivalAt);
  if (!Number.isFinite(time))return '—';
  if (clockTimes)return NY_CLOCK.format(new Date(time));
  const seconds=(time-now)/1000;
  if (seconds<=60)return 'Due soon';
  return Math.ceil(seconds/60)+' min';
}

export function arrivalDirectionLabel(direction,stop) {
  if (stop==='marshak')return direction==='NB'?'To 145th St':'To 125th St';
  return direction==='NB'?'Northbound':'Southbound';
}
