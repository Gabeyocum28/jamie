// Jamie's avatar: a glowing orb with a face you design. One file, two uses:
// - in Meet (the bot injects it): it replaces Jamie's webcam with the animation;
// - in the extension popup: the live preview while you pick a look.
// The bot sets window.__jamieAvatar.state to "listening", "thinking" or "talking";
// a voice can drive the mouth with window.__jamieAvatar.mouth (0..1, the audio level).
(() => {
  const TAU = Math.PI * 2;
  const PALETTES = {  // three blob hues, saturation, color of the face
    ocean: { hues: [190, 215, 165], sat: 90, ink: "#ffffff" },
    violet: { hues: [265, 290, 240], sat: 85, ink: "#ffffff" },
    sunset: { hues: [18, 340, 38], sat: 90, ink: "#ffffff" },
    mint: { hues: [150, 175, 120], sat: 75, ink: "#ffffff" },
    rose: { hues: [330, 350, 300], sat: 80, ink: "#ffffff" },
    gold: { hues: [45, 30, 55], sat: 90, ink: "#3a2400" },
    ice: { hues: [200, 220, 190], sat: 25, ink: "#1b2a3a" },
    crimson: { hues: [355, 12, 335], sat: 85, ink: "#ffffff" },
  };
  const OPTIONS = {
    eyes: ["disc", "dot", "oval", "wide", "square", "rounded", "diamond", "happy", "x", "heart"],
    mouth: ["smile", "grin", "line", "o", "open", "cat", "smirk", "wave", "tongue", "none"],
    color: Object.keys(PALETTES),
    motion: ["float", "bounce", "sway", "pulse", "jelly", "still"],
    accessory: ["none", "headphones", "party-hat", "crown", "antenna", "halo", "glasses", "bowtie"],
  };
  const DEFAULT = Object.fromEntries(Object.entries(OPTIONS).map(([k, v]) => [k, v[0]]));
  const LABELS = { listening: "Listening", thinking: "Thinking", talking: "Speaking" };
  const BLOBS = [  // per blob: [harmonic, amount, speed] wobbles
    [[2, 0.07, 0.9], [3, 0.05, -1.3], [5, 0.025, 1.7]],
    [[2, 0.06, -1.1], [4, 0.045, 1.5], [3, 0.03, 0.7]],
    [[3, 0.07, 1.2], [2, 0.04, -0.8], [6, 0.02, -1.9]],
  ];

  function create(canvas, look = {}) {
    const W = canvas.width, H = canvas.height, ctx = canvas.getContext("2d");
    const u = Math.min(W / 640, H / 480);  // drawn at 640x480, scaled to the canvas
    const CX = 320, CY = 222;
    const av = { state: "listening", mouth: null, look: { ...DEFAULT, ...look }, draw };
    // Few, soft particles: busy noise is what video encoders blur into blocks
    const dust = Array.from({ length: 14 }, () => ({ x: Math.random() * 640, y: Math.random() * 480, r: Math.random() * 1.2 + 0.8, v: Math.random() * 4 + 2 }));
    let bgCanvas = null, bgHue = 0, haloCanvas = null, haloHue = 0;
    let hues = null, speed = 1, clock = 0, level = 0, rings = [], lastRing = 0, last = performance.now();
    let lookX = 0, lookY = 0, lookTo = [0, 0], lookAt = 0, blinkAt = -1;

    const circle = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); };
    const glow = (x, y, r, stops) => {
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      stops.forEach(([at, c]) => g.addColorStop(at, c));
      ctx.fillStyle = g;
      circle(x, y, r);
      ctx.fill();
    };

    function eye(kind, s) {  // centered on 0,0; s = size unit
      ctx.beginPath();
      switch (kind) {
        case "dot": ctx.arc(0, 0, s * 0.55, 0, TAU); break;
        case "oval": ctx.ellipse(0, 0, s * 0.72, s * 1.25, 0, 0, TAU); break;
        case "wide": ctx.ellipse(0, 0, s * 1.3, s * 0.7, 0, 0, TAU); break;
        case "square": ctx.rect(-s * 0.9, -s * 0.9, s * 1.8, s * 1.8); break;
        case "rounded": ctx.roundRect(-s, -s, s * 2, s * 2, s * 0.6); break;
        case "diamond": ctx.moveTo(0, -s * 1.2); ctx.lineTo(s * 1.0, 0); ctx.lineTo(0, s * 1.2); ctx.lineTo(-s * 1.0, 0); ctx.closePath(); break;
        case "happy": ctx.arc(0, s * 0.5, s, Math.PI * 1.15, Math.PI * 1.85); ctx.lineWidth = s * 0.5; ctx.stroke(); return;
        case "x": ctx.moveTo(-s * 0.8, -s * 0.8); ctx.lineTo(s * 0.8, s * 0.8); ctx.moveTo(s * 0.8, -s * 0.8); ctx.lineTo(-s * 0.8, s * 0.8); ctx.lineWidth = s * 0.45; ctx.stroke(); return;
        case "heart":
          ctx.moveTo(0, s * 1.05);
          ctx.bezierCurveTo(-s * 1.6, -s * 0.1, -s * 0.9, -s * 1.4, 0, -s * 0.5);
          ctx.bezierCurveTo(s * 0.9, -s * 1.4, s * 1.6, -s * 0.1, 0, s * 1.05);
          break;
        default: ctx.arc(0, 0, s, 0, TAU);  // disc
      }
      ctx.fill();
    }

    function mouth(kind, s, open) {  // centered on 0,0; open = 0..1 while talking
      if (kind === "none") return;
      ctx.scale(1, 1 + 1.6 * open);
      ctx.beginPath();
      ctx.lineWidth = s * 0.16;
      switch (kind) {
        case "grin": ctx.arc(0, -s * 0.15, s * 0.8, 0, Math.PI); ctx.closePath(); ctx.fill(); return;
        case "line": ctx.moveTo(-s * 0.7, 0); ctx.lineTo(s * 0.7, 0); break;
        case "o": ctx.arc(0, 0, s * 0.3, 0, TAU); break;
        case "open": ctx.ellipse(0, 0, s * 0.6, s * 0.35, 0, 0, TAU); ctx.fill(); return;
        case "cat":
          ctx.arc(-s * 0.3, -s * 0.1, s * 0.3, 0.1 * Math.PI, 0.9 * Math.PI);
          ctx.moveTo(s * 0.6, -s * 0.05);
          ctx.arc(s * 0.3, -s * 0.1, s * 0.3, 0.1 * Math.PI, 0.9 * Math.PI);
          break;
        case "smirk": ctx.rotate(-0.25); ctx.arc(s * 0.1, -s * 0.6, s * 0.7, 0.2 * Math.PI, 0.65 * Math.PI); break;
        case "wave":
          for (let i = 0; i <= 24; i++) {
            const x = -s * 0.8 + (i / 24) * s * 1.6, y = Math.sin((i / 24) * TAU * 1.5) * s * 0.15;
            i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
          }
          break;
        case "tongue":
          ctx.arc(0, -s * 0.55, s * 0.75, 0.15 * Math.PI, 0.85 * Math.PI);
          ctx.stroke();
          ctx.save();
          ctx.fillStyle = "#ff6f91";
          ctx.beginPath();
          ctx.arc(s * 0.12, s * 0.2, s * 0.25, 0, Math.PI);
          ctx.fill();
          ctx.restore();
          return;
        default: ctx.arc(0, -s * 0.55, s * 0.75, 0.15 * Math.PI, 0.85 * Math.PI);  // smile
      }
      ctx.stroke();
    }

    function accessory(kind, R, t, h, eyes) {
      const dark = "#1c1f2b", metal = "#7a82a3";  // dark on the orb, lighter against the background
      ctx.lineCap = ctx.lineJoin = "round";
      switch (kind) {
        case "headphones":
          ctx.strokeStyle = metal;
          ctx.lineWidth = R * 0.09;
          ctx.beginPath();
          ctx.arc(0, -R * 0.05, R * 1.08, Math.PI * 1.08, Math.PI * 1.92);
          ctx.stroke();
          for (const side of [-1, 1]) {
            ctx.fillStyle = dark;
            ctx.beginPath();
            ctx.roundRect(side * R * 1.02 - R * 0.13, -R * 0.3, R * 0.26, R * 0.5, R * 0.1);
            ctx.fill();
            ctx.fillStyle = `hsl(${h}, 90%, 60%)`;
            ctx.fillRect(side * R * 1.02 - R * 0.03, -R * 0.2, R * 0.06, R * 0.3);
          }
          break;
        case "party-hat": {
          ctx.save();
          ctx.translate(R * 0.35, -R * 0.82);
          ctx.rotate(0.35);
          ctx.beginPath();
          ctx.moveTo(-R * 0.3, 0); ctx.lineTo(0, -R * 0.75); ctx.lineTo(R * 0.3, 0); ctx.closePath();
          ctx.fillStyle = "#ff5c8a"; ctx.fill();
          ctx.save(); ctx.clip();
          ctx.fillStyle = "#ffd84d";
          for (let i = 0; i < 4; i++) ctx.fillRect(-R, -R * (0.12 + i * 0.2), R * 2, R * 0.07);
          ctx.restore();
          ctx.fillStyle = "#7df9ff";
          circle(0, -R * 0.78, R * 0.09); ctx.fill();
          ctx.restore();
          break;
        }
        case "crown":
          ctx.beginPath();
          ctx.moveTo(-R * 0.45, -R * 0.78);
          [[-R * 0.5, -R * 1.2], [-R * 0.22, -R * 0.98], [0, -R * 1.3], [R * 0.22, -R * 0.98], [R * 0.5, -R * 1.2], [R * 0.45, -R * 0.78]]
            .forEach(([x, y]) => ctx.lineTo(x, y));
          ctx.closePath();
          ctx.fillStyle = "#ffcc33"; ctx.fill();
          ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 3; ctx.stroke();
          for (const [x, c] of [[-R * 0.25, "#ff4d6d"], [0, "#4dd2ff"], [R * 0.25, "#7dff8a"]]) {
            ctx.fillStyle = c; circle(x, -R * 0.88, R * 0.055); ctx.fill();
          }
          break;
        case "antenna":
          ctx.strokeStyle = metal;
          ctx.lineWidth = R * 0.05;
          ctx.beginPath();
          ctx.moveTo(0, -R * 0.95);
          ctx.quadraticCurveTo(R * 0.1 * Math.sin(t * 2), -R * 1.2, R * 0.05 * Math.sin(t * 2), -R * 1.38);
          ctx.stroke();
          glow(R * 0.05 * Math.sin(t * 2), -R * 1.4, R * 0.22, [[0, `hsla(${h}, 100%, 75%, ${0.6 + 0.4 * Math.sin(t * 4)})`], [1, "hsla(0,0%,0%,0)"]]);
          ctx.fillStyle = `hsl(${h}, 100%, 80%)`;
          circle(R * 0.05 * Math.sin(t * 2), -R * 1.4, R * 0.07); ctx.fill();
          break;
        case "halo":
          ctx.save();
          ctx.shadowColor = "#ffe9a3";
          ctx.shadowBlur = 18;
          ctx.strokeStyle = "#ffe9a3";
          ctx.lineWidth = R * 0.07;
          ctx.beginPath();
          ctx.ellipse(0, -R * 1.25 + 4 * Math.sin(t * 1.5), R * 0.55, R * 0.14, 0, 0, TAU);
          ctx.stroke();
          ctx.restore();
          break;
        case "glasses":
          ctx.strokeStyle = dark;
          ctx.lineWidth = R * 0.05;
          for (const [x, y] of eyes) { ctx.beginPath(); ctx.arc(x, y, R * 0.24, 0, TAU); ctx.stroke(); }
          ctx.beginPath();
          ctx.moveTo(eyes[0][0] + R * 0.24, eyes[0][1]);
          ctx.quadraticCurveTo(0, eyes[0][1] - R * 0.08, eyes[1][0] - R * 0.24, eyes[1][1]);
          ctx.stroke();
          break;
        case "bowtie":
          ctx.fillStyle = "#e63946";
          for (const side of [-1, 1]) {
            ctx.beginPath();
            ctx.moveTo(0, R * 1.08);
            ctx.lineTo(side * R * 0.32, R * 0.92);
            ctx.lineTo(side * R * 0.32, R * 1.26);
            ctx.closePath();
            ctx.fill();
          }
          ctx.fillStyle = "#9b1d28";
          ctx.beginPath(); ctx.roundRect(-R * 0.08, R * 1.0, R * 0.16, R * 0.16, R * 0.04); ctx.fill();
          break;
      }
    }

    function draw() {
      const now = performance.now(), dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const t = now / 1000, L = av.look, pal = PALETTES[L.color] || PALETTES.ocean;
      const thinking = av.state === "thinking", talking = av.state === "talking";
      // Ease colors, speed and voice level toward the state so changes melt into each other
      const want = pal.hues.map((h) => h + (thinking ? 60 : 0));
      hues = hues ? hues.map((h, i) => h + (want[i] - h) * 0.05) : want;
      speed += ((thinking ? 2.6 : talking ? 1.6 : 1) - speed) * 0.05;
      clock += dt * speed;
      const target = talking ? (av.mouth ?? 0.35 + 0.35 * Math.sin(t * 9) * Math.sin(t * 3.7)) : 0;
      level += (target - level) * 0.25;
      const S = pal.sat;

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      // The backdrop is a full-frame gradient: render it only when its color has moved
      if (!bgCanvas || Math.abs(bgHue - hues[0]) > 1) {
        bgCanvas ||= Object.assign(document.createElement("canvas"), { width: W, height: H });
        const b = bgCanvas.getContext("2d");
        b.setTransform(u, 0, 0, u, (W - 640 * u) / 2, (H - 480 * u) / 2);
        const bg = b.createRadialGradient(CX, CY, 40, CX, CY, 480);
        bg.addColorStop(0, `hsl(${hues[0]}, ${S * 0.5}%, 9%)`);
        bg.addColorStop(1, "hsl(230, 40%, 3%)");
        b.fillStyle = bg;
        b.fillRect(-200, -200, 1040, 880);
        bgHue = hues[0];
      }
      ctx.drawImage(bgCanvas, 0, 0);
      ctx.setTransform(u, 0, 0, u, (W - 640 * u) / 2, (H - 480 * u) / 2);
      for (const d of dust) {
        d.y -= d.v * dt;
        if (d.y < 0) (d.y = 480), (d.x = Math.random() * 640);
        ctx.fillStyle = `hsla(${hues[1]}, 80%, 85%, ${0.15 + 0.15 * Math.sin(t + d.x)})`;
        circle(d.x, d.y, d.r);
        ctx.fill();
      }

      // Motion: move the whole character
      let dx = 0, dy = 0, rot = 0, sx = 1, sy = 1;
      switch (L.motion) {
        case "float": dy = 8 * Math.sin(t * 1.2); break;
        case "bounce": { const b = Math.abs(Math.sin(t * 2.4)); dy = -20 * b + 6; sy = 0.94 + 0.06 * b; sx = 2 - sy; break; }
        case "sway": rot = 0.09 * Math.sin(t * 1.3); dx = 6 * Math.sin(t * 1.3); break;
        case "pulse": sx = sy = 1 + 0.045 * Math.sin(t * 2.2); break;
        case "jelly": sx = 1 + 0.045 * Math.sin(t * 3.2); sy = 1 - 0.045 * Math.sin(t * 3.2); break;
      }
      const R = 84 * (1 + 0.02 * Math.sin(t * 1.6) + 0.12 * level);

      ctx.globalCompositeOperation = "lighter";
      // The big soft halo is the most expensive thing to paint and barely changes: paint it once
      // per color, small, and stretch it (it's a blur anyway)
      if (!haloCanvas || Math.abs(haloHue - hues[0]) > 1) {
        haloCanvas ||= Object.assign(document.createElement("canvas"), { width: 128, height: 128 });
        const h = haloCanvas.getContext("2d"), g = h.createRadialGradient(64, 64, 0, 64, 64, 64);
        [[0, `hsla(${hues[0]}, ${S}%, 55%, 0.22)`], [0.45, `hsla(${hues[1]}, ${S}%, 45%, 0.07)`], [1, "hsla(0,0%,0%,0)"]]
          .forEach(([at, c]) => g.addColorStop(at, c));
        h.clearRect(0, 0, 128, 128);
        h.fillStyle = g;
        h.fillRect(0, 0, 128, 128);
        haloHue = hues[0];
      }
      ctx.drawImage(haloCanvas, CX + dx - R * 2.3, CY + dy - R * 2.3, R * 4.6, R * 4.6);
      if (talking && t - lastRing > 0.45 && level > 0.2) rings.push(t), (lastRing = t);
      rings = rings.filter((b) => t - b < 1.6);
      for (const b of rings) {
        const age = (t - b) / 1.6;
        ctx.strokeStyle = `hsla(${hues[1]}, ${S}%, 75%, ${0.35 * (1 - age)})`;
        ctx.lineWidth = 2;
        circle(CX + dx, CY + dy, R * (1.05 + age * 0.9));
        ctx.stroke();
      }

      ctx.save();
      ctx.translate(CX + dx, CY + dy);
      ctx.rotate(rot);
      ctx.scale(sx, sy);

      // The orb: translucent blobs added together, so overlaps glow
      BLOBS.forEach((shape, i) => {
        const r = R * (1 - i * 0.06);
        ctx.beginPath();
        for (let j = 0; j <= 64; j++) {
          const a = (j / 64) * TAU;
          let k = 1;
          for (const [n, amt, sp] of shape) k += amt * Math.sin(n * a + clock * sp + i * 2.1);
          j ? ctx.lineTo(Math.cos(a) * r * k, Math.sin(a) * r * k) : ctx.moveTo(Math.cos(a) * r * k, Math.sin(a) * r * k);
        }
        ctx.closePath();
        const g = ctx.createRadialGradient(-R * 0.3, -R * 0.35, R * 0.1, 0, 0, R * 1.15);
        g.addColorStop(0, `hsla(${hues[i]}, ${S}%, 62%, 0.42)`);
        g.addColorStop(0.55, `hsla(${hues[i]}, ${S * 0.95}%, 45%, 0.28)`);
        g.addColorStop(1, `hsla(${hues[i]}, ${S * 0.9}%, 30%, 0.06)`);
        ctx.fillStyle = g;
        ctx.fill();
      });
      glow(0, 0, R * 0.55, [[0, `hsla(${hues[2]}, ${S}%, 88%, ${0.16 + 0.3 * level})`], [1, "hsla(0,0%,0%,0)"]]);

      // Thinking: sparks on a tilted orbit
      const think = Math.max(0, (speed - 1.6) / 1);
      if (think > 0.05) {
        for (let i = 0; i < 7; i++) {
          const a = clock * 1.4 + (i * TAU) / 7, x = Math.cos(a) * R * 1.55, y = Math.sin(a) * R * 1.55 * 0.35;
          if (Math.sin(a) < 0 && Math.hypot(x, y) < R) continue;
          glow(x, y, 9, [[0, `hsla(${hues[1]}, 100%, 85%, ${0.9 * think})`], [1, "hsla(0,0%,0%,0)"]]);
        }
      }

      ctx.globalCompositeOperation = "source-over";
      const hl = ctx.createRadialGradient(-R * 0.35, -R * 0.45, 0, -R * 0.35, -R * 0.45, R * 0.55);
      hl.addColorStop(0, "rgba(255,255,255,0.18)");
      hl.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = hl;
      circle(-R * 0.35, -R * 0.45, R * 0.55);
      ctx.fill();

      // Face: eyes wander and blink; they look up and aside while thinking
      if (t > lookAt) (lookTo = [Math.random() * 2 - 1, Math.random() * 1.4 - 0.7]), (lookAt = t + 1.5 + Math.random() * 2.5);
      const aim = thinking ? [0.8, -0.9] : lookTo;
      lookX += (aim[0] - lookX) * 0.07;
      lookY += (aim[1] - lookY) * 0.07;
      if (t - blinkAt > 2.5 && Math.random() < 0.012) blinkAt = t;
      const blink = t - blinkAt < 0.16 ? 0.12 : 1;
      const ox = lookX * R * 0.1, oy = lookY * R * 0.08;
      const eyes = [[-R * 0.34 + ox, -R * 0.12 + oy], [R * 0.34 + ox, -R * 0.12 + oy]];
      ctx.fillStyle = ctx.strokeStyle = pal.ink;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.shadowColor = pal.ink === "#ffffff" ? `hsla(${hues[0]}, 100%, 85%, 0.9)` : "transparent";
      ctx.shadowBlur = 8;
      for (const [x, y] of eyes) {
        ctx.save();
        ctx.translate(x, y);
        ctx.scale(1, blink);
        eye(L.eyes, R * 0.13);
        ctx.restore();
      }
      ctx.save();
      ctx.translate(ox * 0.6, R * 0.3 + oy * 0.5);
      mouth(L.mouth, R * 0.3, level);
      ctx.restore();
      ctx.shadowBlur = 0;
      accessory(L.accessory, R, t, hues[0], eyes);
      ctx.restore();

      // Status pill
      ctx.font = "500 17px 'Google Sans', Inter, system-ui, sans-serif";
      ctx.letterSpacing = "1.5px";
      const label = (LABELS[av.state] || "").toUpperCase(), pw = ctx.measureText(label).width + 48, py = 418;
      ctx.fillStyle = "rgba(255,255,255,0.07)";
      ctx.strokeStyle = "rgba(255,255,255,0.12)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(CX - pw / 2, py, pw, 34, 17);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = `hsl(${hues[0]}, ${S}%, ${65 + 15 * Math.sin(t * (talking ? 8 : 3))}%)`;
      circle(CX - pw / 2 + 18, py + 17, 4);
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.textBaseline = "middle";
      ctx.fillText(label, CX - pw / 2 + 32, py + 18);
      ctx.letterSpacing = "0px";
    }
    return av;
  }

  window.JamieAvatar = { OPTIONS, DEFAULT, create };

  // In Meet: hand the animation to Meet as the camera (audio stays real). The bot sets
  // window.__jamieLook before this file runs.
  if (location.hostname !== "meet.google.com" || window.__jamieHooked) return;
  window.__jamieHooked = true;
  let stream;
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints = {}) => {
    if (!constraints.video) return gum(constraints);
    if (!stream) {
      // 16:9 at 720p, the shape and size of a Meet tile, so Meet doesn't stretch a small picture
      const canvas = Object.assign(document.createElement("canvas"), { width: 1280, height: 720 });
      window.__jamieAvatar = create(canvas, window.__jamieLook || {});
      stream = canvas.captureStream(24);
      // "detail": under load, drop frames rather than resolution
      stream.getVideoTracks().forEach((t) => (t.contentHint = "detail"));
      // setInterval, not requestAnimationFrame: rAF stops while the Meet tab is behind the shared tab
      // Ticks at 24fps; the bot lowers .fps while presenting so the shared video gets the CPU
      let tick = 0;
      setInterval(() => tick++ % Math.round(24 / (window.__jamieAvatar.fps || 24)) || window.__jamieAvatar.draw(), 1000 / 24);
    }
    window.__jamieCameraAsked = constraints.video;  // what Meet wanted, for debugging
    const out = new MediaStream(stream.getVideoTracks().map((t) => Object.assign(t.clone(), { contentHint: "detail" })));
    if (constraints.audio) (await gum({ audio: constraints.audio })).getAudioTracks().forEach((t) => out.addTrack(t));
    return out;
  };
})();
