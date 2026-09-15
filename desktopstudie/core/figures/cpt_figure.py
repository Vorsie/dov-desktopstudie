"""qc / fs / Rf against depth. Rf = fs/qc*100 with fs converted from kPa to MPa. The qc axis is
capped near the 99th percentile so a single erratic spike does not flatten the rest of the
profile; the axis label says so whenever that clips real data."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np

from ..model import Cpt
from .common import plt, save

QC_AXIS_MAX = 50.0
QC_AXIS_MIN = 5.0
NO_DATA_MESSAGE = "geen meetreeks beschikbaar"


def _qc_xlim(qc_values: List[float]) -> Tuple[float, bool]:
    """(axis max in MPa, whether that clips a real reading)."""
    finite = [v for v in qc_values if v == v]  # drop NaN
    if not finite:
        return QC_AXIS_MAX, False
    xmax = min(QC_AXIS_MAX, max(QC_AXIS_MIN, 1.15 * float(np.nanpercentile(finite, 99))))
    return xmax, max(finite) > xmax


def _build_cpt_figure(cpt: Cpt):
    p = cpt.profile
    has_data = p is not None and len(p.depth_m) > 0
    has_fs = has_data and any(v is not None for v in p.fs_kpa)
    ncols = 3 if has_fs else 1
    fig, axes = plt.subplots(1, ncols, figsize=(3.2 * ncols, 7), sharey=True)
    axes = [axes] if ncols == 1 else list(axes)
    if not has_data:
        axes[0].text(0.5, 0.5, NO_DATA_MESSAGE, ha="center", va="center", transform=axes[0].transAxes)
        axes[0].set_xlabel("qc [MPa]")
    else:
        qc = [v if v is not None else float("nan") for v in p.qc_mpa]
        axes[0].plot(qc, p.depth_m, lw=0.8, color="#1f4e79")
        xmax, clipped = _qc_xlim(qc)
        axes[0].set_xlim(0, xmax)
        axes[0].set_xlabel(f"qc [MPa] (afgekapt op {xmax:.0f})" if clipped else "qc [MPa]")
    axes[0].set_ylabel("diepte [m-mv]")
    if has_fs and p is not None:
        fs = [v if v is not None else float("nan") for v in p.fs_kpa]
        rf = [(f / 1000.0) / q * 100.0 if (f is not None and q not in (None, 0.0)) else float("nan")
              for f, q in zip(p.fs_kpa, p.qc_mpa)]
        axes[1].plot(fs, p.depth_m, lw=0.8, color="#7f6000")
        axes[1].set_xlabel("fs [kPa]")
        axes[1].set_xlim(left=0)
        axes[2].plot(rf, p.depth_m, lw=0.8, color="#385723")
        axes[2].set_xlabel("Rf [%]")
        axes[2].set_xlim(0, 10)
    for ax in axes:
        ax.grid(True, lw=0.3, alpha=0.6)
        ax.xaxis.set_label_position("top")
        ax.xaxis.tick_top()
    axes[0].invert_yaxis()
    z = f"{cpt.z_mtaw:.2f}" if cpt.z_mtaw is not None else "?"
    first_line = " - ".join(part for part in (cpt.number, cpt.date or "datum onbekend", cpt.method) if part)
    title = f"{first_line}\n{cpt.distance_m:.0f} m van de zone, maaiveld {z} mTAW"
    fig.suptitle(title, fontsize=9, y=1.02)
    return fig, axes


def plot_cpt(cpt: Cpt, path: Path) -> Path:
    fig, _ = _build_cpt_figure(cpt)
    return save(fig, path)
