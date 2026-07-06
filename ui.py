"""The Bloom panel in Properties > Render (Cycles only).

The panel is collapsible (the "drop-down") with an enable checkbox in its header.
"""

import bpy
from bpy.types import Panel


class RENDER_PT_cycles_bloom(Panel):
    bl_label = "Bloom"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.engine == "CYCLES"

    def draw_header(self, context):
        self.layout.prop(context.scene.cycles_bloom, "enabled", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        s = context.scene.cycles_bloom

        body = layout.column()
        body.active = s.enabled
        body.prop(s, "threshold")
        body.prop(s, "smoothness")
        body.prop(s, "size")
        body.prop(s, "intensity")
        body.prop(s, "tint")
        body.prop(s, "clamp")
        body.prop(s, "quality")

        body.separator()
        body.prop(s, "viewport_preview")

        mode = body.column()
        mode.active = s.enabled and s.viewport_preview
        mode.prop(s, "preview_mode")

        if s.enabled and s.viewport_preview:
            info = body.column(align=True)
            info.label(text="Preview shows in Rendered / Material shading", icon="INFO")
            if s.preview_mode == "FAST":
                info.label(text="Fast is approximate; F12 uses Accurate", icon="INFO")


_classes = (RENDER_PT_cycles_bloom,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
