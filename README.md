# Cycles Bloom

Efficient, energy-conserving bloom for the **Cycles** render engine, with a live
viewport preview so you can build your scene around the final look. Hardware
accelerated on **Metal** (Apple Silicon) — both through Blender's own GPU
compositor and through an optional custom GPU pass.

Configuration lives in a collapsible panel in **Properties → Render → Bloom**
(shown only when the render engine is Cycles).

## How it works

There is **one** accurate bloom: a managed **Glare (Bloom)** node inserted into
the scene compositor (`scene.compositing_node_group`). This is the single source
of truth for **F12 final renders** — it uses Blender's energy-conserving,
mip-pyramid Bloom, which runs on the GPU (Metal) compositor.

The viewport can preview that bloom live, in one of two modes:

| Preview Mode | What it is | Matches F12? | Cost |
|--------------|-----------|--------------|------|
| **Accurate** | Blender's native viewport compositor (`use_compositor = ALWAYS`) — the *same* node tree that F12 renders | Pixel-identical | Heavier |
| **Fast** | A custom GPU dual-Kawase bloom drawn over the viewport (Metal, `GPUShaderCreateInfo`) | Approximate (screen-space) | Interactive |

**Final renders always use the Accurate composite.** The Fast preview is a
viewport draw pass and cannot affect F12, so it defers to the accurate composite:

- **on render** — automatically (F12 always renders the node group);
- **on toggle** — set *Preview Mode* back to *Accurate* to see the exact result.

Use **Fast** while navigating a heavy scene, then flip to **Accurate** (or just
hit F12) for the true image.

> The viewport preview only appears in **Rendered** or **Material Preview**
> shading (not Solid/Wireframe).

## Install

1. Clone this repo and build the add-on zip (or grab a prebuilt zip from Releases):
   ```
   git clone https://github.com/cozmiccle/blender-cycles-bloom.git
   cd blender-cycles-bloom
   blender --command extension build --source-dir . --output-filepath cycles_bloom.zip
   ```
2. In Blender: **Edit → Preferences → Get Extensions → Install from Disk…** and
   pick `cycles_bloom.zip` (or point *Install from Disk* at this folder).
3. Set the render engine to **Cycles**; open **Properties → Render → Bloom**.

## Settings

- **Enable Bloom** – builds the compositor node and turns bloom on for F12.
- **Threshold / Smoothness** – which highlights bloom, and how soft the knee is.
- **Size** – spread/radius of the glow.
- **Intensity** – strength added back over the image.
- **Tint** – colour of the glow.
- **Clamp** – cap input brightness to tame fireflies (0 = off).
- **Quality** – Low / Medium / High.
- **Viewport Preview** + **Preview Mode** – live preview and Accurate/Fast toggle.

## Compatibility

- Targets **Blender 5.1+**; tested on **5.1.1** and **5.2 LTS** (beta).
- `blender_version_max` is intentionally omitted so it keeps loading on newer
  builds; drifting API (Glare sockets, viewport-compositor attribute) is handled
  by runtime feature detection.
- Uses the Blender 5.x compositor model: `scene.compositing_node_group`, a
  socket-driven Glare node (`Type = Bloom`), and a Group Output node.

## Notes / limitations

- Enabling bloom when the scene has **no** compositor creates a minimal
  pass-through compositor group and inserts the Glare node; disabling removes it
  and restores the previous state. If you already have a compositor, the Glare
  node is spliced in front of your Group Output non-destructively and removed
  cleanly on disable.
- The **Fast** preview is display-referred (screen-space) and therefore
  approximate; it exists for interactivity, not accuracy. Any GPU error in the
  Fast path disables it gracefully rather than spamming the console.
- GPU shaders are compiled lazily on first draw, so the add-on registers fine in
  `--background` (headless) sessions.
