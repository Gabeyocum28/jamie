# Data room: analysis and charts on the team's own data, on top of the shared core
FROM jamie-base
RUN pip install --no-cache-dir --break-system-packages \
      pandas==2.3.3 numpy==2.3.4 matplotlib==3.10.7 seaborn==0.13.2 plotly==6.3.0 \
      openpyxl==3.1.5 pyarrow==21.0.0
# No GUI for plots: they're saved to files and screen-shared
ENV MPLBACKEND=Agg
