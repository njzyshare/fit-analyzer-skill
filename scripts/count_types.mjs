import { Decoder, Stream } from '@garmin/fitsdk';
import fs from 'fs';

const files = process.argv.slice(2);
for (const IN of files) {
  const bytes = new Uint8Array(fs.readFileSync(IN));
  const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
  const counts = {};
  for (const k of Object.keys(messages)) {
    if (Array.isArray(messages[k])) counts[k] = messages[k].length;
  }
  // also find activity messages
  console.log(`\n${IN.split('\\').pop()}:`);
  console.log('  ', JSON.stringify(counts));
  // print session start_times if multiple
  const sess = messages.sessionMesgs||[];
  if (sess.length>1){ sess.forEach((s,i)=>console.log(`   session[${i}] start=`, (s.fields||s).startTime)); }
  const acts = messages.activityMesgs||[];
  if (acts.length>1){ acts.forEach((a,i)=>console.log(`   activity[${i}]`, JSON.stringify(a.fields||a))); }
  console.log('  errors=', errors.length, errors.slice(0,3));
}
