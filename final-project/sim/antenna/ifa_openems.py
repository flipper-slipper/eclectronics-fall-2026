#!/usr/bin/env python3
"""openEMS FDTD model of the tracker's printed inverted-F antenna (ANT_IFA_2G4_Flex).

Geometry is taken from the KiCad board (nrf52832_qfab_dcdc.kicad_pcb):
  - feed pad at board (169.3037, 124.5); footprint rotated -90 deg
  - feed leg and short leg run +y (away from the ground) for H mm
  - the arm runs -x from the short leg, at y = H
  - ground: B.Cu hatched pour x 133.05..186.1, y 70..124.8, plus a tab to y 126 at x < 140
  - battery BT1 (pouch cell) at x 30.6..82.6, y 74..126; fold line at x = 108.05

Simulation coordinates (mm): origin at the feed pad, x/y as in KiCad minus the feed position.
All copper is modelled as zero-thickness PEC in the z = 0 plane (F.Cu and B.Cu are only
70 um apart). The flex dielectric (--substrate, default clear PET) is replaced by a 0.5 mm thin-sheet
equivalent so the FDTD timestep stays reasonable: (eps_r - 1) * t is kept constant.

Cases:
  flat    - the whole bill lying flat in free space (battery on the far half)
  wallet  - bill folded at the centre line, far half (with battery) folded over the
            electronics with a gap of --gap mm filled with paper (other bills), and
            leather on both outer faces. Battery faces the electronics (worst case).

Outputs (in --out/<name>/): s11.csv, s11.png, summary.json, model.xml (open with AppCSXCAD).
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

# ---------------------------------------------------------------- board constants (KiCad mm)
FEED = (169.3037, 124.5)
FOLD_X = 108.05
BOARD = (30.0, 70.0, 186.1, 136.3)            # Edge.Cuts rectangle
GND_POURS = [(133.05, 70.0, 186.1, 124.8),    # B.Cu hatched electronics ground
             (133.05, 124.8, 140.0, 126.0)]   # small tab at the left
BATT = (30.6, 74.0, 82.6, 126.0)              # BT1 outline (Dwgs.User battery zone)

# ---------------------------------------------------------------- materials
T_FLEX_MODEL = 0.5
# substrate: (eps_r, dielectric thickness mm, tan d); copper excluded from the thickness
SUBSTRATES = {'pi': (3.25, 0.12, 0.004),      # JLC yellow polyimide flex, 0.12 mm
              'clear': (3.2, 0.17, 0.01)}     # JLC transparent PET flex: 70 um core + 2 x 50 um coverlay
                                              # (0.24 mm finished with copper); eps/tan d estimated
EPS_LEATHER, TAN_LEATHER, T_LEATHER = 2.8, 0.07, 1.2
EPS_PAPER, TAN_PAPER = 2.0, 0.05

F0, FC = 2.45e9, 1.0e9          # gaussian excitation: 1.45 .. 3.45 GHz
F_TARGET = 2.44e9
Z0 = 50.0
FINE = 0.25                     # mesh resolution around the antenna (mm)
MAX_RES = 3.0                   # max mesh cell in air (mm), ~lambda/29 at 3.45 GHz
MARGIN = 40.0                   # air around the structure before the PML (mm)


def b2s(x, y):
    """KiCad board coordinates -> simulation coordinates."""
    return x - FEED[0], y - FEED[1]


def rect_b2s(r, mirror=False):
    """Board rectangle (x1, y1, x2, y2) -> sim rectangle, optionally mirrored about the fold."""
    x1, y1 = b2s(r[0], r[1])
    x2, y2 = b2s(r[2], r[3])
    if mirror:
        fs = FOLD_X - FEED[0]
        x1, x2 = 2 * fs - x2, 2 * fs - x1
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def kappa(eps_r, tan_d, f=F0):
    from openEMS.physical_constants import EPS0
    return 2 * np.pi * f * EPS0 * eps_r * tan_d


def lmatch(z, f, z0=Z0):
    """Two-element L-networks that match load z to z0 at f. Returns a list of descriptions."""
    w = 2 * np.pi * f
    r, x = z.real, z.imag

    def part(xval, kind):
        # kind 'series' takes a reactance, 'shunt' takes a susceptance
        if kind == 'series':
            return ('L', xval / w * 1e9, 'nH') if xval > 0 else ('C', -1 / (w * xval) * 1e12, 'pF')
        return ('C', xval / w * 1e12, 'pF') if xval > 0 else ('L', -1 / (w * xval) * 1e9, 'nH')

    out = []
    if r < z0:   # series next to the antenna, shunt on the radio side
        for sgn in (1, -1):
            xs = sgn * np.sqrt(r * (z0 - r)) - x
            bp = sgn * np.sqrt((z0 - r) / r) / z0
            s, p = part(xs, 'series'), part(bp, 'shunt')
            out.append(f"series {s[0]} {s[1]:.2f} {s[2]} at antenna, then shunt {p[0]} {p[1]:.2f} {p[2]} on radio side")
    else:        # shunt next to the antenna, series on the radio side
        for sgn in (1, -1):
            b = (x + sgn * np.sqrt(r / z0) * np.sqrt(r * r + x * x - z0 * r)) / (r * r + x * x)
            xs = 1 / b + x * z0 / r - z0 / (b * r)
            p, s = part(b, 'shunt'), part(xs, 'series')
            out.append(f"shunt {p[0]} {p[1]:.2f} {p[2]} at antenna, then series {s[0]} {s[1]:.2f} {s[2]} toward radio")
    return out


def merge_lines(fine, edges, tol=0.12):
    """Union of mesh lines, dropping generated lines that sit within tol of a geometry edge."""
    edges = np.unique(np.round(edges, 4))
    keep = [v for v in fine if np.min(np.abs(edges - v)) > tol]
    return np.unique(np.concatenate([edges, keep]))


def build(args, sim_path, outdir):
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS

    H, S, L, W = args.height, args.spacing, args.arm, args.width
    fdtd = openEMS(NrTS=args.max_steps, EndCriteria=args.end_criteria)
    fdtd.SetGaussExcite(F0, FC)
    fdtd.SetBoundaryCond(['PML_8'] * 6)
    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)

    ex, ey, ez = [], [], []        # geometry edges that must be on the mesh
    bbox = [[], [], []]

    def box(prop, x1, y1, z1, x2, y2, z2, prio):
        prop.AddBox([x1, y1, z1], [x2, y2, z2], priority=prio)
        ex.extend([x1, x2]); ey.extend([y1, y2]); ez.extend([z1, z2])
        for i, (a, b) in enumerate(((x1, x2), (y1, y2), (z1, z2))):
            bbox[i].extend([a, b])

    pec = csx.AddMetal('copper')
    batt = csx.AddMetal('battery')
    eps_flex, t_flex, tan_flex = SUBSTRATES[args.substrate]
    flex = csx.AddMaterial('flex', epsilon=1 + (eps_flex - 1) * t_flex / T_FLEX_MODEL,
                           kappa=kappa(eps_flex * t_flex / T_FLEX_MODEL, tan_flex))
    hz = T_FLEX_MODEL / 2

    # ---- electronics half (stays put) + full bill when flat
    bx1, by1, bx2, by2 = rect_b2s(BOARD)
    if args.case == 'flat':
        box(flex, bx1, by1, -hz, bx2, by2, hz, 1)
    else:
        fs = FOLD_X - FEED[0]
        box(flex, fs, by1, -hz, bx2, by2, hz, 1)

    # ---- ground pours, with a notch so the feed sits at an edge (B.Cu keepout under the RF line)
    for r in GND_POURS:
        x1, y1, x2, y2 = rect_b2s(r)
        if y2 > 0.29 and x1 < 0 < x2:      # main pour: split around the feed notch
            box(pec, x1, y1, 0, x2, -0.2, 0, 10)
            box(pec, x1, -0.2, 0, -1.0, y2, 0, 10)
            box(pec, 1.0, -0.2, 0, x2, y2, 0, 10)
        else:
            box(pec, x1, y1, 0, x2, y2, 0, 10)

    # ---- antenna
    box(pec, -W / 2, 0.3, 0, W / 2, H + W / 2, 0, 10)                 # feed leg
    box(pec, S - W / 2, -0.2, 0, S + W / 2, H + W / 2, 0, 10)         # short leg (into ground)
    box(pec, S - L - 0.4 * W, H - W / 2, 0, S + W / 2, H + W / 2, 0, 10)  # arm (+round cap)

    port = fdtd.AddLumpedPort(1, Z0, [-W / 2, -0.2, 0], [W / 2, 0.3, 0], 'y', 1.0, priority=20)
    ex.extend([-W / 2, W / 2]); ey.extend([-0.2, 0.3])

    # ---- battery and wallet
    T = args.batt_thickness
    if args.case == 'flat':
        x1, y1, x2, y2 = rect_b2s(BATT)
        box(batt, x1, y1, hz, x2, y2, hz + T, 15)
    else:
        g = args.gap
        z_batt0 = hz + g
        z_top0 = z_batt0 + T
        paper = csx.AddMaterial('paper', epsilon=EPS_PAPER, kappa=kappa(EPS_PAPER, TAN_PAPER))
        leather = csx.AddMaterial('leather', epsilon=EPS_LEATHER, kappa=kappa(EPS_LEATHER, TAN_LEATHER))
        fs = FOLD_X - FEED[0]
        box(paper, fs, by1, hz, bx2, by2, z_top0, 2)                     # bills in the fold
        x1, y1, x2, y2 = rect_b2s(BATT, mirror=True)
        box(batt, x1, y1, z_batt0, x2, y2, z_top0, 15)                    # folded-over battery
        box(flex, fs, by1, z_top0, bx2, by2, z_top0 + T_FLEX_MODEL, 1)    # folded-over flex half
        wx1, wy1, wx2, wy2 = fs - 3, by1 - 3, bx2 + 3, by2 + 3
        box(leather, wx1, wy1, -hz - T_LEATHER, wx2, wy2, -hz, 3)
        ztop = z_top0 + T_FLEX_MODEL
        box(leather, wx1, wy1, ztop, wx2, wy2, ztop + T_LEATHER, 3)

    # ---- mesh
    lo = [min(b) - MARGIN for b in bbox]
    hi = [max(b) + MARGIN for b in bbox]
    fx = np.arange(S - L - 3, S + 3 + 1e-9, FINE)
    fy = np.arange(-1.5, H + 2 + 1e-9, FINE)
    fz = np.array([-hz, 0.0, hz])
    for d, f, e in (('x', fx, ex), ('y', fy, ey), ('z', fz, ez)):
        i = 'xyz'.index(d)
        lines = merge_lines(f, np.array(e + [lo[i], hi[i]]))
        mesh.AddLine(d, lines)
        mesh.SmoothMeshLines(d, MAX_RES, 1.4)

    nf2ff = fdtd.CreateNF2FFBox()
    csx.Write2XML(os.path.join(outdir, 'model.xml'))
    n = [len(mesh.GetLines(d)) for d in 'xyz']
    print(f"mesh {n[0]} x {n[1]} x {n[2]} = {np.prod(n) / 1e6:.2f} Mcells", flush=True)
    return fdtd, port, nf2ff


def postprocess(args, sim_path, port, nf2ff, outdir):
    f = np.linspace(1.6e9, 3.3e9, 851)
    port.CalcPort(sim_path, f)
    s11 = port.uf_ref / port.uf_inc
    zin = port.uf_tot / port.if_tot
    s11_db = 20 * np.log10(np.abs(s11))

    band = (f > 1.8e9) & (f < 3.2e9)
    i_res = np.where(band)[0][np.argmin(s11_db[band])]
    f_res = f[i_res]
    i_t = np.argmin(np.abs(f - F_TARGET))
    below10 = f[s11_db < -10]
    bw = (below10.min(), below10.max()) if below10.size else None

    theta = np.arange(0, 181, 5.0)
    phi = np.arange(0, 361, 5.0)
    ff = nf2ff.CalcNF2FF(sim_path, [f_res, F_TARGET], theta, phi, center=[0, 0, 0])
    p_acc = np.interp([f_res, F_TARGET], f, np.real(port.P_acc))
    p_inc = np.interp([f_res, F_TARGET], f, np.real(port.P_inc))
    rad_eff = ff.Prad / p_acc
    tot_eff = ff.Prad / p_inc

    total_len = args.arm + args.height
    arm_for_target = total_len * f_res / F_TARGET - args.height

    summary = {
        'case': args.case, 'gap_mm': args.gap if args.case == 'wallet' else None,
        'H_mm': args.height, 'S_mm': args.spacing, 'arm_mm': args.arm, 'W_mm': args.width,
        'f_res_GHz': round(f_res / 1e9, 4),
        's11_min_dB': round(float(s11_db[i_res]), 2),
        's11_at_2440_dB': round(float(s11_db[i_t]), 2),
        'zin_at_2440_ohm': [round(float(zin[i_t].real), 1), round(float(zin[i_t].imag), 1)],
        'zin_at_res_ohm': [round(float(zin[i_res].real), 1), round(float(zin[i_res].imag), 1)],
        'bw_minus10dB_GHz': [round(bw[0] / 1e9, 3), round(bw[1] / 1e9, 3)] if bw else None,
        'rad_eff_at_res_pct': round(float(rad_eff[0]) * 100, 1),
        'tot_eff_at_2440_pct': round(float(tot_eff[1]) * 100, 1),
        'Dmax_at_2440_dBi': round(float(10 * np.log10(ff.Dmax[1])), 2),
        'arm_for_2440_mm': round(float(arm_for_target), 2),
        'lmatch_at_2440': lmatch(zin[i_t], F_TARGET),
    }
    with open(os.path.join(outdir, 'summary.json'), 'w') as fh:
        json.dump(summary, fh, indent=2)
    np.savetxt(os.path.join(outdir, 's11.csv'),
               np.column_stack([f / 1e9, s11_db, zin.real, zin.imag]),
               delimiter=',', header='f_GHz,s11_dB,zin_re,zin_im', comments='')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(f / 1e9, s11_db)
    ax[0].axvspan(2.400, 2.4835, color='0.85')
    ax[0].axhline(-10, ls=':', c='0.4')
    ax[0].set(xlabel='GHz', ylabel='|S11| dB', title=f"{args.name}: res {f_res / 1e9:.3f} GHz")
    ax[0].grid(alpha=.3)
    ax[1].plot(f / 1e9, zin.real, label='R')
    ax[1].plot(f / 1e9, zin.imag, label='X')
    ax[1].axvspan(2.400, 2.4835, color='0.85')
    ax[1].set(xlabel='GHz', ylabel='ohm', title='Zin at feed', ylim=(-200, 300))
    ax[1].legend(); ax[1].grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, 's11.png'), dpi=120)
    print(json.dumps(summary, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case', choices=['flat', 'wallet'], default='flat')
    p.add_argument('--gap', type=float, default=2.0, help='wallet: battery-to-flex gap (other bills), mm')
    p.add_argument('--height', type=float, default=8.0, help='H: feed/short leg length, mm')
    p.add_argument('--spacing', type=float, default=3.0, help='S: feed-to-short spacing, mm')
    p.add_argument('--arm', type=float, default=22.0, help='arm length from short-leg centre to open end, mm')
    p.add_argument('--width', type=float, default=1.0, help='trace width, mm')
    p.add_argument('--batt-thickness', type=float, default=1.0)
    p.add_argument('--substrate', choices=sorted(SUBSTRATES), default='clear',
                   help='flex material: clear = transparent PET (board), pi = yellow polyimide 0.12 mm')
    p.add_argument('--threads', type=int, default=0)
    p.add_argument('--max-steps', type=int, default=300000)
    p.add_argument('--end-criteria', type=float, default=1e-4)
    p.add_argument('--name', default=None)
    p.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs'))
    p.add_argument('--simdata', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.simdata'))
    p.add_argument('--setup-only', action='store_true', help='write model.xml and stop')
    p.add_argument('--postprocess-only', action='store_true')
    args = p.parse_args()
    if args.name is None:
        tag = f"_g{args.gap:g}" if args.case == 'wallet' else ''
        args.name = f"{args.case}{tag}_H{args.height:g}_S{args.spacing:g}_L{args.arm:g}"
        if args.substrate != 'clear':
            args.name += f"_{args.substrate}"

    outdir = os.path.join(args.out, args.name)
    sim_path = os.path.join(args.simdata, args.name)
    os.makedirs(outdir, exist_ok=True)
    if not args.postprocess_only and os.path.isdir(sim_path):
        shutil.rmtree(sim_path)
    os.makedirs(sim_path, exist_ok=True)

    fdtd, port, nf2ff = build(args, sim_path, outdir)
    if args.setup_only:
        return
    if not args.postprocess_only:
        fdtd.Run(sim_path, cleanup=False, numThreads=args.threads)
    postprocess(args, sim_path, port, nf2ff, outdir)


if __name__ == '__main__':
    sys.exit(main())
