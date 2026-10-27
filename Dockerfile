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
RUN pip install --no-cache-dir --break-system-packages playwright==1.63.0 websockets==15.0.1 piper-tts==1.3.0

# Jamie's offline voice (Piper); ElevenLabs replaces it when ELEVENLABS_API_KEY is set
RUN mkdir -p /opt/piper && for f in onnx onnx.json; do \
      curl -fsSL -o /opt/piper/en_US-amy-medium.$f \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.$f"; done

# VS Code in the browser, so Jamie can show code being written ("vibe coding") in its shared tab
ARG TARGETARCH
RUN curl -fsSL https://github.com/coder/code-server/releases/download/v4.96.4/code-server-4.96.4-linux-${TARGETARCH}.tar.gz \
      | tar -xz -C /opt \
 && ln -s /opt/code-server-4.96.4-linux-${TARGETARCH}/bin/code-server /usr/local/bin/code-server \
 && mkdir -p /home/pwuser/.local/share/code-server/User \
 && printf '%s' '{"workbench.startupEditor": "none", "workbench.colorTheme": "Default Dark Modern", "editor.fontSize": 20, "terminal.integrated.fontSize": 18, "window.commandCenter": false, "workbench.tips.enabled": false, "security.workspace.trust.enabled": false, "telemetry.telemetryLevel": "off", "chat.commandCenter.enabled": false}' \
      > /home/pwuser/.local/share/code-server/User/settings.json

# Agent logins live in named volumes mounted on these dirs; they must exist so the volumes are pwuser-owned
RUN mkdir -p /data /workspace /app /home/pwuser/.claude /home/pwuser/.codex /home/pwuser/.gemini \
 && chown -R pwuser:pwuser /data /workspace /app /home/pwuser
COPY --chown=pwuser:pwuser jamie/ /app/
# The avatar lives with the extension, which uses it for its live preview
COPY --chown=pwuser:pwuser extension/avatar.js /app/avatar.js
COPY --chown=pwuser:pwuser start.sh /start.sh
RUN chmod +x /start.sh /app/bot.py

# Non-root: Claude Code refuses --dangerously-skip-permissions as root. Environment Dockerfiles that
# need apt should switch to USER root, install, then switch back to USER pwuser.
USER pwuser
# ENABLE_TOOL_SEARCH=false: Claude sees the browser tools right away instead of spending a turn looking them up
ENV DISPLAY=:99 HOME=/home/pwuser ENABLE_TOOL_SEARCH=false
WORKDIR /workspace
ENTRYPOINT ["/start.sh"]
