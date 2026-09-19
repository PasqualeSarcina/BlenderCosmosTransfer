import bpy

def enable_crosswalk_wsm():
    """
    Unisce temporaneamente le zebra crossings e assegna
    direttamente il colore WSM viola hardcoded.

    Ritorna lo stato necessario per ripristinare il grafo.
    """

    NODE_GROUP_NAME = "street layout"
    CURVE_TO_MESH_NODE = "Curve to Mesh"
    EXTRUDE_NODE = "Extrude Mesh.004"
    CROSSWALK_SET_MATERIAL_NODE = "Set Material.002"
    CROSSWALK_MATERIAL_NAME = "WSM_CROSSWALK_PURPLE"

    # RGB [139, 93, 255] normalizzato 0..1
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
    crosswalk_set = tree.nodes.get(CROSSWALK_SET_MATERIAL_NODE)

    if curve_to_mesh is None:
        raise RuntimeError(
            f"Nodo '{CURVE_TO_MESH_NODE}' non trovato"
        )

    if extrude is None:
        raise RuntimeError(
            f"Nodo '{EXTRUDE_NODE}' non trovato"
        )

    if crosswalk_set is None:
        raise RuntimeError(
            f"Nodo '{CROSSWALK_SET_MATERIAL_NODE}' non trovato"
        )

    # ---------------------------------------------------------
    # 1. UNISCE LE STRISCE
    #
    # Curve to Mesh
    #     ↓
    # Split Edges
    #     ↓
    # Scale Elements
    #     ↓
    # Extrude Mesh
    #
    # diventa:
    #
    # Curve to Mesh
    #     ↓
    # Extrude Mesh
    # ---------------------------------------------------------

    curve_output = curve_to_mesh.outputs.get("Mesh")
    extrude_input = extrude.inputs.get("Mesh")

    if curve_output is None:
        raise RuntimeError(
            "Output Mesh di Curve to Mesh non trovato"
        )

    if extrude_input is None:
        raise RuntimeError(
            "Input Mesh di Extrude Mesh non trovato"
        )

    if not extrude_input.is_linked:
        raise RuntimeError(
            "Extrude Mesh.004 non ha input collegato"
        )

    original_link = extrude_input.links[0]
    original_from_socket = original_link.from_socket

    tree.links.remove(original_link)

    tree.links.new(
        curve_output,
        extrude_input,
    )

    # ---------------------------------------------------------
    # 2. CREA MATERIALE VIOLA EMISSIVO
    # ---------------------------------------------------------

    material_socket = crosswalk_set.inputs.get("Material")

    if material_socket is None:
        raise RuntimeError(
            "Socket Material di Set Material.002 non trovato"
        )

    original_material = material_socket.default_value

    material = bpy.data.materials.get(
        CROSSWALK_MATERIAL_NAME
    )

    if material is None:
        material = bpy.data.materials.new(
            CROSSWALK_MATERIAL_NAME
        )

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

    # assegna direttamente il materiale viola
    crosswalk_set.inputs["Material"].default_value = material

    bpy.context.view_layer.update()

    print(
        "WSM crosswalk:",
        "strisce unite |",
        "RGB = [139, 93, 255]"
    )

    return {
        "tree": tree,
        "extrude_input": extrude_input,
        "original_from_socket": original_from_socket,
        "material_socket": material_socket,
        "original_material": original_material,
    }


def disable_crosswalk_wsm(state):
    if state is None:
        return

    tree = state["tree"]
    extrude_input = state["extrude_input"]

    # rimuove Curve to Mesh -> Extrude Mesh
    for link in list(extrude_input.links):
        tree.links.remove(link)

    # ripristina Scale Elements -> Extrude Mesh
    tree.links.new(
        state["original_from_socket"],
        extrude_input,
    )

    # ripristina il materiale precedente
    state["material_socket"].default_value = (
        state["original_material"]
    )

    bpy.context.view_layer.update()

    print("WSM crosswalk ripristinato")