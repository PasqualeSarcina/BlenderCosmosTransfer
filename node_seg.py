import bpy

def set_material_color(mat, rgb):
    color = (
        rgb[0] / 255.0,
        rgb[1] / 255.0,
        rgb[2] / 255.0,
        1.0
    )

    mat.diffuse_color = color

    if mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")

        if bsdf:
            bsdf.inputs["Base Color"].default_value = color


def get_seg_material(name, rgb):

    mat = bpy.data.materials.get(name)

    if mat is None:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True

    # RGB 0-255 -> 0-1
    color = (
        rgb[0] / 255.0,
        rgb[1] / 255.0,
        rgb[2] / 255.0,
        1.0
    )

    mat.diffuse_color = color

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Ricostruiamo completamente il materiale
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")

    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0

    links.new(
        emission.outputs["Emission"],
        output.inputs["Surface"]
    )

    return mat

def apply_citygen_geometry_overrides():

    ng = bpy.data.node_groups["street layout"]
    set_direction_material = ng.nodes["Set Material.005"]

    # -------------------------------------------------
    # FRECCE + COLORI
    # -------------------------------------------------

    arrow_colors = {
        "01_Left_Arrow": (
            "SEG_arrow_left",
            (255, 0, 0)          # rosso
        ),

        "02_Straight_Arrow": (
            "SEG_arrow_straight",
            (0, 255, 255)        # ciano
        ),

        "03_Right_Arrow": (
            "SEG_arrow_right",
            (255, 128, 0)        # arancione
        ),

        "04_Straight_Left_Arrow": (
            "SEG_arrow_straight_left",
            (255, 255, 0)        # giallo
        ),

        "05_Straight_Right_Arrow": (
            "SEG_arrow_straight_right",
            (0, 255, 128)       # verde acqua
        ),
    }

    # -------------------------------------------------
    # SNAPSHOT
    # -------------------------------------------------

    state = {
        "set_material_005_mute": set_direction_material.mute,
        "arrow_materials": {}
    }

    for obj_name in arrow_colors.keys():

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            print("[SEG GN] Oggetto non trovato:", obj_name)
            continue

        state["arrow_materials"][obj_name] = list(
            obj.data.materials
        )

    # -------------------------------------------------
    # DISATTIVA IL MATERIALE GLOBALE
    # -------------------------------------------------

    set_direction_material.mute = True

    # -------------------------------------------------
    # ASSEGNA UN EMISSION DIVERSO A OGNI FRECCIA
    # -------------------------------------------------

    for obj_name, (material_name, color) in arrow_colors.items():

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            continue

        mat = get_seg_material(
            material_name,
            color
        )

        obj.data.materials.clear()
        obj.data.materials.append(mat)

        print(
            "[SEG GN]",
            obj_name,
            "->",
            material_name,
            color
        )

    bpy.context.view_layer.update()

    print("[SEG GN] Set Material.005 -> MUTE")

    return state



def restore_citygen_geometry_overrides(state):

    ng = bpy.data.node_groups.get("street layout")

    if ng:
        node = ng.nodes.get("Set Material.005")

        if node:
            node.mute = state["set_material_005_mute"]

    for obj_name, materials in state["arrow_materials"].items():

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            continue

        obj.data.materials.clear()

        for mat in materials:
            obj.data.materials.append(mat)

    print("[SEG GN] restored")