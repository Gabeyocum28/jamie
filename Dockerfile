# Playwright image = Chromium + all its deps, multi-arch. Keep it current: YouTube caps old Chromium at 360p
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb fluxbox x11vnc novnc websockify curl git ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# jamie-base: the core every environment builds FROM. Agent CLIs: pick one per run with --agent.
RUN npm install -g @anthropic-ai/claude-code @openai/codex@0.162.1 @google/gemini-cli@0.63.0 \
      @playwright/mcp@0.0.83

# The image ships browsers but not the Python package; pin to the image's version so it finds them
RUN pip install --no-cache-dir --break-system-packages playwright==1.63.0

# Agent logins live in named volumes mounted on these dirs; they must exist so the volumes are pwuser-owned
RUN mkdir -p /data /workspace /app /home/pwuser/.claude /home/pwuser/.codex /home/pwuser/.gemini \
 && chown -R pwuser:pwuser /data /workspace /app /home/pwuser
COPY --chown=pwuser:pwuser jamie/ /app/
COPY --chown=pwuser:pwuser start.sh /start.sh
RUN chmod +x /start.sh /app/bot.py

# Non-root: Claude Code refuses --dangerously-skip-permissions as root. Environment Dockerfiles that
# need apt should switch to USER root, install, then switch back to USER pwuser.
USER pwuser
ENV DISPLAY=:99 HOME=/home/pwuser
WORKDIR /workspace
ENTRYPOINT ["/start.sh"]
