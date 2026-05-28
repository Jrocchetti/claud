"""
av_tools.py — AV Ballroom MCP Tool Wrappers

Add to vwx_mcp_server.py with:
    from av_tools import register_av_tools
    register_av_tools(mcp, cmd)

Or append this file's content directly after the existing tools.

Provides:
  Pure-math tools (no VW needed):
    av_calc_throw           — projector throw geometry
    av_calc_speaker_coverage — speaker coverage footprint
    av_calc_sightline       — per-row sightline analysis
    av_calc_seating_capacity — table layout capacity estimate

  VW-dispatching tools (require live VW session):
    av_setup_document       — create AV layers / classes / records
    av_draw_room            — room boundary rectangle
    av_draw_stage           — stage platform with deck annotation
    av_place_speaker        — single speaker / point source
    av_place_speaker_cluster — line-array cluster with rigging marker
    av_place_subwoofer      — sub stack
    av_place_screen         — projection screen or LED wall
    av_place_truss          — truss segment with rigging points
    av_place_round_table    — single round table + chairs
    av_layout_seating       — auto-layout full seating section
    av_place_foh            — Front of House mix position
    av_draw_cable_run       — labelled cable / signal run
    av_place_power_distro   — power distribution unit
    av_rigging_summary      — load summary from rigging records

  Orchestration:
    av_ballroom_layout      — full ballroom from a brief (one-shot)
"""

import json
import math
from typing import Optional
from mcp.server.fastmcp import Context


# ─────────────────────────────────────────────────────────────────────────────
# Helper — injected by register_av_tools
# ─────────────────────────────────────────────────────────────────────────────

_cmd = None   # set to the server's cmd() function


def register_av_tools(mcp_instance, cmd_fn):
    """Call once from vwx_mcp_server.py to register all AV tools."""
    global _cmd
    _cmd = cmd_fn
    _register(mcp_instance)


# ─────────────────────────────────────────────────────────────────────────────
# Pure-math tools
# ─────────────────────────────────────────────────────────────────────────────

def _register(mcp):

    @mcp.tool(structured_output=False)
    def av_calc_throw(
        ctx: Context,
        screen_width_mm: float,
        throw_ratio: Optional[float] = None,
        projector_distance_mm: Optional[float] = None,
        screen_height_mm: Optional[float] = None,
        screen_aspect: str = "16:9",
    ) -> str:
        """Calculate projector throw geometry.

        Provide screen_width_mm and EITHER throw_ratio OR projector_distance_mm.
        Returns throw distance, image dimensions, and recommendations.

        Common throw ratios: 0.8 ultra-short  |  1.2 short  |  1.8–2.0 standard  |  3.0+ long"""
        if ':' in str(screen_aspect):
            aw, ah = [float(v) for v in screen_aspect.split(':')]
            ar = ah / aw
        else:
            ar = float(screen_aspect)

        sw = float(screen_width_mm)
        sh = float(screen_height_mm) if screen_height_mm else sw * ar
        diag_mm = math.sqrt(sw**2 + sh**2)

        result = {
            'screen': {
                'width_mm': sw,  'width_ft':   round(sw/304.8, 2),
                'height_mm': round(sh, 0), 'height_ft': round(sh/304.8, 2),
                'diagonal_mm': round(diag_mm, 0),
                'diagonal_in': round(diag_mm/25.4, 1),
                'aspect': screen_aspect,
            },
        }

        if throw_ratio is not None:
            td = sw * float(throw_ratio)
        elif projector_distance_mm is not None:
            td = float(projector_distance_mm)
            throw_ratio = td / sw
        else:
            result['error'] = 'Provide throw_ratio or projector_distance_mm'
            return json.dumps(result, indent=2)

        result['throw'] = {
            'distance_mm': round(td, 0),
            'distance_ft': round(td/304.8, 2),
            'ratio':        round(td/sw, 3),
            'half_angle_deg': round(math.degrees(math.atan(sw/2 / td)), 2),
        }

        # Lens offset: projector lens height should match screen centre
        screen_centre_h = (2438 + sh/2)   # assuming 8 ft trim
        result['setup_notes'] = {
            'typical_screen_bottom_ft': 8.0,
            'lens_height_at_screen_centre_mm': round(screen_centre_h, 0),
        }

        recs = []
        td_ft = td / 304.8
        if td_ft < 20:
            recs.append("Very short throw — likely needs ultra-short throw or ceiling-mount")
        if td_ft > 120:
            recs.append(f"Long throw {td_ft:.0f}' — verify projector has sufficient brightness (25k+ lm)")
        if sw/304.8 < 14:
            recs.append(f"Screen {sw/304.8:.0f}' wide — may be small for audiences beyond row 15")
        result['recommendations'] = recs

        return json.dumps(result, indent=2)


    @mcp.tool(structured_output=False)
    def av_calc_speaker_coverage(
        ctx: Context,
        trim_mm: float,
        h_angle_deg: float,
        v_angle_deg: float,
        downtilt_deg: float = 15.0,
        floor_height_mm: float = 0.0,
    ) -> str:
        """Calculate flown speaker coverage footprint on the floor.

        trim_mm        : speaker height above floor.
        h_angle_deg    : horizontal coverage (-6 dB angle).
        v_angle_deg    : vertical coverage (-6 dB angle).
        downtilt_deg   : aim angle below horizontal (positive = angled down).
        floor_height_mm: reference floor (0 = level floor under speaker).

        Returns near/far edges of vertical coverage and horizontal spread
        at 5 distances across the coverage zone."""
        eff_h = trim_mm - floor_height_mm
        if eff_h <= 0:
            return json.dumps({'error': 'trim_mm must be greater than floor_height_mm'})

        tilt_r  = math.radians(downtilt_deg)
        half_v  = math.radians(v_angle_deg / 2)
        half_h  = math.radians(h_angle_deg / 2)

        # Floor intercepts
        far_ang  = tilt_r + half_v
        near_ang = tilt_r - half_v

        far_mm  = eff_h * math.tan(far_ang)  if far_ang  < math.radians(89.9) else 99999
        near_mm = eff_h * math.tan(near_ang) if near_ang > 0                  else 0

        # Horizontal spread at 5 sample depths
        spread_data = []
        cap = min(far_mm, 30000)
        for t in range(5):
            d = near_mm + (cap - near_mm) * t / 4 if cap > near_mm else near_mm + t * 3000
            if d > 0:
                spread = 2 * d * math.tan(half_h)
                spread_data.append({
                    'depth_ft': round(d/304.8, 1),
                    'spread_ft': round(spread/304.8, 1),
                    'spread_mm': round(spread, 0),
                })

        recs = []
        trim_ft = trim_mm / 304.8
        if trim_ft < 15:
            recs.append(f"Low trim {trim_ft:.1f}' — consider 18-22' for better even coverage")
        if trim_ft > 30:
            recs.append(f"High trim {trim_ft:.1f}' — verify SPL at near seats")
        if near_mm > 6000:
            recs.append(f"Near-field gap {near_mm/304.8:.0f}' — add front fills or delay speakers")
        if v_angle_deg < 15:
            recs.append("Narrow V angle — check near-field coverage for front rows")
        if h_angle_deg > 120:
            recs.append("Wide H angle — risk of comb filtering with adjacent arrays")

        return json.dumps({
            'trim_ft': round(trim_ft, 1),
            'h_angle': h_angle_deg, 'v_angle': v_angle_deg, 'downtilt': downtilt_deg,
            'coverage': {
                'near_edge_ft': round(near_mm/304.8, 1),
                'far_edge_ft':  round(far_mm/304.8, 1) if far_mm < 90000 else 'unlimited',
                'near_edge_mm': round(near_mm, 0),
                'far_edge_mm':  round(far_mm, 0) if far_mm < 90000 else None,
                'spread_at_depth': spread_data,
            },
            'recommendations': recs,
        }, indent=2)


    @mcp.tool(structured_output=False)
    def av_calc_sightline(
        ctx: Context,
        room_length_mm: float,
        stage_height_mm: float = 762,
        screen_trim_mm: float = 2438,
        seat_row_depth_mm: float = 1829,
        n_rows: int = 20,
        row_1_from_stage_mm: float = 3048,
        eye_height_seated_mm: float = 1180,
        riser_height_per_row_mm: float = 0.0,
    ) -> str:
        """Per-row sightline analysis to stage deck and screen bottom.

        Flat-floor or uniformly raked floor.  Returns a C-value for each row
        (mm of clearance above the previous row's eye-line to the focal point).
        C ≥ 75 mm  → good.  C 30–75 mm → marginal.  C < 30 mm → poor / blocked.

        stage_height_mm       : deck height above audience floor.
        screen_trim_mm        : height of screen bottom from floor.
        seat_row_depth_mm     : row-to-row centre distance.
        row_1_from_stage_mm   : distance from stage edge to front row centre.
        eye_height_seated_mm  : typical seated eye height from row floor (≈ 1180 mm).
        riser_height_per_row_mm: floor rise per row (0 = flat)."""
        rows = []
        prev_eye = 0.0
        prev_dist = 0.0

        for i in range(n_rows):
            row_num  = i + 1
            dist     = row_1_from_stage_mm + i * seat_row_depth_mm
            floor_h  = riser_height_per_row_mm * i
            eye_h    = floor_h + eye_height_seated_mm

            c_stage  = None
            c_screen = None
            stage_ok = True
            screen_ok = True

            if i > 0:
                # C-value to stage edge
                slope_stg = (prev_eye - stage_height_mm) / prev_dist
                req_stg   = stage_height_mm + slope_stg * dist
                c_stage   = round(eye_h - req_stg, 1)
                stage_ok  = c_stage >= 0

                # C-value to screen bottom
                slope_scr = (prev_eye - screen_trim_mm) / prev_dist
                req_scr   = screen_trim_mm + slope_scr * dist
                c_screen  = round(eye_h - req_scr, 1)
                screen_ok = c_screen >= 0

            quality = ('first_row' if i == 0
                       else 'blocked' if (c_stage is not None and c_stage < 0)
                       else 'poor'    if (c_stage is not None and c_stage < 30)
                       else 'marginal'if (c_stage is not None and c_stage < 75)
                       else 'good')

            rows.append({
                'row': row_num,
                'dist_from_stage_ft': round(dist/304.8, 1),
                'eye_height_mm': round(eye_h, 0),
                'c_stage_mm':  c_stage,
                'c_screen_mm': c_screen,
                'stage_visible':  stage_ok,
                'screen_visible': screen_ok,
                'quality': quality,
            })

            prev_eye  = eye_h
            prev_dist = dist

        blocked_stg = sum(1 for r in rows if not r['stage_visible'])
        blocked_scr = sum(1 for r in rows if not r['screen_visible'])
        poor_c      = sum(1 for r in rows if r.get('c_stage_mm') is not None and 0 <= r['c_stage_mm'] < 75)

        recs = []
        if blocked_stg:
            recs.append(f"{blocked_stg} rows have blocked stage view — raise stage or add risers")
        if blocked_scr:
            recs.append(f"{blocked_scr} rows have blocked screen view — raise screen trim")
        if poor_c:
            recs.append(f"{poor_c} rows marginal/poor C-value — consider raked floor or taller stage")
        if screen_trim_mm < 1830:
            recs.append("Screen trim < 6' — will be blocked from most rows beyond row 5 on flat floor")

        return json.dumps({
            'params': {
                'stage_height_mm': stage_height_mm,
                'screen_trim_mm': screen_trim_mm,
                'row_depth_mm': seat_row_depth_mm,
                'floor_type': 'flat' if riser_height_per_row_mm == 0
                              else f'raked {riser_height_per_row_mm}mm/row',
            },
            'summary': {
                'rows_blocked_stage': blocked_stg,
                'rows_blocked_screen': blocked_scr,
                'rows_poor_c_value': poor_c,
            },
            'per_row': rows,
            'recommendations': recs,
        }, indent=2)


    @mcp.tool(structured_output=False)
    def av_calc_seating_capacity(
        ctx: Context,
        room_width_mm: float,
        room_length_mm: float,
        stage_depth_mm: float = 4877,
        foh_depth_mm: float = 2438,
        table_diameter_mm: float = 1828,
        n_seats_per_table: int = 10,
        col_spacing_mm: float = 2743,
        row_spacing_mm: float = 2743,
        side_aisle_mm: float = 1524,
        center_aisle_mm: float = 0,
        back_clearance_mm: float = 1829,
        front_clearance_mm: float = 3048,
    ) -> str:
        """Estimate round-table seating capacity given room and layout constraints.

        Returns: table count, seat count, density, and layout grid parameters.
        All dimensions mm."""
        avail_w = room_width_mm  - 2 * side_aisle_mm - center_aisle_mm
        avail_l = room_length_mm - stage_depth_mm - front_clearance_mm \
                                 - foh_depth_mm   - back_clearance_mm

        if avail_w <= 0 or avail_l <= 0:
            return json.dumps({'error': 'No space left after constraints — check dimensions'})

        n_cols = max(0, int((avail_w - table_diameter_mm) / col_spacing_mm) + 1)
        n_rows = max(0, int((avail_l - table_diameter_mm) / row_spacing_mm) + 1)
        tables = n_cols * n_rows
        seats  = tables * n_seats_per_table

        area_m2 = (room_width_mm/1000) * (room_length_mm/1000)
        density = seats / area_m2 if area_m2 else 0

        circ = math.pi * table_diameter_mm
        arc  = circ / n_seats_per_table

        recs = []
        if arc < 457:
            recs.append(f"Only {arc:.0f} mm/seat — tight; reduce seats per table or use larger table")
        if col_spacing_mm < table_diameter_mm + 914:
            recs.append("Column spacing < table + 3 ft — service access very tight")
        if density > 0.85:
            recs.append(f"High density ({density:.2f}/m²) — verify fire-egress compliance")
        if seats > 600:
            recs.append("Large event (600+ seats) — plan audio sub-zones and satellite screens")

        return json.dumps({
            'room': {
                'width_ft':  round(room_width_mm/304.8, 0),
                'length_ft': round(room_length_mm/304.8, 0),
                'area_m2':   round(area_m2, 0),
                'area_sqft': round(area_m2*10.764, 0),
            },
            'capacity': {
                'tables': tables, 'seats': seats,
                'grid_cols': n_cols, 'grid_rows': n_rows,
            },
            'table': {
                'diameter_in': round(table_diameter_mm/25.4, 0),
                'seats_per_table': n_seats_per_table,
                'arc_per_seat_mm': round(arc, 0),
            },
            'spacing': {
                'col_spacing_ft': round(col_spacing_mm/304.8, 1),
                'row_spacing_ft': round(row_spacing_mm/304.8, 1),
                'available_width_ft':  round(avail_w/304.8, 1),
                'available_length_ft': round(avail_l/304.8, 1),
            },
            'density': {
                'seats_per_m2': round(density, 3),
                'sqft_per_seat': round(107.64/density, 1) if density else None,
            },
            'recommendations': recs,
        }, indent=2)


    # ─────────────────────────────────────────────────────────────────────────
    # VW-dispatching tools (pass-through wrappers)
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_setup_document(ctx: Context) -> str:
        """Create AV standard layers, classes, and record formats in the open VW document.
        Idempotent — safe to run on an existing file.
        Creates: AV-Room … AV-Notes layers; AV-Speaker / AV-Truss / etc. classes;
        AV Device, AV Rigging Point, and AV Cable record formats."""
        return _cmd('av_setup_document', {})

    @mcp.tool(structured_output=False)
    def av_draw_room(ctx: Context, width_mm: float, length_mm: float,
                     origin: str = 'center') -> str:
        """Draw the room boundary rectangle on the AV-Room layer.
        origin: 'center' (default, room centred on 0,0) or 'corner' (origin at SW corner)."""
        return _cmd('av_draw_room', {'width_mm': width_mm, 'length_mm': length_mm,
                                     'origin': origin})

    @mcp.tool(structured_output=False)
    def av_draw_stage(ctx: Context, width_mm: float, depth_mm: float,
                      height_mm: float = 762, room_length_mm: float = 24384,
                      position: str = 'north') -> str:
        """Draw stage platform on the AV-Stage layer.
        position: 'north' (top of drawing, default), 'south', 'east', 'west'.
        height_mm: deck height above audience floor (default 762 = 30 in)."""
        return _cmd('av_draw_stage', {
            'width_mm': width_mm, 'depth_mm': depth_mm,
            'height_mm': height_mm, 'room_length_mm': room_length_mm,
            'position': position,
        })

    @mcp.tool(structured_output=False)
    def av_place_speaker(ctx: Context, x: float, y: float, label: str,
                         trim_mm: float = 6096,
                         h_angle_deg: float = 90, v_angle_deg: float = 30,
                         downtilt_deg: float = 15.0,
                         model: str = '', weight_kg: float = 0,
                         power_w: float = 0,
                         rotation_deg: float = 0,
                         draw_coverage: bool = True) -> str:
        """Place a single speaker or point-source box in plan view.
        Draws footprint rectangle + trim annotation + optional coverage wedge.
        label: e.g. 'L Array', 'C-FILL', 'FRONT-FILL'."""
        return _cmd('av_place_speaker', {
            'x': x, 'y': y, 'label': label, 'trim_mm': trim_mm,
            'h_angle_deg': h_angle_deg, 'v_angle_deg': v_angle_deg,
            'downtilt_deg': downtilt_deg, 'model': model,
            'weight_kg': weight_kg, 'power_w': power_w,
            'rotation_deg': rotation_deg, 'draw_coverage': draw_coverage,
        })

    @mcp.tool(structured_output=False)
    def av_place_speaker_cluster(ctx: Context, x: float, y: float, label: str,
                                  n_boxes: int = 8, trim_mm: float = 6700,
                                  h_angle_deg: float = 90, v_angle_deg: float = 20,
                                  downtilt_deg: float = 18.0,
                                  box_width_mm: float = 560, box_depth_mm: float = 380,
                                  weight_per_box_kg: float = 35,
                                  draw_coverage: bool = True) -> str:
        """Place a line-array cluster with rigging point marker.
        Attaches AV Rigging Point record with trim height and total weight.
        label: 'L', 'R', 'C', 'SL', 'SR', etc."""
        return _cmd('av_place_speaker_cluster', {
            'x': x, 'y': y, 'label': label, 'n_boxes': n_boxes,
            'trim_mm': trim_mm, 'h_angle_deg': h_angle_deg,
            'v_angle_deg': v_angle_deg, 'downtilt_deg': downtilt_deg,
            'box_width_mm': box_width_mm, 'box_depth_mm': box_depth_mm,
            'weight_per_box_kg': weight_per_box_kg, 'draw_coverage': draw_coverage,
        })

    @mcp.tool(structured_output=False)
    def av_place_subwoofer(ctx: Context, x: float, y: float, label: str,
                            n_boxes: int = 4,
                            box_width_mm: float = 750, box_depth_mm: float = 800,
                            weight_per_box_kg: float = 80) -> str:
        """Place a subwoofer stack in plan view on the AV-Audio layer."""
        return _cmd('av_place_subwoofer', {
            'x': x, 'y': y, 'label': label, 'n_boxes': n_boxes,
            'box_width_mm': box_width_mm, 'box_depth_mm': box_depth_mm,
            'weight_per_box_kg': weight_per_box_kg,
        })

    @mcp.tool(structured_output=False)
    def av_place_screen(ctx: Context, x: float, y: float,
                         width_mm: float, label: str,
                         height_mm: Optional[float] = None,
                         aspect: str = '16:9',
                         trim_mm: float = 2438,
                         screen_type: str = 'front-projection',
                         depth_mm: float = 300) -> str:
        """Place a projection screen or LED wall in plan view.
        screen_type: 'front-projection' | 'rear-projection' | 'LED' | 'motorized'.
        trim_mm: screen bottom height from floor (default 2438 = 8 ft).
        Returns width, height, trim, and top height."""
        p: dict = {
            'x': x, 'y': y, 'width_mm': width_mm, 'label': label,
            'aspect': aspect, 'trim_mm': trim_mm,
            'screen_type': screen_type, 'depth_mm': depth_mm,
        }
        if height_mm is not None:
            p['height_mm'] = height_mm
        return _cmd('av_place_screen', p)

    @mcp.tool(structured_output=False)
    def av_place_truss(ctx: Context, x1: float, y1: float, x2: float, y2: float,
                        trim_mm: float = 6096, label: str = 'TRUSS',
                        truss_type: str = '20.5in',
                        capacity_kg: float = 500) -> str:
        """Place a straight truss segment in plan view.
        Draws outline, centerline, and rigging-point circles with records.
        truss_type: '12in' | '18in' | '20.5in' (default) | '30in'."""
        return _cmd('av_place_truss', {
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'trim_mm': trim_mm, 'label': label,
            'truss_type': truss_type, 'capacity_kg': capacity_kg,
        })

    @mcp.tool(structured_output=False)
    def av_place_round_table(ctx: Context, cx: float, cy: float,
                              diameter_mm: float = 1828, n_seats: int = 10,
                              label: str = '') -> str:
        """Place a single round table with chair markers.
        diameter_mm: 1524 = 60 in (5 ft)  |  1828 = 72 in (6 ft, default)."""
        return _cmd('av_place_round_table', {
            'cx': cx, 'cy': cy,
            'diameter_mm': diameter_mm, 'n_seats': n_seats, 'label': label,
        })

    @mcp.tool(structured_output=False)
    def av_layout_seating(ctx: Context,
                           x1: float, y1: float, x2: float, y2: float,
                           diameter_mm: float = 1828, n_seats: int = 10,
                           col_spacing_mm: float = 2743, row_spacing_mm: float = 2743,
                           aisle_x_mm: float = 0,
                           start_table_num: int = 1) -> str:
        """Auto-layout round tables filling a rectangular section.
        col/row_spacing_mm: centre-to-centre table pitch (default 2743 = 9 ft).
        aisle_x_mm: if > 0, leaves a centre aisle of that width.
        Returns tables_placed and total_seats."""
        return _cmd('av_layout_seating', {
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'diameter_mm': diameter_mm, 'n_seats': n_seats,
            'col_spacing_mm': col_spacing_mm, 'row_spacing_mm': row_spacing_mm,
            'aisle_x_mm': aisle_x_mm, 'start_table_num': start_table_num,
        })

    @mcp.tool(structured_output=False)
    def av_place_foh(ctx: Context, cx: float, cy: float,
                      width_mm: float = 3658, depth_mm: float = 1524,
                      label: str = 'FOH', has_riser: bool = True) -> str:
        """Place Front of House mix position.
        Draws the console table footprint and a 3-ft clearance riser perimeter."""
        return _cmd('av_place_foh', {
            'cx': cx, 'cy': cy,
            'width_mm': width_mm, 'depth_mm': depth_mm,
            'label': label, 'has_riser': has_riser,
        })

    @mcp.tool(structured_output=False)
    def av_draw_cable_run(ctx: Context, points: list, cable_type: str = 'audio',
                           label: str = '',
                           from_device: str = '', to_device: str = '',
                           connector_a: str = '', connector_b: str = '') -> str:
        """Draw a cable run as a labelled, colour-coded polyline.
        points: [[x1,y1],[x2,y2],...] in mm.
        cable_type: 'audio' | 'video' | 'power' | 'data' | 'dmx' | 'ethernet' | 'fiber'.
        Returns object IDs and measured length."""
        return _cmd('av_draw_cable_run', {
            'points': points, 'cable_type': cable_type, 'label': label,
            'from_device': from_device, 'to_device': to_device,
            'connector_a': connector_a, 'connector_b': connector_b,
        })

    @mcp.tool(structured_output=False)
    def av_place_power_distro(ctx: Context, cx: float, cy: float,
                               label: str = 'DISTRO', amperage: int = 200,
                               phase: str = '3ph',
                               width_mm: float = 1200, depth_mm: float = 800) -> str:
        """Place a power distribution unit (PDU / distro box)."""
        return _cmd('av_place_power_distro', {
            'cx': cx, 'cy': cy, 'label': label,
            'amperage': amperage, 'phase': phase,
            'width_mm': width_mm, 'depth_mm': depth_mm,
        })

    @mcp.tool(structured_output=False)
    def av_rigging_summary(ctx: Context) -> str:
        """Scan all objects with AV Rigging Point records and return a load summary.
        Flags any point where load exceeds 80 % of rated capacity."""
        return _cmd('av_rigging_summary', {})

    # ─────────────────────────────────────────────────────────────────────────
    # Full-ballroom orchestration
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_ballroom_layout(
        ctx: Context,
        room_width_mm: float,
        room_length_mm: float,
        room_height_mm: float = 9144,
        stage_width_mm: float = 12192,
        stage_depth_mm: float = 4877,
        stage_height_mm: float = 762,
        screen_trim_mm: float = 2743,
        audio_system: str = 'flown_line_array',
        seating_style: str = 'rounds_10',
        foh_position_pct: float = 0.65,
        event_name: str = 'Ballroom Event',
        main_screen_width_mm: Optional[float] = None,
    ) -> str:
        """Orchestrate a complete ballroom AV layout from a brief.

        Runs in sequence:
          1. av_setup_document  (layers / classes / records)
          2. av_draw_room
          3. av_draw_stage
          4. av_place_screen × 3  (IMAG-L, IMAG-R, MAIN)
          5. av_place_speaker_cluster × 2 + av_place_subwoofer × 2
             (or av_place_speaker × 2 for point-source)
          6. av_place_truss × 2  (front + mid)
          7. av_layout_seating
          8. av_place_foh
          9. av_place_power_distro
         10. zoom_to_fit

        audio_system : 'flown_line_array' (default) | 'flown_point_source' | 'ground_stack'
        seating_style: 'rounds_8' | 'rounds_10' (default) | 'rounds_12'
        foh_position_pct: 0.0 = back wall, 1.0 = stage (default 0.65 = 65 % from back)

        Returns a JSON summary and per-element results."""

        results = {}
        errs    = []

        def _do(key, command, params):
            try:
                results[key] = json.loads(_cmd(command, params))
            except Exception as e:
                results[key] = {'error': str(e)}
                errs.append(f"{key}: {e}")

        # ── 1. Document setup ──────────────────────────────────────────────
        _do('setup', 'av_setup_document', {})

        # ── 2. Room ────────────────────────────────────────────────────────
        _do('room', 'av_draw_room', {
            'width_mm': room_width_mm, 'length_mm': room_length_mm, 'origin': 'center',
        })

        # ── 3. Stage ───────────────────────────────────────────────────────
        _do('stage', 'av_draw_stage', {
            'width_mm': stage_width_mm, 'depth_mm': stage_depth_mm,
            'height_mm': stage_height_mm, 'room_length_mm': room_length_mm,
            'position': 'north',
        })
        stage_front_y = -(room_length_mm/2 - stage_depth_mm)   # negative Y = downstage edge

        # ── 4. Screen sizing ───────────────────────────────────────────────
        # Main screens: aim for ≈30° horizontal angle from the back row
        back_row_dist = room_length_mm - stage_depth_mm
        if main_screen_width_mm is None:
            calc_w = 2 * back_row_dist * math.tan(math.radians(15))
            main_screen_width_mm = max(4572, min(calc_w, room_width_mm * 0.50))

        screen_y   = room_length_mm / 2   # at the north (stage) wall
        center_w   = min(stage_width_mm * 0.82, room_width_mm * 0.44)
        imag_x_off = stage_width_mm/2 + main_screen_width_mm/2 + 610
        imag_x_off = min(imag_x_off, room_width_mm/2 - main_screen_width_mm/2 - 305)

        _do('screen_left',  'av_place_screen', {
            'x': -imag_x_off, 'y': screen_y, 'width_mm': main_screen_width_mm,
            'trim_mm': screen_trim_mm, 'screen_type': 'front-projection', 'label': 'IMAG-L',
        })
        _do('screen_right', 'av_place_screen', {
            'x':  imag_x_off, 'y': screen_y, 'width_mm': main_screen_width_mm,
            'trim_mm': screen_trim_mm, 'screen_type': 'front-projection', 'label': 'IMAG-R',
        })
        _do('screen_main', 'av_place_screen', {
            'x': 0, 'y': screen_y, 'width_mm': center_w,
            'trim_mm': screen_trim_mm + 305, 'screen_type': 'front-projection', 'label': 'MAIN',
        })

        # ── 5. Audio ───────────────────────────────────────────────────────
        trim_spk = min(room_height_mm * 0.65, 7315)   # 65 % of ceiling, max 24 ft
        arr_x    = stage_width_mm/2 + 1524             # 5 ft outside stage edge
        arr_y    = stage_front_y + 1524                # slightly upstage of stage front

        if audio_system == 'flown_line_array':
            _do('spk_l', 'av_place_speaker_cluster', {
                'x': -arr_x, 'y': arr_y, 'label': 'L', 'n_boxes': 8,
                'trim_mm': trim_spk, 'h_angle_deg': 90, 'v_angle_deg': 20,
                'downtilt_deg': 18, 'draw_coverage': True,
            })
            _do('spk_r', 'av_place_speaker_cluster', {
                'x':  arr_x, 'y': arr_y, 'label': 'R', 'n_boxes': 8,
                'trim_mm': trim_spk, 'h_angle_deg': 90, 'v_angle_deg': 20,
                'downtilt_deg': 18, 'draw_coverage': True,
            })
            _do('spk_c', 'av_place_speaker', {
                'x': 0, 'y': stage_front_y, 'label': 'C-FILL',
                'trim_mm': trim_spk * 0.55, 'h_angle_deg': 100,
                'v_angle_deg': 60, 'downtilt_deg': 30, 'draw_coverage': False,
            })
        else:  # point source or ground stack
            _do('spk_l', 'av_place_speaker', {
                'x': -stage_width_mm/3, 'y': stage_front_y, 'label': 'L PS',
                'trim_mm': trim_spk * 0.85, 'h_angle_deg': 100,
                'v_angle_deg': 60, 'downtilt_deg': 20, 'draw_coverage': True,
            })
            _do('spk_r', 'av_place_speaker', {
                'x':  stage_width_mm/3, 'y': stage_front_y, 'label': 'R PS',
                'trim_mm': trim_spk * 0.85, 'h_angle_deg': 100,
                'v_angle_deg': 60, 'downtilt_deg': 20, 'draw_coverage': True,
            })

        # Subs (always ground-stack)
        sub_x = stage_width_mm/2 + 200
        _do('sub_l', 'av_place_subwoofer', {'x': -sub_x, 'y': stage_front_y, 'label': 'SUB-L', 'n_boxes': 4})
        _do('sub_r', 'av_place_subwoofer', {'x':  sub_x, 'y': stage_front_y, 'label': 'SUB-R', 'n_boxes': 4})

        # ── 6. Truss ───────────────────────────────────────────────────────
        truss_trim = min(room_height_mm * 0.70, 7925)
        half_stage = stage_width_mm/2 + 1000
        _do('truss_front', 'av_place_truss', {
            'x1': -half_stage, 'y1': stage_front_y + 1000,
            'x2':  half_stage, 'y2': stage_front_y + 1000,
            'trim_mm': truss_trim, 'label': 'T-1 FRONT', 'truss_type': '20.5in',
        })
        _do('truss_mid', 'av_place_truss', {
            'x1': -half_stage, 'y1': stage_front_y + stage_depth_mm * 0.5,
            'x2':  half_stage, 'y2': stage_front_y + stage_depth_mm * 0.5,
            'trim_mm': truss_trim, 'label': 'T-2 MID', 'truss_type': '20.5in',
        })

        # ── 7. Seating ─────────────────────────────────────────────────────
        n_seat = int(seating_style.split('_')[-1]) if '_' in seating_style else 10
        foh_y  = -room_length_mm/2 + room_length_mm * (1 - foh_position_pct)
        seat_x1 = -room_width_mm/2 + 1524
        seat_x2 =  room_width_mm/2 - 1524
        seat_y1 = -room_length_mm/2 + 1524
        seat_y2 = stage_front_y - 3048   # 10 ft clear from stage edge

        _do('seating', 'av_layout_seating', {
            'x1': seat_x1, 'y1': seat_y1, 'x2': seat_x2, 'y2': seat_y2,
            'diameter_mm': 1828, 'n_seats': n_seat,
            'col_spacing_mm': 2743, 'row_spacing_mm': 2743,
            'aisle_x_mm': 0, 'start_table_num': 1,
        })

        # ── 8. FOH ─────────────────────────────────────────────────────────
        _do('foh', 'av_place_foh', {
            'cx': 0, 'cy': foh_y,
            'width_mm': 5486, 'depth_mm': 1524, 'label': 'FOH',
        })

        # ── 9. Power distro ────────────────────────────────────────────────
        _do('power_distro', 'av_place_power_distro', {
            'cx': room_width_mm/2 - 1200, 'cy': stage_front_y,
            'label': 'A-DISTRO', 'amperage': 200, 'phase': '3ph',
        })

        # ── 10. Zoom to fit ────────────────────────────────────────────────
        try:
            results['view'] = json.loads(_cmd('zoom_to_fit', {}))
        except Exception:
            pass

        # ── Summary ────────────────────────────────────────────────────────
        seating = results.get('seating', {})
        summary = {
            'event_name':  event_name,
            'room':        {'width_ft': round(room_width_mm/304.8, 0),
                            'length_ft': round(room_length_mm/304.8, 0),
                            'height_ft': round(room_height_mm/304.8, 0)},
            'stage':       {'width_ft': round(stage_width_mm/304.8, 0),
                            'depth_ft': round(stage_depth_mm/304.8, 0),
                            'deck_in':  round(stage_height_mm/25.4, 0)},
            'screens':     {'main_width_ft':  round(center_w/304.8, 1),
                            'imag_width_ft':  round(main_screen_width_mm/304.8, 1),
                            'trim_ft':        round(screen_trim_mm/304.8, 1)},
            'audio':       {'system': audio_system,
                            'speaker_trim_ft': round(trim_spk/304.8, 1)},
            'seating':     {'tables': seating.get('tables_placed', 0),
                            'total_seats': seating.get('total_seats', 0)},
            'foh':         {'dist_from_stage_ft':
                            round((stage_front_y - foh_y) / 304.8, 0)},
            'errors':      errs,
        }

        return json.dumps({'status': 'ok' if not errs else 'partial',
                           'summary': summary, 'detail': results}, indent=2)
