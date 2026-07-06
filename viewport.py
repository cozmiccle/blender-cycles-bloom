"""Accurate viewport preview.

Turns Blender's native viewport compositor on/off so the *same* compositor node
tree that F12 renders is shown live in the 3D viewport. Because it is literally
the same node tree, this preview is pixel-identical to the final render.

New viewports created by splitting/duplicating inherit a space's shading state,
so applying to all currently-open 3D viewports is enough to make the setting
"stick" in normal use; we also re-apply on file load (see __init__).
"""

import bpy


def _iter_view3d_spaces():
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        yield space


def _accurate_active(settings):
    return (
        settings.enabled
        and settings.viewport_preview
        and settings.preview_mode == "ACCURATE"
    )


def apply(_scene, settings):
    desired = "ALWAYS" if _accurate_active(settings) else "DISABLED"
    for space in _iter_view3d_spaces():
        shading = getattr(space, "shading", None)
        if shading is None or not hasattr(shading, "use_compositor"):
            continue  # feature-detect: skip builds without viewport compositing
        if shading.use_compositor != desired:
            try:
                shading.use_compositor = desired
            except (TypeError, ValueError):
                pass


def shutdown():
    """Called on add-on unregister. The viewport-compositor state is ordinary
    per-space UI state, so we leave it as the user last had it rather than
    forcing it off here; the feature toggle (enabled=False) is what turns it off.
    """
    return
