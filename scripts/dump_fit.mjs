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
  if (fid) {
    const f = fid.fields || fid;
    console.log('FILE_ID:', JSON.stringify(f, (k,v)=> v instanceof Date? v.toISOString(): v));
  }
  const s = (messages.sessionMesgs||[])[0];
  if (s) {
    const f = s.fields || s;
    console.log('SESSION:', JSON.stringify(f, (k,v)=> v instanceof Date? v.toISOString(): v));
  }
  console.log(`COUNTS: laps=${(messages.lapMesgs||[]).length} records=${(messages.recordMesgs||[]).length} events=${(messages.eventMesgs||[]).length} devices=${(messages.deviceInfoMesgs||[]).length}`);

  let i=0;
  for (const lp of (messages.lapMesgs||[])) {
    const f = lp.fields || lp;
    const t = f.timestamp, st = f.startTime;
    console.log(`LAP[${String(i).padStart(2)}] idx=${f.messageIndex} ts=${t?bj(t):t} start=${st?bj(st):st} dist=${f.totalDistance} timer=${f.totalTimerTime} elapsed=${f.totalElapsedTime} moving=${f.totalMovingTime} avgSpeed=${f.avgSpeed} avgHR=${f.avgHeartRate}`);
    i++;
  }
  for (const d of (messages.deviceInfoMesgs||[])) {
    const f = d.fields || d;
    console.log('DEVICE_INFO:', JSON.stringify(f, (k,v)=> v instanceof Date? v.toISOString(): v));
  }
}
