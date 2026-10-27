# Brewline Coffee analytics

Sales and marketing reporting for Brewline Coffee's four regions (North, South, East, West), 2025.
Brewline is a made-up company: all the data here is mock data, generated for a demo.

## Layout

```
data/
  sales.csv            month, region, product, orders, revenue ($); one row per region, product and month
  marketing_spend.csv  month, region, channel (Social, Search, Local), spend ($)
  events.csv           things that happened that affect the numbers: promos, closures, price changes, openings
charts/
  style.py             shared chart style; every chart uses new_chart() and save()
  revenue_by_month.py  monthly revenue for each region
  avg_order_value.py   average order value by region
output/                the rendered charts (PNG), one per script
```

## Making the charts

```
python3 charts/revenue_by_month.py
python3 charts/avg_order_value.py
```

Each script writes `output/<name>.png`. Needs pandas and matplotlib.

## Conventions

- New charts go in `charts/<what_it_shows>.py` and use `style.py`, so the deck looks consistent.
- Money is in dollars. Months are `YYYY-MM`.
- Don't edit the files in `data/`: they're the source of truth.
