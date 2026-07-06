"""Scene-level settings for Cycles Bloom and the central sync() entry point.

Every property's ``update`` callback funnels into :func:`sync`, which is the one
place that pushes state into the three subsystems (compositor node group,
accurate viewport preview, fast GPU preview). A re-entrancy guard prevents a
sync from triggering itself.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
)
from bpy.types import PropertyGroup


# --------------------------------------------------------------------------- #
# Central sync
# --------------------------------------------------------------------------- #
_syncing = False


def sync(scene):
    """Apply the current settings to all subsystems. Safe to call repeatedly."""
    global _syncing
    if _syncing:
        return
    settings = getattr(scene, "cycles_bloom", None)
    if settings is None:
        return

    # Lazy imports avoid an import cycle (these modules may import this one).
    from . import compositor, viewport, engine_gpu

    _syncing = True
    try:
        compositor.apply(scene, settings)
        viewport.apply(scene, settings)
        engine_gpu.apply(scene, settings)
    finally:
        _syncing = False


def _update(self, _context):
    sync(self.id_data)


# --------------------------------------------------------------------------- #
# Property group
# --------------------------------------------------------------------------- #
class CyclesBloomSettings(PropertyGroup):
    enabled: BoolProperty(
        name="Enable Bloom",
        description="Add a Glare/Bloom node group to the compositor. This is the "
        "bloom that appears in F12 final renders",
        default=False,
        update=_update,
    )

    viewport_preview: BoolProperty(
        name="Viewport Preview",
        description="Show the bloom live in the 3D viewport so you can build your "
        "scene around the final look (Rendered / Material Preview shading)",
        default=True,
        update=_update,
    )

    preview_mode: EnumProperty(
        name="Preview Mode",
        description="How the viewport preview is computed. Final renders always "
        "use the Accurate composite regardless of this setting",
        items=(
            (
                "ACCURATE",
                "Accurate",
                "Native viewport compositor — pixel-identical to the F12 render, "
                "but heavier",
            ),
            (
                "FAST",
                "Fast",
                "Custom GPU (Metal) approximation for interactive navigation. "
                "Renders still use the Accurate composite",
            ),
        ),
        default="ACCURATE",
        update=_update,
    )

    # --- Look parameters (feed both the Glare node and the GPU preview) ------ #
    threshold: FloatProperty(
        name="Threshold",
        description="Pixels brighter than this contribute to bloom",
        default=1.0,
        min=0.0,
        soft_max=10.0,
        update=_update,
    )

    smoothness: FloatProperty(
        name="Smoothness",
        description="Soft knee around the threshold (0 = hard cutoff)",
        default=0.1,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update,
    )

    size: FloatProperty(
        name="Size",
        description="Spread / radius of the glow",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update,
    )

    intensity: FloatProperty(
        name="Intensity",
        description="Strength of the bloom added back over the image",
        default=0.1,
        min=0.0,
        soft_max=1.0,
        update=_update,
    )

    tint: FloatVectorProperty(
        name="Tint",
        description="Colour multiplied into the bloom",
        subtype="COLOR",
        size=3,
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        update=_update,
    )

    clamp: FloatProperty(
        name="Clamp",
        description="Maximum brightness fed into bloom to tame fireflies "
        "(0 = no clamp)",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
        update=_update,
    )

    quality: EnumProperty(
        name="Quality",
        description="Trade speed for smoothness of the glow",
        items=(
            ("LOW", "Low", "Fastest, coarser glow"),
            ("MEDIUM", "Medium", "Balanced"),
            ("HIGH", "High", "Smoothest, slowest"),
        ),
        default="MEDIUM",
        update=_update,
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
_classes = (CyclesBloomSettings,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cycles_bloom = bpy.props.PointerProperty(type=CyclesBloomSettings)


def unregister():
    if hasattr(bpy.types.Scene, "cycles_bloom"):
        del bpy.types.Scene.cycles_bloom
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
