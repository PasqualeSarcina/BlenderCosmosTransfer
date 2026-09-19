import bpy

def enable_crosswalk_wsm():

    NODE_GROUP_NAME = "street layout"

    CURVE_TO_MESH_NODE = "Curve to Mesh"
    EXTRUDE_NODE = "Extrude Mesh.004"

    # Set Material globale che rende bianche le lane markings
    LANE_SET_MATERIAL_NODE = "Set Material.004"

    CROSSWALK_SET_LABEL = "WSM_CROSSWALK_PURPLE"
    CROSSWALK_REJOIN_LABEL = "WSM_CROSSWALK_REJOIN"

    MATERIAL_NAME = "WSM_CROSSWALK_PURPLE_MAT"

    # [139, 93, 255]
    PURPLE = (
        139 / 255.0,
        93 / 255.0,
        255 / 255.0,
        1.0,
    )

    tree = bpy.data.node_groups.get(NODE_GROUP_NAME)

    if tree is None:
        raise RuntimeError(
            f"Node group '{NODE_GROUP_NAME}' non trovato"
        )

    curve_to_mesh = tree.nodes.get(CURVE_TO_MESH_NODE)
    extrude = tree.nodes.get(EXTRUDE_NODE)
    lane_set = tree.nodes.get(LANE_SET_MATERIAL_NODE)

    if curve_to_mesh is None:
        raise RuntimeError("Curve to Mesh non trovato")

    if extrude is None:
        raise RuntimeError("Extrude Mesh.004 non trovato")

    if lane_set is None:
        raise RuntimeError("Set Material.004 non trovato")

    # =========================================================
    # 1. UNISCE LE STRISCE
    # =========================================================

    curve_output = curve_to_mesh.outputs.get("Mesh")
    extrude_input = extrude.inputs.get("Mesh")

    if curve_output is None or extrude_input is None:
        raise RuntimeError(
            "Socket Mesh del crosswalk non trovato"
        )

    if not extrude_input.is_linked:
        raise RuntimeError(
            "Extrude Mesh.004 non ha input collegato"
        )

    # Salva:
    # Scale Elements -> Extrude Mesh
    original_extrude_link = extrude_input.links[0]
    original_extrude_from_socket = (
        original_extrude_link.from_socket
    )

    tree.links.remove(original_extrude_link)

    # Curve to Mesh -> Extrude Mesh
    tree.links.new(
        curve_output,
        extrude_input,
    )

    # =========================================================
    # 2. CREA MATERIALE VIOLA EMISSIVO
    # =========================================================

    material = bpy.data.materials.get(MATERIAL_NAME)

    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)

    material.use_nodes = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    nodes.clear()

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = PURPLE
    emission.inputs["Strength"].default_value = 1.0

    output = nodes.new("ShaderNodeOutputMaterial")

    links.new(
        emission.outputs["Emission"],
        output.inputs["Surface"],
    )

    material.diffuse_color = PURPLE

    # =========================================================
    # 3. CREA SET MATERIAL DOPO EXTRUDE
    # =========================================================

    crosswalk_set = None

    for node in tree.nodes:
        if (
            node.bl_idname == "GeometryNodeSetMaterial"
            and node.label == CROSSWALK_SET_LABEL
        ):
            crosswalk_set = node
            break

    if crosswalk_set is None:
        crosswalk_set = tree.nodes.new(
            "GeometryNodeSetMaterial"
        )

        crosswalk_set.name = "WSM Crosswalk Purple"
        crosswalk_set.label = CROSSWALK_SET_LABEL

        crosswalk_set.location = (
            extrude.location.x + 250,
            extrude.location.y,
        )

    crosswalk_set.inputs["Material"].default_value = material

    # =========================================================
    # 4. SCOLLEGA IL CROSSWALK DAL VECCHIO FLUSSO
    # =========================================================

    extrude_output = extrude.outputs.get("Mesh")

    if extrude_output is None:
        raise RuntimeError(
            "Output Mesh di Extrude Mesh.004 non trovato"
        )

    original_crosswalk_downstream = []

    for link in list(extrude_output.links):

        # Salviamo dove andava prima il crosswalk
        original_crosswalk_downstream.append(
            link.to_socket
        )

        tree.links.remove(link)

    # Extrude -> nuovo materiale viola
    crosswalk_geometry_input = (
        crosswalk_set.inputs["Geometry"]
    )

    # pulizia
    for link in list(crosswalk_geometry_input.links):
        tree.links.remove(link)

    tree.links.new(
        extrude_output,
        crosswalk_geometry_input,
    )

    # =========================================================
    # 5. CREA JOIN DOPO SET MATERIAL.004
    #
    # Set Material.004 --------\
    #                           Join -> resto grafo
    # Crosswalk viola ----------/
    # =========================================================

    rejoin = None

    for node in tree.nodes:
        if (
            node.bl_idname == "GeometryNodeJoinGeometry"
            and node.label == CROSSWALK_REJOIN_LABEL
        ):
            rejoin = node
            break

    if rejoin is None:
        rejoin = tree.nodes.new(
            "GeometryNodeJoinGeometry"
        )

        rejoin.name = "WSM Crosswalk Rejoin"
        rejoin.label = CROSSWALK_REJOIN_LABEL

        rejoin.location = (
            lane_set.location.x + 300,
            lane_set.location.y,
        )

    lane_output = lane_set.outputs["Geometry"]

    # =========================================================
    # 6. SALVA IL DOWNSTREAM DI SET MATERIAL.004
    # =========================================================

    lane_downstream = []

    for link in list(lane_output.links):

        if link.to_node == rejoin:
            continue

        lane_downstream.append(
            link.to_socket
        )

        tree.links.remove(link)

    # Pulisce il Join
    for socket in rejoin.inputs:
        for link in list(socket.links):
            tree.links.remove(link)

    # =========================================================
    # 7. REJOIN
    # =========================================================

    tree.links.new(
        lane_output,
        rejoin.inputs["Geometry"],
    )

    tree.links.new(
        crosswalk_set.outputs["Geometry"],
        rejoin.inputs["Geometry"],
    )

    # Join -> vecchio downstream
    for socket in lane_downstream:
        tree.links.new(
            rejoin.outputs["Geometry"],
            socket,
        )

    bpy.context.view_layer.update()

    print(
        "WSM crosswalk:",
        "unito e reinserito DOPO Set Material.004 |",
        "RGB [139, 93, 255]"
    )

    return {
        "tree": tree,

        "extrude_input": extrude_input,
        "original_extrude_from_socket":
            original_extrude_from_socket,

        "extrude_output": extrude_output,
        "original_crosswalk_downstream":
            original_crosswalk_downstream,

        "lane_output": lane_output,
        "lane_downstream": lane_downstream,

        "crosswalk_set": crosswalk_set,
        "rejoin": rejoin,
    }


def disable_crosswalk_wsm(state):

    if state is None:
        return

    tree = state["tree"]

    extrude_input = state["extrude_input"]
    extrude_output = state["extrude_output"]

    lane_output = state["lane_output"]

    crosswalk_set = state["crosswalk_set"]
    rejoin = state["rejoin"]

    # =========================================================
    # 1. RIMUOVE IL REJOIN TEMPORANEO
    # =========================================================

    # Rimuove le uscite del Join
    for link in list(rejoin.outputs["Geometry"].links):
        tree.links.remove(link)

    # Rimuove gli ingressi del Join
    for socket in rejoin.inputs:
        for link in list(socket.links):
            tree.links.remove(link)

    # =========================================================
    # 2. RIPRISTINA SET MATERIAL.004 -> downstream
    # =========================================================

    for socket in state["lane_downstream"]:
        tree.links.new(
            lane_output,
            socket,
        )

    # =========================================================
    # 3. RIMUOVE Extrude -> Set Material viola
    # =========================================================

    for link in list(extrude_output.links):
        tree.links.remove(link)

    # Ripristina il vecchio downstream del crosswalk
    for socket in state["original_crosswalk_downstream"]:
        tree.links.new(
            extrude_output,
            socket,
        )

    # =========================================================
    # 4. RIPRISTINA
    # Scale Elements -> Extrude Mesh
    # =========================================================

    for link in list(extrude_input.links):
        tree.links.remove(link)

    tree.links.new(
        state["original_extrude_from_socket"],
        extrude_input,
    )

    # =========================================================
    # 5. ELIMINA I NODI TEMPORANEI
    # =========================================================

    tree.nodes.remove(crosswalk_set)
    tree.nodes.remove(rejoin)

    bpy.context.view_layer.update()

    print("WSM crosswalk originale ripristinato")


def _get_wsm_emission_material(name, rgb):
    """
    Crea/aggiorna un materiale emissivo con colore RGB 0..255.
    """

    color = (
        rgb[0] / 255.0,
        rgb[1] / 255.0,
        rgb[2] / 255.0,
        1.0,
    )

    material = bpy.data.materials.get(name)

    if material is None:
        material = bpy.data.materials.new(name)

    material.use_nodes = True
    material.diffuse_color = color

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    nodes.clear()

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0

    output = nodes.new("ShaderNodeOutputMaterial")

    links.new(
        emission.outputs["Emission"],
        output.inputs["Surface"],
    )

    return material


def enable_wait_lines_wsm():

    NODE_GROUP_NAME = "street layout"

    STOP_BRANCH_NODE = "Flip Faces"
    STOP_BRANCH_OUTPUT = "Mesh"

    LANE_SET_MATERIAL_NODE = "Set Material.004"

    WAIT_SET_LABEL = "WSM_WAIT_LINES_SET"
    WAIT_REJOIN_LABEL = "WSM_WAIT_LINES_REJOIN"

    WAIT_MATERIAL_NAME = "WSM_WAIT_LINES_GREEN"
    WAIT_RGB = (108, 179, 59)

    tree = bpy.data.node_groups.get(NODE_GROUP_NAME)

    if tree is None:
        raise RuntimeError(
            f"Node group '{NODE_GROUP_NAME}' non trovato"
        )

    stop_branch = tree.nodes.get(STOP_BRANCH_NODE)

    if stop_branch is None:
        raise RuntimeError(
            f"Nodo '{STOP_BRANCH_NODE}' non trovato"
        )

    stop_output = stop_branch.outputs.get(
        STOP_BRANCH_OUTPUT
    )

    if stop_output is None:
        raise RuntimeError(
            f"Output '{STOP_BRANCH_OUTPUT}' non trovato"
        )

    lane_set = tree.nodes.get(
        LANE_SET_MATERIAL_NODE
    )

    if lane_set is None:
        raise RuntimeError(
            f"Nodo '{LANE_SET_MATERIAL_NODE}' non trovato"
        )

    # =========================================================
    # MATERIALE VERDE
    # =========================================================

    wait_material = _get_wsm_emission_material(
        WAIT_MATERIAL_NAME,
        WAIT_RGB,
    )

    # =========================================================
    # SET MATERIAL DEDICATO
    # =========================================================

    wait_set = tree.nodes.new(
        "GeometryNodeSetMaterial"
    )

    wait_set.name = "WSM Wait Lines Material"
    wait_set.label = WAIT_SET_LABEL

    wait_set.location = (
        stop_branch.location.x + 250,
        stop_branch.location.y,
    )

    wait_set.inputs["Material"].default_value = (
        wait_material
    )

    # =========================================================
    # SALVA DOWNSTREAM ORIGINALE DELLE WAIT LINES
    # =========================================================

    original_wait_downstream = []

    for link in list(stop_output.links):

        original_wait_downstream.append(
            link.to_socket
        )

        tree.links.remove(link)

    # Flip Faces -> materiale verde
    tree.links.new(
        stop_output,
        wait_set.inputs["Geometry"],
    )

    # =========================================================
    # REJOIN DOPO Set Material.004
    # =========================================================

    rejoin = tree.nodes.new(
        "GeometryNodeJoinGeometry"
    )

    rejoin.name = "WSM Wait Lines Rejoin"
    rejoin.label = WAIT_REJOIN_LABEL

    rejoin.location = (
        lane_set.location.x + 300,
        lane_set.location.y,
    )

    lane_output = lane_set.outputs["Geometry"]

    # Salva il downstream corrente.
    # Può già essere il rejoin dei crosswalk.
    lane_downstream = []

    for link in list(lane_output.links):

        lane_downstream.append(
            link.to_socket
        )

        tree.links.remove(link)

    # normale segnaletica bianca
    tree.links.new(
        lane_output,
        rejoin.inputs["Geometry"],
    )

    # wait lines verdi
    tree.links.new(
        wait_set.outputs["Geometry"],
        rejoin.inputs["Geometry"],
    )

    # ripristina il resto del grafo
    for socket in lane_downstream:

        tree.links.new(
            rejoin.outputs["Geometry"],
            socket,
        )

    bpy.context.view_layer.update()

    print(
        "WSM wait lines abilitate:",
        "RGB [108, 179, 59]"
    )

    return {
        "tree": tree,
        "stop_output": stop_output,
        "original_wait_downstream":
            original_wait_downstream,
        "lane_output": lane_output,
        "lane_downstream": lane_downstream,
        "wait_set": wait_set,
        "rejoin": rejoin,
    }


def disable_wait_lines_wsm(state):

    if state is None:
        return

    tree = state["tree"]

    stop_output = state["stop_output"]
    lane_output = state["lane_output"]

    wait_set = state["wait_set"]
    rejoin = state["rejoin"]

    # ---------------------------------------------------------
    # Rimuove il rejoin temporaneo
    # ---------------------------------------------------------

    for link in list(rejoin.outputs["Geometry"].links):
        tree.links.remove(link)

    for socket in rejoin.inputs:
        for link in list(socket.links):
            tree.links.remove(link)

    # ---------------------------------------------------------
    # Ripristina Set Material.004 -> downstream
    # ---------------------------------------------------------

    for socket in state["lane_downstream"]:
        tree.links.new(
            lane_output,
            socket,
        )

    # ---------------------------------------------------------
    # Rimuove Flip Faces -> materiale verde
    # ---------------------------------------------------------

    for link in list(stop_output.links):
        tree.links.remove(link)

    # ---------------------------------------------------------
    # Ripristina il ramo originale wait lines
    # ---------------------------------------------------------

    for socket in state["original_wait_downstream"]:
        tree.links.new(
            stop_output,
            socket,
        )

    # ---------------------------------------------------------
    # Elimina nodi temporanei
    # ---------------------------------------------------------

    tree.nodes.remove(wait_set)
    tree.nodes.remove(rejoin)

    bpy.context.view_layer.update()

    print("WSM wait lines ripristinate")


def enable_centerline_wsm():

    NODE_GROUP_NAME = "street layout"

    SEPARATE_NODE = "Separate Geometry.001"
    JOIN_NODE = "Join Geometry.001"
    FINAL_MATERIAL_NODE = "Set Material.004"

    ATTRIBUTE_NAME = "WSM_CENTERLINE"

    YELLOW_RGB = (255, 234, 0)

    tree = bpy.data.node_groups.get(
        NODE_GROUP_NAME
    )

    if tree is None:
        raise RuntimeError(
            f"Node group '{NODE_GROUP_NAME}' non trovato"
        )

    separate = tree.nodes.get(SEPARATE_NODE)
    join = tree.nodes.get(JOIN_NODE)
    final_material = tree.nodes.get(
        FINAL_MATERIAL_NODE
    )

    if separate is None:
        raise RuntimeError(
            f"{SEPARATE_NODE} non trovato"
        )

    if join is None:
        raise RuntimeError(
            f"{JOIN_NODE} non trovato"
        )

    if final_material is None:
        raise RuntimeError(
            f"{FINAL_MATERIAL_NODE} non trovato"
        )

    # =========================================================
    # TROVA:
    #
    # Separate Geometry.001 [Inverted]
    #             ↓
    #       Join Geometry.001
    # =========================================================

    target_link = None

    for link in list(tree.links):

        if (
            link.from_node == separate
            and link.from_socket.name == "Inverted"
            and link.to_node == join
        ):
            target_link = link
            break

    if target_link is None:
        raise RuntimeError(
            "Link Separate Geometry.001 [Inverted] "
            "-> Join Geometry.001 non trovato"
        )

    join_socket = target_link.to_socket

    tree.links.remove(target_link)

    # =========================================================
    # STORE NAMED ATTRIBUTE
    # =========================================================

    store = tree.nodes.new(
        "GeometryNodeStoreNamedAttribute"
    )

    store.name = "WSM Store Centerline"
    store.label = "WSM CENTERLINE ATTRIBUTE"

    store.data_type = "BOOLEAN"
    store.domain = "POINT"

    store.inputs["Name"].default_value = (
        ATTRIBUTE_NAME
    )

    store.inputs["Value"].default_value = True

    store.location = (
        separate.location.x + 250,
        separate.location.y - 150,
    )

    tree.links.new(
        separate.outputs["Inverted"],
        store.inputs["Geometry"],
    )

    tree.links.new(
        store.outputs["Geometry"],
        join_socket,
    )

    # =========================================================
    # READ NAMED ATTRIBUTE
    # =========================================================

    named = tree.nodes.new(
        "GeometryNodeInputNamedAttribute"
    )

    named.name = "WSM Read Centerline"
    named.label = "WSM READ CENTERLINE"

    named.data_type = "BOOLEAN"

    named.inputs["Name"].default_value = (
        ATTRIBUTE_NAME
    )

    # =========================================================
    # MATERIALE GIALLO
    # =========================================================

    yellow_material = _get_wsm_emission_material(
        "WSM_CENTERLINE_YELLOW",
        YELLOW_RGB,
    )

    # =========================================================
    # SET MATERIAL FINALE
    # =========================================================

    center_set = tree.nodes.new(
        "GeometryNodeSetMaterial"
    )

    center_set.name = "WSM Centerline Material"
    center_set.label = "WSM CENTERLINE YELLOW"

    center_set.inputs["Material"].default_value = (
        yellow_material
    )

    center_set.location = (
        final_material.location.x + 250,
        final_material.location.y,
    )

    # Solo la geometria con attributo WSM_CENTERLINE
    tree.links.new(
        named.outputs["Attribute"],
        center_set.inputs["Selection"],
    )

    # =========================================================
    # INSERISCE IL SET MATERIAL DOPO Set Material.004
    # =========================================================

    final_output = final_material.outputs["Geometry"]

    final_downstream = []

    for link in list(final_output.links):

        final_downstream.append(
            link.to_socket
        )

        tree.links.remove(link)

    tree.links.new(
        final_output,
        center_set.inputs["Geometry"],
    )

    for socket in final_downstream:

        tree.links.new(
            center_set.outputs["Geometry"],
            socket,
        )

    bpy.context.view_layer.update()

    print(
        "WSM mezzeria abilitata:",
        "RGB [235, 213, 70]"
    )

    return {
        "tree": tree,
        "separate": separate,
        "join_socket": join_socket,
        "store": store,
        "named": named,
        "center_set": center_set,
        "final_output": final_output,
        "final_downstream": final_downstream,
    }


def disable_centerline_wsm(state):

    if state is None:
        return

    tree = state["tree"]

    center_set = state["center_set"]
    final_output = state["final_output"]

    # =========================================================
    # Rimuove il Set Material giallo
    # =========================================================

    for link in list(
        center_set.outputs["Geometry"].links
    ):
        tree.links.remove(link)

    # Ripristina Set Material.004 -> downstream precedente
    for socket in state["final_downstream"]:

        tree.links.new(
            final_output,
            socket,
        )

    # =========================================================
    # Ripristina il ramo:
    #
    # Separate Geometry.001 [Inverted]
    #               ↓
    #       Join Geometry.001
    # =========================================================

    store = state["store"]

    for link in list(
        store.outputs["Geometry"].links
    ):
        tree.links.remove(link)

    tree.links.new(
        state["separate"].outputs["Inverted"],
        state["join_socket"],
    )

    # =========================================================
    # Elimina nodi temporanei
    # =========================================================

    tree.nodes.remove(center_set)
    tree.nodes.remove(state["named"])
    tree.nodes.remove(store)

    bpy.context.view_layer.update()

    print("WSM mezzeria ripristinata")


def enable_arrows_wsm():
    """
    Colora tutte le frecce stradali con il colore WSM
    road_markings = [20, 254, 185].

    Disattiva temporaneamente Set Material.005 perché,
    altrimenti, il materiale globale delle frecce
    sovrascriverebbe quello degli oggetti sorgente.
    """

    NODE_GROUP_NAME = "street layout"
    DIRECTION_SET_MATERIAL_NODE = "Set Material.005"

    ARROW_OBJECTS = [
        "01_Left_Arrow",
        "02_Straight_Arrow",
        "03_Right_Arrow",
        "04_Straight_Left_Arrow",
        "05_Straight_Right_Arrow",
    ]

    ROAD_MARKINGS_RGB = (20, 254, 185)

    tree = bpy.data.node_groups.get(NODE_GROUP_NAME)

    if tree is None:
        raise RuntimeError(
            f"Node group '{NODE_GROUP_NAME}' non trovato"
        )

    set_direction_material = tree.nodes.get(
        DIRECTION_SET_MATERIAL_NODE
    )

    if set_direction_material is None:
        raise RuntimeError(
            f"Nodo '{DIRECTION_SET_MATERIAL_NODE}' non trovato"
        )

    # ---------------------------------------------------------
    # SALVA STATO ORIGINALE
    # ---------------------------------------------------------

    state = {
        "set_material_mute":
            set_direction_material.mute,

        "arrow_materials": {},
    }

    # ---------------------------------------------------------
    # MATERIALE TURCHESE
    # ---------------------------------------------------------

    turquoise_material = _get_wsm_emission_material(
        "WSM_ROAD_MARKINGS_TURQUOISE",
        ROAD_MARKINGS_RGB,
    )

    # ---------------------------------------------------------
    # DISATTIVA IL SET MATERIAL GLOBALE
    # ---------------------------------------------------------

    set_direction_material.mute = True

    # ---------------------------------------------------------
    # ASSEGNA IL TURCHESE A TUTTE LE FRECCE
    # ---------------------------------------------------------

    for obj_name in ARROW_OBJECTS:

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            print(
                "[WSM] Freccia non trovata:",
                obj_name
            )
            continue

        if not hasattr(obj.data, "materials"):
            print(
                "[WSM] Oggetto senza materials:",
                obj_name
            )
            continue

        # salva tutti i materiali originali
        state["arrow_materials"][obj_name] = list(
            obj.data.materials
        )

        # sostituisce tutto con il materiale WSM
        obj.data.materials.clear()
        obj.data.materials.append(
            turquoise_material
        )

        print(
            "[WSM]",
            obj_name,
            "-> road_markings",
            ROAD_MARKINGS_RGB
        )

    bpy.context.view_layer.update()

    print(
        "[WSM] Set Material.005 -> MUTE | "
        "frecce -> [20, 254, 185]"
    )

    return state

def disable_arrows_wsm(state):
    """
    Ripristina i materiali originali delle frecce
    e lo stato originale di Set Material.005.
    """

    if state is None:
        return

    tree = bpy.data.node_groups.get(
        "street layout"
    )

    if tree is None:
        return

    set_direction_material = tree.nodes.get(
        "Set Material.005"
    )

    # ---------------------------------------------------------
    # RIPRISTINA I MATERIALI ORIGINALI
    # ---------------------------------------------------------

    for obj_name, original_materials in (
        state["arrow_materials"].items()
    ):

        obj = bpy.data.objects.get(obj_name)

        if obj is None:
            continue

        if not hasattr(obj.data, "materials"):
            continue

        obj.data.materials.clear()

        for material in original_materials:
            obj.data.materials.append(material)

    # ---------------------------------------------------------
    # RIPRISTINA Set Material.005
    # ---------------------------------------------------------

    if set_direction_material is not None:
        set_direction_material.mute = (
            state["set_material_mute"]
        )

    bpy.context.view_layer.update()

    print("[WSM] Frecce originali ripristinate")