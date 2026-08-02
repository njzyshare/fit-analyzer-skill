import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';

const IN = process.argv[2];
const bytes = new Uint8Array(fs.readFileSync(IN));
const { messages } = new Decoder(Stream.fromBuffer(bytes)).read({});
const s = (messages.sessionMesgs||[])[0];
const f = s.fields||s;
console.log(`SESSION full fields for ${IN.split('\\').pop()} (${Object.keys(f).length} keys):`);
for (const k of Object.keys(f).sort()) {
  let v = f[k];
  if (v instanceof Date) v = v.toISOString()+' (raw UTC)';
  console.log(`   ${k} = ${JSON.stringify(v)}`);
}
