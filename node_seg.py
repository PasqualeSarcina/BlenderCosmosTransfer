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
    crosswalk_node = ng.nodes["Set Material.002"]

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
            (237, 94, 5)        # arancione
        ),

        "04_Straight_Left_Arrow": (
            "SEG_arrow_straight_left",
            (255, 255, 0)        # giallo
        ),

        "05_Straight_Right_Arrow": (
            "SEG_arrow_straight_right",
            (0, 255, 128)        # verde acqua
        ),
    }

    # -------------------------------------------------
    # SNAPSHOT
    # -------------------------------------------------

    crosswalk_socket = crosswalk_node.inputs["Material"]

    state = {
        "set_material_005_mute": set_direction_material.mute,
        "arrow_materials": {},

        # Salviamo il valore originale
        "crosswalk_old_material": crosswalk_socket.default_value,

        # Salviamo anche l'eventuale collegamento
        "crosswalk_link": None,
    }

    # Se Material è collegato, salviamo da dove arriva
    if crosswalk_socket.is_linked:
        link = crosswalk_socket.links[0]

        state["crosswalk_link"] = {
            "from_socket": link.from_socket,
            "to_socket": link.to_socket,
        }

    # Salva materiali originali delle frecce
    for obj_name in arrow_colors.keys():

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            print("[SEG GN] Oggetto non trovato:", obj_name)
            continue

        state["arrow_materials"][obj_name] = list(
            obj.data.materials
        )

    # =================================================
    # CROSSWALK
    # =================================================

    crosswalk_mat = get_seg_material(
        "SEG_crosswalk",
        (156, 7, 224)           # viola
    )

    # Se il socket è collegato a Crosswalk Material,
    # rimuoviamo temporaneamente il collegamento
    if crosswalk_socket.is_linked:

        for link in list(crosswalk_socket.links):
            ng.links.remove(link)

    # Ora possiamo assegnare direttamente il nostro
    # materiale Emission
    crosswalk_socket.default_value = crosswalk_mat

    print(
        "[SEG GN] Crosswalk -> SEG_crosswalk",
        "(170, 80, 255)"
    )

    # =================================================
    # FRECCE
    # =================================================

    # Disattiva Set Material globale delle frecce
    set_direction_material.mute = True

    # Assegna un Emission diverso a ogni freccia
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