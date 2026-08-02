import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';

const IN = process.argv[2];
function bj(d){ return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19); }
const bytes = new Uint8Array(fs.readFileSync(IN));
const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
const recs = (messages.recordMesgs||[]).map(r=>r.fields||r);
console.log(`FILE ${IN} records=${recs.length} decodeErrors=${errors.length}`);

let prevT=null, prevD=null, gaps=0, drops=0;
let bigGapAt=[];
recs.forEach((f,i)=>{
  const t=f.timestamp, d=f.distance, sp=f.speed;
  if (t!=null && prevT!=null){
    const dt=(t.getTime()-prevT.getTime())/1000;
    if (dt>120){ gaps++; bigGapAt.push({i, dt, prevBJ:bj(prevT), curBJ:bj(t), prevD, curD:d}); }
    if (d!=null && prevD!=null && d < prevD - 0.5){ drops++; if(drops<=5) console.log(`  DROP at rec ${i}: ${prevD} -> ${d}`); }
  }
  prevT=t; prevD=d;
});

console.log(`Timestamp gaps >120s: ${gaps}; distance drops: ${drops}`);
console.log('Big timestamp gaps (activity boundary?):');
for (const g of bigGapAt.slice(0,10)) console.log(`  rec ${g.i}: ${g.prevBJ}(d=${g.prevD}) -> ${g.curBJ}(d=${g.curD})  dt=${g.dt}s`);

// print a window around each big gap
for (const g of bigGapAt.slice(0,3)){
  console.log(`\n--- window around rec ${g.i} ---`);
  const a=Math.max(0,g.i-2), b=Math.min(recs.length-1,g.i+2);
  for(let k=a;k<=b;k++){
    const f=recs[k];
    console.log(`  rec[${k}] t=${f.timestamp?bj(f.timestamp):'?'} d=${f.distance} sp=${f.speed} hr=${f.heartRate}`);
  }
}

// distance range sanity
const ds = recs.map(r=>r.distance).filter(x=>x!=null);
console.log(`\nDistance range: min=${Math.min(...ds)} max=${Math.max(...ds)}`);
// is it monotonic overall?
let nonmono=0; for(let i=1;i<ds.length;i++) if(ds[i]<ds[i-1]-0.5) nonmono++;
console.log(`Non-monotonic distance steps: ${nonmono}`);
