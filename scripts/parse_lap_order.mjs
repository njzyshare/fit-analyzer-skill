import fs from 'fs';
// 手动 FIT 解析：按字节流真实顺序列出 lap 消息
const IN = process.argv[2];
const buf = fs.readFileSync(IN);
const p = buf;
const headerSize = p[0];
const proto = p[1];
const dataSize = p.readUInt32LE(4);
const FIT_EPOCH = Date.UTC(1989,11,31,0,0,0);
function tsToDate(v){ return new Date(FIT_EPOCH + v*1000); }
function bj(d){ return new Date(d.getTime()+8*3600*1000).toISOString().replace('T',' ').slice(0,19); }

const SIZES = {0:1,1:1,2:1,3:2,4:2,5:4,6:4,7:0,8:4,9:8,10:1,11:2,12:4,13:1,14:1,15:1,16:2};
function baseSize(bt){ const t=bt&0x7f; return SIZES[t]!==undefined?SIZES[t]:1; }

let off = headerSize;
const defs = {}; // localNum -> {msgNum, fields:[{num,size,bt}]}
let lapCount = 0;
const lapsInFileOrder = [];
let runningTs = 0;

while (off < headerSize + dataSize) {
  const hdr = p[off];
  if (hdr & 0x80) {
    // definition
    const localNum = hdr & 0x0f;
    const reserved = p[off+1];
    const arch = p[off+2];
    const msgNum = p.readUInt16LE(off+3);
    const nfields = p[off+5];
    let o = off+6;
    const fields = [];
    for (let i=0;i<nfields;i++){
      const num = p[o]; const size = p[o+1]; const bt = p[o+2];
      fields.push({num,size,bt});
      o += 3;
    }
    defs[localNum] = {msgNum, fields};
    off = o;
  } else {
    // data
    const localNum = hdr & 0x0f;
    const def = defs[localNum];
    if (!def) { console.log('MISSING DEF for local', localNum, 'at off', off); break; }
    let o = off+1;
    const vals = {};
    let thisTs = runningTs;
    for (const f of def.fields) {
      const raw = p.slice(o, o+f.size);
      let v = null;
      const t = f.bt & 0x7f;
      if (t===0||t===1||t===2||t===10||t===13){ v = raw[0]; }
      else if (t===3||t===11){ v = raw.readInt16LE(0); }
      else if (t===4||t===12){ v = raw.readUInt16LE(0); }
      else if (t===5){ v = raw.readInt32LE(0); }
      else if (t===6||t===14){ v = raw.readUInt32LE(0); }
      else if (t===8){ v = raw.readFloatLE(0); }
      else if (t===9){ v = raw.readDoubleLE(0); }
      else if (t===7){ v = raw.toString('latin1').replace(/\0.*/,''); }
      vals[f.num] = v;
      if (f.num===253) { thisTs = v; runningTs = v; }
      o += f.size;
    }
    if (def.msgNum===19) { // lap
      lapsInFileOrder.push({
        filePos: lapCount,
        messageIndex: vals[254],
        startTime: vals[2]!=null ? bj(tsToDate(vals[2])) : (thisTs!=null?bj(tsToDate(thisTs)):'?'),
        totalDistance: vals[7]!=null ? (vals[7]/100) : vals[7],
      });
      lapCount++;
    }
    off = o;
  }
}
console.log(`FILE ${IN.split('\\').pop()} proto=0x${proto.toString(16)} headerSize=${headerSize} dataSize=${dataSize}`);
console.log(`Lap messages in RAW FILE ORDER (${lapsInFileOrder.length}):`);
lapsInFileOrder.forEach(l=>{
  const flag = (l.totalDistance!=null && l.totalDistance<500) ? '  <== SHORT' : '';
  console.log(`  filePos=${String(l.filePos).padStart(2)} msgIdx=${l.messageIndex} start=${l.startTime} dist=${l.totalDistance}${flag}`);
});
// 检查：短圈是否在前面
const shortPos = lapsInFileOrder.findIndex(l=>l.totalDistance!=null && l.totalDistance<500);
console.log(`\nSHORT lap raw filePos = ${shortPos} (if != last, order is broken)`);
