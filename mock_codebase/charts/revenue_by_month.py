"""Monthly revenue for each region, 2025."""
import pandas as pd
from matplotlib.ticker import FuncFormatter

from style import DATA, REGION_COLORS, new_chart, save

sales = pd.read_csv(DATA / "sales.csv")
monthly = sales.groupby(["month", "region"])["revenue"].sum().unstack("region").sort_index()

fig, ax = new_chart("Revenue by month", "All products, by region, 2025")
for region in monthly.columns:
    ax.plot(monthly.index, monthly[region] / 1000, marker="o", linewidth=2.5,
            color=REGION_COLORS[region], label=region)
ax.set_ylabel("Revenue ($ thousands)")
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}k"))
ax.set_xticks(range(len(monthly.index)))
ax.set_xticklabels(pd.PeriodIndex(monthly.index, freq="M").strftime("%b"))
ax.legend(title="Region", frameon=False, ncol=4, loc="upper left")
save(fig, "revenue_by_month")
