"""Shared look for Brewline charts, so every chart in the deck matches."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"

REGION_COLORS = {"North": "#4C72B0", "South": "#DD8452", "East": "#55A868", "West": "#C44E52"}


def new_chart(title, subtitle=None):
    """A 12x6.75 (16:9) figure with the house style. Screen-share friendly: big fonts, no clutter."""
    plt.rcParams.update({"font.size": 14, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "axes.axisbelow": True, "grid.alpha": 0.3})
    fig, ax = plt.subplots(figsize=(12, 6.75))
    fig.suptitle(title, fontsize=22, fontweight="bold", x=0.06, ha="left")
    if subtitle:
        ax.set_title(subtitle, fontsize=13, color="#666", loc="left")
    return fig, ax


def save(fig, name):
    """Save to output/<name>.png and return the path."""
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")
    return path
