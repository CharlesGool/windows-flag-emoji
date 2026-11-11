"""把 Twemoji Mozilla 里的国旗合并进 Windows 自带的 Segoe UI Emoji。

其它表情保持 Windows 原样,只新增:
  * 258 个国家/地区旗(区域指示符对,如 🇨🇳)
  * 英格兰/苏格兰/威尔士旗(1F3F4 + 标签序列)
  * E0020-E007F 标签字符(零宽,用于上面的序列)
同时写入 COLR v0 和 v1 两套记录,新旧渲染路径都能显示。
不支持彩色字体的地方(如资源管理器文件列表)显示国家代码字母(AU、CN、ENG),和 Windows 原来一样。

用法: python build_emoji.py [原版seguiemj.ttf] [Twemoji.Mozilla.ttf] [输出.ttf]
"""
import os
import sys

from fontTools.colorLib.builder import buildCOLR
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.otlLib.builder import buildLigatureSubstSubtable
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables.C_P_A_L_ import Color

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 本工具从不覆盖系统的 seguiemj.ttf,所以系统里的永远是原版(Windows 更新后也是新版原版)
SEG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguiemj.ttf")
TW = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "src", "Twemoji.Mozilla.ttf")
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "output", "seguiemj_flags.ttf")

RI = range(0x1F1E6, 0x1F200)
TAGS = range(0xE0020, 0xE0080)
BLACK_FLAG = 0x1F3F4


# 单色回退字形:资源管理器文件列表等不支持彩色字体的地方会画它。
#   "letters" = 和 Windows 原来一样显示国家代码字母(如 AU、CN、ENG)
#   "outline" = 旗帜线稿(外框 + 色块分界线)
MONO_STYLE = "letters"
MONO_LINE = 80          # 线稿线宽(每字 2048 单位)


def mono_letters(seg_gs, letter_glyphs, advance):
    """用 Segoe UI Emoji 原有的区域指示符字母字形拼出国家代码,居中放进一个表情宽度。"""
    widths = [seg_gs[n].width for n in letter_glyphs]
    total = sum(widths)
    s = min(1.0, (advance - 120) / total)       # 太宽(如三个字母)就等比缩小
    x = (advance - total * s) / 2
    pen = TTGlyphPen(None)
    for n, w in zip(letter_glyphs, widths):
        rec = DecomposingRecordingPen(seg_gs)
        seg_gs[n].draw(rec)
        rec.replay(TransformPen(pen, (s, 0, 0, s, x, 0)))
        x += w * s
    return pen.glyph()


def mono_outline(glyphset, layers, xform):
    """把彩色旗帜的各个色块边界画成线稿(外框 + 色块分界线),而不是整块涂黑。"""
    import pathops   # 只有线稿模式需要: pip install skia-pathops
    def path_of(name):
        p = pathops.Path()
        glyphset[name].draw(TransformPen(pathops.PathPen(p), xform))
        return pathops.simplify(p, fix_winding=True)

    def stroked(p, w):
        s = pathops.Path(p)
        s.stroke(w, pathops.LineCap.BUTT_CAP, pathops.LineJoin.ROUND_JOIN, 4.0)
        s.convertConicsToQuads()
        return s

    def op(a, b, kind):
        # skia 偶尔会在复杂轮廓上失败:先简化再试,还不行就跳过这一步(只少一条分界线)
        for x, y in ((a, b), (pathops.simplify(a), pathops.simplify(b))):
            try:
                return pathops.op(x, y, kind, fix_winding=True)
            except pathops.PathOpsError:
                pass
        return a

    above = pathops.Path()           # 上层已覆盖的区域
    lines = pathops.Path()
    for name in reversed(layers):    # 从最上层往下,只取每层露出来的部分
        p = path_of(name)
        visible = op(p, above, pathops.PathOp.DIFFERENCE)
        above = op(above, p, pathops.PathOp.UNION)
        if len(visible):
            lines = op(lines, stroked(visible, MONO_LINE), pathops.PathOp.UNION)
    frame = stroked(above, 2 * MONO_LINE)            # 外框:向内 MONO_LINE 宽
    lines = op(lines, frame, pathops.PathOp.UNION)
    lines = op(lines, above, pathops.PathOp.INTERSECTION)
    out = TTGlyphPen(None)
    lines.draw(Cu2QuPen(out, max_err=1.0, reverse_direction=True))
    return out.glyph()


def union_bounds(glyphset, names):
    pen = BoundsPen(glyphset)
    for n in names:
        glyphset[n].draw(pen)
    return pen.bounds


def main():
    print("原版字体:", SEG)
    seg = TTFont(SEG)
    tw = TTFont(TW)
    if seg["name"].getDebugName(1) != "Segoe UI Emoji":
        sys.exit("输入的不是 Segoe UI Emoji")
    seg_cmap = seg.getBestCmap()
    seg_rev = {}
    for cp, g in seg_cmap.items():
        seg_rev.setdefault(cp, g)
    tw_cmap = tw.getBestCmap()
    tw_rev = {g: cp for cp, g in tw_cmap.items()}
    colr = seg["COLR"].table
    if any(r.BaseGlyph.startswith("flag_") for r in colr.BaseGlyphRecordArray.BaseGlyphRecord):
        sys.exit("这个 seguiemj.ttf 已经合并过国旗,请用原版")

    # ---- 1. 从 Twemoji 的 ccmp 连字里找出所有旗帜序列 ----
    flags = []  # (码位序列, twemoji 连字字形)
    for lk in tw["GSUB"].table.LookupList.Lookup:
        for st in lk.SubTable:
            if lk.LookupType == 7:
                st = st.ExtSubTable
            if st.LookupType != 4:
                continue
            for first, ligs in st.ligatures.items():
                for lg in ligs:
                    cps = [tw_rev.get(g) for g in [first] + lg.Component]
                    if None in cps:
                        continue
                    is_ri = len(cps) == 2 and all(c in RI for c in cps)
                    is_tag = cps[0] == BLACK_FLAG and len(cps) > 2 and all(c in TAGS for c in cps[1:])
                    if is_ri or is_tag:
                        flags.append((tuple(cps), lg.LigGlyph))
    print("找到旗帜:", len(flags))

    # ---- 2. 坐标变换:让 Twemoji 的 😀 与 Segoe 的 😀 大小、位置一致 ----
    tw_gs, seg_gs = tw.getGlyphSet(), seg.getGlyphSet()
    tw_colr = tw["COLR"]
    seg_smile = seg_cmap[0x1F600]
    seg_smile_layers = [
        colr.LayerRecordArray.LayerRecord[i].LayerGlyph
        for r in colr.BaseGlyphRecordArray.BaseGlyphRecord if r.BaseGlyph == seg_smile
        for i in range(r.FirstLayerIndex, r.FirstLayerIndex + r.NumLayers)
    ]
    tb = union_bounds(tw_gs, [l.name for l in tw_colr.ColorLayers[tw_cmap[0x1F600]]])
    sb = union_bounds(seg_gs, seg_smile_layers)
    k = (sb[3] - sb[1]) / (tb[3] - tb[1])
    dx = (sb[0] + sb[2]) / 2 - (tb[0] + tb[2]) / 2 * k
    dy = (sb[1] + sb[3]) / 2 - (tb[1] + tb[3]) / 2 * k
    xform = (k, 0, 0, k, dx, dy)
    advance = seg["hmtx"][seg_smile][0]
    print(f"缩放 {k:.3f}, 字宽 {advance}")

    # ---- 3. 颜色并入 CPAL ----
    cpal = seg["CPAL"]
    tw_pal = tw["CPAL"].palettes[0]
    color_index = {}
    for i, c in enumerate(cpal.palettes[0]):
        color_index.setdefault((c.red, c.green, c.blue, c.alpha), i)

    def seg_color(tw_id):
        c = tw_pal[tw_id]
        key = (c.red, c.green, c.blue, c.alpha)
        if key not in color_index:
            color_index[key] = len(cpal.palettes[0])
            for pal in cpal.palettes:
                pal.append(Color(*[getattr(c, a) for a in ("blue", "green", "red", "alpha")]))
        return color_index[key]

    # ---- 4. 复制字形 ----
    order = list(seg.getGlyphOrder())
    glyf, hmtx = seg["glyf"], seg["hmtx"]
    existing = set(order)

    def add_glyph(name, glyph, adv, lsb=None):
        assert name not in existing, name
        existing.add(name)
        order.append(name)
        glyf.glyphs[name] = glyph
        glyph.recalcBounds(glyf)
        hmtx.metrics[name] = (adv, getattr(glyph, "xMin", 0) if lsb is None else lsb)

    def draw_copy(names):
        pen = TTGlyphPen(None)
        tp = TransformPen(pen, xform)
        for n in names:
            tw_gs[n].draw(tp)
        return pen.glyph()

    seg.setGlyphOrder(order)  # 确保 glyf 已完整加载
    layer_map = {}
    v0_glyphs, v1_glyphs, clips = {}, {}, {}
    lig_map = {}
    for cps, tw_lig in flags:
        layers = tw_colr.ColorLayers[tw_lig]
        new_layers = []
        for L in layers:
            if L.name not in layer_map:
                nn = "flg." + L.name
                add_glyph(nn, draw_copy([L.name]), advance)
                layer_map[L.name] = nn
            new_layers.append((layer_map[L.name], seg_color(L.colorID)))
        base = "flag_" + "_".join(f"{c:X}" for c in cps)
        if MONO_STYLE == "letters":
            if cps[0] in RI:
                letters = [chr(c - 0x1F1E6 + 65) for c in cps]
            else:   # 🏴 + 标签 gbeng/gbsct/gbwls + 结束符 -> ENG/SCT/WLS
                letters = [chr(c - 0xE0000).upper() for c in cps[1:-1]][2:]
            mono = mono_letters(seg_gs, [seg_cmap[0x1F1E6 + ord(ch) - 65] for ch in letters], advance)
        else:
            mono = mono_outline(tw_gs, [L.name for L in layers], xform)
        add_glyph(base, mono, advance)  # 单色回退字形
        v0_glyphs[base] = new_layers
        v1_glyphs[base] = {
            "Format": ot.PaintFormat.PaintColrLayers,
            "Layers": [
                {"Format": ot.PaintFormat.PaintGlyph, "Glyph": g,
                 "Paint": {"Format": ot.PaintFormat.PaintSolid, "PaletteIndex": ci, "Alpha": 1.0}}
                for g, ci in new_layers
            ],
        }
        # 彩色显示的裁切框按彩色图层算(单色回退字形可能只是字母,范围更小)
        boxes = [glyf[n] for n, _ in new_layers if hasattr(glyf[n], "xMin")]
        clips[base] = (min(b.xMin for b in boxes), min(b.yMin for b in boxes),
                       max(b.xMax for b in boxes), max(b.yMax for b in boxes))
        lig_map[cps] = base

    # ---- 5. 标签字符(零宽空字形)----
    for cp in TAGS:
        if cp not in seg_cmap:
            name = f"tag{cp:X}"
            add_glyph(name, TTGlyphPen(None).glyph(), 0, 0)
            seg_rev[cp] = name
            for t in seg["cmap"].tables:
                if t.isUnicode() and t.format in (12, 13):
                    t.cmap[cp] = name
    seg.setGlyphOrder(order)
    glyf.glyphOrder = order
    if len(order) > 65535:
        sys.exit(f"字形数超限: {len(order)}")
    if len(cpal.palettes[0]) > 65535:
        sys.exit("颜色数超限")
    cpal.numPaletteEntries = len(cpal.palettes[0])

    # ---- 6. COLR:v0 和 v1 都追加 ----
    for base, layers in v0_glyphs.items():
        r = ot.BaseGlyphRecord()
        r.BaseGlyph, r.FirstLayerIndex, r.NumLayers = base, len(colr.LayerRecordArray.LayerRecord), len(layers)
        colr.BaseGlyphRecordArray.BaseGlyphRecord.append(r)
        for g, ci in layers:
            lr = ot.LayerRecord()
            lr.LayerGlyph, lr.PaletteIndex = g, ci
            colr.LayerRecordArray.LayerRecord.append(lr)

    mini1 = buildCOLR(v1_glyphs, version=1, glyphMap=seg.getReverseGlyphMap(),
                      clipBoxes=clips).table
    off1 = len(colr.LayerList.Paint)
    for r in mini1.BaseGlyphList.BaseGlyphPaintRecord:
        r.Paint.FirstLayerIndex += off1
        colr.BaseGlyphList.BaseGlyphPaintRecord.append(r)
    colr.LayerList.Paint.extend(mini1.LayerList.Paint)
    colr.LayerList.LayerCount = len(colr.LayerList.Paint)
    for g, box in mini1.ClipList.clips.items():
        colr.ClipList.clips[g] = box
    gid = seg.getGlyphID
    colr.BaseGlyphRecordArray.BaseGlyphRecord.sort(key=lambda r: gid(r.BaseGlyph))
    colr.BaseGlyphRecordCount = len(colr.BaseGlyphRecordArray.BaseGlyphRecord)
    colr.LayerRecordCount = len(colr.LayerRecordArray.LayerRecord)
    colr.BaseGlyphList.BaseGlyphPaintRecord.sort(key=lambda r: gid(r.BaseGlyph))
    colr.BaseGlyphList.BaseGlyphCount = len(colr.BaseGlyphList.BaseGlyphPaintRecord)

    # ---- 7. GSUB:在 ccmp 末尾加一个连字查找 ----
    ligs = {}
    for cps, base in lig_map.items():
        ligs[tuple(seg_rev[c] for c in cps)] = base
    st = buildLigatureSubstSubtable(ligs)
    lk = ot.Lookup()
    lk.LookupType, lk.LookupFlag, lk.SubTable, lk.SubTableCount = 4, 0, [st], 1
    gsub = seg["GSUB"].table
    gsub.LookupList.Lookup.append(lk)
    gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
    new_idx = gsub.LookupList.LookupCount - 1
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag == "ccmp":
            fr.Feature.LookupListIndex.append(new_idx)
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)

    # ---- 8. 收尾 ----
    if "DSIG" in seg:
        del seg["DSIG"]  # 原签名修改后已失效
    for rec in seg["name"].names:
        if rec.nameID == 5:
            rec.string = str(rec.toUnicode()) + "; flags from Twemoji (CC-BY 4.0)"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    seg.save(OUT)
    print(f"完成: {OUT}  字形 {len(order)}  颜色 {cpal.numPaletteEntries}  旗帜 {len(lig_map)}")


if __name__ == "__main__":
    main()
