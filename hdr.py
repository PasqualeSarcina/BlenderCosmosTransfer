import os

import bpy


def apply_hdr(path: str, scene: bpy.context.scene):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"HDR file not found: {path}")

    if scene.world is None:
        scene.world = bpy.data.worlds.new(name="CosmosWorld")

    scene.world.use_nodes = True

    # Get the environment node tree of the current scene
    node_tree = scene.world.node_tree
    if node_tree is None:
        raise RuntimeError("Unable to create the World node tree")

    tree_nodes = node_tree.nodes

    # Clear all nodes
    tree_nodes.clear()

    # Add Background node
    node_background = tree_nodes.new(type='ShaderNodeBackground')

    # Add Environment Texture node
    node_environment = tree_nodes.new('ShaderNodeTexEnvironment')
    # Load and assign the image to the node property
    node_environment.image = bpy.data.images.load(path, check_existing=True)

    node_environment.location = -300, 0

    # Add Output node
    node_output = tree_nodes.new(type='ShaderNodeOutputWorld')
    node_output.location = 200, 0

    # Link all nodes
    links = node_tree.links
    links.new(node_environment.outputs["Color"], node_background.inputs["Color"])
    links.new(node_background.outputs["Background"], node_output.inputs["Surface"])
