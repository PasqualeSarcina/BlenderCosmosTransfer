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
DEFAULT_GENERATOR_OBJECT_NAME = "City_Generator_2.0_Object"
DEFAULT_BAKED_TRAFFIC_COLLECTION_NAMES = {"Traffic_Baked"}
DEFAULT_BAKED_CAR_OBJECT_NAMES = {
    "body",
    "front",
    "back",
    "parked body",
    "parked front",
    "parked back",
}
DEFAULT_BAKED_CAR_BODY_NAMES = {"body", "parked body"}


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


def _find_generator_node_group(node_group_name, wsm_config):
    root_tree = bpy.data.node_groups.get(node_group_name)
    if root_tree is not None:
        return root_tree

    generator_object_name = wsm_config.get(
        "generator_object_name",
        DEFAULT_GENERATOR_OBJECT_NAME,
    )
    generator_object = bpy.data.objects.get(generator_object_name)
    if generator_object is None:
        return None

    for modifier in generator_object.modifiers:
        if modifier.type != "NODES":
            continue
        if modifier.node_group is not None:
            print(
                f"Node group '{node_group_name}' non trovato; "
                f"uso '{modifier.node_group.name}' dal modificatore "
                f"'{modifier.name}'."
            )
            return modifier.node_group

    return None


def _matches_blender_name(name, expected_names):
    name_lower = name.casefold()
    return any(
        name_lower == expected.casefold()
        or name_lower.startswith(f"{expected.casefold()}.")
        for expected in expected_names
    )


def _mesh_component_bounds(mesh):
    vertex_count = len(mesh.vertices)
    if vertex_count == 0:
        return []

    parents = list(range(vertex_count))
    used_vertices = set()

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first, second):
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for edge in mesh.edges:
        first, second = edge.vertices
        used_vertices.update((first, second))
        union(first, second)

    if not used_vertices:
        used_vertices.update(range(vertex_count))

    components = {}
    for vertex_index in used_vertices:
        components.setdefault(find(vertex_index), []).append(vertex_index)

    bounds = []
    for indices in components.values():
        coordinates = [mesh.vertices[index].co for index in indices]
        minimum = coordinates[0].copy()
        maximum = coordinates[0].copy()
        for coordinate in coordinates[1:]:
            minimum.x = min(minimum.x, coordinate.x)
            minimum.y = min(minimum.y, coordinate.y)
            minimum.z = min(minimum.z, coordinate.z)
            maximum.x = max(maximum.x, coordinate.x)
            maximum.y = max(maximum.y, coordinate.y)
            maximum.z = max(maximum.z, coordinate.z)
        bounds.append((minimum, maximum))

    return bounds


def _box_mesh_geometry(bounds, padding):
    vertices = []
    faces = []

    for minimum, maximum in bounds:
        min_x = minimum.x - padding[0]
        min_y = minimum.y - padding[1]
        min_z = minimum.z - padding[2]
        max_x = maximum.x + padding[0]
        max_y = maximum.y + padding[1]
        max_z = maximum.z + padding[2]
        offset = len(vertices)

        vertices.extend([
            (min_x, min_y, min_z),
            (max_x, min_y, min_z),
            (max_x, max_y, min_z),
            (min_x, max_y, min_z),
            (min_x, min_y, max_z),
            (max_x, min_y, max_z),
            (max_x, max_y, max_z),
            (min_x, max_y, max_z),
        ])
        faces.extend([
            (offset + 0, offset + 3, offset + 2, offset + 1),
            (offset + 4, offset + 5, offset + 6, offset + 7),
            (offset + 0, offset + 1, offset + 5, offset + 4),
            (offset + 1, offset + 2, offset + 6, offset + 5),
            (offset + 2, offset + 3, offset + 7, offset + 6),
            (offset + 3, offset + 0, offset + 4, offset + 7),
        ])

    return vertices, faces


def _normalize_bbox_padding(value):
    if isinstance(value, (int, float)):
        padding = (float(value),) * 3
    else:
        padding = tuple(float(item) for item in value)
        if len(padding) != 3:
            raise ValueError(
                "wsm.baked_bbox_padding deve essere un numero o [x, y, z]"
            )
    if any(item < 0.0 for item in padding):
        raise ValueError("wsm.baked_bbox_padding non puo' essere negativo")
    return padding


def _update_baked_box(box_state, depsgraph, padding):
    source = box_state["source"]
    box_object = box_state["box_object"]
    box_mesh = box_state["box_mesh"]
    evaluated_object = source.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_object.to_mesh()

    try:
        bounds = _mesh_component_bounds(evaluated_mesh)
        if not bounds:
            if not box_state.get("warned_empty", False):
                print(
                    f"ATTENZIONE: mesh baked '{source.name}' vuota nel "
                    "depsgraph; mantengo l'ultimo parallelepipedo valido."
                )
                box_state["warned_empty"] = True
            return 0

        vertices, faces = _box_mesh_geometry(bounds, padding)
        box_mesh.clear_geometry()
        box_mesh.from_pydata(vertices, [], faces)
        box_mesh.update()
        box_object.matrix_world = evaluated_object.matrix_world.copy()
        box_object.hide_render = False
        box_state["warned_empty"] = False
        return len(bounds)
    finally:
        evaluated_object.to_mesh_clear()


def _cleanup_baked_boxes(change):
    handler = change.get("handler")
    if handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(handler)

    for obj, previous_hide_render in change.get("source_states", []):
        obj.hide_render = previous_hide_render

    for box_state in change.get("box_states", []):
        box_object = box_state["box_object"]
        box_mesh = box_state["box_mesh"]
        if box_object.name in bpy.data.objects:
            bpy.data.objects.remove(box_object, do_unlink=True)
        if box_mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(box_mesh)

    collection = change.get("collection")
    if collection is not None and collection.name in bpy.data.collections:
        bpy.data.collections.remove(collection)


def _enable_baked_car_boxes(car_material, wsm_config):
    collection_names = set(
        wsm_config.get(
            "baked_traffic_collection_names",
            DEFAULT_BAKED_TRAFFIC_COLLECTION_NAMES,
        )
    )
    object_names = set(
        wsm_config.get(
            "baked_car_object_names",
            DEFAULT_BAKED_CAR_OBJECT_NAMES,
        )
    )
    body_names = set(
        wsm_config.get(
            "baked_car_body_names",
            DEFAULT_BAKED_CAR_BODY_NAMES,
        )
    )
    padding = _normalize_bbox_padding(
        wsm_config.get("baked_bbox_padding", [0.0, 0.0, 0.0])
    )

    collections = [
        collection for collection in bpy.data.collections
        if _matches_blender_name(collection.name, collection_names)
    ]
    if not collections:
        return []

    source_objects = []
    body_objects = []
    visited_objects = set()

    for collection in collections:
        for obj in collection.all_objects:
            if obj.type != "MESH":
                continue
            if not _matches_blender_name(obj.name, object_names):
                continue
            if obj.as_pointer() in visited_objects:
                continue

            visited_objects.add(obj.as_pointer())
            source_objects.append(obj)
            if _matches_blender_name(obj.name, body_names):
                body_objects.append(obj)

    if not source_objects:
        return []
    if not body_objects:
        body_objects = source_objects

    temporary_collection = bpy.data.collections.new(
        "WSM_Baked_Car_Boxes"
    )
    bpy.context.scene.collection.children.link(temporary_collection)
    change = {
        "kind": "baked_boxes",
        "collection": temporary_collection,
        "source_states": [
            (obj, obj.hide_render) for obj in source_objects
        ],
        "box_states": [],
        "handler": None,
    }

    try:
        for source in body_objects:
            box_mesh = bpy.data.meshes.new(f"WSM_Box_{source.name}")
            box_mesh.materials.append(car_material)
            box_object = bpy.data.objects.new(
                f"WSM_Box_{source.name}",
                box_mesh,
            )
            temporary_collection.objects.link(box_object)
            change["box_states"].append({
                "source": source,
                "box_object": box_object,
                "box_mesh": box_mesh,
                "warned_empty": False,
            })

        def update_boxes(_scene, depsgraph=None):
            current_depsgraph = (
                depsgraph
                if depsgraph is not None
                else bpy.context.evaluated_depsgraph_get()
            )
            counts = {}
            for box_state in change["box_states"]:
                counts[box_state["source"].name] = _update_baked_box(
                    box_state,
                    current_depsgraph,
                    padding,
                )
            return counts

        # Calcola i box mentre le mesh sorgenti sono ancora renderizzabili.
        # Alcuni bake restituiscono geometria vuota dopo hide_render=True.
        initial_counts = update_boxes(bpy.context.scene)
        for source_name, count in initial_counts.items():
            print(f"WSM baked: '{source_name}' -> {count} parallelepipedi")

        for source in source_objects:
            source.hide_render = True

        change["handler"] = update_boxes
        bpy.app.handlers.frame_change_post.append(update_boxes)

    except Exception:
        _cleanup_baked_boxes(change)
        raise

    print(
        "Geometry Nodes del generatore non disponibile: "
        f"creati parallelepipedi WSM per {len(body_objects)} mesh body "
        f"e nascoste {len(source_objects)} mesh auto baked."
    )
    return [change]


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

    root_tree = _find_generator_node_group(
        node_group_name,
        wsm_config,
    )

    if root_tree is None:
        changes = _enable_baked_car_boxes(
            car_material,
            wsm_config,
        )
        if changes:
            bpy.context.view_layer.update()
            return changes
        raise RuntimeError(
            f"Node group '{node_group_name}' non trovato e nessuna "
            "mesh auto compatibile trovata nelle collection baked"
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
                        "kind": "geometry_nodes",
                        "tree": tree,
                        "source_socket": source_socket,
                        "target_socket": target_socket,
                        "realize": realize,
                        "bounding_box": bounding_box,
                        "set_material": set_material,
                    })

        if not changes:
            changes = _enable_baked_car_boxes(
                car_material,
                wsm_config,
            )
            if not changes:
                raise RuntimeError(
                    "Nessun ramo Geometry Nodes delle car e nessuna "
                    "mesh auto baked sono stati trovati"
                )

    except Exception:
        disable_car_bounding_boxes(changes)
        raise

    bpy.context.view_layer.update()

    print(f"Rami car modificati: {len(changes)}")
    return changes

def disable_car_bounding_boxes(changes):
    for change in reversed(changes):
        if change.get("kind") == "baked_boxes":
            _cleanup_baked_boxes(change)
            continue

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
