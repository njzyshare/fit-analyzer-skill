#!/usr/bin/env node
/**
 * FIT 编码器 — 从 stdin JSON 读取数据，输出 .fit 到 stdout
 *
 * 用法:
 *   node fit_encode.mjs < input_data.json > output.fit
 *   cat data.json | node fit_encode.mjs > activity.fit
 *
 * JSON 输入格式:
 * {
 *   "points": [                         // record 数据点（必选）
 *     {
 *       "lat": 24.614057,               // WGS84 纬度（度数）
 *       "lon": 118.1377545,             // WGS84 经度（度数）
 *       "ts": 1766274707000,            // Unix 毫秒时间戳
 *       "hr": 173,                      // 心率（可选，null/省略=255）
 *       "cadence": 179,                 // 步频（可选，null/省略=255）
 *       "distance": 0,                  // 累计距离（米，可选）
 *       "altitude": 10.5,               // 海拔（米，可选，null/省略=65535）
 *       "speed": 3.446,                 // 速度（m/s，可选，null/省略=0）
 *     }
 *   ],
 *   "laps": [                           // 计圈（可选）
 *     {
 *       "start_idx": 0,                 // 对应 points 中的索引范围
 *       "end_idx": 290,
 *       "totalDistance": 1003,
 *       "totalElapsedTime": 291,
 *       "avgHeartRate": 162,
 *       "maxHeartRate": 173,
 *       "avgCadence": 180,
 *       "avgSpeed": 3.45,
 *       "maxSpeed": 3.7,
 *       "totalCalories": 75,
 *     }
 *   ],
 *   "session": {                        // 会话概要（必选）
 *     "startTime": 1766274707000,       // Unix ms
 *     "totalTime": 6199000,             // 总计时长（ms）
 *     "totalDistance": 21360,           // 总距离（米）
 *     "totalCalories": 1588,            // 总卡路里（kcal）
 *     "avgHeartRate": 173,
 *     "maxHeartRate": 190,
 *     "avgCadence": 179,
 *     "maxCadence": 186,
 *     "sport": "running",               // 运动类型
 *     "subSport": "generic",
 *   },
 *   "manufacturer": 1,                  // 制造商（默认1=generic）
 *   "product": 1,                       // 产品ID（默认1）
 *   "productName": "huawei",            // 产品名（默认"huawei"）
 *   "serialNumber": 3500000001,         // 序列号（随机生成）
 * }
 */

import {Encoder, Decoder, Stream, Profile} from '@garmin/fitsdk';

// ===== 读取 stdin =====
let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const buf = encodeFit(data);
    process.stdout.write(Buffer.from(buf));
  } catch (e) {
    process.stderr.write(`[ERROR] ${e.message}\n`);
    process.stderr.write(e.stack + '\n');
    process.exit(1);
  }
});

// ===== FIT 编码 =====
function encodeFit(data) {
  const pts = data.points || [];
  const laps = data.laps || [];
  const session = data.session || {};
  const serialNumber = data.serialNumber || (3500000000 + Math.floor(Math.random() * 10000000));
  const manufacturer = data.manufacturer || 1;
  const product = data.product || 1;
  const productName = data.productName || 'huawei';

  if (pts.length === 0) throw new Error('points array is empty');

  const FIT_INVALID_U8 = 255;
  const FIT_INVALID_U16 = 65535;

  // 时间对象
  const startDate = new Date(session.startTime || pts[0].ts);
  const endDate = new Date(session.startTime + session.totalTime || pts[pts.length - 1].ts);

  // 半圆坐标转换
  function toSemi(v) {
    return Math.round(v * (2 ** 32 / 360));
  }

  const enc = new Encoder();

  // file_id
  enc.writeMesg({
    mesgNum: Profile.MesgNum.FILE_ID,
    type: 'activity',
    manufacturer: manufacturer,
    serialNumber: serialNumber,
    product: product,
    timeCreated: startDate,
    productName: productName,
  });

  // device_info
  try {
    enc.writeMesg({
      mesgNum: Profile.MesgNum.DEVICE_INFO,
      timestamp: endDate,
      deviceIndex: 0,
      manufacturer: manufacturer,
      serialNumber: serialNumber,
      product: product,
      sourceType: 'local',
    });
  } catch (e) {}

  // device_settings
  try {
    enc.writeMesg({
      mesgNum: Profile.MesgNum.DEVICE_SETTINGS,
      activeTimeZone: 0,
      utcOffset: 28800,
      timeMode: ['hour24'],
      dateMode: 'monthDay',
    });
  } catch (e) {}

  // user_profile
  try {
    enc.writeMesg({
      mesgNum: Profile.MesgNum.USER_PROFILE,
      gender: 'male',
      age: 34,
      weight: 74,
      height: 1.77,
      restingHeartRate: 60,
      weightSetting: 'metric',
      heightSetting: 'metric',
      distSetting: 'metric',
    });
  } catch (e) {}

  // file_creator
  try {
    enc.writeMesg({
      mesgNum: Profile.MesgNum.FILE_CREATOR,
      softwareVersion: 2238,
    });
  } catch (e) {}

  // sport
  try {
    enc.writeMesg({
      mesgNum: Profile.MesgNum.SPORT,
      sport: session.sport || 'running',
      subSport: session.subSport || 'generic',
    });
  } catch (e) {}

  // event: start
  enc.writeMesg({
    mesgNum: Profile.MesgNum.EVENT,
    timestamp: new Date(pts[0].ts),
    event: 'timer',
    eventType: 'start',
    eventGroup: 0,
  });

  // records — 固定字段布局
  for (const p of pts) {
    const rec = {
      mesgNum: Profile.MesgNum.RECORD,
      timestamp: new Date(p.ts),
      positionLat: p.lat != null ? toSemi(p.lat) : 0,
      positionLong: p.lon != null ? toSemi(p.lon) : 0,
      heartRate: (p.hr != null && p.hr > 0) ? p.hr : FIT_INVALID_U8,
      cadence: (p.cadence != null && p.cadence > 0) ? p.cadence : FIT_INVALID_U8,
      distance: p.distance != null ? p.distance : 0,
      speed: p.speed != null ? p.speed : 0,
      enhancedSpeed: p.speed != null ? p.speed : 0,
      enhancedAltitude: p.altitude != null ? Math.round(p.altitude) : FIT_INVALID_U16,
    };
    enc.writeMesg(rec);
  }

  // event: stop
  enc.writeMesg({
    mesgNum: Profile.MesgNum.EVENT,
    timestamp: new Date(pts[pts.length - 1].ts),
    event: 'timer',
    eventType: 'stop',
    eventGroup: 0,
  });

  // time_in_zone (optional)
  if (session.timeInZone && session.timeInZone.length > 0) {
    try {
      for (const tz of session.timeInZone) {
        enc.writeMesg({
          mesgNum: Profile.MesgNum.TIME_IN_ZONE,
          timestamp: endDate,
          referenceMesg: 'session',
          referenceIndex: 0,
          timeInZone: tz.seconds,
          hrZone: tz.zone,
        });
      }
    } catch (e) {}
  }

  // laps
  for (let i = 0; i < laps.length; i++) {
    const lap = laps[i];
    const lapStart = new Date(lap.startTime || pts[lap.start_idx || 0].ts);
    const lapEnd = new Date(lap.endTime || pts[lap.end_idx || pts.length - 1].ts);
    const ld = {
      mesgNum: Profile.MesgNum.LAP,
      messageIndex: i,
      timestamp: lapEnd,
      startTime: lapStart,
      totalElapsedTime: lap.totalElapsedTime || 0,
      totalTimerTime: lap.totalElapsedTime || 0,
      totalDistance: lap.totalDistance || 0,
      startPositionLat: lap.startLat != null ? toSemi(lap.startLat) : undefined,
      startPositionLong: lap.startLon != null ? toSemi(lap.startLon) : undefined,
      endPositionLat: lap.endLat != null ? toSemi(lap.endLat) : undefined,
      endPositionLong: lap.endLon != null ? toSemi(lap.endLon) : undefined,
      avgSpeed: lap.avgSpeed || 0,
      maxSpeed: lap.maxSpeed || 0,
      avgHeartRate: lap.avgHeartRate || undefined,
      maxHeartRate: lap.maxHeartRate || undefined,
      avgCadence: lap.avgCadence || undefined,
      totalCalories: lap.totalCalories || 0,
      event: 'lap',
      eventType: 'stop',
      lapTrigger: 'distance',
      sport: session.sport || 'running',
      subSport: session.subSport || 'generic',
    };
    // 清理 undefined
    for (const k of Object.keys(ld)) if (ld[k] === undefined) delete ld[k];
    enc.writeMesg(ld);
  }

  // session
  const totalTimeSec = session.totalTime ? session.totalTime / 1000 : 0;
  const avgSpeed = session.totalDistance && totalTimeSec > 0 ? session.totalDistance / totalTimeSec : 0;
  enc.writeMesg({
    mesgNum: Profile.MesgNum.SESSION,
    timestamp: endDate,
    startTime: startDate,
    totalElapsedTime: totalTimeSec,
    totalTimerTime: totalTimeSec,
    totalDistance: session.totalDistance || 0,
    avgSpeed: avgSpeed,
    enhancedAvgSpeed: avgSpeed,
    maxSpeed: session.maxSpeed || avgSpeed,
    enhancedMaxSpeed: session.maxSpeed || avgSpeed,
    avgHeartRate: session.avgHeartRate || undefined,
    maxHeartRate: session.maxHeartRate || undefined,
    totalCalories: session.totalCalories || 0,
    numLaps: laps.length,
    sport: session.sport || 'running',
    subSport: session.subSport || 'generic',
    trigger: 'activityEnd',
    event: 'session',
    eventType: 'stop',
    avgCadence: session.avgCadence || undefined,
    maxCadence: session.maxCadence || undefined,
    totalTrainingEffect: session.trainingEffect || undefined,
    totalAnaerobicTrainingEffect: session.anaerobicTrainingEffect || undefined,
  });

  // activity
  enc.writeMesg({
    mesgNum: Profile.MesgNum.ACTIVITY,
    timestamp: endDate,
    localTimestamp: Math.round(endDate.getTime() / 1000 + 28800),
    numSessions: 1,
    type: 'manual',
    event: 'activity',
    eventType: 'stop',
    eventGroup: 0,
  });

  return enc.close();
}
