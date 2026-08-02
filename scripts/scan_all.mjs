import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';
import path from 'path';

const dir = process.argv[2] || '.';
function bj(d){ return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19); }
const files = fs.readdirSync(dir).filter(f=>f.toLowerCase().endsWith('.fit') && /merged|sdk|run/i.test(f))
  .map(f=>path.join(dir,f));

for (const IN of files) {
  try {
    const bytes = new Uint8Array(fs.readFileSync(IN));
    const proto = bytes[1];
    const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
    const laps = (messages.lapMesgs||[]).map(l=>l.fields||l);
    const laps5 = laps[4] ? laps[4].totalDistance : '?';
    const lastLap = laps.length? laps[laps.length-1].totalDistance : '?';
    const s = (messages.sessionMesgs||[])[0];
    const st = s? (s.fields||s).startTime : null;
    const ev = (messages.eventMesgs||[]).length;
    console.log(`${IN.split('\\').pop().padEnd(28)} proto=0x${proto.toString(16)} laps=${String(laps.length).padStart(2)} lap5=${String(laps5).padStart(7)} lastLap=${String(lastLap).padStart(7)} sessStart=${st?bj(st):'?'} events=${ev} err=${errors.length}`);
  } catch(e){ console.log(`${IN.split('\\').pop()}  DECODE-FAIL: ${e.message}`); }
}
