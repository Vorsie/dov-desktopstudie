"""qc / fs / Rf against depth. Rf = fs/qc*100 with fs converted from kPa to MPa."""
from __future__ import annotations

from pathlib import Path

from ..model import Cpt
from .common import plt, save


def plot_cpt(cpt: Cpt, path: Path) -> Path:
    p = cpt.profile
    has_fs = p is not None and any(v is not None for v in p.fs_kpa)
    ncols = 3 if has_fs else 1
    fig, axes = plt.subplots(1, ncols, figsize=(3.2 * ncols, 7), sharey=True)
    axes = [axes] if ncols == 1 else list(axes)
    if p is not None:
        qc = [v if v is not None else float("nan") for v in p.qc_mpa]
        axes[0].plot(qc, p.depth_m, lw=0.8, color="#1f4e79")
    axes[0].set_xlabel("qc [MPa]")
    axes[0].set_ylabel("diepte [m-mv]")
    axes[0].set_xlim(left=0)
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
    title = (f"{cpt.number} - {cpt.date or 'datum onbekend'} - {cpt.method or ''}\n"
             f"{cpt.distance_m:.0f} m van de zone, maaiveld {z} mTAW")
    fig.suptitle(title, fontsize=9)
    return save(fig, path)
