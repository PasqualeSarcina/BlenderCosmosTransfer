import bpy

from segmentation_utils import (
    apply_segmentation,
    enter_fast_segmentation_render_mode,
    exit_fast_segmentation_render_mode,
    get_or_create_emission_material,
    reset_object_segmentation_state,
    restore_geometry_modifier_material_assignments,
    restore_geometry_node_material_assignments,
    restore_material_assignments,
    restore_material_id_remaps,
)


DEFAULT_NODE_GROUP_NAME = "City_Generator_2.0"
DEFAULT_CAR_COLLECTION_NAMES = {"car model"}
DEFAULT_CAR_OBJECT_NAMES = {"parking car", "Low poly car "}


def iter_nested_node_trees(root_tree):
    pending = [root_tree]
    visited = set()

    while pending:
        tree = pending.pop()

        if tree.as_pointer() in visited:
            continue

        visited.add(tree.as_pointer())
        yield tree

        for node in tree.nodes:
            nested_tree = getattr(node, "node_tree", None)

            if nested_tree is not None:
                pending.append(nested_tree)


def is_car_source_node(
    node,
    car_collection_names=None,
    car_object_names=None,
):
    if car_collection_names is None:
        car_collection_names = DEFAULT_CAR_COLLECTION_NAMES
    if car_object_names is None:
        car_object_names = DEFAULT_CAR_OBJECT_NAMES

    # Auto complete: body + ruote nella collection "car model"
    if node.bl_idname == "GeometryNodeCollectionInfo":
        socket = node.inputs.get("Collection")
        collection = socket.default_value if socket else None

        return (
            collection is not None
            and collection.name in car_collection_names
        )

    # Parking car e Low poly car
    if node.bl_idname == "GeometryNodeObjectInfo":
        socket = node.inputs.get("Object")
        obj = socket.default_value if socket else None

        return (
            obj is not None
            and obj.name in car_object_names
        )

    return False


def _normalize_color(color):
    values = [float(value) for value in color]
    if len(values) != 3:
        raise ValueError("wsm.car_color deve contenere tre valori RGB")
    if any(value > 1.0 for value in values):
        values = [value / 255.0 for value in values]
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("wsm.car_color deve usare valori 0..1 oppure 0..255")
    return (*values, 1.0)


def enable_car_bounding_boxes(car_material, wsm_config=None):
    wsm_config = wsm_config or {}
    node_group_name = wsm_config.get(
        "node_group_name",
        DEFAULT_NODE_GROUP_NAME,
    )
    car_collection_names = set(
        wsm_config.get(
            "car_collection_names",
            DEFAULT_CAR_COLLECTION_NAMES,
        )
    )
    car_object_names = set(
        wsm_config.get(
            "car_object_names",
            DEFAULT_CAR_OBJECT_NAMES,
        )
    )

    root_tree = bpy.data.node_groups.get(node_group_name)

    if root_tree is None:
        raise RuntimeError(
            f"Node group '{node_group_name}' non trovato"
        )

    changes = []

    try:
        for tree in iter_nested_node_trees(root_tree):
            for source_node in list(tree.nodes):
                if not is_car_source_node(
                    source_node,
                    car_collection_names,
                    car_object_names,
                ):
                    continue

                direct_links = [
                    link
                    for output in source_node.outputs
                    for link in list(output.links)
                    if (
                        link.to_node.bl_idname
                        == "GeometryNodeInstanceOnPoints"
                        and link.to_socket.name == "Instance"
                    )
                ]

                for original_link in direct_links:
                    source_socket = original_link.from_socket
                    target_socket = original_link.to_socket

                    # Rimuove solamente il collegamento originale dell'auto.
                    tree.links.remove(original_link)

                    realize = tree.nodes.new(
                        "GeometryNodeRealizeInstances"
                    )
                    realize.name = "WSM_Realize_Car"
                    realize.label = "WSM: complete car"
                    realize.location = (
                        source_node.location.x + 220,
                        source_node.location.y,
                    )

                    bounding_box = tree.nodes.new(
                        "GeometryNodeBoundBox"
                    )
                    bounding_box.name = "WSM_Car_Bounding_Box"
                    bounding_box.label = "WSM: car bounding box"
                    bounding_box.location = (
                        source_node.location.x + 440,
                        source_node.location.y,
                    )

                    use_radius = bounding_box.inputs.get("Use Radius")
                    if use_radius is not None:
                        use_radius.default_value = False

                    set_material = tree.nodes.new(
                        "GeometryNodeSetMaterial"
                    )
                    set_material.name = "WSM_Car_Set_Material"
                    set_material.label = "WSM: car material"
                    set_material.location = (
                        source_node.location.x + 660,
                        source_node.location.y,
                    )
                    set_material.inputs["Material"].default_value = (
                        car_material
                    )

                    tree.links.new(
                        source_socket,
                        realize.inputs["Geometry"],
                    )
                    tree.links.new(
                        realize.outputs["Geometry"],
                        bounding_box.inputs["Geometry"],
                    )
                    tree.links.new(
                        bounding_box.outputs["Bounding Box"],
                        set_material.inputs["Geometry"],
                    )
                    tree.links.new(
                        set_material.outputs["Geometry"],
                        target_socket,
                    )

                    changes.append({
                        "tree": tree,
                        "source_socket": source_socket,
                        "target_socket": target_socket,
                        "realize": realize,
                        "bounding_box": bounding_box,
                        "set_material": set_material,
                    })

        if not changes:
            raise RuntimeError(
                "Nessun ramo Geometry Nodes delle car e' stato trovato"
            )

    except Exception:
        disable_car_bounding_boxes(changes)
        raise

    bpy.context.view_layer.update()

    print(f"Rami car modificati: {len(changes)}")
    return changes

def disable_car_bounding_boxes(changes):
    for change in reversed(changes):
        tree = change["tree"]

        # Rimuovendo i nodi vengono rimossi anche i relativi collegamenti
        tree.nodes.remove(change["set_material"])
        tree.nodes.remove(change["bounding_box"])
        tree.nodes.remove(change["realize"])

        # Ripristina il collegamento originale
        tree.links.new(
            change["source_socket"],
            change["target_socket"],
        )

    bpy.context.view_layer.update()


def _restore_segmentation(scene, result):
    restore_material_assignments(scene, result["material_snapshot"])
    restore_geometry_node_material_assignments(
        result["geometry_node_material_snapshot"]
    )
    restore_geometry_modifier_material_assignments(
        result["geometry_modifier_material_snapshot"]
    )
    restore_material_id_remaps(result["material_id_remaps"])
    reset_object_segmentation_state(scene)


def enter_wsm_mode(scene, wsm_config):
    if not wsm_config or "classes" not in wsm_config:
        raise ValueError("Configurazione 'wsm.classes' mancante")

    render_state = enter_fast_segmentation_render_mode(scene)
    color_state = {
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
    }
    segmentation_result = None
    car_changes = []

    try:
        scene.view_settings.view_transform = "Raw"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0

        # Il fallback background rende nero tutto; le classi configurate
        # mantengono colorati corsie, segnaletica e bordi del marciapiede.
        segmentation_result = apply_segmentation(wsm_config, scene)

        car_material = get_or_create_emission_material(
            "EMIT_SEG__WSM_CAR",
            _normalize_color(
                wsm_config.get("car_color", [20, 116, 194])
            ),
        )
        car_changes = enable_car_bounding_boxes(
            car_material,
            wsm_config,
        )
        bpy.context.view_layer.update()

        return {
            "render_state": render_state,
            "color_state": color_state,
            "segmentation_result": segmentation_result,
            "car_changes": car_changes,
        }

    except Exception:
        if car_changes:
            disable_car_bounding_boxes(car_changes)
        if segmentation_result is not None:
            _restore_segmentation(scene, segmentation_result)
        scene.view_settings.view_transform = color_state["view_transform"]
        scene.view_settings.look = color_state["look"]
        scene.view_settings.exposure = color_state["exposure"]
        scene.view_settings.gamma = color_state["gamma"]
        exit_fast_segmentation_render_mode(scene, render_state)
        raise


def exit_wsm_mode(scene, state):
    try:
        disable_car_bounding_boxes(state["car_changes"])
    finally:
        try:
            _restore_segmentation(
                scene,
                state["segmentation_result"],
            )
        finally:
            color_state = state["color_state"]
            scene.view_settings.view_transform = color_state["view_transform"]
            scene.view_settings.look = color_state["look"]
            scene.view_settings.exposure = color_state["exposure"]
            scene.view_settings.gamma = color_state["gamma"]
            exit_fast_segmentation_render_mode(
                scene,
                state["render_state"],
            )
            bpy.context.view_layer.update()
