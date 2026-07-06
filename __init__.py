"""Cycles Bloom — Metal-accelerated bloom for Cycles with live viewport preview.

Architecture (see the plan for full rationale):
  * One accurate bloom lives in the compositor as a managed Glare[Bloom] node
    group; it is the single source of truth for F12 final renders.
  * The viewport can preview that bloom live in two modes:
      - ACCURATE: Blender's native viewport compositor (pixel-identical to F12).
      - FAST:     a custom GPU (Metal) dual-filter pass, for when the accurate
                  preview is too slow. It never touches F12 and defers to the
                  accurate composite on render and via the mode toggle.
"""

import bpy
from bpy.app.handlers import persistent

from . import properties, compositor, viewport, engine_gpu, ui


# --------------------------------------------------------------------------- #
# File-load persistence
# --------------------------------------------------------------------------- #
@persistent
def _on_load_post(_dummy):
    """Re-apply runtime state (viewport preview / draw handler) after a .blend
    is loaded, so a saved scene with bloom enabled comes back live."""
    for scene in bpy.data.scenes:
        settings = getattr(scene, "cycles_bloom", None)
        if settings is not None and settings.enabled:
            properties.sync(scene)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register():
    properties.register()
    ui.register()

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    # Tear down runtime hooks only. The compositor node group is ordinary saved
    # scene data (native Glare nodes) and keeps rendering in F12 even without the
    # add-on, so we deliberately leave it and the user's use_compositor state
    # untouched here. The *feature* toggle (enabled=False) is what removes them.
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)

    engine_gpu.shutdown()
    viewport.shutdown()

    ui.unregister()
    properties.unregister()
