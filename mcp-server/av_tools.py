"""
av_tools.py — AV Corporate Event / Spotlight MCP Tool Wrappers

Add to vwx_mcp_server.py with:
    from av_tools import register_av_tools
    register_av_tools(mcp, cmd)

Vectorworks Spotlight notes:
  - Layers are named AV-Lighting, AV-Seating, AV-Rigging, etc. to align with
    Spotlight's event planning conventions.
  - AV Seat records (Row, Seat_Num, Section, ADA, Status, Assignment) can be
    queried from Spotlight's custom worksheet reports.
  - For final client-facing seating maps, use Spotlight's native Seating Section
    tool on top of / instead of the av_layout_* drawn geometry.

Provides:
  Pure-math tools (no VW needed):
    av_calc_throw              — projector throw geometry
    av_calc_speaker_coverage   — speaker coverage footprint
    av_calc_sightline          — per-row sightline analysis
    av_calc_seating_capacity   — round-table layout capacity estimate
    av_calc_theater_capacity   — theater-row seating capacity estimate

  VW-dispatching tools (require live VW session):
    av_setup_document          — create AV layers / classes / records
    av_draw_room               — room boundary
    av_draw_stage              — stage platform
    av_place_speaker           — single speaker / point source
    av_place_speaker_cluster   — line-array cluster
    av_place_subwoofer         — sub stack
    av_place_screen            — projection screen or LED wall
    av_place_truss             — truss with rigging points
    av_place_round_table       — single round table + chairs
    av_layout_seating          — banquet round-table grid
    av_place_foh               — Front of House mix position
    av_draw_cable_run          — labelled cable / signal run
    av_place_power_distro      — PDU / distro box
    av_rigging_summary         — load summary from rigging records
    — Corporate additions —
    av_place_podium            — corporate podium / lectern + conf monitor
    av_place_head_table        — panel / dais head table with chairs
    av_layout_theater_seating  — theater rows with lettered/numbered seats + ADA
    av_layout_classroom        — classroom-style table rows
    av_place_camera_position   — broadcast / streaming camera marker
    av_place_confidence_monitor— stage confidence monitor / prompter
    av_layout_cocktail_tables  — reception high-top table grid
    av_draw_seating_legend     — capacity legend box
    av_place_registration      — registration / check-in desk

  Orchestration:
    av_ballroom_layout         — generic ballroom layout from a brief
    av_corporate_event_layout  — corporate event by type:
                                 'awards_gala' | 'keynote' | 'reception' | 'training'
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
    if cmd_fn is None:
        raise ValueError('cmd_fn must not be None — pass the server cmd() function')
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
    # Pure-math: theater seating capacity
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_calc_theater_capacity(
        ctx: Context,
        room_width_mm: float,
        room_length_mm: float,
        stage_depth_mm: float = 4877,
        foh_depth_mm: float = 2438,
        seat_width_mm: float = 508,
        seat_depth_mm: float = 305,
        row_spacing_mm: float = 914,
        n_aisles: int = 1,
        aisle_width_mm: float = 1219,
        side_clearance_mm: float = 1524,
        front_clearance_mm: float = 3048,
        back_clearance_mm: float = 1829,
        ada_end_seats: bool = True,
    ) -> str:
        """Estimate theater-style seating capacity and provide layout parameters.

        Returns: rows, seats per row, total seats, ADA count, and density.
        Also calculates the last-row distance from stage for sightline planning.
        All dimensions mm."""
        avail_w = room_width_mm  - 2 * side_clearance_mm - n_aisles * aisle_width_mm
        avail_l = room_length_mm - stage_depth_mm - front_clearance_mm \
                                 - foh_depth_mm   - back_clearance_mm

        if avail_w <= 0 or avail_l <= 0:
            return json.dumps({'error': 'No space after constraints — check dimensions'})

        n_cols = max(0, int(avail_w / seat_width_mm))
        n_rows = max(0, int((avail_l - seat_depth_mm) / row_spacing_mm) + 1)
        seats_per_row = n_cols
        total_seats   = n_rows * seats_per_row

        ada_per_row   = 2 if ada_end_seats else 0
        ada_total     = n_rows * ada_per_row

        last_row_dist = front_clearance_mm + (n_rows - 1) * row_spacing_mm
        area_m2       = (room_width_mm / 1000) * (room_length_mm / 1000)
        density       = total_seats / area_m2 if area_m2 else 0

        recs = []
        if seats_per_row > 30:
            recs.append(f"Row width {seats_per_row} seats — add a centre aisle around col {seats_per_row//2}")
        if row_spacing_mm < 864:
            recs.append("Row spacing < 34 in — tight for egress; codes often require 32 in min")
        if last_row_dist / room_length_mm > 0.85:
            recs.append("Last row very far back — consider adding satellite screens or a balcony delay")
        if density > 1.1:
            recs.append(f"High density ({density:.2f}/m²) — verify fire egress calculations")

        return json.dumps({
            'room': {
                'width_ft':  round(room_width_mm / 304.8, 0),
                'length_ft': round(room_length_mm / 304.8, 0),
            },
            'capacity': {
                'rows': n_rows,
                'seats_per_row': seats_per_row,
                'total_seats': total_seats,
                'ada_seats': ada_total,
            },
            'geometry': {
                'avail_width_ft':  round(avail_w / 304.8, 1),
                'avail_length_ft': round(avail_l / 304.8, 1),
                'last_row_from_stage_ft': round(last_row_dist / 304.8, 1),
                'front_clearance_ft': round(front_clearance_mm / 304.8, 1),
            },
            'density': {
                'seats_per_m2': round(density, 3),
                'sqft_per_seat': round(107.64 / density, 1) if density else None,
            },
            'recommendations': recs,
        }, indent=2)

    # ─────────────────────────────────────────────────────────────────────────
    # Corporate VW-dispatch wrappers
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_place_podium(
        ctx: Context,
        cx: float, cy: float,
        label: str = 'PODIUM',
        width_mm: float = 610,
        depth_mm: float = 460,
        confidence_monitor: bool = True,
        monitor_width_mm: float = 686,
    ) -> str:
        """Place a corporate podium / lectern on the stage.
        Draws the podium footprint and optionally a confidence monitor marker
        on a stand downstage of the podium facing the presenter.
        Placed on AV-Stage layer; monitor on AV-Video / AV-Confidence-Mon class."""
        return _cmd('av_place_podium', {
            'cx': cx, 'cy': cy, 'label': label,
            'width_mm': width_mm, 'depth_mm': depth_mm,
            'confidence_monitor': confidence_monitor,
            'monitor_width_mm': monitor_width_mm,
        })

    @mcp.tool(structured_output=False)
    def av_place_head_table(
        ctx: Context,
        cx: float, cy: float,
        n_seats: int = 6,
        width_mm: float = 4877,
        depth_mm: float = 762,
        label: str = 'HEAD TABLE',
        chair_w_mm: float = 480,
        chair_d_mm: float = 400,
    ) -> str:
        """Place a corporate head table / panel dais.
        Chairs are drawn on the downstage (audience-facing) side only.
        Placed on AV-Head-Table layer.

        Common widths: 2438 = 8 ft (4-person) | 3658 = 12 ft (5-person) |
                       4877 = 16 ft (6-person) | 6096 = 20 ft (8-person)."""
        return _cmd('av_place_head_table', {
            'cx': cx, 'cy': cy, 'n_seats': n_seats,
            'width_mm': width_mm, 'depth_mm': depth_mm,
            'label': label, 'chair_w_mm': chair_w_mm, 'chair_d_mm': chair_d_mm,
        })

    @mcp.tool(structured_output=False)
    def av_layout_theater_seating(
        ctx: Context,
        x1: float, y1: float, x2: float, y2: float,
        seat_width_mm: float = 508,
        seat_depth_mm: float = 305,
        row_spacing_mm: float = 914,
        row_label_style: str = 'alpha',
        aisle_after_cols: list = [],
        aisle_width_mm: float = 1219,
        ada_at_row_ends: bool = True,
        section_label: str = 'General',
    ) -> str:
        """Auto-layout theater-style rows of seats within a boundary.

        Rows are lettered A, B, C ... (skipping I and O) from stage outward.
        Each seat gets an AV Seat record (Row, Seat_Num, Section, ADA) queryable
        from Spotlight worksheets.

        row_label_style : 'alpha' (A/B/C, default) | 'numeric' (1/2/3).
        aisle_after_cols: e.g. [8] inserts a centre aisle after column 8.
        ada_at_row_ends : mark first and last seat of every row as ADA (default True).
        section_label   : written into each seat record for section-based reporting."""
        return _cmd('av_layout_theater_seating', {
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'seat_width_mm': seat_width_mm, 'seat_depth_mm': seat_depth_mm,
            'row_spacing_mm': row_spacing_mm, 'row_label_style': row_label_style,
            'aisle_after_cols': aisle_after_cols, 'aisle_width_mm': aisle_width_mm,
            'ada_at_row_ends': ada_at_row_ends, 'section_label': section_label,
        })

    @mcp.tool(structured_output=False)
    def av_layout_classroom(
        ctx: Context,
        x1: float, y1: float, x2: float, y2: float,
        table_width_mm: float = 762,
        table_depth_mm: float = 610,
        seats_per_table_unit: int = 1,
        row_spacing_mm: float = 1829,
        center_aisle_mm: float = 0,
        table_units_per_row: int = 0,
        start_table_num: int = 1,
    ) -> str:
        """Auto-layout classroom-style rows of rectangular tables with chairs.
        Tables face the stage; chairs are on the downstage side of each table.

        table_width_mm / seats_per_table_unit: a 762 mm (30 in) unit holds 1 person;
        use 1524 mm + seats_per_table_unit=2 for 2-person tables.
        row_spacing_mm default 1829 (72 in) accommodates table + chair + clearance."""
        return _cmd('av_layout_classroom', {
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'table_width_mm': table_width_mm, 'table_depth_mm': table_depth_mm,
            'seats_per_table_unit': seats_per_table_unit,
            'row_spacing_mm': row_spacing_mm,
            'center_aisle_mm': center_aisle_mm,
            'table_units_per_row': table_units_per_row,
            'start_table_num': start_table_num,
        })

    @mcp.tool(structured_output=False)
    def av_layout_cocktail_tables(
        ctx: Context,
        x1: float, y1: float, x2: float, y2: float,
        diameter_mm: float = 686,
        col_spacing_mm: float = 2134,
        row_spacing_mm: float = 2134,
        n_stools: int = 3,
        start_table_num: int = 1,
    ) -> str:
        """Auto-layout cocktail / high-top reception tables.
        diameter_mm default 686 = 27 in (standard cocktail table).
        n_stools: 0 = standing cocktail only; 3–4 = bar stools shown in plan.
        Returns tables_placed and capacity_estimate."""
        return _cmd('av_layout_cocktail_tables', {
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'diameter_mm': diameter_mm,
            'col_spacing_mm': col_spacing_mm, 'row_spacing_mm': row_spacing_mm,
            'n_stools': n_stools, 'start_table_num': start_table_num,
        })

    @mcp.tool(structured_output=False)
    def av_place_camera_position(
        ctx: Context,
        cx: float, cy: float,
        label: str = 'CAM-1',
        camera_type: str = 'broadcast',
        aim_deg: float = 270,
    ) -> str:
        """Mark a camera position in plan view on the AV-Cameras layer.
        Draws an operator zone circle and a directional triangle.
        camera_type: 'broadcast' | 'handheld' | 'ptz' | 'jib' | 'streaming'.
        aim_deg: 270 = pointing toward stage (default for FOH position)."""
        return _cmd('av_place_camera_position', {
            'cx': cx, 'cy': cy, 'label': label,
            'camera_type': camera_type, 'aim_deg': aim_deg,
        })

    @mcp.tool(structured_output=False)
    def av_place_confidence_monitor(
        ctx: Context,
        cx: float, cy: float,
        label: str = 'CONF-1',
        width_mm: float = 1067,
        depth_mm: float = 50,
    ) -> str:
        """Place a confidence monitor / stage monitor on the AV-Video layer.
        Positioned on stage floor facing the presenter.
        Typical placement: 1–2 m downstage of the podium, near stage edge.
        width_mm default 1067 ≈ 42 in diagonal monitor."""
        return _cmd('av_place_confidence_monitor', {
            'cx': cx, 'cy': cy, 'label': label,
            'width_mm': width_mm, 'depth_mm': depth_mm,
        })

    @mcp.tool(structured_output=False)
    def av_place_registration(
        ctx: Context,
        cx: float, cy: float,
        label: str = 'REGISTRATION',
        width_mm: float = 3658,
        depth_mm: float = 762,
        n_staff_chairs: int = 4,
        queue_depth_mm: float = 2438,
    ) -> str:
        """Place a registration / check-in desk on the AV-FOH layer.
        Draws the desk, staff chairs, and a dotted queue-management zone.
        Typically placed near the main entrance, perpendicular to guest flow."""
        return _cmd('av_place_registration', {
            'cx': cx, 'cy': cy, 'label': label,
            'width_mm': width_mm, 'depth_mm': depth_mm,
            'n_staff_chairs': n_staff_chairs, 'queue_depth_mm': queue_depth_mm,
        })

    @mcp.tool(structured_output=False)
    def av_draw_seating_legend(
        ctx: Context,
        cx: float, cy: float,
        event_name: str = 'EVENT',
        sections: list = [],
        box_width_mm: float = 3000,
        row_height_mm: float = 300,
    ) -> str:
        """Draw a seating capacity legend / key box on the AV-Notes layer.
        sections: list of dicts with keys: label (str), seats (int), tables (int, optional).
        Example: [{'label':'General','tables':20,'seats':200},{'label':'VIP','seats':50}]
        Returns total_seats and total_tables from the legend."""
        return _cmd('av_draw_seating_legend', {
            'cx': cx, 'cy': cy, 'event_name': event_name,
            'sections': sections,
            'box_width_mm': box_width_mm, 'row_height_mm': row_height_mm,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # LED walls
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_calc_led_wall(
        ctx: Context,
        pixel_pitch_mm: float,
        physical_width_mm: Optional[float] = None,
        physical_height_mm: Optional[float] = None,
        content_width_px: Optional[int] = None,
        content_height_px: Optional[int] = None,
        panel_width_mm: float = 500,
        panel_height_mm: float = 500,
        weight_per_panel_kg: float = 8.5,
        power_per_m2_w: float = 200,
        audience_distance_mm: Optional[float] = None,
    ) -> str:
        """Calculate LED wall specifications — no VW connection required.

        Provide EITHER physical dimensions OR content resolution (not both):
          physical_width_mm + physical_height_mm  → snaps to panels, returns pixel count
          content_width_px  + content_height_px   → returns physical size for that resolution

        Common corporate pixel pitches:
          P1.9  ultra-fine, studio / command centre,  MVD ~15 m
          P2.6  fine detail, close viewing (≤8 m),   MVD ~21 m
          P3.9  most common ballroom / corporate,     MVD ~31 m
          P4.8  mid-range, large venues,              MVD ~38 m
          P5.9  cost-effective, 20 m+ audience,       MVD ~47 m

        weight_per_panel_kg: 8–9 kg typical for 500×500 mm indoor rental cabinet.
        power_per_m2_w:      150 W/m² typical average; 300 W/m² peak max draw.
        audience_distance_mm: if provided, returns whether pixel pitch is adequate."""
        pp = float(pixel_pitch_mm)
        pw = float(panel_width_mm)
        ph = float(panel_height_mm)
        mvd_m = pp * 8   # comfortable rule-of-thumb (pp * 1000 / 125)

        if physical_width_mm is not None and physical_height_mm is not None:
            panels_wide = max(1, round(float(physical_width_mm) / pw))
            panels_tall = max(1, round(float(physical_height_mm) / ph))
            act_w = panels_wide * pw
            act_h = panels_tall * ph
        elif content_width_px is not None and content_height_px is not None:
            act_w_exact = content_width_px * pp
            act_h_exact = content_height_px * pp
            panels_wide = math.ceil(act_w_exact / pw)
            panels_tall = math.ceil(act_h_exact / ph)
            act_w = panels_wide * pw
            act_h = panels_tall * ph
        else:
            return json.dumps({'error': 'Provide (physical_width_mm + physical_height_mm) '
                                        'or (content_width_px + content_height_px)'})

        total_panels = panels_wide * panels_tall
        area_m2      = (act_w / 1000) * (act_h / 1000)
        total_kg     = total_panels * float(weight_per_panel_kg)
        total_pwr    = area_m2 * float(power_per_m2_w)
        native_w     = int(act_w / pp)
        native_h     = int(act_h / pp)

        # Aspect ratio
        g = math.gcd(native_w, native_h)
        ar_str = f'{native_w//g}:{native_h//g}'

        recs = []
        if audience_distance_mm is not None:
            ad_m = float(audience_distance_mm) / 1000
            if ad_m < mvd_m:
                recs.append(f"Audience at {ad_m:.0f} m < MVD {mvd_m:.0f} m — "
                             f"consider finer pitch (P{pp*0.67:.1f} or P{pp*0.5:.1f})")
            else:
                recs.append(f"P{pp} adequate — audience {ad_m:.0f} m, MVD {mvd_m:.0f} m ✓")

        if native_w % 1920 == 0 or native_h % 1080 == 0:
            recs.append(f"Native resolution {native_w}×{native_h} is a clean {ar_str} multiple — "
                        "no scaling artifacts from 1080p/4K content")
        else:
            recs.append(f"Native {native_w}×{native_h} ({ar_str}) — content will scale; "
                        f"nearest 16:9 sizes: {(native_w//16)*16}×{(native_w//16)*9} or "
                        f"{(native_h//9)*16}×{(native_h//9)*9}")

        if total_pwr > 20000:
            recs.append(f"Total power {total_pwr/1000:.1f} kW — plan dedicated 3-phase circuit(s)")
        if total_kg > 500:
            recs.append(f"Total weight {total_kg:.0f} kg — verify venue rigging capacity")

        return json.dumps({
            'pixel_pitch_mm': pp,
            'physical': {
                'width_mm': act_w,   'width_ft':  round(act_w/304.8, 2),
                'height_mm': act_h,  'height_ft': round(act_h/304.8, 2),
                'area_m2': round(area_m2, 2),
            },
            'panels': {
                'wide': panels_wide, 'tall': panels_tall,
                'total': total_panels,
                'cabinet_mm': f'{int(pw)}×{int(ph)}',
            },
            'content': {
                'native_resolution': f'{native_w}×{native_h}',
                'aspect_ratio': ar_str,
                'recommended_source': (
                    '3840×2160 (4K)' if native_w >= 3840 else
                    '1920×1080 (1080p)' if native_w >= 1920 else
                    f'{native_w}×{native_h} (custom)'
                ),
            },
            'loading': {
                'total_weight_kg': round(total_kg, 1),
                'total_power_w':   round(total_pwr, 0),
                'total_power_kw':  round(total_pwr/1000, 2),
                'kg_per_m2':       round(total_kg/area_m2, 1),
                'w_per_m2':        power_per_m2_w,
            },
            'sightline': {
                'mvd_m':          round(mvd_m, 1),
                'mvd_ft':         round(mvd_m*3.281, 0),
                'comfortable_viewing_m': round(mvd_m * 1.5, 1),
            },
            'recommendations': recs,
        }, indent=2)

    @mcp.tool(structured_output=False)
    def av_place_led_wall(
        ctx: Context,
        cx: float, cy: float,
        width_mm: float,
        height_mm: float,
        label: str = 'LED',
        pixel_pitch_mm: float = 3.9,
        panel_width_mm: float = 500,
        panel_height_mm: float = 500,
        plan_depth_mm: float = 300,
        trim_mm: float = 2438,
        support_type: str = 'flown',
        weight_per_panel_kg: float = 8.5,
        power_per_m2_w: float = 200,
    ) -> str:
        """Place an LED video wall in plan view on the AV-Video layer.

        Width is snapped outward to the nearest whole panel so the wall always
        divides into complete cabinets. Draws:
          • Filled rectangle (LED face footprint)
          • Vertical seam lines at every panel-width boundary
          • Rigging point circles above (if flown/hybrid)
          • Ground-support leg footprints below (if ground/hybrid)
          • Spec annotation: size, pixel pitch, panel count, weight, power, MVD
          • AV LED Wall record with full specifications

        support_type: 'flown' | 'ground' | 'hybrid'
        trim_mm: bottom-of-wall height from floor (default 2438 = 8 ft)

        Common widths by format:
          1500 mm (3×500) — small breakout / confidence
          3000 mm (6×500) — side IMAG compact
          4500 mm (9×500) — IMAG standard
          6000 mm (12×500) — IMAG wide
          9000–15000 mm    — stage backdrop"""
        return _cmd('av_place_led_wall', {
            'cx': cx, 'cy': cy,
            'width_mm': width_mm, 'height_mm': height_mm,
            'label': label, 'pixel_pitch_mm': pixel_pitch_mm,
            'panel_width_mm': panel_width_mm,
            'panel_height_mm': panel_height_mm,
            'plan_depth_mm': plan_depth_mm,
            'trim_mm': trim_mm, 'support_type': support_type,
            'weight_per_panel_kg': weight_per_panel_kg,
            'power_per_m2_w': power_per_m2_w,
        })

    @mcp.tool(structured_output=False)
    def av_place_led_backdrop(
        ctx: Context,
        stage_width_mm: float,
        room_length_mm: float,
        height_mm: float = 4000,
        pixel_pitch_mm: float = 3.9,
        panel_width_mm: float = 500,
        panel_height_mm: float = 500,
        cx: float = 0,
        overhang_mm: float = 0,
        support_type: str = 'ground',
        label: str = 'BACKDROP',
    ) -> str:
        """Place a full-width LED backdrop flush against the stage back wall.

        Positions the wall at room_length_mm/2 − 150 mm (150 mm offset from wall),
        width = stage_width_mm + 2×overhang_mm, snapped to panel multiples.
        Defaults to ground support (most common corporate staging).

        height_mm: typical range 3000–6000 mm for corporate events.
        overhang_mm: how far each side extends beyond the stage edge (0 = flush).

        For a 40-ft stage at P3.9 with 500×500 panels:
          stage_width_mm=12192, height_mm=4000 → 24×8 panels = 192 cabinets"""
        return _cmd('av_place_led_backdrop', {
            'stage_width_mm': stage_width_mm, 'room_length_mm': room_length_mm,
            'height_mm': height_mm, 'pixel_pitch_mm': pixel_pitch_mm,
            'panel_width_mm': panel_width_mm, 'panel_height_mm': panel_height_mm,
            'cx': cx, 'overhang_mm': overhang_mm,
            'support_type': support_type, 'label': label,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Generic ballroom orchestration (existing)
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
        stage_front_y = room_length_mm/2 - stage_depth_mm   # downstage edge, positive Y (north-wall stage)

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


    # ─────────────────────────────────────────────────────────────────────────
    # Corporate event orchestration
    # ─────────────────────────────────────────────────────────────────────────

    @mcp.tool(structured_output=False)
    def av_corporate_event_layout(
        ctx: Context,
        event_type: str,
        room_width_mm: float,
        room_length_mm: float,
        room_height_mm: float = 9144,
        stage_width_mm: float = 9144,
        stage_depth_mm: float = 4267,
        stage_height_mm: float = 762,
        screen_trim_mm: float = 2743,
        event_name: str = 'Corporate Event',
        head_table_seats: int = 0,
        camera_positions: int = 2,
        main_screen_width_mm: Optional[float] = None,
    ) -> str:
        """Orchestrate a complete corporate event layout by event type.

        event_type values:
          'awards_gala'  — banquet rounds + head table on stage + podium + IMAG screens +
                           line arrays + cameras.  Gala dinner / awards ceremony format.
          'keynote'      — theater-style seating + stage + podium + confidence monitors +
                           main screen + flanking IMAG + center cluster or point source.
                           Town hall / all-hands / product launch format.
          'reception'    — cocktail high-tops filling the room + minimal stage or no stage +
                           background audio point sources.  Pre-dinner or standalone format.
          'training'     — classroom rows + large main screen + minimal flanking audio.
                           Training session / breakout / workshop format.

        Corporate-specific steps vs generic av_ballroom_layout:
          • Podium with confidence monitor placed center or SR on stage
          • Head table drawn on stage for gala / awards (head_table_seats > 0)
          • Camera positions placed at FOH and side aisles
          • Registration desk placed at room back
          • Seating legend generated automatically
          • Layer: AV-Lighting created for Spotlight lighting design integration

        Returns a JSON summary and per-element results."""

        results = {}
        errs    = []

        def _do(key, command, params):
            try:
                results[key] = json.loads(_cmd(command, params))
            except Exception as e:
                results[key] = {'error': str(e)}
                errs.append(f'{key}: {e}')

        rl = room_length_mm
        rw = room_width_mm
        rh = room_height_mm
        sw = stage_width_mm
        sd = stage_depth_mm
        sh = stage_height_mm

        # Derived geometry (origin = room center, +Y = toward stage/north)
        stage_back_y  =  rl / 2
        stage_front_y =  rl / 2 - sd          # downstage edge
        room_back_y   = -rl / 2               # back wall
        trim_spk      = min(rh * 0.65, 7315)  # speaker trim ≤ 24 ft

        if main_screen_width_mm is None:
            back_dist = rl - sd
            calc_w = 2 * back_dist * math.tan(math.radians(15))
            main_screen_width_mm = max(4572, min(calc_w, rw * 0.50))

        # ── 1. Document setup ──────────────────────────────────────────────
        _do('setup', 'av_setup_document', {})

        # ── 2. Room ────────────────────────────────────────────────────────
        _do('room', 'av_draw_room', {'width_mm': rw, 'length_mm': rl})

        # ── 3. Stage (skip for reception) ──────────────────────────────────
        if event_type != 'reception':
            _do('stage', 'av_draw_stage', {
                'width_mm': sw, 'depth_mm': sd,
                'height_mm': sh, 'room_length_mm': rl, 'position': 'north',
            })

        # ── 4. Screens ─────────────────────────────────────────────────────
        scr_y    = stage_back_y
        center_w = main_screen_width_mm   # fallback; overridden for gala/keynote below
        if event_type in ('awards_gala', 'keynote'):
            center_w = min(sw * 0.80, rw * 0.44)
            imag_off = sw/2 + main_screen_width_mm/2 + 610
            imag_off = min(imag_off, rw/2 - main_screen_width_mm/2 - 305)
            _do('screen_l', 'av_place_screen', {
                'x': -imag_off, 'y': scr_y, 'width_mm': main_screen_width_mm,
                'trim_mm': screen_trim_mm, 'label': 'IMAG-L',
            })
            _do('screen_r', 'av_place_screen', {
                'x':  imag_off, 'y': scr_y, 'width_mm': main_screen_width_mm,
                'trim_mm': screen_trim_mm, 'label': 'IMAG-R',
            })
            _do('screen_main', 'av_place_screen', {
                'x': 0, 'y': scr_y, 'width_mm': center_w,
                'trim_mm': screen_trim_mm + 305, 'label': 'MAIN',
            })
        elif event_type == 'training':
            # Single wide screen centered above stage
            _do('screen_main', 'av_place_screen', {
                'x': 0, 'y': scr_y, 'width_mm': min(sw * 0.9, rw * 0.55),
                'trim_mm': screen_trim_mm, 'label': 'MAIN',
            })

        # ── 5. Podium + confidence monitors ────────────────────────────────
        pod_x = sw * 0.15   # slightly stage-right of centre
        pod_y = stage_back_y - sd * 0.4
        if event_type in ('awards_gala', 'keynote', 'training'):
            _do('podium', 'av_place_podium', {
                'cx': pod_x, 'cy': pod_y, 'label': 'PODIUM',
                'confidence_monitor': True,
            })
            # Two confidence monitors downstage
            conf_y = stage_front_y + 600
            _do('conf_l', 'av_place_confidence_monitor', {
                'cx': -sw * 0.25, 'cy': conf_y, 'label': 'CONF-L',
            })
            _do('conf_r', 'av_place_confidence_monitor', {
                'cx':  sw * 0.25, 'cy': conf_y, 'label': 'CONF-R',
            })

        # ── 6. Head table (awards gala) ────────────────────────────────────
        n_ht = head_table_seats if head_table_seats > 0 else (6 if event_type == 'awards_gala' else 0)
        if n_ht > 0:
            ht_w = max(2438, n_ht * 762)   # 762 mm per seat
            _do('head_table', 'av_place_head_table', {
                'cx': -sw * 0.20, 'cy': stage_back_y - sd * 0.7,
                'width_mm': ht_w, 'n_seats': n_ht, 'label': 'HEAD TABLE',
            })

        # ── 7. Audio ───────────────────────────────────────────────────────
        arr_x = sw/2 + 1524
        arr_y = stage_front_y + 1524

        if event_type in ('awards_gala', 'keynote'):
            _do('spk_l', 'av_place_speaker_cluster', {
                'x': -arr_x, 'y': arr_y, 'label': 'L',
                'n_boxes': 8, 'trim_mm': trim_spk,
                'h_angle_deg': 90, 'v_angle_deg': 20, 'downtilt_deg': 18,
            })
            _do('spk_r', 'av_place_speaker_cluster', {
                'x':  arr_x, 'y': arr_y, 'label': 'R',
                'n_boxes': 8, 'trim_mm': trim_spk,
                'h_angle_deg': 90, 'v_angle_deg': 20, 'downtilt_deg': 18,
            })
            _do('spk_c', 'av_place_speaker', {
                'x': 0, 'y': stage_front_y, 'label': 'C-FILL',
                'trim_mm': trim_spk * 0.50, 'h_angle_deg': 100,
                'v_angle_deg': 60, 'downtilt_deg': 30, 'draw_coverage': False,
            })
            # Subs ground-stack
            sub_x = sw/2 + 200
            _do('sub_l', 'av_place_subwoofer', {'x': -sub_x, 'y': stage_front_y, 'label': 'SUB-L', 'n_boxes': 4})
            _do('sub_r', 'av_place_subwoofer', {'x':  sub_x, 'y': stage_front_y, 'label': 'SUB-R', 'n_boxes': 4})
        elif event_type in ('training', 'reception'):
            # Lighter point-source flanking
            ps_x = sw/2 + 600
            ps_trim = min(rh * 0.55, 5486)
            _do('spk_l', 'av_place_speaker', {
                'x': -ps_x, 'y': stage_front_y if event_type == 'training' else 0,
                'label': 'L PS', 'trim_mm': ps_trim,
                'h_angle_deg': 100, 'v_angle_deg': 60, 'downtilt_deg': 20,
            })
            _do('spk_r', 'av_place_speaker', {
                'x':  ps_x, 'y': stage_front_y if event_type == 'training' else 0,
                'label': 'R PS', 'trim_mm': ps_trim,
                'h_angle_deg': 100, 'v_angle_deg': 60, 'downtilt_deg': 20,
            })

        # ── 8. Truss (gala + keynote) ──────────────────────────────────────
        if event_type in ('awards_gala', 'keynote'):
            truss_trim = min(rh * 0.72, 7925)
            hs = sw/2 + 1000
            _do('truss_front', 'av_place_truss', {
                'x1': -hs, 'y1': stage_front_y + 900,
                'x2':  hs, 'y2': stage_front_y + 900,
                'trim_mm': truss_trim, 'label': 'T-1 FRONT',
            })

        # ── 9. Seating ─────────────────────────────────────────────────────
        foh_y    = room_back_y + rl * 0.32   # FOH at ~32 % from back wall
        seat_x1  = -rw/2 + 1524
        seat_x2  =  rw/2 - 1524
        seat_y1  = room_back_y + 1524
        seat_y2  = stage_front_y - 3048

        sections_legend = []

        if event_type == 'awards_gala':
            _do('seating', 'av_layout_seating', {
                'x1': seat_x1, 'y1': seat_y1, 'x2': seat_x2, 'y2': seat_y2,
                'diameter_mm': 1828, 'n_seats': 10,
                'col_spacing_mm': 2743, 'row_spacing_mm': 2743,
                'aisle_x_mm': 1829, 'start_table_num': 1,
            })
            s = results.get('seating', {})
            sections_legend = [
                {'label': 'General Seating',
                 'tables': s.get('tables_placed', 0),
                 'seats':  s.get('total_seats',   0)},
                {'label': 'Head Table', 'seats': n_ht},
            ]

        elif event_type == 'keynote':
            # Center aisle after approx half the columns
            _do('seating', 'av_layout_theater_seating', {
                'x1': seat_x1, 'y1': seat_y1, 'x2': seat_x2, 'y2': seat_y2,
                'seat_width_mm': 508, 'seat_depth_mm': 305, 'row_spacing_mm': 914,
                'row_label_style': 'alpha', 'aisle_after_cols': [],
                'ada_at_row_ends': True, 'section_label': 'General',
            })
            s = results.get('seating', {})
            sections_legend = [
                {'label': 'General', 'seats': s.get('total_seats', 0)},
                {'label': 'ADA', 'seats': s.get('rows', 0) * 2},
            ]

        elif event_type == 'training':
            _do('seating', 'av_layout_classroom', {
                'x1': seat_x1, 'y1': seat_y1, 'x2': seat_x2, 'y2': seat_y2,
                'table_width_mm': 762, 'table_depth_mm': 610,
                'seats_per_table_unit': 1, 'row_spacing_mm': 1829,
                'center_aisle_mm': 1219,
            })
            s = results.get('seating', {})
            sections_legend = [
                {'label': 'Classroom', 'seats': s.get('total_seats', 0)},
            ]

        elif event_type == 'reception':
            _do('seating', 'av_layout_cocktail_tables', {
                'x1': seat_x1, 'y1': seat_y1, 'x2': seat_x2,
                'y2': room_back_y + rl * 0.85,   # fill most of room
                'diameter_mm': 686, 'col_spacing_mm': 2134,
                'row_spacing_mm': 2134, 'n_stools': 3,
            })
            s = results.get('seating', {})
            sections_legend = [
                {'label': 'Cocktail', 'tables': s.get('tables_placed', 0),
                 'seats': s.get('capacity_estimate', 0)},
            ]

        # ── 10. FOH ────────────────────────────────────────────────────────
        _do('foh', 'av_place_foh', {
            'cx': 0, 'cy': foh_y,
            'width_mm': 5486, 'depth_mm': 1524, 'label': 'FOH',
        })

        # ── 11. Camera positions ───────────────────────────────────────────
        if camera_positions > 0 and event_type != 'reception':
            cam_y = foh_y + 600
            _do('cam_c', 'av_place_camera_position', {
                'cx': 0, 'cy': cam_y, 'label': 'CAM-1', 'camera_type': 'broadcast',
            })
            if camera_positions >= 2:
                side_x = rw * 0.38
                _do('cam_l', 'av_place_camera_position', {
                    'cx': -side_x, 'cy': foh_y + rl * 0.12,
                    'label': 'CAM-2', 'camera_type': 'handheld',
                })
            if camera_positions >= 3:
                _do('cam_r', 'av_place_camera_position', {
                    'cx': side_x, 'cy': foh_y + rl * 0.12,
                    'label': 'CAM-3', 'camera_type': 'handheld',
                })

        # ── 12. Power distro ───────────────────────────────────────────────
        _do('power', 'av_place_power_distro', {
            'cx': rw/2 - 1200, 'cy': stage_front_y,
            'label': 'A-DISTRO', 'amperage': 200, 'phase': '3ph',
        })

        # ── 13. Registration desk ──────────────────────────────────────────
        reg_x = rw * 0.30
        _do('registration', 'av_place_registration', {
            'cx': reg_x, 'cy': room_back_y + 1800,
            'label': 'REGISTRATION', 'width_mm': 3658,
            'n_staff_chairs': 4, 'queue_depth_mm': 2134,
        })

        # ── 14. Seating legend ─────────────────────────────────────────────
        legend_x = -rw/2 - 4000
        _do('legend', 'av_draw_seating_legend', {
            'cx': legend_x, 'cy': rl/2,
            'event_name': event_name, 'sections': sections_legend,
        })

        # ── 15. Zoom to fit ────────────────────────────────────────────────
        try:
            results['view'] = json.loads(_cmd('zoom_to_fit', {}))
        except Exception:
            pass

        # ── Summary ────────────────────────────────────────────────────────
        seat_data = results.get('seating', {})
        summary = {
            'event_name':  event_name,
            'event_type':  event_type,
            'room':   {'width_ft':  round(rw/304.8, 0),
                       'length_ft': round(rl/304.8, 0),
                       'height_ft': round(rh/304.8, 0)},
            'stage':  {'width_ft': round(sw/304.8, 0),
                       'depth_ft': round(sd/304.8, 0),
                       'deck_in':  round(sh/25.4, 0)},
            'screens': {'main_width_ft': round(center_w / 304.8, 1),
                        'trim_ft': round(screen_trim_mm/304.8, 1)},
            'seating': {
                'type':       event_type,
                'total_seats': (seat_data.get('total_seats') or
                                seat_data.get('capacity_estimate', 0)),
            },
            'cameras': camera_positions,
            'head_table_seats': n_ht,
            'spotlight_layers': [
                'AV-Lighting',   # place Spotlight lighting devices here
                'AV-Seating',    # AV Seat records queryable via worksheet
                'AV-Head-Table', 'AV-Cameras', 'AV-ADA',
            ],
            'errors': errs,
        }

        return json.dumps({
            'status': 'ok' if not errs else 'partial',
            'summary': summary, 'detail': results,
        }, indent=2)
