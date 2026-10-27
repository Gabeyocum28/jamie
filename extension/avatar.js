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
  const BLOBS = [  // per blob: [harmonic, amount, speed] wobbles
    [[2, 0.07, 0.9], [3, 0.05, -1.3], [5, 0.025, 1.7]],
    [[2, 0.06, -1.1], [4, 0.045, 1.5], [3, 0.03, 0.7]],
    [[3, 0.07, 1.2], [2, 0.04, -0.8], [6, 0.02, -1.9]],
  ];

  function create(canvas, look = {}) {
    const W = canvas.width, H = canvas.height, ctx = canvas.getContext("2d");
    const u = Math.min(W / 640, H / 480);  // drawn at 640x480, scaled to the canvas
    const CX = 320, CY = 240;
    const av = { state: "listening", mouth: null, look: { ...DEFAULT, ...look }, draw };
    // Flat colors only: gradients, glows and soft particles are what Meet's encoder smears into blocks
    let ear = 0, hues = null, speed = 1, clock = 0, level = 0, last = performance.now();
    let lookX = 0, lookY = 0, lookTo = [0, 0], lookAt = 0, blinkAt = -1;

    const circle = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); };

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
          ctx.fillStyle = `hsl(${h}, 100%, ${72 + 12 * Math.sin(t * 4)}%)`;
          circle(R * 0.05 * Math.sin(t * 2), -R * 1.4, R * 0.07); ctx.fill();
          break;
        case "halo":
          ctx.strokeStyle = "#ffe9a3";
          ctx.lineWidth = R * 0.07;
          ctx.beginPath();
          ctx.ellipse(0, -R * 1.25 + 4 * Math.sin(t * 1.5), R * 0.55, R * 0.14, 0, 0, TAU);
          ctx.stroke();
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
      ctx.fillStyle = "hsl(230, 30%, 8%)";
      ctx.fillRect(0, 0, W, H);
      ctx.setTransform(u, 0, 0, u, (W - 640 * u) / 2, (H - 480 * u) / 2);

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

      ctx.save();
      ctx.translate(CX + dx, CY + dy);
      ctx.rotate(rot);
      ctx.scale(sx, sy);

      // The orb: three flat wobbly layers, each a bit smaller and lighter; brighter while people talk to it
      ear += ((av.hearing ? 1 : 0) - ear) * 0.12;
      BLOBS.forEach((shape, i) => {
        const r = R * (1 - i * 0.08);
        ctx.beginPath();
        for (let j = 0; j <= 64; j++) {
          const a = (j / 64) * TAU;
          let k = 1;
          for (const [n, amt, sp] of shape) k += amt * Math.sin(n * a + clock * sp + i * 2.1);
          j ? ctx.lineTo(Math.cos(a) * r * k, Math.sin(a) * r * k) : ctx.moveTo(Math.cos(a) * r * k, Math.sin(a) * r * k);
        }
        ctx.closePath();
        ctx.fillStyle = `hsl(${hues[i]}, ${S}%, ${30 + i * 7 + 8 * ear + 6 * level}%)`;
        ctx.fill();
      });

      // Thinking: dots on a tilted orbit
      const think = Math.max(0, (speed - 1.6) / 1);
      if (think > 0.05) {
        ctx.fillStyle = `hsla(${hues[1]}, 100%, 80%, ${Math.min(1, think)})`;
        for (let i = 0; i < 7; i++) {
          const a = clock * 1.4 + (i * TAU) / 7, x = Math.cos(a) * R * 1.55, y = Math.sin(a) * R * 1.55 * 0.35;
          if (Math.sin(a) < 0 && Math.hypot(x, y) < R) continue;
          circle(x, y, 5);
          ctx.fill();
        }
      }

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
      accessory(L.accessory, R, t, hues[0], eyes);
      ctx.restore();
    }
    return av;
  }

  window.JamieAvatar = { OPTIONS, DEFAULT, create };

  // In Meet: hand the animation to Meet as the camera, and a voice channel as the microphone.
  // The bot sets window.__jamieLook (and, in tests, __jamieMicPassthrough) before this file runs.
  if (location.hostname !== "meet.google.com" || window.__jamieHooked) return;
  window.__jamieHooked = true;
  let stream;
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);

  // Jamie's microphone is a mixer: silent unless Jamie speaks (voice.say), so it can stay unmuted.
  // The container's fake device (a beep) never reaches Meet; tests pass their recording through.
  const voice = (window.__jamieVoice = { ctx: null, dest: null, source: null, generation: 0, finish: null });
  async function mic(constraints) {
    if (!voice.ctx) {
      voice.ctx = new AudioContext();
      voice.dest = voice.ctx.createMediaStreamDestination();
      voice.analyser = voice.ctx.createAnalyser();
      voice.analyser.fftSize = 512;
      voice.analyser.connect(voice.dest);
      if (window.__jamieMicPassthrough) {
        const real = await gum({ audio: constraints.audio });
        voice.ctx.createMediaStreamSource(real).connect(voice.dest);
      }
    }
    return voice.dest.stream.getAudioTracks().map((t) => t.clone());
  }
  voice.say = async (b64) => {  // play audio (any format the browser decodes) into the call; resolves when done
    voice.stop();
    const generation = voice.generation;
    // Replies can arrive before Meet first asks for its microphone. Discard the unused clone.
    if (!voice.ctx) (await mic({ audio: true })).forEach((track) => track.stop());
    await voice.ctx.resume();
    if (generation !== voice.generation) return;
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buffer = await voice.ctx.decodeAudioData(bytes.buffer);
    if (generation !== voice.generation) return;  // interrupted while decoding
    const src = (voice.source = voice.ctx.createBufferSource());
    src.buffer = buffer;
    src.connect(voice.analyser);
    const level = new Uint8Array(voice.analyser.fftSize), av = window.__jamieAvatar;
    const prev = av && av.state;
    if (av) av.state = "talking";
    const meter = setInterval(() => {  // the avatar's mouth follows the real loudness
      voice.analyser.getByteTimeDomainData(level);
      const rms = Math.sqrt(level.reduce((s, v) => s + (v - 128) ** 2, 0) / level.length) / 128;
      if (av) av.mouth = Math.min(1, rms * 4);
    }, 50);
    await new Promise((done, reject) => {
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        clearInterval(meter);
        src.disconnect();
        // An old source's delayed onended must not reset a newer reply's face or source.
        if (voice.source === src) {
          voice.source = voice.finish = null;
          if (av) { av.mouth = null; if (av.state === "talking") av.state = prev === "talking" ? "listening" : prev || "listening"; }
        }
        done();
      };
      voice.finish = src.onended = finish;
      try { src.start(); } catch (e) { reject(e); finish(); }
    });
  };
  voice.stop = () => {
    voice.generation++;  // also invalidates a reply still waiting for resume/decode
    try { voice.source && voice.source.stop(); } catch (e) {}
    if (voice.finish) voice.finish();
  };

  navigator.mediaDevices.getUserMedia = async (constraints = {}) => {
    if (!constraints.video) {
      return constraints.audio ? new MediaStream(await mic(constraints)) : gum(constraints);
    }
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
    if (constraints.audio) (await mic(constraints)).forEach((t) => out.addTrack(t));
    return out;
  };
})();
