"""The accurate bloom: a managed Glare(Bloom) node in the scene compositor.
This is the single source of truth for F12 final renders.

Blender 5.x compositor model (verified on 5.1):
  * The scene compositor is a CompositorNodeTree data-block referenced by
    ``scene.compositing_node_group`` (there is no more ``scene.node_tree`` /
    ``scene.use_nodes`` compositor, and ``CompositorNodeComposite`` is gone).
  * The tree's final image leaves through a Group Output node, whose inputs are
    defined by the tree's interface.
  * The Glare node is fully socket-driven: a ``Type`` menu socket (``'Bloom'``),
    a ``Quality`` menu socket (``'High'/'Medium'/'Low'``) and float/colour
    sockets for the look. Menu socket values are the human-readable labels.

We insert exactly one tagged Glare node in front of the Group Output, so
enabling is non-destructive and removal restores the original wiring. If we had
to create the whole compositor group ourselves, we tear it back down on disable.
"""

import bpy

# Tags so we only ever touch data we created.
_NODE_TAG = "cycles_bloom_owned"
_TREE_TAG = "cycles_bloom_created"

_QUALITY = {"LOW": "Low", "MEDIUM": "Medium", "HIGH": "High"}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def apply(scene, settings):
    if not settings.enabled:
        remove(scene)
        return
    tree = _ensure_tree(scene)
    if tree is None:
        return
    glare = _ensure_glare(tree)
    if glare is not None:
        _write_params(glare, settings)


def remove(scene):
    tree = scene.compositing_node_group
    if tree is None:
        return
    for node in [n for n in tree.nodes if n.get(_NODE_TAG)]:
        _bypass_and_delete(tree, node)

    # If we created the whole group and nothing but the pass-through remains,
    # restore the original "no compositor" state.
    if tree.get(_TREE_TAG):
        kinds = {n.type for n in tree.nodes}
        if kinds <= {"R_LAYERS", "GROUP_OUTPUT"}:
            scene.compositing_node_group = None
            try:
                bpy.data.node_groups.remove(tree)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Tree / node management
# --------------------------------------------------------------------------- #
def _ensure_tree(scene):
    tree = scene.compositing_node_group
    if tree is not None:
        return tree

    tree = bpy.data.node_groups.new("Cycles Bloom Compositor", "CompositorNodeTree")
    tree[_TREE_TAG] = 1

    has_output = any(
        getattr(it, "in_out", "") == "OUTPUT" for it in tree.interface.items_tree
    )
    if not has_output:
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")

    rlayers = tree.nodes.new("CompositorNodeRLayers")
    out = tree.nodes.new("NodeGroupOutput")
    out.location = (400, 0)
    tree.links.new(rlayers.outputs["Image"], out.inputs[0])

    scene.compositing_node_group = tree
    return tree


def _find_owned(tree):
    for node in tree.nodes:
        if node.get(_NODE_TAG):
            return node
    return None


def _get_output(tree):
    for node in tree.nodes:
        if node.type == "GROUP_OUTPUT":
            return node
    # Create one, fed by Render Layers if present.
    out = tree.nodes.new("NodeGroupOutput")
    if not any(getattr(it, "in_out", "") == "OUTPUT" for it in tree.interface.items_tree):
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rlayers = next((n for n in tree.nodes if n.type == "R_LAYERS"), None)
    if rlayers is not None:
        tree.links.new(rlayers.outputs["Image"], out.inputs[0])
    return out


def _ensure_glare(tree):
    existing = _find_owned(tree)
    if existing is not None:
        return existing

    output = _get_output(tree)
    out_in = output.inputs[0]

    upstream = None
    for link in list(tree.links):
        if link.to_socket == out_in:
            upstream = link.from_socket
            break
    if upstream is None:
        rlayers = next((n for n in tree.nodes if n.type == "R_LAYERS"), None)
        if rlayers is not None:
            upstream = rlayers.outputs.get("Image")

    glare = tree.nodes.new("CompositorNodeGlare")
    glare[_NODE_TAG] = 1
    glare.label = "Cycles Bloom"
    glare.location = (output.location.x - 300, output.location.y)
    _set_menu(glare, "Type", "Bloom", "Fog Glow")

    if upstream is not None:
        tree.links.new(upstream, glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], out_in)
    return glare


def _bypass_and_delete(tree, node):
    upstream = None
    img_in = node.inputs.get("Image")
    for link in tree.links:
        if link.to_socket == img_in:
            upstream = link.from_socket
            break

    img_out = node.outputs.get("Image")
    downstream = [link.to_socket for link in tree.links if link.from_socket == img_out]

    tree.nodes.remove(node)

    if upstream is not None:
        for target in downstream:
            try:
                tree.links.new(upstream, target)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Parameter writing (socket-driven, with light name fallbacks for forward compat)
# --------------------------------------------------------------------------- #
def _set_menu(node, name, value, fallback=None):
    sock = node.inputs.get(name)
    if sock is None:
        return
    for candidate in (value, fallback):
        if candidate is None:
            continue
        try:
            sock.default_value = candidate
            return
        except (TypeError, ValueError):
            continue


def _set_socket(node, names, value):
    for name in names:
        sock = node.inputs.get(name)
        if sock is None or not hasattr(sock, "default_value"):
            continue
        try:
            sock.default_value = value
            return True
        except (TypeError, ValueError):
            continue
    return False


def _write_params(glare, s):
    _set_menu(glare, "Quality", _QUALITY.get(s.quality, "Medium"))
    _set_socket(glare, ["Threshold", "Highlights Threshold"], s.threshold)
    _set_socket(glare, ["Smoothness", "Highlights Smoothness"], s.smoothness)
    _set_socket(glare, ["Size"], s.size)
    _set_socket(glare, ["Strength"], s.intensity)
    _set_socket(glare, ["Tint"], (s.tint[0], s.tint[1], s.tint[2], 1.0))

    if s.clamp > 0.0:
        _set_socket(glare, ["Clamp"], True)
        _set_socket(glare, ["Maximum"], s.clamp)
    else:
        _set_socket(glare, ["Clamp"], False)
