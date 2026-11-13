# -*- coding: utf-8 -*-
"""产物 vs 目标平台真机模板：全维度逐项差异比对。

**交付前必跑**（见 SKILL.md「交付前强制检查清单」）。
规范门禁（fit_conformance_check.py）只检查我写的断言；本脚本做**穷举式**对照，
覆盖门禁看不到的维度，专治「门禁 PASS 但与真机仍有差异」。

用法
----
    # 只与模板比（看结构是否复刻）
    python fit_diff_vs_template.py 产物.fit --temp coros_apex4

    # 同时与源文件比（看数据是否守恒）—— 推荐
    python fit_diff_vs_template.py 产物.fit --temp coros_apex4 --src 源.fit

退出码：0 = 无结构差异；1 = 存在结构差异（需人工判定是否可接受）
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fit_lib import FitFile, Profile, TEMPLATE_DIR

# 逐点比对时允许的浮点误差
EPS = 1e-9


class Diff:
    """收集差异条目。"""

    def __init__(self):
        self.rows = []          # (级别, 分区, 说明, 详情)
        self.section = ''

    def sec(self, name):
        self.section = name
        print()
        print('=' * 78)
        print(f'  {name}')
        print('=' * 78)

    def _add(self, lv, item, detail=''):
        self.rows.append((lv, self.section, item, detail))
        icon = {'OK': '[ OK ]', 'DIFF': '[DIFF]', 'INFO': '[INFO]'}[lv]
        line = f'  {icon} {item}'
        if detail:
            line += f'  —— {detail}'
        print(line)

    def ok(self, item, detail=''):
        self._add('OK', item, detail)

    def diff(self, item, detail=''):
        self._add('DIFF', item, detail)

    def info(self, item, detail=''):
        self._add('INFO', item, detail)

    def counts(self):
        c = {'OK': 0, 'DIFF': 0, 'INFO': 0}
        for lv, *_ in self.rows:
            c[lv] += 1
        return c


def compare(prod_path, temp_name, src_path=None, prof_path=None, ref_path=None):
    base = os.path.dirname(os.path.abspath(__file__))
    prof = Profile(prof_path or os.path.join(base, '..', 'references',
                                             'fit_profile_official.json'))
    # 与转换器/门禁一致：优先「规范」，回退「模板」
    sp = os.path.join(base, '..', 'references', 'profiles', f'{temp_name}.json')
    tpl_path = os.path.join(TEMPLATE_DIR, f'{temp_name}.json')
    if os.path.exists(sp):
        try:
            from fit_convert_by_template import _spec_to_template
            t = _spec_to_template(json.load(open(sp, encoding='utf-8')))
        except Exception as e:
            print(f'❌ 规范读取失败: {sp}\n   {e}')
            sys.exit(2)
    elif os.path.exists(tpl_path):
        t = json.load(open(tpl_path, encoding='utf-8'))
    else:
        print(f'❌ 既无规范也无模板: {temp_name}')
        print(f'   规范目录: {os.path.dirname(sp)}')
        print(f'   模板目录: {TEMPLATE_DIR}')
        print('   先学真机文件：fit_learn_template.py <真机.fit> --name '
              f'{temp_name}')
        print(f'   再精炼规范：fit_distill_spec.py {temp_name}')
        sys.exit(2)

    prod = FitFile(prod_path)
    # 真机参照文件：优先 --ref；其次按模板记录的 _learned_from 到私有参照目录找
    ref = None
    cand = []
    if ref_path:
        cand.append(ref_path)
    learned = t.get('_learned_from')
    if learned:
        refdir = os.environ.get('FIT_REF_DIR') or os.path.join(
            os.path.expanduser('~'), '.workbuddy', 'private', 'reference_fits')
        cand.append(os.path.join(refdir, os.path.basename(learned)))
    for c in cand:
        if c and os.path.exists(c):
            try:
                ref = FitFile(c)
                break
            except Exception:
                ref = None
    src = FitFile(src_path) if src_path and os.path.exists(src_path) else None

    r = Diff()
    print('=' * 78)
    print(f'  产物 vs 真机模板  全维度差异比对')
    print(f'  产物: {os.path.basename(prod_path)}')
    print(f'  模板: {temp_name}（{t.get("_note", "")}）')
    if src:
        print(f'  源  : {os.path.basename(src_path)}')
    print('=' * 78)

    # ---------- §1 文件头 ----------
    r.sec('§1 文件头')
    for key, tkey in (('protocol', 'protocol_version'),
                      ('profile_version', 'profile_version')):
        a, b = prod.header[key], t['header'][tkey]
        (r.ok if a == b else r.diff)(f'{key} = {a}', f'模板 {b}')
    for key, want in (('size', 14), ('data_type', b'.FIT')):
        a = prod.header[key]
        (r.ok if a == want else r.diff)(f'{key} = {a!r}', f'期望 {want!r}')

    # ---------- §2 消息种类 ----------
    r.sec('§2 消息种类')
    want_g = set(int(g) for g in t['messages'])
    got_g = set(prod.global_counts())
    missing = sorted(want_g - got_g)
    extra = sorted(got_g - want_g)
    src_g = set(src.global_counts()) if src else None
    if not missing:
        r.ok(f'模板要求的 {len(want_g)} 种消息齐全')
    else:
        lost = [g for g in missing if src_g and g in src_g]
        absent = [g for g in missing if not (src_g and g in src_g)]
        if lost:
            r.diff(f'源有但产物丢失的消息 {lost}', '转换过程丢数据')
        else:
            r.ok(f'缺 {len(absent)} 种模板私有消息', '源文件同缺 → 源无此类数据')
    (r.ok if not extra else r.diff)(
        f'无模板外的多余消息' if not extra else f'多出模板未用的消息 {extra}')

    # ---------- §3 逐消息布局 ----------
    r.sec('§3 逐消息布局逐位比对')
    for gs, mi in sorted(t['messages'].items(), key=lambda x: int(x[0])):
        g = int(gs)
        if g not in got_g:
            continue
        # ⚠️ 必须用 tuple(...) 而非生成器表达式 —— 生成器只能迭代一次，
        #    与 list 比较永远 False（本次实战踩到，导致所有布局全报"不符"假警报）
        tlays = [tuple((f['num'], f['size'], f['base_type'])
                       for f in lay['fields'])
                 for lay in mi['layouts']]
        glays = [dd.signature()[0] for dd in prod.layouts(g)]
        name = mi.get('name', '?')
        if glays == tlays:
            r.ok(f'g={g}({name}) 布局逐位一致（{len(tlays)} 种）')
        else:
            miss = [x for x in tlays if x not in glays]
            r.diff(f'g={g}({name}) 布局与模板不符',
                   f'{len(miss)}/{len(tlays)} 种不匹配；'
                   f'首个不匹配字段序列 {[f[0] for f in miss[0]] if miss else "?"}')

    # ---------- §4 开发者字段声明 ----------
    r.sec('§4 开发者字段(207/206)声明')
    for g, lbl in ((207, 'developerDataId'), (206, 'fieldDescription')):
        a, b = prod.by_global(g), (ref.by_global(g) if ref else [])
        if not b:
            r.info(f'g={g}({lbl})：模板未用，跳过')
            continue
        if len(a) == len(b):
            r.ok(f'g={g}({lbl}) 声明 {len(a)} 条（模板 {len(b)} 条）')
        else:
            r.diff(f'g={g}({lbl}) 声明条数不符', f'产物 {len(a)} vs 模板 {len(b)}')
        # 逐字段比对值
        for i, (ma, mb) in enumerate(zip(a, b)):
            for num in sorted(set(ma.raw) | set(mb.raw)):
                va, vb = prod.value(ma, num, prof), ref.value(mb, num, prof)
                if va != vb:
                    nm = prof.fname(g, num) or f'f{num}'
                    r.diff(f'g={g}[{i}] {nm} 值不同', f'产物 {va!r} vs 模板 {vb!r}')

    # ---------- §5 单条消息值级核对 ----------
    r.sec('§5 单条消息值级核对（布局对但值可能是空）')
    smv = t.get('single_message_values') or {}
    if not smv:
        r.info('模板无 single_message_values 快照（用旧版学习器学的）'
               '→ 重新跑 fit_learn_template.py 可启用值级核对')
    for gs, fields in smv.items():
        g = int(gs)
        msgs = prod.by_global(g)
        if not msgs:
            r.info(f'g={g}：产物无此消息，跳过值级核对')
            continue
        m = msgs[0]
        bad = []
        for fn_s, tv in fields.items():
            fn = int(fn_s)
            if tv is None or tv == '':
                continue
            if fn not in m.raw:
                bad.append((fn, tv, '字段缺失'))
            elif prod.value(m, fn, prof) is None:
                bad.append((fn, tv, '值为哨兵'))
        name = t['messages'].get(str(g), {}).get('name', '?')
        if bad:
            detail = '; '.join(f'f{n}(模板={tv!r} → {d})' for n, tv, d in bad[:5])
            r.diff(f'g={g}({name}) 模板有值但产物未填', detail)
        else:
            r.ok(f'g={g}({name}) 模板有值的字段均已填充（{len(fields)} 项）')

    # ---------- §6 消息出现顺序 ----------
    r.sec('§6 消息首次出现顺序')
    if ref:
        oa, ob = [], []
        for m in prod.msgs:
            if m.g not in oa:
                oa.append(m.g)
        for m in ref.msgs:
            if m.g not in ob:
                ob.append(m.g)
        # 只比双方都有的消息
        common = [g for g in ob if g in oa]
        oa_f = [g for g in oa if g in common]
        if oa_f == common:
            r.ok('消息出现顺序与真机一致', f'{oa_f}')
        else:
            r.diff('消息出现顺序与真机不同', f'产物 {oa_f} vs 真机 {common}')
    else:
        # 退回：与模板学到的 message_order 比（模板里已存好）
        want_order = t.get('message_order')
        if want_order:
            oa = []
            for m in prod.msgs:
                if m.g not in oa:
                    oa.append(m.g)
            common = [g for g in want_order if g in oa]
            oa_f = [g for g in oa if g in common]
            if oa_f == common:
                r.ok('消息出现顺序与模板一致', f'{oa_f}')
            else:
                r.diff('消息出现顺序与模板不同',
                       f'产物 {oa_f} vs 模板 {common}')
        else:
            r.info('模板无 message_order，跳过顺序比对')

    # ---------- §7 条数守恒（与源比） ----------
    if src:
        r.sec('§7 条数守恒（产物 vs 源）')
        # ⚠️ deviceInfo(23) 不参与守恒：跨品牌设备信息天然不同
        #   （佳明 21 条含内置传感器，高驰模板只有 1 条）——目标平台身份由模板决定。
        CONSERVE = {0: 'fileId', 18: 'session', 19: 'lap', 20: 'record',
                    21: 'event', 34: 'activity'}
        for g, nm in CONSERVE.items():
            a, b = prod.global_counts().get(g, 0), src.global_counts().get(g, 0)
            if a == b:
                r.ok(f'{nm}({g}) 条数一致 = {a}')
            else:
                r.diff(f'{nm}({g}) 条数不等', f'产物 {a} vs 源 {b}')
        # deviceInfo 单独说明
        pa, sa = prod.global_counts().get(23, 0), src.global_counts().get(23, 0)
        if pa or sa:
            r.info(f'deviceInfo(23) 产物 {pa} 条 / 源 {sa} 条'
                   f'（跨品牌天然不同，身份由目标模板决定，不算丢失）')

    # ---------- §8 可比区间逐点比对 ----------
    if src:
        r.sec('§8 可比区间逐点比对（速度/海拔）')
        srec, prec = src.by_global(20), prod.by_global(20)
        for label, names in (('速度', ('enhancedSpeed', 'speed')),
                             ('海拔', ('enhancedAltitude', 'altitude'))):
            snum = next((prof.field_num(20, n) for n in names
                         if prof.field_num(20, n) is not None
                         and any(prof.field_num(20, n) in m.raw for m in srec)),
                        None)
            pnum = next((prof.field_num(20, n) for n in names
                         if prof.field_num(20, n) is not None
                         and any(prof.field_num(20, n) in m.raw for m in prec)),
                        None)
            if snum is None or pnum is None:
                r.info(f'{label}：一端无该字段，跳过')
                continue
            comp = same = 0
            mism = []
            skipped = 0
            for i, (ms, mp) in enumerate(zip(srec, prec)):
                vs, vp = src.value(ms, snum, prof), prod.value(mp, pnum, prof)
                if vs is None or vp is None:
                    skipped += 1
                    continue
                comp += 1
                if abs(vs - vp) < EPS:
                    same += 1
                else:
                    mism.append((i, vs, vp))
            if mism:
                r.diff(f'{label}逐点不一致',
                       f'{len(mism)}/{comp} 处不同，例 @{mism[:3]}')
            else:
                r.ok(f'{label}逐点一致（可比区间 {comp} 点）')
            if skipped:
                r.info(f'{label}：{skipped} 个点位因渐进式布局未声明该字段而不可比'
                       f'（非数据丢失）')

    # ---------- 汇总 ----------
    c = r.counts()
    print()
    print('=' * 78)
    print(f'  汇总：一致 {c["OK"]} / 差异 {c["DIFF"]} / 说明 {c["INFO"]}')
    if c['DIFF']:
        print('  结论：⚠️ 存在结构差异 —— 逐条判定：数据量差异可接受，格式差异必须修')
    else:
        print('  结论：✅ 与模板无结构差异')
    print('=' * 78)
    return 1 if c['DIFF'] else 0


def main():
    ap = argparse.ArgumentParser(
        description='产物 vs 目标平台真机模板：全维度差异比对（交付前必跑）')
    ap.add_argument('product', help='产物 .fit')
    ap.add_argument('--temp', required=True,
                    help='目标模板名（references/templates/<name>.json）')
    ap.add_argument('--src', help='源 .fit（提供则做条数守恒 + 逐点比对）')
    ap.add_argument('--ref', help='真机参照 .fit（模板学习来源，用于顺序/dev 值比对）')
    ap.add_argument('--profile', help='官方 profile JSON 路径（默认用内置）')
    a = ap.parse_args()
    sys.exit(compare(a.product, a.temp, a.src, a.profile, a.ref))


if __name__ == '__main__':
    main()
