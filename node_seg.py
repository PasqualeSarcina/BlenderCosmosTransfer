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

    # STOP LINE
    lane_material_node = ng.nodes["Set Material.004"]
    stop_source_node = ng.nodes["Flip Faces"]

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

        # stop line
        "stop_source_links": [],
        "lane_output_links": [],
        "stop_temp_nodes": [],

        # cars
        "car_materials": {},
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
        # AUTO
        # =================================================

        car_mat = get_seg_material(
            "SEG_car",
            (0, 0, 255)
        )

        car_name_patterns = [
            "low poly car",
            "parking car",
            "car body",
            "car front wheels",
            "car back wheels",
        ]

        for obj in bpy.data.objects:

            name_lower = obj.name.lower()

            if not any(
                    pattern in name_lower
                    for pattern in car_name_patterns
            ):
                continue

            if not hasattr(obj.data, "materials"):
                continue

            state["car_materials"][obj.name] = list(
                obj.data.materials
            )

            if len(obj.data.materials) == 0:

                obj.data.materials.append(car_mat)

            else:

                for i in range(len(obj.data.materials)):
                    obj.data.materials[i] = car_mat

            print(
                "[SEG GN] CAR:",
                obj.name,
                "-> BLUE"
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
    # STOP LINE
    # =================================================

    stop_mat = get_seg_material(
        "SEG_stop_line",
        (255, 255, 255)  # bianco, per ora
    )

    # Output di Flip Faces.
    # Normalmente si chiama "Mesh".
    stop_output = stop_source_node.outputs.get("Mesh")

    if stop_output is None:
        raise RuntimeError(
            "[SEG GN] Output Mesh di Flip Faces non trovato"
        )

    # -------------------------------------------------
    # 1. SALVA E SCOLLEGA IL RAMO STOP
    # -------------------------------------------------

    for link in list(stop_output.links):
        state["stop_source_links"].append({
            "from_socket": link.from_socket,
            "to_socket": link.to_socket,
        })

        ng.links.remove(link)

    # -------------------------------------------------
    # 2. CREA SET MATERIAL DEDICATO
    # -------------------------------------------------

    stop_set_mat = ng.nodes.new(
        type="GeometryNodeSetMaterial"
    )

    stop_set_mat.name = "__SEG_STOP_SET_MATERIAL__"
    stop_set_mat.label = "SEG Stop Line"

    stop_set_mat.inputs["Material"].default_value = stop_mat

    ng.links.new(
        stop_output,
        stop_set_mat.inputs["Geometry"]
    )

    state["stop_temp_nodes"].append(
        stop_set_mat.name
    )

    # -------------------------------------------------
    # 3. INTERCETTA L'USCITA DI SET MATERIAL.004
    # -------------------------------------------------

    lane_output = lane_material_node.outputs.get("Geometry")

    if lane_output is None:
        raise RuntimeError(
            "[SEG GN] Output Geometry di Set Material.004 non trovato"
        )

    for link in list(lane_output.links):
        state["lane_output_links"].append({
            "from_socket": link.from_socket,
            "to_socket": link.to_socket,
        })

        ng.links.remove(link)

    # -------------------------------------------------
    # 4. CREA JOIN DOPO SET MATERIAL.004
    # -------------------------------------------------

    stop_join = ng.nodes.new(
        type="GeometryNodeJoinGeometry"
    )

    stop_join.name = "__SEG_STOP_REJOIN__"
    stop_join.label = "SEG Stop Rejoin"

    state["stop_temp_nodes"].append(
        stop_join.name
    )

    # Lane normali, già passate da Set Material.004
    ng.links.new(
        lane_output,
        stop_join.inputs["Geometry"]
    )

    # Stop line, con il proprio materiale
    ng.links.new(
        stop_set_mat.outputs["Geometry"],
        stop_join.inputs["Geometry"]
    )

    # -------------------------------------------------
    # 5. RICOLLEGA IL FLUSSO ORIGINALE
    # -------------------------------------------------

    for old_link in state["lane_output_links"]:
        ng.links.new(
            stop_join.outputs["Geometry"],
            old_link["to_socket"]
        )

    print("[SEG GN] Stop line -> SEG_stop_line")

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