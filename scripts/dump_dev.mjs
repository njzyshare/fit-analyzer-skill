import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';
const f = process.argv[2];
const bytes = new Uint8Array(fs.readFileSync(f));
const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
console.log('=== file_id ===');
const fid = messages.fileIdMesgs[0].fields || messages.fileIdMesgs[0];
console.log(JSON.stringify(fid));
console.log('=== device_info count:', (messages.deviceInfoMesgs||[]).length, '===');
for (const m of (messages.deviceInfoMesgs||[])) {
  const x = m.fields || m;
  console.log(JSON.stringify(x));
}
console.log('=== msg type counts ===');
for (const k of Object.keys(messages)) {
  if (Array.isArray(messages[k])) console.log(k, messages[k].length);
}
if (errors.length) console.log('DECODE ERRORS:', errors.slice(0,5));
