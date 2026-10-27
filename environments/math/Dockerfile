# Math room: exact algebra, numerics and plotting, on top of the shared core
FROM jamie-base
RUN pip install --no-cache-dir --break-system-packages \
      sympy==1.14.0 numpy==2.3.4 scipy==1.16.3 matplotlib==3.10.7
# No GUI for plots: they're saved to files and screen-shared
ENV MPLBACKEND=Agg
