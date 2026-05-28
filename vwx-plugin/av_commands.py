"""
av_commands.py — AV Ballroom Previz Extension for vwx-mcp

Loaded automatically by the patched vwx_mcp_bridge.py alongside commands.py.
All coordinate units: millimetres.
Origin convention: (0,0) = room floor center.  +Y = toward stage (north wall).

Requires: commands.py helpers (_c8, _h, _oid, _bbox, _collect,
          _with_layer_class, _restore, _newobj_result, _safe, AV record names).
"""

import vs
import math as _math
import traceback

# Re-use helpers from commands.py (already in scope when loaded via exec/import)
# If running standalone, define minimal stubs so this file is parseable.
try:
    _c8  # noqa: F821  — defined in commands.py
except NameError:
    def _c8(v): return min(65535, int(v) * 257)
    def _c255(v): return round(v / 257)
    def _oid(h): return None
    def _h(oid): return None
    def _bbox(h): return None
    def _collect(c, lim=500): return []
    def _with_layer_class(p): return (None, None)
    def _restore(prev): pass
    def _newobj_result(p, fallback=None): return {'status': 'ok'}
    def _safe(fn, default=None):
        try: return fn()
        except: return default

# ─────────────────────────────────────────────────────────────────────────────
# Record format names
# ─────────────────────────────────────────────────────────────────────────────

AV_REC_DEVICE  = 'AV Device'
AV_REC_RIGGING = 'AV Rigging Point'
AV_REC_CABLE   = 'AV Cable'
AV_REC_SEAT    = 'AV Seat'         # theater/corporate seat assignment record


# ─────────────────────────────────────────────────────────────────────────────
# Standard layer / class tables
# ─────────────────────────────────────────────────────────────────────────────

_AV_LAYERS = [
    # Venue shell
    'AV-Room',        # room boundary
    'AV-Stage',       # stage platform / risers
    # Technical systems
    'AV-Rigging',     # truss, motors, fly points
    'AV-Lighting',    # lighting positions (Spotlight-compatible layer name)
    'AV-Audio',       # speakers, subs, monitors
    'AV-Video',       # screens, LED walls, projectors, confidence monitors
    'AV-Power',       # power distribution
    'AV-Signal',      # cable runs
    # Event layout
    'AV-Seating',     # audience tables and chairs
    'AV-Head-Table',  # corporate head table / dais / panel table
    'AV-FOH',         # mix positions, production desks
    'AV-Cameras',     # camera positions (broadcast, streaming, recording)
    'AV-ADA',         # accessible seating positions
    # Documentation
    'AV-Dims',
    'AV-Notes',
]

# (fill_rgb, pen_rgb, lw_hundredths_mm)
_AV_CLASSES = {
    'AV-Stage':         ((80,  80,  80), (40,  40,  40),  35),
    'AV-Rigging':       ((220,120,  20),(180, 80,   0),   35),
    'AV-Speaker':       ((30, 100, 200),(  0, 60, 160),   35),
    'AV-Subwoofer':     ((10,  60, 140),(  0, 30, 100),   35),
    'AV-Screen':        ((200, 30,  80),(160,  0,  50),   35),
    'AV-LED-Wall':      ((240, 20,  60),(200,  0,  30),   50),
    'AV-Truss':         ((220,140,   0),(180,100,   0),   50),
    'AV-Motor':         ((255,160,   0),(200,120,   0),   25),
    'AV-Power-Distro':  ((200,100,   0),(160, 60,   0),   35),
    'AV-Cable-Audio':   ((50, 150, 255),( 20,100, 200),   18),
    'AV-Cable-Video':   ((220, 50, 100),(180, 10,  60),   18),
    'AV-Cable-Power':   ((255,140,   0),(200, 90,   0),   18),
    'AV-Cable-Data':    ((80, 200,  80),( 40,160,  40),   18),
    'AV-Seating-Table': ((220,200, 180),(120,120, 120),   18),
    'AV-Seating-Chair': ((180,180, 180),(100,100, 100),   13),
    'AV-FOH':           ((80, 180,  80),( 40,130,  40),   35),
    'AV-Dims':          ((  0,  0,   0),(  0,  0,   0),   18),
    'AV-Notes':         (( 40, 40,  40),( 20, 20,  20),   13),
    'AV-Coverage':      (( 50, 150, 255), ( 20, 100, 200),  13),
    # Corporate / Spotlight additions
    'AV-Podium':        ((200, 200, 200), (100, 100, 100),  35),
    'AV-Camera':        (( 30,  30,  30), (  0,   0,   0),  50),
    'AV-Confidence-Mon':((200,  30,  80), (160,   0,  50),  35),
    'AV-Head-Table':    ((240, 220, 175), (120,  95,  45),  35),
    'AV-Theater-Chair': ((200, 200, 215), ( 90,  90, 110),  13),
    'AV-ADA':           (( 40, 175,  80), ( 15, 135,  50),  25),
    'AV-Registration':  (( 90, 190, 235), ( 40, 140, 190),  35),
    'AV-Cocktail-Table':((235, 215, 195), (125, 110,  90),  25),
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _av_class_exists(name):
    try:
        for i in range(1, vs.ClassNum() + 1):
            if _safe(lambda i=i: vs.GetClName(i)) == name:
                return True
    except Exception:
        pass
    return False


def _av_set_class_style(name, fill_rgb, pen_rgb, lw_hundredths):
    try:
        vs.NameClass(name)
        fr, fg, fb = fill_rgb
        pr, pg, pb = pen_rgb
        vs.SetClFillFore(name, (_c8(fr), _c8(fg), _c8(fb)))
        vs.SetClFillBack(name, (_c8(fr), _c8(fg), _c8(fb)))
        vs.SetClPenFore(name,  (_c8(pr), _c8(pg), _c8(pb)))
        vs.SetClPenBack(name,  (_c8(pr), _c8(pg), _c8(pb)))
        vs.SetClLW(name, lw_hundredths)
    except Exception:
        pass


def _av_attach_record(h, rec_name, fields_dict):
    """Attach a record to handle h and set field values (silently ignores errors)."""
    try:
        vs.SetRecord(h, rec_name)
        for k, v in fields_dict.items():
            try: vs.SetRField(h, rec_name, k, str(v))
            except Exception: pass
    except Exception:
        pass


def _av_draw_text(x, y, text, size_mm=150, align='center', layer=None, cls=None):
    """Convenience: place a single text object, return handle."""
    if layer: vs.Layer(layer)
    if cls:   vs.NameClass(cls)
    amap = {'left': 1, 'center': 2, 'right': 3}
    vs.TextOrigin((x, y))
    vs.TextJust(amap.get(align, 2))
    vs.TextSize(size_mm)
    vs.CreateText(text)
    return vs.LNewObj()


# ─────────────────────────────────────────────────────────────────────────────
# Document setup
# ─────────────────────────────────────────────────────────────────────────────

def av_setup_document(p):
    """Create AV standard layers, classes, and record formats.

    Idempotent — existing layers/classes/records are left untouched.
    Returns counts of created vs. already-existing items."""
    created_layers, existing_layers = [], []
    created_classes, existing_classes = [], []
    record_results = []

    # Layers
    for name in _AV_LAYERS:
        if vs.GetLayerByName(name):
            existing_layers.append(name)
        else:
            try:
                vs.CreateLayer(name, 1)  # type 1 = design layer
                created_layers.append(name)
            except Exception as e:
                created_layers.append(f'{name}(ERR:{e})')

    # Classes
    for name, (fill, pen, lw) in _AV_CLASSES.items():
        if _av_class_exists(name):
            existing_classes.append(name)
        else:
            _av_set_class_style(name, fill, pen, lw)
            created_classes.append(name)

    # Record formats
    for rec_name, fields in [
        (AV_REC_DEVICE, [
            ('Device_Type', '', 4), ('Model', '', 4), ('Label', '', 4),
            ('Channel', '', 4), ('Weight_kg', '0', 3), ('Power_W', '0', 1),
            ('Trim_mm', '0', 1), ('Notes', '', 4),
        ]),
        (AV_REC_RIGGING, [
            ('Point_ID', '', 4), ('Trim_mm', '0', 1), ('Load_kg', '0', 3),
            ('Capacity_kg', '500', 3), ('Motor_Type', '', 4),
            ('Chain_mm', '0', 1), ('Notes', '', 4),
        ]),
        (AV_REC_CABLE, [
            ('Cable_Type', 'audio', 4), ('Length_mm', '0', 1),
            ('From_Device', '', 4), ('To_Device', '', 4),
            ('Connector_A', '', 4), ('Connector_B', '', 4), ('Notes', '', 4),
        ]),
        (AV_REC_SEAT, [
            ('Row', '', 4), ('Seat_Num', '0', 1), ('Section', 'General', 4),
            ('ADA', 'No', 4), ('Status', 'Available', 4), ('Assignment', '', 4),
        ]),
    ]:
        try:
            if vs.GetObject(rec_name):
                record_results.append(f'{rec_name}: exists')
            else:
                # NewField creates the record if it doesn't exist (first call)
                sentinel, first = '_sentinel_', True
                for fname, fdef, ftype in [(sentinel, '', 4)] + fields:
                    if first:
                        vs.NewField(rec_name, fname, fdef, ftype, 0)
                        first = False
                    else:
                        vs.NewField(rec_name, fname, fdef, ftype, 0)
                # Remove the sentinel field
                try: _safe(lambda: vs.DelField(rec_name, sentinel))
                except Exception: pass
                record_results.append(f'{rec_name}: created')
        except Exception as e:
            record_results.append(f'{rec_name}: error {e}')

    return {
        'status': 'ok',
        'layers_created': created_layers,
        'layers_existing': existing_layers,
        'classes_created': created_classes,
        'classes_existing': existing_classes,
        'records': record_results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Room geometry
# ─────────────────────────────────────────────────────────────────────────────

def av_draw_room(p):
    """Draw room boundary rectangle.

    width_mm, length_mm: room dimensions (mm).
    origin: 'center' (default) or 'corner'."""
    prev = _with_layer_class({'layer': 'AV-Room', 'class': 'AV-Stage'})
    try:
        w = float(p.get('width_mm',  30480))   # 100 ft
        l = float(p.get('length_mm', 24384))   # 80 ft
        orig = p.get('origin', 'center')

        if orig == 'center':
            x1, y1, x2, y2 = -w/2, -l/2, w/2, l/2
        else:
            x1, y1, x2, y2 = 0, 0, w, l

        vs.Rect((x1, y1), (x2, y2))
        h = vs.LNewObj()
        if h:
            vs.SetFPat(h, 0)   # no fill
            vs.SetLW(h, 75)    # 0.75 mm wall line

        return {
            'status': 'ok',
            'object_id': _oid(h),
            'bounds': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
            'center': {'x': (x1+x2)/2, 'y': (y1+y2)/2},
        }
    finally:
        _restore(prev)


def av_draw_stage(p):
    """Draw stage platform.

    width_mm, depth_mm: stage dimensions.
    height_mm: deck height above floor (default 762 = 30 in).
    position: 'north' (top/+Y wall, default) | 'south' | 'east' | 'west'.
    room_length_mm: needed to push stage to the wall.
    room_width_mm: needed for east/west positions.

    Returns stage bounds and key Y coordinate (front edge)."""
    prev = _with_layer_class({'layer': 'AV-Stage', 'class': 'AV-Stage'})
    try:
        sw  = float(p.get('width_mm',  12192))  # 40 ft
        sd  = float(p.get('depth_mm',   4877))  # 16 ft
        sh  = float(p.get('height_mm',   762))  # 30 in
        rl  = float(p.get('room_length_mm', 24384))
        rw  = float(p.get('room_width_mm',  30480))
        pos = p.get('position', 'north')

        if pos == 'north':
            y2 = rl / 2;  y1 = y2 - sd
            x1 = -sw/2;   x2 =  sw/2
            front_y = y1
        elif pos == 'south':
            y1 = -rl/2;   y2 = y1 + sd
            x1 = -sw/2;   x2 =  sw/2
            front_y = y2
        elif pos == 'east':
            x2 = rw/2;    x1 = x2 - sd
            y1 = -sw/2;   y2 =  sw/2
            front_y = x1
        else:  # west
            x1 = -rw/2;   x2 = x1 + sd
            y1 = -sw/2;   y2 =  sw/2
            front_y = x2

        vs.Rect((x1, y1), (x2, y2))
        stage_h = vs.LNewObj()
        if stage_h:
            vs.SetFPat(stage_h, 4)  # diagonal hatch
            vs.SetLW(stage_h, 50)

        # Deck label
        deck_in = sh / 25.4
        lbl = _av_draw_text(
            (x1+x2)/2, (y1+y2)/2,
            f"STAGE\n+{deck_in:.0f}\" ({sh/304.8:.1f}')",
            size_mm=200,
        )

        return {
            'status': 'ok',
            'object_ids': [i for i in [_oid(stage_h), _oid(lbl)] if i],
            'bounds': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
            'deck_height_mm': sh,
            'front_y': front_y,
            'center_x': (x1+x2)/2,
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Speaker placement
# ─────────────────────────────────────────────────────────────────────────────

def _av_coverage_arc(cx, cy, far_mm, h_angle_deg, aim_deg=270, steps=16):
    """Draw a wedge polygon for speaker coverage in plan.

    aim_deg: direction the speaker faces in VW angle space
             (270 = facing -Y / downstage is typical).
    Returns handle of the polyline, or None on failure."""
    half = h_angle_deg / 2
    pts = [(cx, cy)]
    for i in range(steps + 1):
        a = _math.radians(aim_deg - half + h_angle_deg * i / steps)
        pts.append((cx + far_mm * _math.cos(a), cy + far_mm * _math.sin(a)))
    pts.append((cx, cy))

    try:
        vs.NameClass('AV-Coverage')
        vs.OpenPoly()
        vs.BeginPoly()
        for pt in pts:
            vs.Add2DVertex((pt[0], pt[1]), 0, 0)
        vs.EndPoly()
        h = vs.LNewObj()
        if h:
            vs.SetFPat(h, 0)
            vs.SetLW(h, 13)
            try: vs.SetOpacity(h, 35)
            except Exception: pass
        return h
    except Exception:
        return None


def av_place_speaker(p):
    """Place a speaker or point-source PA box in plan view.

    x, y          : position (mm).
    label         : e.g. 'L Array', 'C-FILL'.
    model         : model string stored in record.
    h_angle_deg   : horizontal coverage (default 90°).
    v_angle_deg   : vertical coverage (default 30°).
    downtilt_deg  : tilt below horizontal (default 15°).
    trim_mm       : flown height above floor (default 6096 = 20 ft).
    rotation_deg  : box rotation in plan (0 = facing downstage/-Y).
    draw_coverage : draw coverage wedge (default True).
    weight_kg     : for rigging records.
    power_w       : power consumption."""
    prev = _with_layer_class({'layer': 'AV-Audio', 'class': 'AV-Speaker'})
    try:
        x     = float(p.get('x', 0))
        y     = float(p.get('y', 0))
        label = str(p.get('label', 'SPK'))
        model = str(p.get('model', ''))
        h_ang = float(p.get('h_angle_deg', 90))
        v_ang = float(p.get('v_angle_deg', 30))
        tilt  = float(p.get('downtilt_deg', 15))
        trim  = float(p.get('trim_mm', 6096))
        rot   = float(p.get('rotation_deg', 0))
        draw_cov = bool(p.get('draw_coverage', True))
        weight = float(p.get('weight_kg', 0))
        power  = float(p.get('power_w', 0))

        bw, bd = 650, 450  # plan footprint (mm)

        vs.Rect((x - bw/2, y - bd/2), (x + bw/2, y + bd/2))
        box_h = vs.LNewObj()
        if box_h:
            if rot:
                vs.HRotate(box_h, (x, y), rot)
            vs.SetFPat(box_h, 1)
            vs.SetFillFore(box_h, (_c8(30), _c8(100), _c8(200)))
            vs.SetFillBack(box_h, (_c8(30), _c8(100), _c8(200)))

        trim_ft = trim / 304.8
        lbl_h  = _av_draw_text(x, y + bd/2 + 250,
                                f"{label}\nT:{trim_ft:.1f}'", size_mm=150)

        ids = [_oid(h) for h in [box_h, lbl_h] if h]

        # Coverage wedge
        cov_h = None
        if draw_cov and trim > 0:
            tilt_r = _math.radians(tilt)
            far_v  = tilt + v_ang/2
            far_mm = (trim * _math.tan(_math.radians(far_v))
                      if far_v < 89 else 30000)
            aim = 270 + rot  # downstage direction offset by box rotation
            cov_h = _av_coverage_arc(x, y, far_mm, h_ang, aim_deg=aim)
            vs.NameClass('AV-Speaker')
            if cov_h:
                ids.append(_oid(cov_h))

        # Record
        if box_h:
            _av_attach_record(box_h, AV_REC_DEVICE, {
                'Device_Type': 'Speaker', 'Model': model, 'Label': label,
                'Trim_mm': int(trim), 'Weight_kg': weight, 'Power_W': int(power),
            })

        return {
            'status': 'ok', 'object_ids': ids,
            'position': {'x': x, 'y': y}, 'trim_mm': trim,
        }
    finally:
        _restore(prev)


def av_place_speaker_cluster(p):
    """Place a line-array cluster with rigging point marker.

    n_boxes          : cabinets in the array (default 8).
    box_width_mm     : cabinet width in plan (default 560 mm).
    box_depth_mm     : cabinet depth in plan (default 380 mm).
    label            : 'L', 'R', 'C', 'SL', 'SR', etc.
    trim_mm          : bottom-of-cluster height (default 6700 mm).
    h_angle_deg      : horizontal coverage (default 90°).
    v_angle_deg      : total vertical span of array (default 20°).
    downtilt_deg     : array aim angle below horizontal (default 18°).
    weight_per_box_kg: per-cabinet weight for rigging load calc (default 35 kg)."""
    prev = _with_layer_class({'layer': 'AV-Audio', 'class': 'AV-Speaker'})
    try:
        x     = float(p.get('x', 0))
        y     = float(p.get('y', 0))
        n     = int(p.get('n_boxes', 8))
        bw    = float(p.get('box_width_mm', 560))
        bd    = float(p.get('box_depth_mm', 380))
        label = str(p.get('label', 'LA'))
        trim  = float(p.get('trim_mm', 6700))
        h_ang = float(p.get('h_angle_deg', 90))
        v_ang = float(p.get('v_angle_deg', 20))
        tilt  = float(p.get('downtilt_deg', 18))
        w_per = float(p.get('weight_per_box_kg', 35))
        draw_cov = bool(p.get('draw_coverage', True))

        # Cabinet footprint in plan
        vs.Rect((x - bw/2, y - bd/2), (x + bw/2, y + bd/2))
        box_h = vs.LNewObj()
        if box_h:
            vs.SetFPat(box_h, 1)
            vs.SetFillFore(box_h, (_c8(30), _c8(100), _c8(200)))
            vs.SetFillBack(box_h, (_c8(30), _c8(100), _c8(200)))

        # Rigging point marker (circle)
        vs.NameClass('AV-Motor')
        vs.ArcByCenter((x, y), 150, 0, 360)
        rig_h = vs.LNewObj()
        if rig_h:
            vs.SetFPat(rig_h, 0)
        vs.NameClass('AV-Speaker')

        trim_ft  = trim / 304.8
        total_kg = n * w_per
        lbl_h = _av_draw_text(
            x, y + bd/2 + 300,
            f"{label} ({n}x)\nT:{trim_ft:.1f}'  {total_kg:.0f}kg",
            size_mm=175,
        )

        ids = [_oid(h) for h in [box_h, rig_h, lbl_h] if h]

        # Coverage wedge
        if draw_cov and trim > 0:
            far_v  = tilt + v_ang/2
            far_mm = (trim * _math.tan(_math.radians(far_v))
                      if far_v < 89 else 30000)
            cov_h = _av_coverage_arc(x, y, far_mm, h_ang)
            vs.NameClass('AV-Speaker')
            if cov_h:
                ids.append(_oid(cov_h))

        # Rigging record
        if box_h:
            _av_attach_record(box_h, AV_REC_RIGGING, {
                'Trim_mm': int(trim), 'Load_kg': int(total_kg), 'Capacity_kg': 500,
            })
            _av_attach_record(box_h, AV_REC_DEVICE, {
                'Device_Type': 'Line Array', 'Label': label,
                'Trim_mm': int(trim), 'Weight_kg': total_kg,
            })

        return {
            'status': 'ok', 'object_ids': ids,
            'position': {'x': x, 'y': y},
            'trim_mm': trim, 'total_weight_kg': total_kg,
        }
    finally:
        _restore(prev)


def av_place_subwoofer(p):
    """Place a subwoofer stack (ground or flown).

    n_boxes       : cabinets side-by-side (default 4).
    box_width_mm  : per-cabinet width (default 750 mm).
    box_depth_mm  : per-cabinet depth (default 800 mm)."""
    prev = _with_layer_class({'layer': 'AV-Audio', 'class': 'AV-Subwoofer'})
    try:
        x     = float(p.get('x', 0))
        y     = float(p.get('y', 0))
        n     = int(p.get('n_boxes', 4))
        bw    = float(p.get('box_width_mm', 750)) * n
        bd    = float(p.get('box_depth_mm', 800))
        label = str(p.get('label', 'SUB'))
        weight = float(p.get('weight_per_box_kg', 80))

        vs.Rect((x - bw/2, y - bd/2), (x + bw/2, y + bd/2))
        box_h = vs.LNewObj()
        if box_h:
            vs.SetFPat(box_h, 1)
            vs.SetFillFore(box_h, (_c8(10), _c8(40), _c8(100)))
            vs.SetFillBack(box_h, (_c8(10), _c8(40), _c8(100)))

        lbl_h = _av_draw_text(x, y, f"{label}\n({n}x)", size_mm=150)

        ids = [_oid(h) for h in [box_h, lbl_h] if h]

        if box_h:
            _av_attach_record(box_h, AV_REC_DEVICE, {
                'Device_Type': 'Subwoofer', 'Label': label,
                'Weight_kg': n * weight,
            })

        return {
            'status': 'ok', 'object_ids': ids,
            'position': {'x': x, 'y': y},
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Screen placement
# ─────────────────────────────────────────────────────────────────────────────

def av_place_screen(p):
    """Place a projection screen or LED wall in plan view.

    x, y         : center in plan (mm).
    width_mm     : screen image width.
    height_mm    : screen image height (computed from aspect if omitted).
    aspect       : '16:9' | '4:3' | float  (default '16:9').
    trim_mm      : height of screen bottom from floor (default 2438 = 8 ft).
    screen_type  : 'front-projection' | 'rear-projection' | 'LED' | 'motorized'.
    label        : 'MAIN' | 'IMAG-L' | 'IMAG-R' etc.
    depth_mm     : plan-view depth of screen frame (default 300 mm)."""
    prev = _with_layer_class({'layer': 'AV-Video', 'class': 'AV-Screen'})
    try:
        cx    = float(p.get('x', 0))
        cy    = float(p.get('y', 0))
        sw    = float(p.get('width_mm', 5486))    # 18 ft
        asp   = p.get('aspect', '16:9')
        if isinstance(asp, str) and ':' in asp:
            aw, ah = [float(v) for v in asp.split(':')]
            ar = ah / aw
        else:
            ar = float(asp) if asp else 9/16
        sh    = float(p.get('height_mm', sw * ar))
        trim  = float(p.get('trim_mm', 2438))
        stype = str(p.get('screen_type', 'front-projection'))
        label = str(p.get('label', 'SCREEN'))
        sdep  = float(p.get('depth_mm', 300))

        vs.Rect((cx - sw/2, cy - sdep/2), (cx + sw/2, cy + sdep/2))
        scr_h = vs.LNewObj()
        if scr_h:
            vs.SetFPat(scr_h, 1)
            vs.SetLW(scr_h, 50)
            if 'LED' in stype.upper():
                vs.SetFillFore(scr_h, (_c8(240), _c8(20),  _c8(60)))
                vs.SetFillBack(scr_h, (_c8(240), _c8(20),  _c8(60)))
            else:
                vs.SetFillFore(scr_h, (_c8(200), _c8(30),  _c8(80)))
                vs.SetFillBack(scr_h, (_c8(200), _c8(30),  _c8(80)))

        top_mm = trim + sh
        lbl_h = _av_draw_text(
            cx, cy + sdep/2 + 250,
            f"{label}  {sw/304.8:.1f}'W × {sh/304.8:.1f}'H\n"
            f"Trim: {trim/304.8:.1f}'   Top: {top_mm/304.8:.1f}'",
            size_mm=150,
        )

        # Width dim
        vs.NameClass('AV-Dims')
        vs.LinDimN((cx - sw/2, cy - sdep/2 - 400),
                   (cx + sw/2, cy - sdep/2 - 400), 0, 0)
        dim_h = vs.LNewObj()
        vs.NameClass('AV-Screen')

        ids = [_oid(h) for h in [scr_h, lbl_h, dim_h] if h]

        if scr_h:
            _av_attach_record(scr_h, AV_REC_DEVICE, {
                'Device_Type': stype, 'Label': label,
                'Trim_mm': int(trim),
            })

        return {
            'status': 'ok', 'object_ids': ids,
            'width_mm': sw, 'height_mm': sh,
            'trim_mm': trim, 'top_mm': top_mm,
            'center': {'x': cx, 'y': cy},
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Truss
# ─────────────────────────────────────────────────────────────────────────────

def av_place_truss(p):
    """Place a straight truss segment in plan view.

    x1,y1 → x2,y2 : endpoints (mm).
    trim_mm        : underside height from floor (default 6096 = 20 ft).
    truss_type     : '12in' | '18in' | '20.5in' (default) | '30in'.
    label          : truss ID shown on drawing.
    capacity_kg    : per-point load capacity (default 500 kg).

    Draws the truss outline, centerline, and rigging-point markers at
    each endpoint with AV Rigging Point records attached."""
    prev = _with_layer_class({'layer': 'AV-Rigging', 'class': 'AV-Truss'})
    try:
        x1 = float(p.get('x1', -3048));  y1 = float(p.get('y1', 0))
        x2 = float(p.get('x2',  3048));  y2 = float(p.get('y2', 0))
        trim    = float(p.get('trim_mm', 6096))
        ttype   = str(p.get('truss_type', '20.5in'))
        label   = str(p.get('label', 'TRUSS'))
        cap     = float(p.get('capacity_kg', 500))

        tw_map  = {'12in': 305, '18in': 457, '20.5in': 521, '30in': 762}
        tw      = float(tw_map.get(ttype, 521))

        dx = x2 - x1;  dy = y2 - y1
        length = _math.sqrt(dx**2 + dy**2)
        if length < 1:
            return {'error': 'zero-length truss'}

        nx = -dy / length * tw/2;  ny = dx / length * tw/2

        pts = [(x1+nx, y1+ny), (x2+nx, y2+ny),
               (x2-nx, y2-ny), (x1-nx, y1-ny)]
        vs.ClosePoly()
        vs.BeginPoly()
        for pt in pts:
            vs.Add2DVertex((pt[0], pt[1]), 0, 0)
        vs.EndPoly()
        truss_h = vs.LNewObj()
        if truss_h:
            vs.SetFPat(truss_h, 1)
            vs.SetFillFore(truss_h, (_c8(220), _c8(140), _c8(0)))
            vs.SetFillBack(truss_h, (_c8(220), _c8(140), _c8(0)))
            vs.SetLW(truss_h, 50)

        # Centerline
        vs.MoveTo((x1, y1));  vs.LineTo((x2, y2))
        cl_h = vs.LNewObj()
        if cl_h:
            vs.SetFPat(cl_h, 0);  vs.SetLW(cl_h, 25)

        # Label
        mcx = (x1+x2)/2;  mcy = (y1+y2)/2
        lbl_h = _av_draw_text(
            mcx, mcy,
            f"{label}  T:{trim/304.8:.1f}'  ({length/304.8:.0f}')",
            size_mm=150,
        )

        ids = [_oid(h) for h in [truss_h, cl_h, lbl_h] if h]

        # Rigging-point circles at endpoints
        for px, py in [(x1, y1), (x2, y2)]:
            vs.NameClass('AV-Motor')
            vs.ArcByCenter((px, py), 200, 0, 360)
            rph = vs.LNewObj()
            if rph:
                vs.SetFPat(rph, 0)
                ids.append(_oid(rph))
                _av_attach_record(rph, AV_REC_RIGGING, {
                    'Trim_mm': int(trim), 'Capacity_kg': int(cap),
                })
            vs.NameClass('AV-Truss')

        return {
            'status': 'ok', 'object_ids': ids,
            'length_mm': round(length, 1), 'trim_mm': trim,
            'endpoints': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Seating
# ─────────────────────────────────────────────────────────────────────────────

def av_place_round_table(p):
    """Place a single round table with chair markers.

    cx, cy        : center (mm).
    diameter_mm   : table diameter (default 1828 = 72 in / 6 ft).
    n_seats       : chairs around the table (default 10).
    label         : table number string."""
    prev = _with_layer_class({'layer': 'AV-Seating', 'class': 'AV-Seating-Table'})
    try:
        cx  = float(p.get('cx', 0))
        cy  = float(p.get('cy', 0))
        dia = float(p.get('diameter_mm', 1828))
        n   = int(p.get('n_seats', 10))
        lbl = str(p.get('label', ''))

        vs.ArcByCenter((cx, cy), dia/2, 0, 360)
        tbl_h = vs.LNewObj()
        if tbl_h:
            vs.SetFPat(tbl_h, 1)
            vs.SetFillFore(tbl_h, (_c8(220), _c8(200), _c8(175)))
            vs.SetFillBack(tbl_h, (_c8(220), _c8(200), _c8(175)))
            vs.SetLW(tbl_h, 25)

        setback = dia/2 + 60   # chair center from table center
        chair_r = 220           # chair circle radius (≈9 in seat)

        ids = [_oid(tbl_h)] if tbl_h else []

        vs.NameClass('AV-Seating-Chair')
        for i in range(n):
            a = 2 * _math.pi * i / n
            sx = cx + setback * _math.cos(a)
            sy = cy + setback * _math.sin(a)
            vs.ArcByCenter((sx, sy), chair_r, 0, 360)
            ch = vs.LNewObj()
            if ch:
                vs.SetFPat(ch, 1)
                vs.SetFillFore(ch, (_c8(180), _c8(180), _c8(180)))
                vs.SetFillBack(ch, (_c8(180), _c8(180), _c8(180)))
                vs.SetLW(ch, 13)
                ids.append(_oid(ch))
        vs.NameClass('AV-Seating-Table')

        if lbl:
            lbl_h = _av_draw_text(cx, cy, lbl, size_mm=120)
            if lbl_h: ids.append(_oid(lbl_h))

        return {
            'status': 'ok', 'object_ids': ids,
            'center': {'x': cx, 'y': cy},
            'diameter_mm': dia, 'n_seats': n,
        }
    finally:
        _restore(prev)


def av_layout_seating(p):
    """Auto-layout round tables in a rectangular section.

    x1,y1,x2,y2     : section boundary (mm).
    diameter_mm      : table diameter (default 1828 mm).
    n_seats          : seats per table (default 10).
    col_spacing_mm   : center-to-center column pitch (default 2743 = 9 ft).
    row_spacing_mm   : center-to-center row pitch (default 2743 = 9 ft).
    aisle_x_mm       : if > 0, skip tables within ±aisle_x/2 of x=0.
    start_table_num  : first table number (default 1).

    Returns tables_placed, total_seats, and per-table details."""
    prev = _with_layer_class({'layer': 'AV-Seating', 'class': 'AV-Seating-Table'})
    try:
        x1 = float(p.get('x1', -9144));  y1 = float(p.get('y1', -9144))
        x2 = float(p.get('x2',  9144));  y2 = float(p.get('y2',  4877))
        dia    = float(p.get('diameter_mm', 1828))
        n_seat = int(p.get('n_seats', 10))
        col_sp = float(p.get('col_spacing_mm', 2743))
        row_sp = float(p.get('row_spacing_mm', 2743))
        aisle  = float(p.get('aisle_x_mm', 0))
        tnum   = int(p.get('start_table_num', 1))

        sec_w = x2 - x1;  sec_l = y2 - y1

        n_cols = max(1, int((sec_w - dia) / col_sp) + 1)
        n_rows = max(1, int((sec_l - dia) / row_sp) + 1)

        total_w = (n_cols - 1) * col_sp
        total_l = (n_rows - 1) * row_sp
        sx = (x1+x2)/2 - total_w/2
        sy = (y1+y2)/2 - total_l/2

        tables = []
        for row in range(n_rows):
            for col in range(n_cols):
                tx = sx + col * col_sp
                ty = sy + row * row_sp
                # Boundary clearance
                if tx - dia/2 < x1 or tx + dia/2 > x2: continue
                if ty - dia/2 < y1 or ty + dia/2 > y2: continue
                # Centre aisle
                if aisle > 0 and abs(tx) < aisle/2: continue

                av_place_round_table({
                    'cx': tx, 'cy': ty,
                    'diameter_mm': dia, 'n_seats': n_seat,
                    'label': str(tnum),
                })
                tables.append({'number': tnum, 'x': tx, 'y': ty})
                tnum += 1

        return {
            'status': 'ok',
            'tables_placed': len(tables),
            'total_seats': len(tables) * n_seat,
            'tables': tables,
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# FOH position
# ─────────────────────────────────────────────────────────────────────────────

def av_place_foh(p):
    """Place Front of House mix position.

    cx, cy      : center (mm).
    width_mm    : total width of FOH run (default 3658 = 12 ft).
    depth_mm    : front-to-back depth (default 1524 = 5 ft).
    label       : 'FOH' | 'A1' | 'V1' | etc.
    has_riser   : draw 3-ft clearance perimeter (default True)."""
    prev = _with_layer_class({'layer': 'AV-FOH', 'class': 'AV-FOH'})
    try:
        cx  = float(p.get('cx', 0))
        cy  = float(p.get('cy', 0))
        fw  = float(p.get('width_mm', 3658))
        fd  = float(p.get('depth_mm', 1524))
        lbl = str(p.get('label', 'FOH'))
        has_riser = bool(p.get('has_riser', True))

        ids = []

        if has_riser:
            pad = 915  # 3 ft clearance
            vs.Rect((cx - fw/2 - pad, cy - fd/2 - pad),
                    (cx + fw/2 + pad, cy + fd/2 + pad))
            riser_h = vs.LNewObj()
            if riser_h:
                vs.SetFPat(riser_h, 0);  vs.SetLW(riser_h, 18)
                try: vs.SetObjectVariableInt(riser_h, 4, 2)   # dash style
                except Exception: pass
            if riser_h: ids.append(_oid(riser_h))

        vs.Rect((cx - fw/2, cy - fd/2), (cx + fw/2, cy + fd/2))
        foh_h = vs.LNewObj()
        if foh_h:
            vs.SetFPat(foh_h, 1)
            vs.SetFillFore(foh_h, (_c8(80),  _c8(180), _c8(80)))
            vs.SetFillBack(foh_h, (_c8(80),  _c8(180), _c8(80)))
            vs.SetLW(foh_h, 35)
        if foh_h: ids.append(_oid(foh_h))

        lbl_h = _av_draw_text(
            cx, cy,
            f"{lbl}  {fw/304.8:.0f}'×{fd/304.8:.0f}'",
            size_mm=200,
        )
        if lbl_h: ids.append(_oid(lbl_h))

        return {
            'status': 'ok', 'object_ids': ids,
            'center': {'x': cx, 'y': cy},
            'width_mm': fw, 'depth_mm': fd,
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Cable runs
# ─────────────────────────────────────────────────────────────────────────────

_CABLE_CLASS = {
    'audio':    'AV-Cable-Audio',
    'video':    'AV-Cable-Video',
    'power':    'AV-Cable-Power',
    'data':     'AV-Cable-Data',
    'dmx':      'AV-Cable-Data',
    'ethernet': 'AV-Cable-Data',
    'fiber':    'AV-Cable-Data',
}
_CABLE_RGB = {
    'audio':    (50,  150, 255),
    'video':    (220, 50,  100),
    'power':    (255, 140, 0),
    'data':     (80,  200, 80),
    'dmx':      (200, 80,  200),
    'ethernet': (50,  200, 50),
    'fiber':    (255, 200, 0),
}


def av_draw_cable_run(p):
    """Draw a cable run as a labelled polyline.

    points      : [[x1,y1],[x2,y2],...] waypoints (mm).
    cable_type  : 'audio'|'video'|'power'|'data'|'dmx'|'ethernet'|'fiber'.
    label       : signal name (e.g. 'A1-L MAIN').
    from_device, to_device, connector_a, connector_b: stored in record.

    Returns object_ids and measured length."""
    ctype = str(p.get('cable_type', 'audio')).lower()
    cls   = _CABLE_CLASS.get(ctype, 'AV-Cable-Audio')
    prev  = _with_layer_class({'layer': 'AV-Signal', 'class': cls})
    try:
        pts = p.get('points', [])
        if len(pts) < 2:
            return {'error': 'need at least 2 points'}
        label    = str(p.get('label', ''))
        from_dev = str(p.get('from_device', ''))
        to_dev   = str(p.get('to_device', ''))

        vs.OpenPoly()
        vs.BeginPoly()
        for pt in pts:
            vs.Add2DVertex((float(pt[0]), float(pt[1])), 0, 0)
        vs.EndPoly()
        line_h = vs.LNewObj()

        total_mm = sum(
            _math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2)
            for i in range(len(pts)-1)
        )

        if line_h:
            rgb = _CABLE_RGB.get(ctype, (50, 150, 255))
            col = tuple(_c8(v) for v in rgb)
            vs.SetPenFore(line_h, col)
            vs.SetPenBack(line_h, col)
            vs.SetLW(line_h, 18)
            try: vs.SetObjEndMarker(line_h, 1, 0.1, 1.0, True, True)
            except Exception: pass

        # Label at midpoint
        mi = len(pts) // 2
        mx = (pts[mi-1][0] + pts[mi][0]) / 2 if mi > 0 else pts[0][0]
        my = (pts[mi-1][1] + pts[mi][1]) / 2 if mi > 0 else pts[0][1]
        disp = f"{label}  ({total_mm/304.8:.0f}')" if label else \
               f"{ctype.upper()}  ({total_mm/304.8:.0f}')"
        vs.NameClass('AV-Notes')
        vs.TextOrigin((mx, my + 150))
        vs.TextJust(2);  vs.TextSize(100)
        vs.CreateText(disp)
        lbl_h = vs.LNewObj()
        vs.NameClass(cls)

        ids = [_oid(h) for h in [line_h, lbl_h] if h]

        if line_h:
            _av_attach_record(line_h, AV_REC_CABLE, {
                'Cable_Type': ctype, 'Length_mm': int(total_mm),
                'From_Device': from_dev, 'To_Device': to_dev,
                'Connector_A': p.get('connector_a', ''),
                'Connector_B': p.get('connector_b', ''),
                'Notes': label,
            })

        return {
            'status': 'ok', 'object_ids': ids,
            'length_mm': round(total_mm, 0), 'length_ft': round(total_mm/304.8, 1),
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Power distribution
# ─────────────────────────────────────────────────────────────────────────────

def av_place_power_distro(p):
    """Place a power distribution unit (PDU / distro box).

    cx, cy      : center (mm).
    label       : 'A-DISTRO' | 'STAGE PWR' etc.
    amperage    : service amps (default 200).
    phase       : '1ph' | '3ph' (default '3ph').
    width_mm    : physical width (default 1200 mm).
    depth_mm    : physical depth (default 800 mm)."""
    prev = _with_layer_class({'layer': 'AV-Power', 'class': 'AV-Power-Distro'})
    try:
        cx  = float(p.get('cx', 0));  cy  = float(p.get('cy', 0))
        lbl = str(p.get('label', 'DISTRO'))
        amp = int(p.get('amperage', 200))
        ph  = str(p.get('phase', '3ph'))
        pw  = float(p.get('width_mm', 1200))
        pd  = float(p.get('depth_mm', 800))

        vs.Rect((cx - pw/2, cy - pd/2), (cx + pw/2, cy + pd/2))
        h = vs.LNewObj()
        if h:
            vs.SetFPat(h, 1)
            vs.SetFillFore(h, (_c8(200), _c8(100), _c8(0)))
            vs.SetFillBack(h, (_c8(200), _c8(100), _c8(0)))
            vs.SetLW(h, 35)

        lbl_h = _av_draw_text(cx, cy, f"{lbl}\n{amp}A / {ph}", size_mm=150)
        ids = [_oid(x) for x in [h, lbl_h] if x]

        return {'status': 'ok', 'object_ids': ids, 'center': {'x': cx, 'y': cy}}
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Rigging load summary
# ─────────────────────────────────────────────────────────────────────────────

def av_rigging_summary(p):
    """Collect all AV Rigging Point records and return a load summary.

    Scans all objects for the AV Rigging Point record.
    Flags any point where load_kg > capacity_kg * 0.8 (80 % WLL)."""
    points = []
    for h in _collect('ALL', 5000):
        try:
            for i in range(1, vs.NumRecords(h) + 1):
                rh = vs.GetRecord(h, i)
                if rh and vs.GetName(rh) == AV_REC_RIGGING:
                    bb = _bbox(h)
                    cx = (bb['x1']+bb['x2'])/2 if bb else 0
                    cy = (bb['y1']+bb['y2'])/2 if bb else 0
                    trim = _safe(lambda: float(vs.GetRField(h, AV_REC_RIGGING, 'Trim_mm') or 0), 0)
                    load = _safe(lambda: float(vs.GetRField(h, AV_REC_RIGGING, 'Load_kg') or 0), 0)
                    cap  = _safe(lambda: float(vs.GetRField(h, AV_REC_RIGGING, 'Capacity_kg') or 500), 500)
                    pid  = _safe(lambda: vs.GetRField(h, AV_REC_RIGGING, 'Point_ID') or '', '')
                    points.append({
                        'object_id': _oid(h), 'point_id': pid,
                        'x': round(cx, 0), 'y': round(cy, 0),
                        'trim_mm': trim, 'load_kg': load, 'capacity_kg': cap,
                        'utilization_pct': round(100*load/cap, 1) if cap else None,
                        'warning': load > cap * 0.8,
                    })
                    break
        except Exception:
            continue

    total = sum(pt['load_kg'] for pt in points)
    return {
        'status': 'ok',
        'rigging_points': len(points),
        'total_load_kg': round(total, 1),
        'warnings': sum(1 for pt in points if pt['warning']),
        'points': points,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Corporate / Spotlight: staging elements
# ─────────────────────────────────────────────────────────────────────────────

def av_place_podium(p):
    """Place a corporate podium / lectern on stage.

    cx, cy            : center position (mm).
    width_mm          : podium width (default 610 = 24 in).
    depth_mm          : podium depth (default 460 = 18 in).
    label             : 'PODIUM' | 'LECTERN' | presenter name.
    confidence_monitor: draw a confidence monitor marker downstage of podium (default True).
    monitor_width_mm  : confidence monitor screen width (default 686 = 27 in diag ≈ 24 in wide).

    Returns object_ids and center position."""
    prev = _with_layer_class({'layer': 'AV-Stage', 'class': 'AV-Podium'})
    try:
        cx  = float(p.get('cx', 0))
        cy  = float(p.get('cy', 0))
        pw  = float(p.get('width_mm', 610))
        pd  = float(p.get('depth_mm', 460))
        lbl = str(p.get('label', 'PODIUM'))
        has_conf = bool(p.get('confidence_monitor', True))
        mon_w    = float(p.get('monitor_width_mm', 686))

        vs.Rect((cx - pw/2, cy - pd/2), (cx + pw/2, cy + pd/2))
        pod_h = vs.LNewObj()
        if pod_h:
            vs.SetFPat(pod_h, 4)   # light hatch
            vs.SetFillFore(pod_h, (_c8(200), _c8(200), _c8(200)))
            vs.SetFillBack(pod_h, (_c8(200), _c8(200), _c8(200)))
            vs.SetLW(pod_h, 50)

        lbl_h = _av_draw_text(cx, cy, lbl, size_mm=130)
        ids = [_oid(h) for h in [pod_h, lbl_h] if h]

        if has_conf:
            mon_d = 50   # plan depth of monitor
            mon_y = cy - pd/2 - 400 - mon_d  # downstage of podium
            vs.NameClass('AV-Confidence-Mon')
            vs.Rect((cx - mon_w/2, mon_y), (cx + mon_w/2, mon_y + mon_d))
            mon_h = vs.LNewObj()
            if mon_h:
                vs.SetFPat(mon_h, 1)
                vs.SetFillFore(mon_h, (_c8(200), _c8(30), _c8(80)))
                vs.SetFillBack(mon_h, (_c8(200), _c8(30), _c8(80)))
                ids.append(_oid(mon_h))
            _av_draw_text(cx, mon_y - 200, 'CONF', size_mm=100)

        _av_attach_record(pod_h, AV_REC_DEVICE, {
            'Device_Type': 'Podium', 'Label': lbl,
        })

        return {'status': 'ok', 'object_ids': ids, 'center': {'x': cx, 'y': cy}}
    finally:
        _restore(prev)


def av_place_head_table(p):
    """Place a corporate head table / panel dais.

    Chairs are placed on the downstage (audience-facing) side only.

    cx, cy      : center of table (mm).
    width_mm    : table width (default 4877 = 16 ft for 6-person panel).
    depth_mm    : table depth (default 762 = 30 in standard banquet table).
    n_seats     : panelists (default 6).
    label       : 'HEAD TABLE' | 'PANEL' | 'DAIS'.
    chair_w_mm  : chair width (default 480 mm).
    chair_d_mm  : chair depth (default 400 mm)."""
    prev = _with_layer_class({'layer': 'AV-Head-Table', 'class': 'AV-Head-Table'})
    try:
        cx  = float(p.get('cx', 0))
        cy  = float(p.get('cy', 0))
        tw  = float(p.get('width_mm', 4877))
        td  = float(p.get('depth_mm', 762))
        n   = int(p.get('n_seats', 6))
        lbl = str(p.get('label', 'HEAD TABLE'))
        cw  = float(p.get('chair_w_mm', 480))
        cd  = float(p.get('chair_d_mm', 400))

        vs.Rect((cx - tw/2, cy - td/2), (cx + tw/2, cy + td/2))
        tbl_h = vs.LNewObj()
        if tbl_h:
            vs.SetFPat(tbl_h, 1)
            vs.SetFillFore(tbl_h, (_c8(240), _c8(220), _c8(175)))
            vs.SetFillBack(tbl_h, (_c8(240), _c8(220), _c8(175)))
            vs.SetLW(tbl_h, 50)

        ids = [_oid(tbl_h)] if tbl_h else []

        # Chairs on the downstage (south/audience) side
        gap = (tw - n * cw) / (n + 1)
        vs.NameClass('AV-Seating-Chair')
        for i in range(n):
            cx_i = cx - tw/2 + gap + i * (cw + gap) + cw/2
            cy_i = cy - td/2 - 80 - cd/2   # 80 mm clearance from table edge
            vs.Rect((cx_i - cw/2, cy_i - cd/2), (cx_i + cw/2, cy_i + cd/2))
            ch = vs.LNewObj()
            if ch:
                vs.SetFPat(ch, 1)
                vs.SetFillFore(ch, (_c8(200), _c8(200), _c8(200)))
                vs.SetFillBack(ch, (_c8(200), _c8(200), _c8(200)))
                vs.SetLW(ch, 18)
                ids.append(_oid(ch))

        lbl_h = _av_draw_text(cx, cy, f'{lbl}\n({n} seats)', size_mm=160)
        if lbl_h: ids.append(_oid(lbl_h))

        _av_attach_record(tbl_h, AV_REC_DEVICE, {
            'Device_Type': 'Head Table', 'Label': lbl,
        }) if tbl_h else None

        return {
            'status': 'ok', 'object_ids': ids,
            'n_seats': n, 'center': {'x': cx, 'y': cy},
            'bounds': {'x1': cx-tw/2, 'y1': cy-td/2, 'x2': cx+tw/2, 'y2': cy+td/2},
        }
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Corporate / Spotlight: seating layouts
# ─────────────────────────────────────────────────────────────────────────────

_ROW_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'   # skip I and O (visual confusion)


def av_layout_theater_seating(p):
    """Auto-layout theater-style rows of numbered seats.

    Rows grow from stage-end toward back of room (+Y → -Y in VW convention).

    x1,y1,x2,y2       : section boundary (mm).
    seat_width_mm      : per-seat width centre-to-centre (default 508 = 20 in).
    seat_depth_mm      : seat front-to-back (default 305 mm).
    row_spacing_mm     : row pitch centre-to-centre (default 914 = 36 in).
    row_label_style    : 'alpha' (A, B, C … skip I/O) | 'numeric' (1, 2, 3).
    aisle_after_cols   : list of column numbers after which to insert a centre aisle,
                         e.g. [8] for a single centre aisle after col 8.
    aisle_width_mm     : aisle width (default 1219 = 48 in).
    ada_at_row_ends    : True = mark end seats on every row as ADA (default False).
    section_label      : zone label written into the AV Seat record (default 'General').

    Returns rows, total_seats, and per-row breakdown."""
    x1 = float(p.get('x1', -9000)); y1 = float(p.get('y1', -9000))
    x2 = float(p.get('x2',  9000)); y2 = float(p.get('y2',  3000))
    seat_w   = float(p.get('seat_width_mm',  508))
    seat_d   = float(p.get('seat_depth_mm',  305))
    row_sp   = float(p.get('row_spacing_mm', 914))
    style    = str(p.get('row_label_style', 'alpha'))
    aisle_after = [int(v) for v in p.get('aisle_after_cols', [])]
    aisle_w  = float(p.get('aisle_width_mm', 1219))
    ada_ends = bool(p.get('ada_at_row_ends', False))
    section  = str(p.get('section_label', 'General'))

    sec_w = x2 - x1
    n_aisles = len(aisle_after)
    usable_w = sec_w - n_aisles * aisle_w
    n_cols   = max(1, int(usable_w / seat_w))
    n_rows   = max(1, int((abs(y2 - y1) - seat_d) / row_sp) + 1)

    # Grid starts at row nearest stage (largest Y value in the boundary)
    # and grows toward y1 (further from stage).
    stage_end_y = max(y1, y2)
    back_end_y  = min(y1, y2)

    # Centre the grid horizontally
    total_grid_w = n_cols * seat_w + n_aisles * aisle_w
    start_x      = (x1 + x2) / 2 - total_grid_w / 2

    def _row_label(i):
        if style == 'alpha':
            return _ROW_LETTERS[i % len(_ROW_LETTERS)]
        return str(i + 1)

    prev = _with_layer_class({'layer': 'AV-Seating', 'class': 'AV-Theater-Chair'})
    rows_data = []
    total_seats = 0

    try:
        for row_idx in range(n_rows):
            # Rows numbered from stage outward: row 0 = closest to stage
            row_y = stage_end_y - row_sp/2 - row_idx * row_sp
            if row_y - seat_d/2 < back_end_y:
                break

            rl   = _row_label(row_idx)
            cur_x = start_x
            col_idx = 0
            seat_num = 1
            aisle_set = set(aisle_after)
            seats_in_row = 0

            while col_idx < n_cols:
                is_ada = ada_ends and (col_idx == 0 or col_idx == n_cols - 1)
                sx = cur_x + seat_w / 2

                if is_ada:
                    vs.NameClass('AV-ADA')
                else:
                    vs.NameClass('AV-Theater-Chair')

                # Seat rectangle with 25 mm gap each side
                vs.Rect((sx - seat_w/2 + 25, row_y - seat_d/2),
                        (sx + seat_w/2 - 25, row_y + seat_d/2))
                sh = vs.LNewObj()
                if sh:
                    rgb = (40, 175, 80) if is_ada else (200, 200, 215)
                    vs.SetFPat(sh, 1)
                    vs.SetFillFore(sh, (_c8(rgb[0]), _c8(rgb[1]), _c8(rgb[2])))
                    vs.SetFillBack(sh, (_c8(rgb[0]), _c8(rgb[1]), _c8(rgb[2])))
                    vs.SetLW(sh, 13)
                    _av_attach_record(sh, AV_REC_SEAT, {
                        'Row': rl, 'Seat_Num': seat_num, 'Section': section,
                        'ADA': 'Yes' if is_ada else 'No',
                    })

                cur_x += seat_w
                seat_num += 1
                col_idx += 1
                seats_in_row += 1

                # Insert aisle gap
                if col_idx in aisle_set:
                    cur_x += aisle_w

            # Row label at left of row
            vs.NameClass('AV-Notes')
            _av_draw_text(start_x - 400, row_y, rl, size_mm=175, align='center')
            vs.NameClass('AV-Theater-Chair')

            total_seats += seats_in_row
            rows_data.append({'row': rl, 'seats': seats_in_row,
                               'y_mm': round(row_y, 0)})
    finally:
        _restore(prev)

    return {
        'status': 'ok',
        'rows': len(rows_data),
        'cols': n_cols,
        'total_seats': total_seats,
        'row_detail': rows_data,
    }


def av_layout_classroom(p):
    """Auto-layout classroom-style rows of rectangular tables with chairs.

    Tables face the stage.  Chairs sit on the downstage side of each table.

    x1,y1,x2,y2         : section boundary (mm).
    table_width_mm       : per-seat unit width (default 762 = 30 in per seat).
    table_depth_mm       : table front-to-back (default 610 = 24 in).
    seats_per_table_unit : chairs per 762 mm table unit (default 1).
    row_spacing_mm       : row pitch (default 1829 = 72 in, table + chair + clearance).
    table_units_per_row  : number of 762 mm table units per row (auto-computed if 0).
    center_aisle_mm      : centre aisle width (default 0).
    start_table_num      : first table number (default 1).

    Returns rows_placed, total_seats."""
    x1  = float(p.get('x1', -9000)); y1 = float(p.get('y1', -9000))
    x2  = float(p.get('x2',  9000)); y2 = float(p.get('y2',  3000))
    tw  = float(p.get('table_width_mm',   762))   # per unit
    td  = float(p.get('table_depth_mm',   610))
    sptu = int(p.get('seats_per_table_unit', 1))
    row_sp = float(p.get('row_spacing_mm', 1829))
    n_units = int(p.get('table_units_per_row', 0))
    c_aisle = float(p.get('center_aisle_mm', 0))
    tnum    = int(p.get('start_table_num', 1))

    sec_w = x2 - x1
    if n_units == 0:
        n_units = max(1, int((sec_w - c_aisle) / tw))

    stage_end_y = max(y1, y2)
    back_end_y  = min(y1, y2)
    n_rows = max(1, int((abs(y2 - y1) - td) / row_sp) + 1)

    left_block  = n_units // 2
    right_block = n_units - left_block
    left_w  = left_block  * tw
    right_w = right_block * tw
    total_w = left_w + right_w + c_aisle

    lx1 = (x1 + x2) / 2 - total_w / 2
    rx1 = lx1 + left_w + c_aisle

    chair_w = tw * 0.85
    chair_d = 400
    chair_gap = 60   # gap between chair back and table edge

    prev = _with_layer_class({'layer': 'AV-Seating', 'class': 'AV-Seating-Table'})
    rows_data = []
    total_seats = 0

    try:
        for row_idx in range(n_rows):
            row_y = stage_end_y - td/2 - row_idx * row_sp
            if row_y - td/2 < back_end_y:
                break

            seats_in_row = 0

            for block_x, n_blk in [(lx1, left_block), (rx1, right_block)]:
                for unit_i in range(n_blk):
                    ux = block_x + unit_i * tw
                    vs.Rect((ux, row_y - td/2), (ux + tw, row_y + td/2))
                    tbl_h = vs.LNewObj()
                    if tbl_h:
                        vs.SetFPat(tbl_h, 1)
                        vs.SetFillFore(tbl_h, (_c8(220), _c8(210), _c8(190)))
                        vs.SetFillBack(tbl_h, (_c8(220), _c8(210), _c8(190)))
                        vs.SetLW(tbl_h, 18)

                    # Chair(s) on downstage side of this unit
                    for s in range(sptu):
                        cof = (s + 0.5) / sptu
                        cx_c = ux + tw * cof
                        cy_c = row_y - td/2 - chair_gap - chair_d/2
                        vs.NameClass('AV-Seating-Chair')
                        vs.Rect((cx_c - chair_w/(2*sptu), cy_c - chair_d/2),
                                (cx_c + chair_w/(2*sptu), cy_c + chair_d/2))
                        ch = vs.LNewObj()
                        if ch:
                            vs.SetFPat(ch, 1)
                            vs.SetFillFore(ch, (_c8(180), _c8(180), _c8(180)))
                            vs.SetFillBack(ch, (_c8(180), _c8(180), _c8(180)))
                            vs.SetLW(ch, 13)
                        vs.NameClass('AV-Seating-Table')
                        seats_in_row += 1

            total_seats += seats_in_row
            rows_data.append({'row': row_idx + 1, 'seats': seats_in_row,
                               'y_mm': round(row_y, 0)})
            tnum += 1
    finally:
        _restore(prev)

    return {
        'status': 'ok',
        'rows': len(rows_data),
        'total_seats': total_seats,
        'row_detail': rows_data,
    }


def av_layout_cocktail_tables(p):
    """Auto-layout cocktail / high-top reception tables in a grid.

    x1,y1,x2,y2      : section boundary (mm).
    diameter_mm       : table top diameter (default 686 = 27 in high top).
    col_spacing_mm    : centre-to-centre column pitch (default 2134 = 7 ft).
    row_spacing_mm    : centre-to-centre row pitch (default 2134 = 7 ft).
    n_stools          : bar stools per table (0 = standing only, default 3).
    start_table_num   : first table number (default 1).

    Returns tables_placed, total_capacity."""
    x1  = float(p.get('x1', -9000)); y1 = float(p.get('y1', -9000))
    x2  = float(p.get('x2',  9000)); y2 = float(p.get('y2',  3000))
    dia    = float(p.get('diameter_mm',   686))
    col_sp = float(p.get('col_spacing_mm', 2134))
    row_sp = float(p.get('row_spacing_mm', 2134))
    n_st   = int(p.get('n_stools', 3))
    tnum   = int(p.get('start_table_num', 1))

    sec_w = x2 - x1;  sec_l = abs(y2 - y1)
    n_cols = max(1, int((sec_w - dia) / col_sp) + 1)
    n_rows = max(1, int((sec_l - dia) / row_sp) + 1)
    total_w = (n_cols - 1) * col_sp
    total_l = (n_rows - 1) * row_sp
    sx = (x1 + x2)/2 - total_w/2
    sy_start = (min(y1,y2) + max(y1,y2))/2 - total_l/2

    prev = _with_layer_class({'layer': 'AV-Seating', 'class': 'AV-Cocktail-Table'})
    tables = []

    try:
        for ri in range(n_rows):
            for ci in range(n_cols):
                tx = sx + ci * col_sp
                ty = sy_start + ri * row_sp
                if tx - dia/2 < x1 or tx + dia/2 > x2: continue
                if ty - dia/2 < min(y1,y2) or ty + dia/2 > max(y1,y2): continue

                vs.ArcByCenter((tx, ty), dia/2, 0, 360)
                th = vs.LNewObj()
                if th:
                    vs.SetFPat(th, 1)
                    vs.SetFillFore(th, (_c8(235), _c8(215), _c8(195)))
                    vs.SetFillBack(th, (_c8(235), _c8(215), _c8(195)))
                    vs.SetLW(th, 25)

                # Bar stools
                if n_st > 0:
                    stool_r = 170
                    setback = dia/2 + 60
                    vs.NameClass('AV-Seating-Chair')
                    for s in range(n_st):
                        a = 2 * _math.pi * s / n_st
                        sx_s = tx + setback * _math.cos(a)
                        sy_s = ty + setback * _math.sin(a)
                        vs.ArcByCenter((sx_s, sy_s), stool_r, 0, 360)
                        st = vs.LNewObj()
                        if st:
                            vs.SetFPat(st, 1)
                            vs.SetFillFore(st, (_c8(200), _c8(200), _c8(210)))
                            vs.SetLW(st, 13)
                    vs.NameClass('AV-Cocktail-Table')

                _av_draw_text(tx, ty, str(tnum), size_mm=100)
                tables.append({'number': tnum, 'x': tx, 'y': ty})
                tnum += 1
    finally:
        _restore(prev)

    cap = len(tables) * max(n_st, 3)   # estimate 3 pax standing if no stools
    return {
        'status': 'ok',
        'tables_placed': len(tables),
        'capacity_estimate': cap,
        'tables': tables,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Corporate / Spotlight: AV positions
# ─────────────────────────────────────────────────────────────────────────────

def av_place_camera_position(p):
    """Mark a camera position in plan view.

    cx, cy       : position (mm).
    label        : 'CAM-1' | 'BROADCAST' | 'STREAMING' | 'RECORD'.
    camera_type  : 'broadcast' | 'handheld' | 'ptz' | 'jib' | 'streaming'.
    aim_deg      : direction camera faces (270 = toward stage/-Y, default).

    Draws a filled triangle (footprint) pointing toward the aim direction and a
    circle for the operator zone.  PTZ draws a circle only (no operator)."""
    prev = _with_layer_class({'layer': 'AV-Cameras', 'class': 'AV-Camera'})
    try:
        cx   = float(p.get('cx', 0))
        cy   = float(p.get('cy', 0))
        lbl  = str(p.get('label', 'CAM'))
        ctype = str(p.get('camera_type', 'broadcast')).lower()
        aim  = float(p.get('aim_deg', 270))

        ids = []
        aim_r = _math.radians(aim)

        if ctype == 'ptz':
            # PTZ: just a small filled circle on a wall/ceiling
            vs.ArcByCenter((cx, cy), 250, 0, 360)
            h = vs.LNewObj()
            if h:
                vs.SetFPat(h, 1)
                vs.SetFillFore(h, (_c8(30), _c8(30), _c8(30)))
                ids.append(_oid(h))
        else:
            # Operator zone circle
            zone_r = 750   # 1.5 m diameter working zone
            vs.ArcByCenter((cx, cy), zone_r, 0, 360)
            zone_h = vs.LNewObj()
            if zone_h:
                vs.SetFPat(zone_h, 0); vs.SetLW(zone_h, 18)
                try: vs.SetLSN(zone_h, 3)   # dashed
                except Exception: pass
            if zone_h: ids.append(_oid(zone_h))

            # Camera direction triangle (pointing toward aim)
            tip_d = 400    # triangle tip distance from cx,cy
            base_w = 350   # half-width at base
            perp_r = aim_r + _math.pi/2
            tip  = (cx + tip_d * _math.cos(aim_r), cy + tip_d * _math.sin(aim_r))
            bl   = (cx + base_w * _math.cos(perp_r), cy + base_w * _math.sin(perp_r))
            br   = (cx - base_w * _math.cos(perp_r), cy - base_w * _math.sin(perp_r))
            vs.ClosePoly(); vs.BeginPoly()
            for pt in [tip, bl, br, tip]:
                vs.Add2DVertex((pt[0], pt[1]), 0, 0)
            vs.EndPoly()
            tri_h = vs.LNewObj()
            if tri_h:
                vs.SetFPat(tri_h, 1)
                vs.SetFillFore(tri_h, (_c8(30), _c8(30), _c8(30)))
                vs.SetFillBack(tri_h, (_c8(30), _c8(30), _c8(30)))
                vs.SetLW(tri_h, 25)
                ids.append(_oid(tri_h))

        lbl_h = _av_draw_text(cx, cy - zone_r - 350 if ctype != 'ptz' else cy - 400,
                               lbl, size_mm=150)
        if lbl_h: ids.append(_oid(lbl_h))

        _av_attach_record(ids[0] if ids else None, AV_REC_DEVICE, {
            'Device_Type': f'Camera-{ctype}', 'Label': lbl,
        }) if ids else None

        return {'status': 'ok', 'object_ids': ids, 'position': {'x': cx, 'y': cy}}
    finally:
        _restore(prev)


def av_place_confidence_monitor(p):
    """Place a confidence monitor / stage monitor on stage floor in plan.

    cx, cy       : center (mm).
    width_mm     : screen width (default 1067 = 42 in diagonal ≈ 37 in wide).
    depth_mm     : plan depth (default 50 mm — flat on floor or slim stand).
    label        : 'CONF-1' | 'PROMPTER' | 'STAGE-MON'.
    facing       : 'presenter' (default, monitor faces upstage toward presenter)
                   | 'audience' (turned for audience-view / preview monitor).

    Placed on AV-Video layer with AV-Confidence-Mon class."""
    prev = _with_layer_class({'layer': 'AV-Video', 'class': 'AV-Confidence-Mon'})
    try:
        cx   = float(p.get('cx', 0))
        cy   = float(p.get('cy', 0))
        mw   = float(p.get('width_mm', 1067))
        md   = float(p.get('depth_mm', 50))
        lbl  = str(p.get('label', 'CONF'))

        vs.Rect((cx - mw/2, cy - md/2), (cx + mw/2, cy + md/2))
        h = vs.LNewObj()
        if h:
            vs.SetFPat(h, 1)
            vs.SetFillFore(h, (_c8(200), _c8(30), _c8(80)))
            vs.SetFillBack(h, (_c8(200), _c8(30), _c8(80)))
            vs.SetLW(h, 35)

        lbl_h = _av_draw_text(cx, cy + md/2 + 200, lbl, size_mm=120)
        ids = [_oid(x) for x in [h, lbl_h] if x]

        if h:
            _av_attach_record(h, AV_REC_DEVICE, {
                'Device_Type': 'Confidence Monitor', 'Label': lbl,
                'Trim_mm': 0,
            })

        return {'status': 'ok', 'object_ids': ids, 'center': {'x': cx, 'y': cy}}
    finally:
        _restore(prev)


# ─────────────────────────────────────────────────────────────────────────────
# Corporate / Spotlight: ancillary elements
# ─────────────────────────────────────────────────────────────────────────────

def av_place_registration(p):
    """Place a registration / check-in desk.

    cx, cy        : center of desk footprint (mm).
    width_mm      : desk width (default 3658 = 12 ft, space for 4 staff).
    depth_mm      : desk depth (default 762 = 30 in).
    n_staff_chairs: chairs on service (back) side (default 4).
    label         : 'REGISTRATION' | 'CHECK-IN' | 'BADGE PICKUP'.
    queue_depth_mm: if > 0, draws a dotted queue-management zone in front (default 2438)."""
    prev = _with_layer_class({'layer': 'AV-FOH', 'class': 'AV-Registration'})
    try:
        cx   = float(p.get('cx', 0))
        cy   = float(p.get('cy', 0))
        dw   = float(p.get('width_mm',  3658))
        dd   = float(p.get('depth_mm',   762))
        n_ch = int(p.get('n_staff_chairs', 4))
        lbl  = str(p.get('label', 'REGISTRATION'))
        q_d  = float(p.get('queue_depth_mm', 2438))

        ids = []

        # Queue zone (dotted boundary in front of desk)
        if q_d > 0:
            vs.Rect((cx - dw/2, cy - dd/2 - q_d), (cx + dw/2, cy - dd/2))
            qh = vs.LNewObj()
            if qh:
                vs.SetFPat(qh, 0); vs.SetLW(qh, 13)
                try: vs.SetLSN(qh, 3)
                except Exception: pass
            if qh: ids.append(_oid(qh))

        vs.Rect((cx - dw/2, cy - dd/2), (cx + dw/2, cy + dd/2))
        dh = vs.LNewObj()
        if dh:
            vs.SetFPat(dh, 1)
            vs.SetFillFore(dh, (_c8(90),  _c8(190), _c8(235)))
            vs.SetFillBack(dh, (_c8(90),  _c8(190), _c8(235)))
            vs.SetLW(dh, 35)
        if dh: ids.append(_oid(dh))

        # Staff chairs on back side
        if n_ch > 0:
            cw = min(480, dw / (n_ch + 1))
            gap = (dw - n_ch * cw) / (n_ch + 1)
            vs.NameClass('AV-Seating-Chair')
            for i in range(n_ch):
                cx_i = cx - dw/2 + gap + i * (cw + gap) + cw/2
                cy_i = cy + dd/2 + 80 + 200   # behind desk
                vs.ArcByCenter((cx_i, cy_i), 220, 0, 360)
                ch = vs.LNewObj()
                if ch:
                    vs.SetFPat(ch, 1)
                    vs.SetFillFore(ch, (_c8(180), _c8(180), _c8(180)))
                    vs.SetLW(ch, 13)
                    ids.append(_oid(ch))

        lbl_h = _av_draw_text(cx, cy, lbl, size_mm=160)
        if lbl_h: ids.append(_oid(lbl_h))

        return {'status': 'ok', 'object_ids': ids, 'center': {'x': cx, 'y': cy}}
    finally:
        _restore(prev)


def av_draw_seating_legend(p):
    """Draw a seating capacity legend box on the AV-Notes layer.

    cx, cy        : top-left corner of the box (mm).
    event_name    : event title shown at top.
    sections      : list of dicts, each with keys: label, tables (opt), seats.
                    e.g. [{'label':'General','tables':20,'seats':200},
                          {'label':'VIP','tables':5,'seats':50},
                          {'label':'ADA','seats':10}]
    box_width_mm  : legend box width (default 3000 mm).
    row_height_mm : height per line (default 250 mm).

    Returns object_ids of all legend elements."""
    prev = _with_layer_class({'layer': 'AV-Notes', 'class': 'AV-Notes'})
    try:
        cx       = float(p.get('cx', -15000))
        cy       = float(p.get('cy',  -5000))
        ev_name  = str(p.get('event_name', 'EVENT'))
        sections = p.get('sections', [])
        box_w    = float(p.get('box_width_mm', 3000))
        row_h    = float(p.get('row_height_mm', 300))

        n_rows  = 2 + len(sections)   # title + header + section rows
        box_h   = n_rows * row_h + 400

        # Box outline
        vs.Rect((cx, cy - box_h), (cx + box_w, cy))
        bh = vs.LNewObj()
        if bh:
            vs.SetFPat(bh, 0); vs.SetLW(bh, 35)

        ids = [_oid(bh)] if bh else []

        # Title
        lh = _av_draw_text(cx + box_w/2, cy - row_h/2,
                            ev_name.upper(), size_mm=225, align='center')
        if lh: ids.append(_oid(lh))

        # Column headers
        hdr = 'SECTION              TABLES    SEATS'
        lh = _av_draw_text(cx + box_w/2, cy - row_h - row_h/2,
                            hdr, size_mm=150, align='center')
        if lh: ids.append(_oid(lh))

        # Section rows
        total_seats = 0
        total_tables = 0
        for i, sec in enumerate(sections):
            row_y = cy - row_h * (i + 2) - row_h / 2
            tbl_txt = str(sec.get('tables', '—'))
            seat_txt = str(sec.get('seats', 0))
            line = f"{sec.get('label',''):<20}  {tbl_txt:>6}    {seat_txt:>6}"
            lh = _av_draw_text(cx + box_w/2, row_y,
                                line, size_mm=150, align='center')
            if lh: ids.append(_oid(lh))
            total_seats  += int(sec.get('seats', 0))
            total_tables += int(sec.get('tables', 0)) if 'tables' in sec else 0

        # Total row
        tot_y = cy - row_h * (len(sections) + 2) - row_h / 2 - 50
        vs.MoveTo((cx, tot_y + row_h)); vs.LineTo((cx + box_w, tot_y + row_h))
        lh_line = vs.LNewObj()
        if lh_line: ids.append(_oid(lh_line))

        tot_txt = f"{'TOTAL':<20}  {total_tables:>6}    {total_seats:>6}"
        lh = _av_draw_text(cx + box_w/2, tot_y + row_h/2,
                            tot_txt, size_mm=175, align='center')
        if lh: ids.append(_oid(lh))

        return {
            'status': 'ok', 'object_ids': ids,
            'total_seats': total_seats, 'total_tables': total_tables,
        }
    finally:
        _restore(prev)
