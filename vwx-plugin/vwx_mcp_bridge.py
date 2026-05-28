#!/usr/bin/env python3
"""
VWX MCP Bridge — runs inside Vectorworks 2026 as a Workspace Script.
AV-extended version: hot-reloads av_commands.py alongside commands.py.

Workflow:
  1. VW -> Scripts menu -> Run Script -> vwx_mcp_bridge.py
  2. Dialog appears "Active on :9878 [Stop]"
  3. Run bridge/vwx-mcp.bat outside VW
  4. Claude Code has 150+ tools (base + AV ballroom extension)

ALL vs.* calls happen on VW main thread via RegisterDialogForTimerEvents.
Socket I/O runs in a background thread. Thread-safe queue bridges them.
"""
import os, sys, socket, threading, queue, json, traceback, time

try:
    _DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _base = os.path.join(os.environ.get('APPDATA', ''),
                         'Nemetschek', 'Vectorworks', '2026', 'Plug-ins')
    for _name in ('VWX-MCP', 'VW-MCP'):
        _cand = os.path.join(_base, _name)
        if os.path.isdir(_cand):
            _DIR = _cand
            break
    else:
        _DIR = os.path.join(_base, 'VWX-MCP')

if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

_LOG = os.path.join(_DIR, 'bridge.log')

def _log(msg):
    try:
        with open(_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

_log(f"=== Bridge start, dir={_DIR}, py={sys.version.split()[0]} ===")

import vs

VW_PORT = int(os.environ.get('VW_MCP_PORT', '9878'))

_SKIP       = frozenset({1, 2, 4, 5, 2255, 2256, 12255, 12256, 12001, 12002})
_SETUP_IDS  = frozenset({2255, 12255})
_CANCEL_IDS = frozenset({2, 12002})

_q    = queue.Queue()
_res  = {}
_evts = {}
_ctr  = [0]
_run  = [True]
_lock = threading.Lock()


def _dispatch(cmd, params):
    """Route a command to commands.py, then av_commands.py if not found there."""
    try:
        import commands, importlib
        importlib.reload(commands)

        # Also reload av_commands if present
        av_mod = None
        try:
            import av_commands as _av
            importlib.reload(_av)
            av_mod = _av
        except ImportError:
            pass   # av_commands.py not installed — that's fine
        except Exception as e:
            _log(f"av_commands reload error: {e}")

        fn = getattr(commands, cmd, None)
        if fn is None and av_mod is not None:
            fn = getattr(av_mod, cmd, None)

        if fn is None:
            # Last resort: try executing as a script fragment
            return {'error': f'Unknown command: {cmd}'}

        return fn(params)

    except Exception as e:
        return {'error': str(e), 'traceback': traceback.format_exc()}


def _handle(conn):
    buf = b''
    conn.settimeout(300.0)
    try:
        while True:
            while b'\n' not in buf:
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    return
                if not chunk:
                    return
                buf += chunk
            line, buf = buf.split(b'\n', 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except Exception as e:
                conn.sendall(json.dumps({'error': f'bad JSON: {e}'}).encode() + b'\n')
                continue

            cmd_type = msg.get('type', '')
            prms     = msg.get('params', {})

            with _lock:
                _ctr[0] += 1
                cid = _ctr[0]
            evt = threading.Event()
            with _lock:
                _evts[cid] = evt
            _q.put((cid, cmd_type, prms))
            _log(f"Queued cid={cid} type={cmd_type}")

            if evt.wait(120):
                with _lock:
                    result = _res.pop(cid, {'error': 'no result'})
            else:
                with _lock:
                    _evts.pop(cid, None);  _res.pop(cid, None)
                result = {'error': 'timeout — VW main thread unresponsive'}

            try:
                conn.sendall(json.dumps(result).encode() + b'\n')
            except Exception as e:
                _log(f"Send fail cid={cid}: {e}")
                return
    except Exception as e:
        _log(f"Handle error: {e}")
    finally:
        try: conn.close()
        except Exception: pass


def _server():
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', VW_PORT))
        srv.listen(5)
        srv.settimeout(1.0)
        _log(f"Socket BOUND on 127.0.0.1:{VW_PORT}")
    except Exception as e:
        _log(f"BIND FAIL on :{VW_PORT}: {e}\n{traceback.format_exc()}")
        return
    try:
        while _run[0]:
            try:
                conn, addr = srv.accept()
                _log(f"Accept from {addr}")
                threading.Thread(target=_handle, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                _log(f"Accept error: {e}")
                if _run[0]: continue
                break
    finally:
        _log("Socket closing")
        try: srv.close()
        except Exception: pass


def _pump():
    n = 0
    while not _q.empty() and n < 20:
        try:
            cid, cmd, prms = _q.get_nowait()
        except queue.Empty:
            break
        _log(f"Pump dispatching cid={cid} cmd={cmd}")
        result = _dispatch(cmd, prms)
        if isinstance(result, dict) and result.get('error'):
            _log(f"Pump ERROR cid={cid}: {str(result.get('error'))[:200]}")
        else:
            _log(f"Pump OK cid={cid}")
        with _lock:
            _res[cid] = result
            evt = _evts.pop(cid, None)
        if evt: evt.set()
        n += 1


_event_log_count = [0]

def _cb(item, data):
    if _event_log_count[0] < 30:
        _event_log_count[0] += 1
        _log(f"dlg event item={item} data={data}")
    if item in _SETUP_IDS:
        try:
            vs.RegisterDialogForTimerEvents(_dlg_id[0], 100)
            _log("Timer registered in setup")
        except Exception as e:
            _log(f"Timer register fail: {e}")
        return False
    if item in _CANCEL_IDS:
        _run[0] = False
        return True
    if item not in _SKIP:
        _pump()
    return False


_dlg_id = [None]


def start():
    _run[0] = True
    t = threading.Thread(target=_server, daemon=True)
    t.start()
    _log(f"Server thread started: alive={t.is_alive()}")

    # Check whether av_commands is available and log
    av_available = os.path.isfile(os.path.join(_DIR, 'av_commands.py'))
    status_line = f'Active  -  TCP :{VW_PORT}' + ('  +AV' if av_available else '')

    dlg = vs.CreateLayout('VW MCP Bridge', False, '', 'Stop')
    _dlg_id[0] = dlg
    vs.CreateStaticText(dlg, 4, status_line, 42)
    vs.CreateStaticText(dlg, 5,
        'Claude Code has full VW access' + (' + AV ballroom tools' if av_available else ''),
        42)
    vs.SetFirstLayoutItem(dlg, 4)
    vs.SetBelowItem(dlg, 4, 5, 0, 0)
    _log(f"Layout created dlg={dlg}, av_commands={av_available}")

    vs.RunLayoutDialog(dlg, _cb)
    _run[0] = False
    _log("Dialog closed, _run=False")


start()
