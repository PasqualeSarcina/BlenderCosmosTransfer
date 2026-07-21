import bpy
import random
import re


def _normalize_color_value(value):
    """
    Accetta:
    - [r, g, b] con valori 0..1 oppure 0..255
    """

    vals = list(value)
    if any(v > 1.0 for v in vals):
        vals = [v / 255.0 for v in vals]
    return (float(vals[0]), float(vals[1]), float(vals[2]), 1.0)


# =========================================================
# MATERIALI EMISSION
# =========================================================

def get_or_create_emission_material(name, color_rgba):
    """
    Crea o aggiorna un materiale emission puro.
    """
    if name in bpy.data.materials:
        mat = bpy.data.materials[name]
    else:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    emission = nodes.new(type="ShaderNodeEmission")
    emission.inputs["Color"].default_value = color_rgba
    emission.inputs["Strength"].default_value = 1.0

    output = nodes.new(type="ShaderNodeOutputMaterial")
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return mat


def get_or_create_transparent_material(name):
    """Create a fully transparent material for ignored carrier geometry."""
    if name in bpy.data.materials:
        mat = bpy.data.materials[name]
    else:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    transparent = nodes.new(type="ShaderNodeBsdfTransparent")
    output = nodes.new(type="ShaderNodeOutputMaterial")
    links.new(transparent.outputs["BSDF"], output.inputs["Surface"])

    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"

    return mat


# =========================================================
# MATCH
# =========================================================

def object_matches_rule(obj, match_rule):
    name = obj.name.lower()

    exacts = [x.lower() for x in match_rule.get("object_name_exact", [])]
    contains = [x.lower() for x in match_rule.get("object_name_contains", [])]
    collection_exacts = [
        x.lower() for x in match_rule.get("collection_name_exact", [])
    ]

    if exacts and name in exacts:
        return True

    if contains and any(token in name for token in contains):
        return True

    if collection_exacts:
        for collection in obj.users_collection:
            collection_name = collection.name.lower()
            if any(
                collection_name == expected
                or collection_name.startswith(f"{expected}.")
                for expected in collection_exacts
            ):
                return True

    return False


def material_matches_rule(mat, match_rule):
    if mat is None:
        return False

    name = mat.name.lower()

    exacts = [x.lower() for x in match_rule.get("material_name_exact", [])]
    contains = [x.lower() for x in match_rule.get("material_name_contains", [])]

    if exacts and name in exacts:
        return True

    if contains and any(token in name for token in contains):
        return True

    return False


# =========================================================
# SNAPSHOT / RESTORE MATERIALI
# =========================================================

def snapshot_material_assignments(scene):
    """
    Salva i materiali originali per ogni object/material slot.
    """
    snapshot = {}

    for obj in scene.objects:
        if obj.type != "MESH":
            continue

        snapshot[obj.name] = []
        for slot in obj.material_slots:
            snapshot[obj.name].append(slot.material.name if slot.material else None)

    return snapshot


def restore_material_assignments(scene, snapshot):
    """
    Ripristina i materiali originali dopo un render di segmentazione.
    """
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if obj.name not in snapshot:
            continue

        saved_slots = snapshot[obj.name]
        for i, saved_mat_name in enumerate(saved_slots):
            if i >= len(obj.material_slots):
                continue

            if saved_mat_name is None:
                obj.material_slots[i].material = None
            elif saved_mat_name in bpy.data.materials:
                obj.material_slots[i].material = bpy.data.materials[saved_mat_name]


def iter_scene_geometry_material_sockets(scene):
    """Yield Material input sockets in Geometry Nodes used by the scene."""
    pending_trees = []
    seen_tree_pointers = set()

    for obj in scene.objects:
        for modifier in obj.modifiers:
            if modifier.type == "NODES" and modifier.node_group is not None:
                pending_trees.append(modifier.node_group)

    while pending_trees:
        node_tree = pending_trees.pop()
        tree_pointer = node_tree.as_pointer()

        if tree_pointer in seen_tree_pointers:
            continue

        seen_tree_pointers.add(tree_pointer)

        for node in node_tree.nodes:
            nested_tree = getattr(node, "node_tree", None)
            if nested_tree is not None:
                pending_trees.append(nested_tree)

            for input_socket in node.inputs:
                if getattr(input_socket, "type", None) == "MATERIAL":
                    yield node_tree, node, input_socket


def snapshot_geometry_node_material_assignments(scene):
    """Save direct Material references used by the scene's Geometry Nodes."""
    return [
        (input_socket, input_socket.default_value)
        for _, _, input_socket in iter_scene_geometry_material_sockets(scene)
    ]


def restore_geometry_node_material_assignments(snapshot):
    for input_socket, saved_material in snapshot:
        input_socket.default_value = saved_material


def iter_scene_geometry_modifier_material_inputs(scene):
    """Yield Material values stored on Geometry Nodes modifiers.

    Group interface inputs are stored as modifier ID properties (for example
    ``modifier["Socket_50"]``), not as node input defaults.  When an interface
    input is linked, this value overrides the defaults inside the node tree.
    """
    for obj in scene.objects:
        for modifier in obj.modifiers:
            if modifier.type != "NODES" or modifier.node_group is None:
                continue

            for property_name, value in modifier.items():
                if isinstance(value, bpy.types.Material):
                    yield obj, modifier, property_name, value


def snapshot_geometry_modifier_material_assignments(scene):
    """Save Material values supplied through Geometry Nodes modifiers."""
    return [
        (modifier, property_name, material)
        for _, modifier, property_name, material
        in iter_scene_geometry_modifier_material_inputs(scene)
    ]


def restore_geometry_modifier_material_assignments(snapshot):
    for modifier, property_name, saved_material in snapshot:
        modifier[property_name] = saved_material


def restore_material_id_remaps(snapshot):
    """Restore global material remaps in reverse application order."""
    for original_material, replacement_material in reversed(snapshot):
        replacement_material.user_remap(original_material)


def update_scene_geometry_nodes(scene):
    updated_trees = set()

    for node_tree, _, _ in iter_scene_geometry_material_sockets(scene):
        tree_pointer = node_tree.as_pointer()
        if tree_pointer in updated_trees:
            continue
        node_tree.update_tag()
        updated_trees.add(tree_pointer)

    bpy.context.view_layer.update()


# =========================================================
# RESET METADATI OBJECT
# =========================================================

def reset_object_segmentation_state(scene):
    for obj in scene.objects:
        if obj.type != "MESH":
            continue

        if "class_id" in obj:
            del obj["class_id"]
        if "instance_id" in obj:
            del obj["instance_id"]

        obj.pass_index = 0


# =========================================================
# GROUPING ISTANZE
# =========================================================

def compute_instance_group_key(obj, class_name):
    """
    Qui decidi TU come raggruppare le istanze.
    Attualmente:
    - default: ogni oggetto è un'istanza
    - esempio hardcoded per car: suffix finale .001, .002, ...
    """
    name = obj.name

    # ESEMPIO hardcoded per classi tipo car con body/wheels
    if class_name == "car":
        m = re.search(r"\.(\d+)$", name)
        if m:
            return f"{class_name}::{m.group(1)}"

    # default: un oggetto = una istanza
    return f"{class_name}::OBJ::{name}"


# =========================================================
# COLORE PER CLASSE / ISTANZA
# =========================================================

def resolve_class_color(class_name, class_cfg, class_color_cache):
    color_cfg = class_cfg.get("color")
    if not color_cfg:
        return None

    mode = color_cfg["mode"]

    if mode == "fixed":
        return _normalize_color_value(color_cfg["value"])

    if mode == "random":
        if class_name not in class_color_cache:
            class_color_cache[class_name] = (random.random(), random.random(), random.random(), 1.0)
        return class_color_cache[class_name]

    # random_instance si gestisce più avanti, per istanza
    if mode == "random_instance":
        return None

    raise ValueError(f"color.mode non supportato: {mode}")


def resolve_instance_color(instance_id, instance_color_cache):
    if instance_id not in instance_color_cache:
        instance_color_cache[instance_id] = (random.random(), random.random(), random.random(), 1.0)
    return instance_color_cache[instance_id]


# =========================================================
# APPLY SEGMENTATION
# =========================================================

def apply_segmentation(seg_cfg, scene=None):
    """
    Applica UNA singola istanza di segmentazione.

    Regole:
    - "background" è una classe speciale di fallback:
        * non ha mode
        * non ha match
        * ha solo "color"
        * viene applicata a tutto ciò che non è stato matchato
    - classi mode='object':
        * assegnano class_id
        * assegnano instance_id
        * assegnano obj.pass_index = instance_id
        * opzionalmente sostituiscono i materiali con emission
    - classi mode='material':
        * matchano i materiali per nome
        * rimpiazzano gli slot matchati con emission
        * NON assegnano class_id / instance_id

    Ritorna:
    {
        "material_snapshot": ...,
        "instance_metadata": {
            instance_id: {
                "class_name": ...,
                "class_id": ...,
                "objects": [...]
            }
        }
    }
    """
    if scene is None:
        scene = bpy.context.scene

    classes_cfg = seg_cfg["classes"]

    background_cfg = classes_cfg.get("background")
    foreground_classes = {
        class_name: class_cfg
        for class_name, class_cfg in classes_cfg.items()
        if class_name != "background"
    }

    # 1) salva materiali originali
    material_snapshot = snapshot_material_assignments(scene)
    geometry_node_material_snapshot = snapshot_geometry_node_material_assignments(
        scene
    )
    geometry_modifier_material_snapshot = (
        snapshot_geometry_modifier_material_assignments(scene)
    )
    source_materials = [
        material
        for material in bpy.data.materials
        if not material.name.startswith("EMIT_SEG__")
    ]
    material_id_remaps = []

    # 2) resetta stato object-based precedente
    reset_object_segmentation_state(scene)

    # cache colori
    class_color_cache = {}
    instance_color_cache = {}

    # mapping instance key -> instance id
    next_instance_id = 1
    global_instance_map = {}
    instance_metadata = {}

    # tracking di ciò che è già stato matchato
    matched_object_names = set()
    matched_slots = set()  # (obj_name, slot_index)
    matched_geometry_node_sockets = set()
    matched_geometry_modifier_inputs = set()

    # -----------------------------------------------------
    # MATERIALI IGNORATI: decal/helper trasparenti
    # -----------------------------------------------------
    ignore_material_rule = seg_cfg.get("ignore_materials")

    if ignore_material_rule:
        ignored_replacement_pointers = set()

        for original_mat in source_materials:
            if not material_matches_rule(original_mat, ignore_material_rule):
                continue

            transparent_name = f"EMIT_SEG__IGNORE__SRC__{original_mat.name}"
            transparent_mat = get_or_create_transparent_material(transparent_name)
            original_mat.user_remap(transparent_mat)
            material_id_remaps.append((original_mat, transparent_mat))
            ignored_replacement_pointers.add(transparent_mat.as_pointer())

        for obj in scene.objects:
            if obj.type != "MESH":
                continue

            for slot_index, slot in enumerate(obj.material_slots):
                if (
                    slot.material is not None
                    and slot.material.as_pointer() in ignored_replacement_pointers
                ):
                    matched_slots.add((obj.name, slot_index))

        for _, _, input_socket in iter_scene_geometry_material_sockets(scene):
            current_mat = input_socket.default_value
            if (
                current_mat is not None
                and current_mat.as_pointer() in ignored_replacement_pointers
            ):
                matched_geometry_node_sockets.add(input_socket.as_pointer())

        for _, modifier, property_name, current_mat in (
            iter_scene_geometry_modifier_material_inputs(scene)
        ):
            if current_mat.as_pointer() in ignored_replacement_pointers:
                matched_geometry_modifier_inputs.add(
                    (modifier.as_pointer(), property_name)
                )

    # -----------------------------------------------------
    # PRIMA PASSATA: OBJECT CLASSES
    # -----------------------------------------------------
    for class_name, class_cfg in foreground_classes.items():
        if class_cfg["mode"] != "object":
            continue

        class_id = class_cfg["class_id"]
        match_rule = class_cfg["match"]
        color_cfg = class_cfg.get("color")

        matched_objects = [
            obj for obj in scene.objects
            if obj.type == "MESH" and object_matches_rule(obj, match_rule)
        ]

        for obj in matched_objects:
            matched_object_names.add(obj.name)

            # assegna class_id
            obj["class_id"] = class_id

            # assegna instance_id
            group_key = compute_instance_group_key(obj, class_name)
            if group_key not in global_instance_map:
                global_instance_map[group_key] = next_instance_id
                next_instance_id += 1

            instance_id = global_instance_map[group_key]
            obj["instance_id"] = instance_id
            obj.pass_index = instance_id

            # metadata
            if instance_id not in instance_metadata:
                instance_metadata[instance_id] = {
                    "class_name": class_name,
                    "class_id": class_id,
                    "objects": []
                }
            instance_metadata[instance_id]["objects"].append(obj.name)

            # opzionale: semantic RGB via emission
            if color_cfg:
                if color_cfg["mode"] == "random_instance":
                    rgba = resolve_instance_color(instance_id, instance_color_cache)
                else:
                    rgba = resolve_class_color(class_name, class_cfg, class_color_cache)

                if rgba is not None:
                    em_name = f"EMIT_SEG__OBJ__{class_name}__{instance_id}"
                    em_mat = get_or_create_emission_material(em_name, rgba)

                    # sostituisce TUTTI i materiali dell'oggetto
                    if len(obj.material_slots) == 0:
                        obj.data.materials.append(em_mat)
                        matched_slots.add((obj.name, 0))
                    else:
                        for slot_index, slot in enumerate(obj.material_slots):
                            slot.material = em_mat
                            matched_slots.add((obj.name, slot_index))

    # -----------------------------------------------------
    # SECONDA PASSATA: MATERIAL CLASSES
    # -----------------------------------------------------
    for class_name, class_cfg in foreground_classes.items():
        if class_cfg["mode"] != "material":
            continue

        match_rule = class_cfg["match"]
        color_cfg = class_cfg["color"]

        # colore della classe materiale
        if color_cfg["mode"] == "fixed":
            rgba = _normalize_color_value(color_cfg["value"])
        elif color_cfg["mode"] == "random":
            rgba = class_color_cache.get(class_name)
            if rgba is None:
                rgba = (random.random(), random.random(), random.random(), 1.0)
                class_color_cache[class_name] = rgba
        elif color_cfg["mode"] == "random_instance":
            raise ValueError(
                f"La classe materiale '{class_name}' usa random_instance, "
                f"ma per mode='material' non esistono istanze."
            )
        else:
            raise ValueError(f"color.mode non supportato: {color_cfg['mode']}")

        replacement_pointers = set()

        # Remap globale: copre slot, Geometry Nodes, istanze e materiali
        # incorporati nella geometria valutata. Ogni materiale originale usa
        # un'emissione distinta per consentire un ripristino uno-a-uno.
        for original_mat in source_materials:
            if not material_matches_rule(original_mat, match_rule):
                continue

            em_name = f"EMIT_SEG__MAT__{class_name}__SRC__{original_mat.name}"
            em_mat = get_or_create_emission_material(em_name, rgba)
            original_mat.user_remap(em_mat)
            material_id_remaps.append((original_mat, em_mat))
            replacement_pointers.add(em_mat.as_pointer())

        # Segna i riferimenti rimappati per evitare che il fallback background
        # li sovrascriva nella terza passata.
        for obj in scene.objects:
            if obj.type != "MESH":
                continue

            for slot_index, slot in enumerate(obj.material_slots):
                if (
                    slot.material is not None
                    and slot.material.as_pointer() in replacement_pointers
                ):
                    matched_slots.add((obj.name, slot_index))

        for _, _, input_socket in iter_scene_geometry_material_sockets(scene):
            current_mat = input_socket.default_value
            if (
                current_mat is not None
                and current_mat.as_pointer() in replacement_pointers
            ):
                matched_geometry_node_sockets.add(input_socket.as_pointer())

        for _, modifier, property_name, current_mat in (
            iter_scene_geometry_modifier_material_inputs(scene)
        ):
            if current_mat.as_pointer() in replacement_pointers:
                matched_geometry_modifier_inputs.add(
                    (modifier.as_pointer(), property_name)
                )

    # -----------------------------------------------------
    # TERZA PASSATA: BACKGROUND FALLBACK
    # -----------------------------------------------------
    if background_cfg is not None:
        color_cfg = background_cfg["color"]

        if color_cfg["mode"] == "fixed":
            rgba = _normalize_color_value(color_cfg["value"])
        elif color_cfg["mode"] == "random":
            rgba = class_color_cache.get("background")
            if rgba is None:
                rgba = (random.random(), random.random(), random.random(), 1.0)
                class_color_cache["background"] = rgba
        elif color_cfg["mode"] == "random_instance":
            raise ValueError(
                "La classe 'background' non può usare random_instance "
                "perché è un fallback globale e non ha istanze."
            )
        else:
            raise ValueError(f"color.mode non supportato: {color_cfg['mode']}")

        em_name = "EMIT_SEG__BACKGROUND"
        em_mat = get_or_create_emission_material(em_name, rgba)

        for obj in scene.objects:
            if obj.type != "MESH":
                continue

            # caso 1: oggetto già preso da una object class
            if obj.name in matched_object_names:
                continue

            # se l'oggetto non ha slot, assegna background
            if len(obj.material_slots) == 0:
                obj.data.materials.append(em_mat)
                continue

            # assegna background solo agli slot non già matchati
            for slot_index, slot in enumerate(obj.material_slots):
                if (obj.name, slot_index) in matched_slots:
                    continue
                slot.material = em_mat

        # Applica il fallback anche ai materiali assegnati dentro Geometry Nodes.
        for _, _, input_socket in iter_scene_geometry_material_sockets(scene):
            if input_socket.as_pointer() in matched_geometry_node_sockets:
                continue
            if input_socket.default_value is None:
                continue
            input_socket.default_value = em_mat

        # Gli input dell'interfaccia del node group sono salvati sul
        # modificatore e prevalgono sui default dei socket interni.
        for _, modifier, property_name, _ in (
            iter_scene_geometry_modifier_material_inputs(scene)
        ):
            modifier_key = (modifier.as_pointer(), property_name)
            if modifier_key in matched_geometry_modifier_inputs:
                continue
            modifier[property_name] = em_mat

    update_scene_geometry_nodes(scene)

    return {
        "material_snapshot": material_snapshot,
        "geometry_node_material_snapshot": geometry_node_material_snapshot,
        "geometry_modifier_material_snapshot": (
            geometry_modifier_material_snapshot
        ),
        "material_id_remaps": material_id_remaps,
        "instance_metadata": instance_metadata
    }

# =========================================================
# FAST SEGMENTATION RENDER MODE
# =========================================================

def _get_object_hide_state(obj):
    return {
        "hide_viewport": obj.hide_viewport,
        "hide_render": obj.hide_render
    }


def _set_world_black(scene):
    if scene.world is None:
        return

    scene.world.use_nodes = False
    scene.world.color = (0.0, 0.0, 0.0)


def enter_fast_segmentation_render_mode(scene=None):
    """
    Salva lo stato corrente del render e imposta una modalità
    ultra-leggera per la segmentazione.

    Obiettivo:
    - solo emission flat
    - niente HDRI / world lighting
    - niente ombre
    - niente bloom / SSR / AO / volumetric
    - sample minimi
    - niente depth pass
    """
    if scene is None:
        scene = bpy.context.scene

    view_layer = bpy.context.view_layer

    state = {
        "render_engine": scene.render.engine,
        "film_transparent": scene.render.film_transparent,
        "view_layer_use_pass_z": view_layer.use_pass_z,
        "world_exists": scene.world is not None,
        "world_use_nodes": scene.world.use_nodes if scene.world else None,
        "world_color": tuple(scene.world.color) if scene.world else None,
        "light_states": {},
        "eevee": {}
    }

    # salva stato luci
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.data is not None:
            state["light_states"][obj.name] = {
                "energy": obj.data.energy,
                "hide_render": obj.hide_render,
            }

    # -----------------------------------------------------
    # ENGINE-SPECIFIC SETTINGS
    # -----------------------------------------------------
    engine = scene.render.engine

    # Blender 4.x / Eevee Next usa comunque scene.eevee
    if hasattr(scene, "eevee"):
        eevee = scene.eevee

        eevee_keys = [
            "taa_render_samples",
            "taa_samples",
            "use_shadows",
            "use_gtao",
            "use_bloom",
            "use_ssr",
            "use_ssr_refraction",
            "use_motion_blur",
            "use_volumetric_lights",
            "use_volumetric_shadows",
            "use_soft_shadows",
        ]

        for key in eevee_keys:
            if hasattr(eevee, key):
                state["eevee"][key] = getattr(eevee, key)

        # settaggi minimali
        if hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = 2
        if hasattr(eevee, "taa_samples"):
            eevee.taa_samples = 2

        if hasattr(eevee, "use_shadows"):
            eevee.use_shadows = False
        if hasattr(eevee, "use_gtao"):
            eevee.use_gtao = False
        if hasattr(eevee, "use_bloom"):
            eevee.use_bloom = False
        if hasattr(eevee, "use_ssr"):
            eevee.use_ssr = False
        if hasattr(eevee, "use_ssr_refraction"):
            eevee.use_ssr_refraction = False
        if hasattr(eevee, "use_motion_blur"):
            eevee.use_motion_blur = False
        if hasattr(eevee, "use_volumetric_lights"):
            eevee.use_volumetric_lights = False
        if hasattr(eevee, "use_volumetric_shadows"):
            eevee.use_volumetric_shadows = False
        if hasattr(eevee, "use_soft_shadows"):
            eevee.use_soft_shadows = False

    # -----------------------------------------------------
    # WORLD / HDRI OFF
    # -----------------------------------------------------
    _set_world_black(scene)

    # -----------------------------------------------------
    # LUCI OFF
    # -----------------------------------------------------
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.data is not None:
            obj.data.energy = 0.0
            obj.hide_render = True

    # -----------------------------------------------------
    # PASS INUTILI OFF
    # -----------------------------------------------------
    view_layer.use_pass_z = False

    # opzionale
    scene.render.film_transparent = False

    return state


def exit_fast_segmentation_render_mode(scene=None, state=None):
    """
    Ripristina lo stato salvato da enter_fast_segmentation_render_mode().
    """
    if scene is None:
        scene = bpy.context.scene

    if state is None:
        return

    view_layer = bpy.context.view_layer

    # render base
    if "render_engine" in state:
        scene.render.engine = state["render_engine"]

    if "film_transparent" in state:
        scene.render.film_transparent = state["film_transparent"]

    if "view_layer_use_pass_z" in state:
        view_layer.use_pass_z = state["view_layer_use_pass_z"]

    # world
    if scene.world is not None and state.get("world_exists"):
        if "world_use_nodes" in state and state["world_use_nodes"] is not None:
            scene.world.use_nodes = state["world_use_nodes"]
        if "world_color" in state and state["world_color"] is not None:
            scene.world.color = state["world_color"]

    # eevee
    if hasattr(scene, "eevee"):
        eevee = scene.eevee
        for key, value in state.get("eevee", {}).items():
            if hasattr(eevee, key):
                setattr(eevee, key, value)

    # lights
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.name in state.get("light_states", {}):
            saved = state["light_states"][obj.name]
            if obj.data is not None:
                obj.data.energy = saved["energy"]
            obj.hide_render = saved["hide_render"]
