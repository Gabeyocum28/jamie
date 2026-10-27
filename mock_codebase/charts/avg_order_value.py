"""Average order value (AOV) by region, 2025: how much a customer spends per order."""
import pandas as pd

from style import DATA, REGION_COLORS, new_chart, save

sales = pd.read_csv(DATA / "sales.csv")
by_region = sales.groupby("region")
aov = (by_region["revenue"].sum() / by_region.size()).sort_values(ascending=False)

fig, ax = new_chart("Average order value by region", "Revenue per order, 2025")
bars = ax.bar(aov.index, aov.values, color=[REGION_COLORS[r] for r in aov.index])
ax.bar_label(bars, labels=[f"${v:,.2f}" for v in aov.values], padding=4, fontsize=14)
ax.set_ylabel("Average order value ($)")
save(fig, "avg_order_value")
