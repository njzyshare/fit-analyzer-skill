import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';

const files = process.argv.slice(2);
function bj(d){ return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19); }

for (const IN of files) {
  const bytes = new Uint8Array(fs.readFileSync(IN));
  const proto = bytes[1];
  const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
  console.log(`\n################ ${IN}  proto=0x${proto.toString(16)}  decodeErrors=${errors.length} ################`);

  const fid = (messages.fileIdMesgs||[])[0];
  if (fid) console.log('FILE_ID:', JSON.stringify(fid.fields||fid, (k,v)=> v instanceof Date? v.toISOString(): v));
  const s = (messages.sessionMesgs||[])[0];
  if (s) {
    const f = s.fields||s;
    console.log('SESSION start_time=', f.startTime?bj(f.startTime):f.startTime,
                ' timestamp=', f.timestamp?bj(f.timestamp):f.timestamp,
                ' totalElapsed=', f.totalElapsedTime, ' totalTimer=', f.totalTimerTime,
                ' totalDist=', f.totalDistance, ' numLaps=', f.numLaps,
                ' tzOffset=', f.timezoneOffset, ' localTimestamp=', f.localTimestamp?bj(f.localTimestamp):f.localTimestamp);
  }
  const recs = messages.recordMesgs||[];
  if (recs.length){
    const r0 = recs[0].fields||recs[0];
    const rN = recs[recs.length-1].fields||recs[recs.length-1];
    console.log('REC first ts=', r0.timestamp?bj(r0.timestamp):r0.timestamp, ' dist=', r0.distance,
                ' last ts=', rN.timestamp?bj(rN.timestamp):rN.timestamp, ' dist=', rN.distance);
  }

  const laps = (messages.lapMesgs||[]).map(l=>l.fields||l);
  console.log(`\nLAPS count=${laps.length}`);
  let prevST=null, monotonic=true, orderIssues=[];
  laps.forEach((f,i)=>{
    const st = f.startTime, ts = f.timestamp;
    if (st && prevST && st.getTime() < prevST.getTime()){ monotonic=false; orderIssues.push(i); }
    if (st) prevST = st;
    const short = (f.totalDistance!=null && f.totalDistance < 500);
    const tag = short ? '  <== SHORT' : '';
    console.log(`LAP[${String(i).padStart(2)}] idx=${f.messageIndex} start=${st?bj(st):st} end=${ts?bj(ts):ts} dist=${f.totalDistance} timer=${f.totalTimerTime} elapsed=${f.totalElapsedTime} posLat=${f.startPositionLat} posLong=${f.startPositionLong}${tag}`);
  });
  console.log(`\nstartTime monotonic=${monotonic}  nonMonotonicIndices=${JSON.stringify(orderIssues)}`);

  // 把短圈按 start_time 排名，看它是第几个
  const shortIdx = laps.map((f,i)=>({i, st:f.startTime, dist:f.totalDistance})).filter(x=>x.dist!=null && x.dist<500);
  console.log('SHORT laps (dist<500m):', JSON.stringify(shortIdx.map(x=>({idx:x.i, start:x.st?bj(x.st):x.st, dist:x.dist}))));
}
