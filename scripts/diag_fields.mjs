import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';

const files = process.argv.slice(2);
function bj(d){ return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19); }

for (const IN of files) {
  const bytes = new Uint8Array(fs.readFileSync(IN));
  const proto = bytes[1];
  const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
  console.log(`\n################ ${IN}  proto=0x${proto.toString(16)}  decodeErrors=${errors.length} ################`);

  const dumpFields = (label, m)=>{
    if(!m) { console.log(label, '= MISSING'); return; }
    const f = m.fields||m;
    console.log(`\n${label} (keys=${Object.keys(f).length}):`);
    for (const k of Object.keys(f)) {
      let v = f[k];
      if (v instanceof Date) v = bj(v)+' (local+8)';
      console.log(`   ${k} = ${JSON.stringify(v)}`);
    }
  };

  dumpFields('FILE_ID', (messages.fileIdMesgs||[])[0]);
  dumpFields('SESSION', (messages.sessionMesgs||[])[0]);
  const laps = messages.lapMesgs||[];
  dumpFields('LAP[0]', laps[0]);
  dumpFields('LAP[last]', laps[laps.length-1]);
  dumpFields('DEVICE_INFO[0]', (messages.deviceInfoMesgs||[])[0]);
}
