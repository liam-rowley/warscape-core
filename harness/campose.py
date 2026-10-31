#!/usr/bin/env python3
"""The battle camera's pose from the cam_read probe's back projections (J43).

purpose: turn the output of proxy/<game>/lua/probes/cam_read.lua (the camera position trilaterated in Lua, and the screen position, depth and
         distance of points around it from BattleUI.BackProjectPosition) into a pose x y z yaw pitch fov with its fit error; ctl.py cam reads
         the camera back with it
usage: campose.py <ctl result .json | cam_read text file>   (prints the pose as JSON); library: parse(text), solve(parsed) -> pose dict
when: every ctl cam readback, and by hand on a saved probe result
not-a-verb: pure maths on a probe's text, called by ctl.py; a J12 core candidate with ctl.py

Conventions (measured, run harness/runs/20261030_j43pc): world y is up; yaw = atan2(forward.x, forward.z) in degrees (-180..180], so a camera
looking along -z has yaw 180; pitch = asin(forward.y) in degrees (negative looks down); fov = the vertical field of view in degrees. The
camera has no roll (the fit assumes none and its error shows it). Screen x grows to the camera's right = (cos yaw, 0, -sin yaw).
"""
import json
import math
import sys
from pathlib import Path


class PoseError(ValueError):
    pass


def parse(text):
    """'cam C=x,y,z S=w,h P=x,y,z,sx,sy,depth,dist;...' -> {'C': [..], 'W':, 'H':, 'pts': [(P, sx, sy, depth, dist)]}"""
    text = (text or '').strip()
    if not text.startswith('cam '):
        raise PoseError(f'not a cam_read result: {text[:120]!r}')
    if text.startswith('cam none'):
        raise PoseError(text)
    fields = dict(tok.split('=', 1) for tok in text[4:].split(' ') if '=' in tok)
    try:
        c = [float(v) for v in fields['C'].split(',')]
        w, h = (float(v) for v in fields['S'].split(','))
        pts = []
        for item in fields.get('P', '').split(';'):
            if item:
                v = [float(x) for x in item.split(',')]
                pts.append((v[0:3], v[3], v[4], v[5], v[6]))
    except (KeyError, ValueError) as e:
        raise PoseError(f'cam_read result unreadable: {e}')
    return {'C': c, 'W': w, 'H': h, 'pts': pts}


def _basis(yaw, pitch):
    fw = (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))
    rt = (math.cos(yaw), 0.0, -math.sin(yaw))
    up = (fw[1] * rt[2] - fw[2] * rt[1], fw[2] * rt[0] - fw[0] * rt[2], fw[0] * rt[1] - fw[1] * rt[0])   # forward x right: y >= 0
    return fw, rt, up


def project(c, yaw, pitch, f, p, w, h):
    """Pinhole projection of world point p for a camera at c (radians, focal length f in pixels). None when behind the camera."""
    fw, rt, up = _basis(yaw, pitch)
    v = [p[k] - c[k] for k in range(3)]
    z = sum(v[k] * fw[k] for k in range(3))
    if z <= 1e-6:
        return None
    x = sum(v[k] * rt[k] for k in range(3))
    y = sum(v[k] * up[k] for k in range(3))
    return w / 2 + f * x / z, h / 2 - f * y / z


def _err(c, yaw, pitch, f, pts, w, h):
    e = 0.0
    for p, sx, sy, _, _ in pts:
        q = project(c, yaw, pitch, f, p, w, h)
        if q is None:
            return float('inf')
        e += (q[0] - sx) ** 2 + (q[1] - sy) ** 2
    return e


def solve(parsed, min_points=4):
    """Fit yaw, pitch and the focal length to the on-screen points in front of the camera. Returns the pose dict:
    x y z yaw pitch fov (degrees), plus rms_px (fit error), points (used), dist_err_m (worst |distance - |P - C||)."""
    c, w, h = parsed['C'], parsed['W'], parsed['H']
    pts = [t for t in parsed['pts'] if 0 < t[3] < 1 and -w <= t[1] <= 2 * w and -h <= t[2] <= 2 * h]
    if len(pts) < min_points:
        raise PoseError(f'only {len(pts)} back-projected points in front of the camera (need {min_points})')
    dist_err = max(abs(math.dist(p, c) - d) for p, _, _, _, d in parsed['pts']) if parsed['pts'] else None
    # start: the point nearest the screen centre gives the forward direction; f from a 70 degree vertical fov
    p0 = min(pts, key=lambda t: (t[1] - w / 2) ** 2 + (t[2] - h / 2) ** 2)[0]
    v = [p0[k] - c[k] for k in range(3)]
    n = math.sqrt(sum(x * x for x in v))
    yaw, pitch, f = math.atan2(v[0], v[2]), math.asin(max(-1.0, min(1.0, v[1] / n))), (h / 2) / math.tan(math.radians(35))
    e = _err(c, yaw, pitch, f, pts, w, h)
    step = [math.radians(2), math.radians(2), 50.0]
    while step[0] > 1e-9:
        improved = False
        for i in range(3):
            for s in (1, -1):
                cand = [yaw, pitch, f]
                cand[i] += s * step[i]
                ce = _err(c, cand[0], cand[1], cand[2], pts, w, h)
                if ce < e:
                    (yaw, pitch, f), e, improved = cand, ce, True
        if not improved:
            step = [s / 2 for s in step]
    yd = math.degrees(math.atan2(math.sin(yaw), math.cos(yaw)))
    if yd <= -180:
        yd += 360
    return {'x': c[0], 'y': c[1], 'z': c[2], 'yaw': yd, 'pitch': math.degrees(pitch), 'fov': math.degrees(2 * math.atan((h / 2) / f)),
            'rms_px': math.sqrt(e / len(pts)), 'points': len(pts), 'dist_err_m': dist_err}


def from_ctl(result):
    """A ctl `lua cam_read.lua` result dict -> pose dict (raises PoseError with the chunk's text on a failure)."""
    if result.get('status') != 'ok':
        raise PoseError(f"cam_read failed: {result.get('reason') or result.get('chunk')}")
    return solve(parse(result.get('chunk', '')))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.splitlines()[0])
        print('usage: campose.py <ctl result .json | cam_read text file>')
        return 2
    raw = Path(argv[0]).read_text(encoding='utf-8')
    try:
        pose = from_ctl(json.loads(raw)) if raw.lstrip().startswith('{') else solve(parse(raw))
    except PoseError as e:
        print(json.dumps({'error': str(e)}))
        return 1
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in pose.items()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
