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