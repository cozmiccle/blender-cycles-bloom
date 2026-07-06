"""Fast GPU preview (Metal).

A custom dual-Kawase bloom drawn over the 3D viewport via a POST_PIXEL draw
handler. This is the interactivity fallback for when the accurate viewport
compositor is too slow. It is *preview only*: a viewport draw handler cannot
affect F12, so final renders always use the accurate composite (compositor.py).

Design notes:
  * Shaders are built with gpu.types.GPUShaderCreateInfo (GLSL cross-compiled to
    MSL on the Metal backend). The legacy raw-GLSL GPUShader constructor is
    OpenGL-only and would fail on Metal, so it is deliberately not used.
  * Shader/pyramid resources are created lazily on the first draw, so the add-on
    still registers in --background (no GPU context) mode.
  * The whole draw path is guarded: any GPU error disables the fast path and
    removes the handler instead of spamming every redraw.
"""

import bpy

_handle = None
_failed = False  # set True after a GPU error so we don't retry every frame

# Lazily-built GPU resources
_shaders = None       # dict name -> GPUShader
_batches = None        # dict name -> GPUBatch (fullscreen quad per shader)
_offscreens = []       # bloom mip pyramid
_pyramid_key = None    # (base_w, base_h, levels)


# --------------------------------------------------------------------------- #
# Handler lifecycle
# --------------------------------------------------------------------------- #
def _fast_active(settings):
    return (
        settings.enabled
        and settings.viewport_preview
        and settings.preview_mode == "FAST"
        and not _failed
    )


def apply(_scene, settings):
    active = _fast_active(settings)
    if active and _handle is None:
        _add_handler()
    elif not active and _handle is not None:
        _remove_handler()
    _tag_redraw()


def _add_handler():
    global _handle
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")


def _remove_handler():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None


def shutdown():
    """Called on add-on unregister: remove the handler and free GPU resources."""
    _remove_handler()
    _free_pyramid()


def _tag_redraw():
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            if window.screen is None:
                continue
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


# --------------------------------------------------------------------------- #
# GPU resources
# --------------------------------------------------------------------------- #
_VERT_SRC = """
void main() {
    uv = uv_in;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_BRIGHT_FRAG = """
void main() {
    vec3 col = texture(image, uv).rgb;
    if (clamp_max > 0.0) col = min(col, vec3(clamp_max));
    float br = max(col.r, max(col.g, col.b));
    float knee = threshold * smoothness + 1e-5;
    float soft = clamp(br - threshold + knee, 0.0, 2.0 * knee);
    soft = soft * soft / (4.0 * knee + 1e-5);
    float contrib = max(soft, br - threshold) / max(br, 1e-5);
    FragColor = vec4(col * max(contrib, 0.0), 1.0);
}
"""

_DOWN_FRAG = """
void main() {
    vec2 hp = texel * 0.5;
    vec4 s = texture(image, uv) * 4.0;
    s += texture(image, uv + vec2(-hp.x, -hp.y));
    s += texture(image, uv + vec2( hp.x,  hp.y));
    s += texture(image, uv + vec2( hp.x, -hp.y));
    s += texture(image, uv + vec2(-hp.x,  hp.y));
    FragColor = vec4(s.rgb / 8.0, 1.0);
}
"""

_UP_FRAG = """
void main() {
    vec2 hp = texel * 0.5;
    vec4 s  = texture(image, uv + vec2(-hp.x * 2.0, 0.0));
    s += texture(image, uv + vec2(-hp.x,  hp.y)) * 2.0;
    s += texture(image, uv + vec2( 0.0,  hp.y * 2.0));
    s += texture(image, uv + vec2( hp.x,  hp.y)) * 2.0;
    s += texture(image, uv + vec2( hp.x * 2.0, 0.0));
    s += texture(image, uv + vec2( hp.x, -hp.y)) * 2.0;
    s += texture(image, uv + vec2( 0.0, -hp.y * 2.0));
    s += texture(image, uv + vec2(-hp.x, -hp.y)) * 2.0;
    FragColor = vec4(s.rgb / 12.0, 1.0);
}
"""

_COMPOSITE_FRAG = """
void main() {
    vec3 bloom = texture(image, uv).rgb;
    FragColor = vec4(bloom * intensity * tint, 1.0);
}
"""


def _make_shader(name, frag_src, constants):
    import gpu

    iface = gpu.types.GPUStageInterfaceInfo("cb_%s_iface" % name)
    iface.smooth("VEC2", "uv")

    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC2", "pos")
    info.vertex_in(1, "VEC2", "uv_in")
    info.vertex_out(iface)
    info.sampler(0, "FLOAT_2D", "image")
    for ctype, cname in constants:
        info.push_constant(ctype, cname)
    info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(_VERT_SRC)
    info.fragment_source(frag_src)
    return gpu.shader.create_from_info(info)


def _ensure_shaders():
    global _shaders, _batches
    if _shaders is not None:
        return
    from gpu_extras.batch import batch_for_shader

    specs = {
        "bright": (_BRIGHT_FRAG, [("FLOAT", "threshold"), ("FLOAT", "smoothness"),
                                  ("FLOAT", "clamp_max")]),
        "down": (_DOWN_FRAG, [("VEC2", "texel")]),
        "up": (_UP_FRAG, [("VEC2", "texel")]),
        "composite": (_COMPOSITE_FRAG, [("FLOAT", "intensity"), ("VEC3", "tint")]),
    }
    shaders, batches = {}, {}
    quad = {
        "pos": ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
        "uv_in": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    }
    for name, (frag, consts) in specs.items():
        sh = _make_shader(name, frag, consts)
        shaders[name] = sh
        batches[name] = batch_for_shader(sh, "TRI_FAN", quad)
    _shaders, _batches = shaders, batches


def _ensure_pyramid(base_w, base_h, levels):
    global _offscreens, _pyramid_key
    key = (base_w, base_h, levels)
    if key == _pyramid_key and _offscreens:
        return
    _free_pyramid()

    import gpu

    offs = []
    for i in range(levels):
        w = max(1, base_w >> i)
        h = max(1, base_h >> i)
        offs.append(gpu.types.GPUOffScreen(w, h, format="RGBA16F"))
    _offscreens = offs
    _pyramid_key = key


def _free_pyramid():
    global _offscreens, _pyramid_key
    for off in _offscreens:
        try:
            off.free()
        except Exception:
            pass
    _offscreens = []
    _pyramid_key = None


# --------------------------------------------------------------------------- #
# Draw
# --------------------------------------------------------------------------- #
def _levels_for(settings):
    base = {"LOW": 4, "MEDIUM": 5, "HIGH": 6}.get(settings.quality, 5)
    return max(2, min(7, round(base * (0.5 + settings.size))))


def _draw():
    global _failed
    context = bpy.context
    scene = context.scene
    settings = getattr(scene, "cycles_bloom", None)
    if settings is None or not _fast_active(settings):
        return

    space = context.space_data
    if space is None or space.type != "VIEW_3D":
        return
    # Only meaningful over the shaded result, not Solid/Wireframe.
    if space.shading.type not in {"RENDERED", "MATERIAL"}:
        return

    region = context.region
    if region is None:
        return
    w, h = region.width, region.height
    if w < 8 or h < 8:
        return

    try:
        _render_bloom(settings, w, h)
    except Exception as exc:  # noqa: BLE001 — never let a draw error recur
        _failed = True
        print("[Cycles Bloom] Fast preview disabled after GPU error:", exc)
        _remove_handler()


def _render_bloom(settings, w, h):
    import gpu

    _ensure_shaders()

    base_w, base_h = max(1, w // 2), max(1, h // 2)
    levels = _levels_for(settings)
    # Don't go below ~2px on the smallest level.
    while levels > 2 and (base_w >> (levels - 1) < 2 or base_h >> (levels - 1) < 2):
        levels -= 1
    _ensure_pyramid(base_w, base_h, levels)

    # 1) Capture the current viewport colour into a texture.
    fb = gpu.state.active_framebuffer_get()
    buf = fb.read_color(0, 0, w, h, 4, 0, "FLOAT")
    buf.dimensions = w * h * 4
    src = gpu.types.GPUTexture((w, h), format="RGBA16F", data=buf)

    off = _offscreens

    # 2) Bright-pass into the half-res base level.
    with off[0].bind():
        gpu.state.blend_set("NONE")
        sh = _shaders["bright"]
        sh.bind()
        sh.uniform_sampler("image", src)
        sh.uniform_float("threshold", settings.threshold)
        sh.uniform_float("smoothness", settings.smoothness)
        sh.uniform_float("clamp_max", settings.clamp)
        _batches["bright"].draw(sh)

    # 3) Downsample chain.
    for i in range(1, levels):
        prev = off[i - 1]
        with off[i].bind():
            gpu.state.blend_set("NONE")
            sh = _shaders["down"]
            sh.bind()
            sh.uniform_sampler("image", prev.texture_color)
            sh.uniform_float("texel", (1.0 / prev.width, 1.0 / prev.height))
            _batches["down"].draw(sh)

    # 4) Upsample + accumulate back down the pyramid (additive onto each level).
    for i in range(levels - 2, -1, -1):
        smaller = off[i + 1]
        with off[i].bind():
            gpu.state.blend_set("ADDITIVE")
            sh = _shaders["up"]
            sh.bind()
            sh.uniform_sampler("image", smaller.texture_color)
            sh.uniform_float("texel", (1.0 / smaller.width, 1.0 / smaller.height))
            _batches["up"].draw(sh)

    # 5) Composite the accumulated bloom additively over the viewport.
    gpu.state.blend_set("ADDITIVE")
    sh = _shaders["composite"]
    sh.bind()
    sh.uniform_sampler("image", off[0].texture_color)
    sh.uniform_float("intensity", settings.intensity)
    sh.uniform_float("tint", tuple(settings.tint))
    _batches["composite"].draw(sh)
    gpu.state.blend_set("NONE")
