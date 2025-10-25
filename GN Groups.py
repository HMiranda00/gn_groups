import bpy
import bmesh
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, BoolProperty, EnumProperty, CollectionProperty, PointerProperty
from mathutils import Vector, Matrix
import os

# Importar o sistema de gizmos para grupos
try:
    import gn_groups_gizmo
except ImportError:
    pass

# Definir lista global para armazenar keymaps do addon
addon_keymaps = []

bl_info = {
    "name": "GN Groups",
    "author": "Henrique Miranda",
    "version": (2, 4, 1),
    "blender": (2, 80, 0),
    "location": "View3D > Object",
    "description": "Advanced grouping functionality for Blender",
    "category": "Object",
}

def load_node_group():
    # Get the path of the current script
    script_file = os.path.realpath(__file__)
    directory = os.path.dirname(script_file)
    
    # Path to your .blend file
    blend_file_path = os.path.join(directory, "group_node_tree.blend")
    
    # Load the node group from the .blend file
    with bpy.data.libraries.load(blend_file_path) as (data_from, data_to):
        data_to.node_groups = ["GroupNodeTree"]  # "GroupNodeTree" should be the name of your node group in the .blend file
    
    return data_to.node_groups[0]

class GNGroupsPreferences(AddonPreferences):
    bl_idname = __name__

    use_separate_scene: BoolProperty(
        name="Use Separate Scene",
        description="Store groups in a separate scene (legacy mode) or in a collection in the current scene",
        default=False
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_separate_scene")
        layout.label(text="Note: Changing this setting will not affect existing groups")

def get_gngroups_storage(context, create=True):
    """Get or create the storage location for GN Groups based on preferences"""
    preferences = context.preferences.addons[__name__].preferences
    
    if preferences.use_separate_scene:
        # Use separate scene method (legacy)
        groups_scene = bpy.data.scenes.get("GNGroups")
        if not groups_scene and create:
            groups_scene = bpy.data.scenes.new(name="GNGroups")
        
        if groups_scene and create:
            groups_collection = groups_scene.collection.children.get("GNGroups")
            if not groups_collection:
                groups_collection = bpy.data.collections.new("GNGroups")
                groups_scene.collection.children.link(groups_collection)
            return groups_scene, groups_collection
        return groups_scene, None
    else:
        # Use collection method (new default)
        groups_collection = bpy.data.collections.get("GNGroups")
        if not groups_collection and create:
            groups_collection = bpy.data.collections.new("GNGroups")
            # Set exclude properties
            groups_collection.hide_viewport = True
            groups_collection.hide_render = True
            bpy.context.scene.collection.children.link(groups_collection)
            
            # Get the view layer collection for the GNGroups collection
            view_layer = context.view_layer
            groups_layer_collection = None
            for layer_coll in view_layer.layer_collection.children:
                if layer_coll.collection == groups_collection:
                    groups_layer_collection = layer_coll
                    groups_layer_collection.exclude = True
                    break
        elif groups_collection and create:
            # Ensure all child collections inherit visibility settings
            for child_collection in groups_collection.children:
                child_collection.hide_viewport = groups_collection.hide_viewport
                child_collection.hide_render = groups_collection.hide_render
                
            # Also update view layer exclude settings if possible
            view_layer = context.view_layer
            groups_layer_collection = None
            for layer_coll in view_layer.layer_collection.children:
                if layer_coll.collection == groups_collection:
                    groups_layer_collection = layer_coll
                    break
                    
            if groups_layer_collection:
                for child_layer_coll in groups_layer_collection.children:
                    child_layer_coll.exclude = groups_layer_collection.exclude
                
        return context.scene, groups_collection

def update_group_materials(group_obj, group_collection):
    """Update materials of the group object based on objects in collection"""
    # Clear existing materials
    while group_obj.data.materials:
        group_obj.data.materials.pop()
    
    # Add materials from all objects in the collection
    for obj in group_collection.objects:
        if obj.material_slots:
            for slot in obj.material_slots:
                if slot.material:
                    if slot.material.name not in group_obj.data.materials:
                        group_obj.data.materials.append(slot.material)

def get_group_collection_from_object(group_obj):
    """Get the collection linked to a group object"""
    for mod in group_obj.modifiers:
        if f"gng_" in mod.name and mod.type == 'NODES':
            # Find the collection input socket
            for input in mod.node_group.interface.items_tree:
                if input.bl_socket_idname == 'NodeSocketCollection':
                    collection_socket = input
                    # Get the collection
                    return mod[collection_socket.identifier]
    return None

def detect_group_cycles(group_collection, visited=None, path=None):
    """Detect cycles in group hierarchy to prevent infinite recursion"""
    if visited is None:
        visited = set()
    if path is None:
        path = []
        
    # Mark current collection as visited
    visited.add(group_collection.name)
    path.append(group_collection.name)
    
    # Check all objects in this collection that are groups
    for obj in group_collection.objects:
        if any(f"gng_" in mod.name for mod in obj.modifiers):
            # This object is a group, get its collection
            nested_collection = get_group_collection_from_object(obj)
            if nested_collection:
                if nested_collection.name in path:
                    # Cycle detected
                    cycle_path = path[path.index(nested_collection.name):] + [nested_collection.name]
                    return True, cycle_path
                if nested_collection.name not in visited:
                    # Recursively check this nested collection
                    has_cycle, cycle_path = detect_group_cycles(nested_collection, visited, path.copy())
                    if has_cycle:
                        return True, cycle_path
    
    return False, []

class GROUP_OT_create_group(Operator):
    bl_idname = "object.create_group"
    bl_label = "Create Group"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Create a new group from selected objects"

    group_name: StringProperty(
        name="Group Name",
        default="",
        description="Name for the new group"
    )

    def invoke(self, context, event):
        # Set default name to the last selected object
        selected_objects = context.selected_objects
        if selected_objects:
            self.group_name = selected_objects[-1].name
        else:
            self.group_name = "group"
            
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'WARNING'}, "No objects selected")
            return {'CANCELLED'}

        # Check if we're creating a group that contains other groups
        contains_groups = False
        for obj in selected_objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                contains_groups = True
                break
                
        if contains_groups:
            # Make sure we're not creating a cyclical group structure
            storage_scene, groups_collection = get_gngroups_storage(context)
            
            # For each group in selected objects, check if it already includes any of the other selected objects
            for group_obj in [obj for obj in selected_objects if any(f"gng_" in mod.name for mod in obj.modifiers)]:
                group_collection = get_group_collection_from_object(group_obj)
                if group_collection:
                    # Check all non-group objects being grouped
                    for regular_obj in [obj for obj in selected_objects if not any(f"gng_" in mod.name for mod in obj.modifiers)]:
                        if regular_obj in group_collection.objects:
                            self.report({'ERROR'}, f"Cyclic dependency detected: {regular_obj.name} is already in group {group_obj.name}")
                            return {'CANCELLED'}

        original_scene = context.scene

        # Get or create the storage location based on preferences
        storage_scene, groups_collection = get_gngroups_storage(context)
        if not groups_collection:
            self.report({'ERROR'}, "Could not create GNGroups storage location")
            return {'CANCELLED'}

        new_collection = bpy.data.collections.new(self.group_name)
        groups_collection.children.link(new_collection)
        
        # Apply the same visibility settings to the new collection as the parent collection
        # in collection mode (not separate scene mode)
        preferences = context.preferences.addons[__name__].preferences
        if not preferences.use_separate_scene:
            new_collection.hide_viewport = groups_collection.hide_viewport
            new_collection.hide_render = groups_collection.hide_render
            
            # If we can get the view layer collection, set exclude too
            view_layer = context.view_layer
            parent_view_layer_collection = None
            for layer_coll in view_layer.layer_collection.children:
                if layer_coll.collection == groups_collection:
                    parent_view_layer_collection = layer_coll
                    break
                    
            if parent_view_layer_collection:
                for layer_coll in parent_view_layer_collection.children:
                    if layer_coll.collection == new_collection:
                        layer_coll.exclude = parent_view_layer_collection.exclude
                        break

        # Calculate the center point of all selected objects
        center = Vector((0, 0, 0))
        for obj in selected_objects:
            center += obj.matrix_world.translation
        center /= len(selected_objects)

        # Move objects to new collection and adjust their positions
        for obj in selected_objects:
            # Desvincular o objeto de todas as collections atuais
            for collection in list(bpy.data.collections):
                if obj.name in collection.objects:
                    collection.objects.unlink(obj)
            # Desvincular da coleção da cena também, se estiver lá
            if obj.name in context.scene.collection.objects:
                context.scene.collection.objects.unlink(obj)
                
            # Agora vincular à nova coleção do grupo
            new_collection.objects.link(obj)
            
            # Calculate the offset from the center
            offset = obj.matrix_world.translation - center
            
            # Set the object's position relative to the new center
            obj.matrix_world.translation = offset

        # Create vertex object in main scene
        mesh = bpy.data.meshes.new(self.group_name)
        vertex_obj = bpy.data.objects.new(self.group_name, mesh)
        context.collection.objects.link(vertex_obj)
        
        bm = bmesh.new()
        bm.verts.new((0, 0, 0))
        bm.to_mesh(mesh)
        bm.free()
        
        # Set the vertex object's position to the calculated center
        vertex_obj.location = center

        # Create Geometry Nodes modifier
        gn_modifier = vertex_obj.modifiers.new(name=f"gng_{self.group_name}", type='NODES')

        # Load the pre-made node group
        node_group = load_node_group()
        if node_group is None:
            self.report({'ERROR'}, "Failed to load the node group. Make sure 'group_node_tree.blend' is in the addon folder.")
            return {'CANCELLED'}

        # Assign the loaded node group to the modifier
        gn_modifier.node_group = node_group

        # Find the correct input socket for the collection
        collection_socket = None
        for input in node_group.interface.items_tree:
            if input.bl_socket_idname == 'NodeSocketCollection':
                collection_socket = input
                break

        if collection_socket:
            # Set the collection
            gn_modifier[collection_socket.identifier] = new_collection
        else:
            self.report({'WARNING'}, "Could not find a collection input in the node group.")

        # Apply materials
        update_group_materials(vertex_obj, new_collection)

        # After creating, check for cycles in the full hierarchy
        has_cycle, cycle_path = detect_group_cycles(new_collection)
        if has_cycle:
            # We'll allow the group to be created but warn the user
            cycle_str = " → ".join(cycle_path)
            self.report({'WARNING'}, f"Potential cycle in group hierarchy detected: {cycle_str}")

        self.report({'INFO'}, f"Group '{self.group_name}' created successfully")
        return {'FINISHED'}

def should_display_group(context, group_collection, groups_collection):
    """Determina se um grupo deve ser exibido com base no estado de expansão dos grupos pais"""
    if not groups_collection:
        return True
        
    # Grupos no nível raiz sempre são exibidos
    if group_collection.name in [coll.name for coll in groups_collection.children]:
        return True
        
    # Encontrar o grupo pai deste grupo
    parent_collection = None
    parent_index = -1
    
    for i, parent_coll in enumerate(groups_collection.children):
        for obj in parent_coll.objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                group_coll = get_group_collection_from_object(obj)
                if group_coll and group_coll == group_collection:
                    parent_collection = parent_coll
                    parent_index = i
                    break
        if parent_collection:
            break
            
    if not parent_collection:
        # Se não encontramos um pai, assumimos que deve ser exibido (poderia ser um erro)
        return True
        
    # Verificar se o pai está expandido usando propriedade individual
    is_parent_expanded = False
    if parent_index < 64:
        is_parent_expanded = getattr(context.scene, f"group_expanded_{parent_index}", False)
        
    # Este grupo só deve ser exibido se o pai estiver expandido
    return is_parent_expanded

def sort_groups_hierarchically(context, groups_collection):
    """Organiza os grupos em ordem hierárquica (de cima para baixo)"""
    if not groups_collection or not groups_collection.children:
        return []
        
    # Primeiro, identificar os grupos de nível raiz (sem pais)
    root_groups = []
    child_groups = []
    
    # Mapear cada grupo ao seu nível hierárquico
    group_levels = {}
    
    for group_coll in groups_collection.children:
        level = get_group_hierarchy_level(context, group_coll)
        group_levels[group_coll.name] = level
        
        if level == 0:
            root_groups.append(group_coll)
        else:
            child_groups.append(group_coll)
    
    # Ordenar grupos de nível não-raiz pelo nível hierárquico
    child_groups.sort(key=lambda x: group_levels[x.name])
    
    # Combinar grupos raiz com grupos filho
    return root_groups + child_groups

class GROUP_OT_ungroup(Operator):
    bl_idname = "object.ungroup"
    bl_label = "Ungroup"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Extract all objects from the group"
    
    def execute(self, context):
        # Verificar se estamos em modo de edição (visualização local)
        is_in_local_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    is_in_local_view = True
                    break
        
        # Comportamento diferente se estiver em modo de edição ou não
        if is_in_local_view and context.selected_objects:
            # Estamos em modo de edição e há objetos selecionados
            # Desagrupar os objetos selecionados do grupo em edição
            
            # Primeiro, precisamos encontrar qual é o grupo sendo editado
            active_group_collection = None
            storage_scene, groups_collection = get_gngroups_storage(context, create=False)
            if not groups_collection:
                self.report({'WARNING'}, "Coleção de grupos não encontrada")
                return {'CANCELLED'}
                
            # Tentar identificar qual coleção de grupo está sendo editada
            # baseando-se nos objetos selecionados
            for coll in groups_collection.children:
                for obj in context.selected_objects:
                    if obj.name in coll.objects:
                        active_group_collection = coll
                        break
                if active_group_collection:
                    break
                    
            if not active_group_collection:
                self.report({'WARNING'}, "Não foi possível identificar o grupo em edição")
                return {'CANCELLED'}
            
            # Encontrar o objeto do grupo na cena
            group_obj = None
            for obj in context.view_layer.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == active_group_collection:
                                group_obj = obj
                                break
                if group_obj:
                    break
                    
            if not group_obj:
                self.report({'WARNING'}, "Objeto de grupo não encontrado")
                return {'CANCELLED'}
            
            # Verificar se existem outras instâncias deste grupo
            has_other_instances = False
            for obj in context.view_layer.objects:
                if obj != group_obj and any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == active_group_collection:
                                has_other_instances = True
                                break
                if has_other_instances:
                    break
            
            # Get transformation matrix of the group object
            group_matrix = group_obj.matrix_world.copy()
            
            # Obter a coleção onde os objetos desagrupados serão movidos
            # Será a coleção do usuário atual, fora da coleção GNGroups
            target_collection = context.scene.collection
            for coll in context.view_layer.layer_collection.children:
                if coll.collection != groups_collection and coll.collection.library is None:
                    # Encontrar a primeira coleção visível que não é a GNGroups
                    if not coll.exclude:
                        target_collection = coll.collection
                        break
            
            # Se houver mais instâncias, criar cópias e mover
            # Caso contrário, mover diretamente
            selected_objects = context.selected_objects.copy()
            for obj in selected_objects:
                if obj.name in active_group_collection.objects:
                    if has_other_instances:
                        # Criar uma cópia
                        new_obj = obj.copy()
                        if obj.data:
                            new_obj.data = obj.data.copy()
                            
                        # Aplicar materiais
                        for slot in obj.material_slots:
                            if slot.material:
                                if slot.material.name not in new_obj.data.materials:
                                    new_obj.data.materials.append(slot.material)
                                    
                        # Aplicar transformações (grupo + posição relativa do objeto)
                        new_obj.matrix_world = group_matrix @ obj.matrix_world
                        
                        # Adicionar à coleção alvo
                        target_collection.objects.link(new_obj)
                    else:
                        # Caso não haja outras instâncias, mover diretamente
                        # Remover da coleção atual
                        active_group_collection.objects.unlink(obj)
                        
                        # Aplicar transformações
                        obj.matrix_world = group_matrix @ obj.matrix_world
                        
                        # Adicionar à coleção alvo
                        target_collection.objects.link(obj)
            
            # Se não houver outras instâncias e não sobrar nenhum objeto no grupo,
            # podemos remover completamente o grupo
            if not has_other_instances and len(active_group_collection.objects) == 0:
                bpy.data.objects.remove(group_obj)
                # Armazenar o nome da coleção antes de removê-la
                collection_name = active_group_collection.name
                # Limpar referências
                active_group_collection = None
                # Remover a coleção pelo nome
                bpy.data.collections.remove(bpy.data.collections.get(collection_name))
                
                self.report({'INFO'}, f"Group '{collection_name}' ungrouped successfully")
            else:
                self.report({'INFO'}, f"Group '{active_group_collection.name}' ungrouped successfully")
            return {'FINISHED'}
        else:
            # Comportamento padrão: desagrupar o grupo inteiro
            active_obj = context.active_object
            if not active_obj or not any(f"gng_" in mod.name for mod in active_obj.modifiers):
                self.report({'WARNING'}, "O objeto selecionado não é um Grupo GN")
                return {'CANCELLED'}
            
            # Get the group modifier
            gn_modifier = None
            for mod in active_obj.modifiers:
                if f"gng_" in mod.name and mod.type == 'NODES':
                    gn_modifier = mod
                    break
                    
            if not gn_modifier or not gn_modifier.node_group:
                self.report({'WARNING'}, "Modificador de grupo inválido")
                return {'CANCELLED'}
                
            # Find the collection input socket
            collection_socket = None
            for input in gn_modifier.node_group.interface.items_tree:
                if input.bl_socket_idname == 'NodeSocketCollection':
                    collection_socket = input
                    break
                    
            if not collection_socket:
                self.report({'WARNING'}, "Não foi possível encontrar a coleção no grupo de nós")
                return {'CANCELLED'}
                
            # Get the group collection
            group_collection = gn_modifier[collection_socket.identifier]
            if not group_collection:
                self.report({'WARNING'}, "Coleção do grupo não encontrada")
                return {'CANCELLED'}
                
            # Get transformation matrix of the group object
            group_matrix = active_obj.matrix_world.copy()
            
            # Obter a coleção alvo - usar a coleção atual do contexto
            target_collection = context.collection
            
            # Create duplicates of all objects in the group at the current position
            new_objects = []
            for obj in group_collection.objects:
                # Create a duplicate
                new_obj = obj.copy()
                if obj.data:
                    new_obj.data = obj.data.copy()
                    
                # Apply materials
                for slot in obj.material_slots:
                    if slot.material:
                        if slot.material.name not in new_obj.data.materials:
                            new_obj.data.materials.append(slot.material)
                            
                # Link to target collection
                target_collection.objects.link(new_obj)
                
                # Apply transformations (group transformation + relative object position)
                new_obj.matrix_world = group_matrix @ obj.matrix_world
                
                new_objects.append(new_obj)
                all_new_objects.append(new_obj)  # Adicionar à lista global um por um
                
            # Select newly created objects
            bpy.ops.object.select_all(action='DESELECT')
            for obj in new_objects:
                obj.select_set(True)
            context.view_layer.objects.active = new_objects[0] if new_objects else None
            
            # Verificar se existem outras instâncias deste grupo
            has_other_instances = False
            for obj in context.view_layer.objects:
                if obj is not None and obj != active_obj and obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == group_collection:
                                has_other_instances = True
                                break
                if has_other_instances:
                    break
            
            # Remove the group instance
            bpy.data.objects.remove(active_obj)
            
            # Se for a última instância, remover a coleção também
            if not has_other_instances:
                # Armazenar o nome da coleção para relatório
                group_collection_name = group_collection.name
                # Limpar qualquer referência à coleção antes de removê-la
                group_collection = None
                # Agora remover a coleção pelo nome
                bpy.data.collections.remove(bpy.data.collections.get(group_collection_name))
                
                self.report({'INFO'}, f"Group '{group_collection_name}' ungrouped successfully")
            else:
                self.report({'INFO'}, f"Group '{group_collection.name}' ungrouped successfully")
            return {'FINISHED'}

class GROUP_OT_rename(Operator):
    bl_idname = "object.rename_group"
    bl_label = "Rename Group"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Rename the selected group"
    
    new_name: StringProperty(
        name="New Name",
        default="",
        description="New name for the group"
    )
    
    def invoke(self, context, event):
        active_obj = context.active_object
        if active_obj:
            self.new_name = active_obj.name
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
        
    def execute(self, context):
        active_obj = context.active_object
        if not active_obj or not any(f"gng_" in mod.name for mod in active_obj.modifiers):
            self.report({'WARNING'}, "Selected object is not a GN Group")
            return {'CANCELLED'}
            
        old_name = active_obj.name
        
        # Get the group modifier
        gn_modifier = None
        for mod in active_obj.modifiers:
            if f"gng_" in mod.name and mod.type == 'NODES':
                gn_modifier = mod
                break
                
        if not gn_modifier or not gn_modifier.node_group:
            self.report({'WARNING'}, "Invalid group modifier")
            return {'CANCELLED'}
            
        # Find the collection input socket
        collection_socket = None
        for input in gn_modifier.node_group.interface.items_tree:
            if input.bl_socket_idname == 'NodeSocketCollection':
                collection_socket = input
                break
                
        if not collection_socket:
            self.report({'WARNING'}, "Could not find collection in node group")
            return {'CANCELLED'}
            
        # Get the group collection
        group_collection = gn_modifier[collection_socket.identifier]
        if not group_collection:
            self.report({'WARNING'}, "Group collection not found")
            return {'CANCELLED'}
            
        # Rename the collection and the object
        group_collection.name = self.new_name
        active_obj.name = self.new_name
        active_obj.data.name = self.new_name
        
        # Rename the modifier
        gn_modifier.name = f"gng_{self.new_name}"
        
        self.report({'INFO'}, f"Group renamed from '{old_name}' to '{self.new_name}'")
        return {'FINISHED'}

class GROUP_OT_toggle_edit_mode(Operator):
    bl_idname = "object.toggle_group_edit_mode"
    bl_label = "Toggle Group Edit Mode"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Enter or exit edit mode for groups"

    @classmethod
    def poll(cls, context):
        # Em modo de visualização local sempre habilitar (para permitir sair do modo de edição)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    return True
        
        # Se estamos fora do modo de visualização local, verificar se há pelo menos um grupo selecionado
        # Isso permite a edição de vários grupos de uma só vez
        if context.active_object and any(f"gng_" in mod.name for mod in context.active_object.modifiers):
            # Se o objeto ativo é um grupo, permitir a edição
            return True
            
        # Nenhum grupo selecionado/ativo, seguir comportamento padrão do Blender para TAB
        return False

    def execute(self, context):
        # Check preferences to determine storage method
        preferences = context.preferences.addons[__name__].preferences
        
        # Check if we're in local view mode
        is_in_local_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    is_in_local_view = True
                    break
        
        # Verificar se temos objetos selecionados
        has_selected_objects = len(context.selected_objects) > 0
        
        if preferences.use_separate_scene and context.scene.name == "GNGroups":
            # We're in the groups scene (legacy mode)
            if not has_selected_objects:
                # No objects selected, so exit the group
                main_scene = next((scene for scene in bpy.data.scenes if scene.name != "GNGroups"), None)
                if main_scene:
                    context.window.scene = main_scene
                    bpy.ops.view3d.localview()
                else:
                    self.report({'WARNING'}, "Main scene not found")
                    return {'CANCELLED'}
            else:
                # Objects selected, handle nested group editing
                active_obj = context.active_object
                if active_obj and any(f"gng_" in mod.name for mod in active_obj.modifiers):
                    # We have a group inside a group, edit it
                    group_name = active_obj.name
                    
                    # Find the GN modifier
                    gn_modifier = None
                    for mod in active_obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            gn_modifier = mod
                            break
                    
                    if not gn_modifier or not gn_modifier.node_group:
                        self.report({'WARNING'}, "Invalid group modifier")
                        return {'CANCELLED'}
                    
                    # Find the collection input socket
                    collection_socket = None
                    for input in gn_modifier.node_group.interface.items_tree:
                        if input.bl_socket_idname == 'NodeSocketCollection':
                            collection_socket = input
                            break
                    
                    if not collection_socket:
                        self.report({'WARNING'}, "Could not find collection in node group")
                        return {'CANCELLED'}
                    
                    # Get the group collection
                    group_collection = gn_modifier[collection_socket.identifier]
                    if not group_collection:
                        self.report({'WARNING'}, "Group collection not found")
                        return {'CANCELLED'}
                    
                    # Select the objects in the nested group
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj in group_collection.objects:
                        obj.select_set(True)
                    context.view_layer.objects.active = next(iter(group_collection.objects), None)
                    
                    # Enter local view if not already in it
                    if not is_in_local_view:
                        bpy.ops.view3d.localview()
                    
                    return {'FINISHED'}
                else:
                    # Default behavior for regular objects
                    return {'PASS_THROUGH'}
        elif not preferences.use_separate_scene and is_in_local_view:
            # We're in local view mode (new method)
            # Primeiro, verificar se não há objetos selecionados - se não tiver, sair do grupo
            if not has_selected_objects:
                # Sem objetos selecionados, sair do modo de edição
                # Update materials before exiting
                group_objects = [obj for obj in bpy.data.objects if obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers)]
                for group_obj in group_objects:
                    for mod in group_obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            gn_modifier = mod
                            # Find the collection input socket
                            collection_socket = None
                            for input in gn_modifier.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket:
                                # Get the group collection
                                group_collection = gn_modifier[collection_socket.identifier]
                                if group_collection:
                                    # Update materials
                                    update_group_materials(group_obj, group_collection)
                
                # Exit local view
                bpy.ops.view3d.localview()
                
                # Reset visibility of GNGroups collection and all child collections
                groups_collection = bpy.data.collections.get("GNGroups")
                if groups_collection:
                    # Hide the main collection
                    groups_collection.hide_viewport = True
                    groups_collection.hide_render = True
                    
                    # Hide all child collections too
                    for child_collection in groups_collection.children:
                        child_collection.hide_viewport = True
                        child_collection.hide_render = True
                    
                    # Also update view layer exclude settings if possible
                    view_layer = context.view_layer
                    groups_layer_collection = None
                    for layer_coll in view_layer.layer_collection.children:
                        if layer_coll.collection == groups_collection:
                            groups_layer_collection = layer_coll
                            groups_layer_collection.exclude = True
                            break
                            
                    if groups_layer_collection:
                        for child_layer_coll in groups_layer_collection.children:
                            child_layer_coll.exclude = True
                    
                return {'FINISHED'}
            
            # First check if a nested group is selected
            active_obj = context.active_object
            
            if active_obj and any(f"gng_" in mod.name for mod in active_obj.modifiers):
                # We have a group inside a group, enter edit mode for it
                # Find the GN modifier
                gn_modifier = None
                for mod in active_obj.modifiers:
                    if f"gng_" in mod.name and mod.type == 'NODES':
                        gn_modifier = mod
                        break
                
                if not gn_modifier or not gn_modifier.node_group:
                    # Not a proper group - exit local view
                    bpy.ops.view3d.localview()
                    return {'FINISHED'}
                
                # Find the collection input socket
                collection_socket = None
                for input in gn_modifier.node_group.interface.items_tree:
                    if input.bl_socket_idname == 'NodeSocketCollection':
                        collection_socket = input
                        break
                
                if not collection_socket:
                    # No collection socket - exit local view
                    bpy.ops.view3d.localview()
                    return {'FINISHED'}
                
                # Get the group collection
                nested_collection = gn_modifier[collection_socket.identifier]
                if not nested_collection:
                    # No collection - exit local view
                    bpy.ops.view3d.localview()
                    return {'FINISHED'}

                # We have a valid nested group - make its objects visible and select them
                nested_collection.hide_viewport = False
                
                # Update view layer exclude settings if possible
                view_layer = context.view_layer
                groups_collection = bpy.data.collections.get("GNGroups")
                if groups_collection:
                    groups_layer_collection = None
                    group_layer_collection = None
                    
                    for layer_coll in view_layer.layer_collection.children:
                        if layer_coll.collection == groups_collection:
                            groups_layer_collection = layer_coll
                            groups_layer_collection.exclude = False
                            
                            # Procurar a layer_collection para a collection do grupo
                            for child_layer_coll in groups_layer_collection.children:
                                if child_layer_coll.collection == nested_collection:
                                    child_layer_coll.exclude = False
                                    group_layer_collection = child_layer_coll
                                else:
                                    child_layer_coll.exclude = True
                            break
                    
                    # Ativar a collection do grupo para que novos objetos sejam adicionados a ela
                    if group_layer_collection:
                        # Definir a collection do grupo como ativa
                        context.view_layer.active_layer_collection = group_layer_collection
                    
                    # Select the objects in the group
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj in nested_collection.objects:
                        obj.select_set(True)
                    context.view_layer.objects.active = next(iter(nested_collection.objects), None)
                    
                    # Exit current local view and enter a new one to focus on the nested group
                    bpy.ops.view3d.localview()  # Exit current
                    bpy.ops.view3d.localview()  # Enter new local view with newly selected objects
                    
                    return {'FINISHED'}
            else:
                # Se não for grupo e tiver selecionado, deixe o comportamento padrão do TAB em objetos
                if not any(obj for obj in context.selected_objects if any(f"gng_" in mod.name for mod in obj.modifiers)):
                    # Se não houver grupos selecionados, deixe o comportamento padrão do TAB
                    return {'PASS_THROUGH'}
                    
                # Update materials before exiting
                group_objects = [obj for obj in bpy.data.objects if obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers)]
                for group_obj in group_objects:
                    for mod in group_obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            gn_modifier = mod
                            # Find the collection input socket
                            collection_socket = None
                            for input in gn_modifier.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket:
                                # Get the group collection
                                group_collection = gn_modifier[collection_socket.identifier]
                                if group_collection:
                                    # Update materials
                                    update_group_materials(group_obj, group_collection)
                
                # Exit local view
                bpy.ops.view3d.localview()
                
                # Reset visibility of GNGroups collection and all child collections
                groups_collection = bpy.data.collections.get("GNGroups")
                if groups_collection:
                    # Hide the main collection
                    groups_collection.hide_viewport = True
                    groups_collection.hide_render = True
                    
                    # Hide all child collections too
                    for child_collection in groups_collection.children:
                        child_collection.hide_viewport = True
                        child_collection.hide_render = True
                    
                    # Also update view layer exclude settings if possible
                    view_layer = context.view_layer
                    groups_layer_collection = None
                    for layer_coll in view_layer.layer_collection.children:
                        if layer_coll.collection == groups_collection:
                            groups_layer_collection = layer_coll
                            groups_layer_collection.exclude = True
                            break
                            
                    if groups_layer_collection:
                        for child_layer_coll in groups_layer_collection.children:
                            child_layer_coll.exclude = True
                    
                return {'FINISHED'}
        else:
            # We're in main scene
            active_obj = context.active_object
            # Verificar se temos pelo menos um grupo selecionado e o objeto ativo é um grupo
            selected_group_objects = [obj for obj in context.selected_objects if any(f"gng_" in mod.name for mod in obj.modifiers)]
            
            if active_obj and any(f"gng_" in mod.name for mod in active_obj.modifiers) and selected_group_objects:
                # Tem pelo menos um grupo selecionado e o objeto ativo é um grupo
                
                # Coletar todas as collections de grupos selecionados
                group_collections = []
                group_layer_collections = []
                
                for group_obj in selected_group_objects:
                    # Find the GN modifier
                    gn_modifier = None
                    for mod in group_obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            gn_modifier = mod
                            break
                    
                    if not gn_modifier or not gn_modifier.node_group:
                        continue
                    
                    # Find the collection input socket
                    collection_socket = None
                    for input in gn_modifier.node_group.interface.items_tree:
                        if input.bl_socket_idname == 'NodeSocketCollection':
                            collection_socket = input
                            break
                    
                    if not collection_socket:
                        continue
                    
                    # Get the group collection
                    group_collection = gn_modifier[collection_socket.identifier]
                    if group_collection and group_collection not in group_collections:
                        group_collections.append(group_collection)
                
                # Se não encontramos collections válidas, sair
                if not group_collections:
                    self.report({'WARNING'}, "No valid group collections found")
                    return {'CANCELLED'}
                
                # Obter a collection do grupo ativo (para definir como collection ativa)
                active_group_collection = None
                for mod in active_obj.modifiers:
                    if f"gng_" in mod.name and mod.type == 'NODES':
                        for input in mod.node_group.interface.items_tree:
                            if input.bl_socket_idname == 'NodeSocketCollection':
                                collection_socket = input
                                active_group_collection = mod[collection_socket.identifier]
                                break
                        if active_group_collection:
                            break
                
                if preferences.use_separate_scene:
                    # Legacy mode - go to separate scene
                    groups_scene = bpy.data.scenes.get("GNGroups")
                    if not groups_scene:
                        self.report({'WARNING'}, "Groups scene not found")
                        return {'CANCELLED'}

                    context.window.scene = groups_scene
                    
                    # Select all objects from all group collections
                    bpy.ops.object.select_all(action='DESELECT')
                    active_obj_in_groups = None
                    
                    for group_collection in group_collections:
                        for obj in group_collection.objects:
                            obj.select_set(True)
                            if not active_obj_in_groups:
                                active_obj_in_groups = obj
                    
                    # Set active object from any of the collections
                    if active_obj_in_groups:
                        groups_scene.view_layers[0].objects.active = active_obj_in_groups
                    
                    # Enter local view
                    bpy.ops.view3d.localview()
                    
                else:
                    # New mode - use local view in current scene
                    # First make the GNGroups collection and only the target group collections visible temporarily
                    groups_collection = bpy.data.collections.get("GNGroups")
                    if groups_collection:
                        # Store original visibility states
                        was_main_hidden = groups_collection.hide_viewport
                        
                        # Make main collection visible temporarily
                        groups_collection.hide_viewport = False
                        
                        # Set group collection visibility
                        for child_collection in groups_collection.children:
                            # Hide all collections except the ones we're editing
                            if child_collection in group_collections:
                                child_collection.hide_viewport = False
                            else:
                                child_collection.hide_viewport = True
                                
                        # Update view layer exclude settings
                        view_layer = context.view_layer
                        groups_layer_collection = None
                        active_group_layer_collection = None
                        
                        for layer_coll in view_layer.layer_collection.children:
                            if layer_coll.collection == groups_collection:
                                groups_layer_collection = layer_coll
                                groups_layer_collection.exclude = False
                                
                                # Procurar as layer_collections para as collections dos grupos
                                for child_layer_coll in groups_layer_collection.children:
                                    if child_layer_coll.collection in group_collections:
                                        child_layer_coll.exclude = False
                                        # Se for a collection do grupo ativo, guardar referência
                                        if child_layer_coll.collection == active_group_collection:
                                            active_group_layer_collection = child_layer_coll
                                    else:
                                        child_layer_coll.exclude = True
                                break
                        
                        # Ativar a collection do grupo ativo para que novos objetos sejam adicionados a ela
                        if active_group_layer_collection:
                            # Definir a collection do grupo ativo como a collection ativa
                            context.view_layer.active_layer_collection = active_group_layer_collection
                        
                        # Remover lógica de manter seleção atual, apenas selecionar objetos dos grupos
                        bpy.ops.object.select_all(action='DESELECT')
                        
                        # Selecionar todos os objetos dos grupos
                        for group_collection in group_collections:
                            for obj in group_collection.objects:
                                obj.select_set(True)
                        
                        # Garantir que o objeto ativo seja o grupo ativo
                        context.view_layer.objects.active = active_obj
                        
                        # Enter local view com todos os objetos selecionados
                        bpy.ops.view3d.localview()
                    else:
                        self.report({'WARNING'}, "GNGroups collection not found")
                        return {'CANCELLED'}
            else:
                # Not a group object, so keep default Blender behavior
                return {'PASS_THROUGH'}

        return {'FINISHED'}

def register_active_group_index():
    # Check if already registered to avoid error
    if not hasattr(bpy.types.Scene, "active_group_index"):
        bpy.types.Scene.active_group_index = bpy.props.IntProperty(
            name="Active Group Index",
            default=0
        )
    
    # Individual group_expanded_0…63 properties store whether a group is expanded
    # in the hierarchy view. group_expanded_states itself is only a sentinel so
    # this block runs once.
    if not hasattr(bpy.types.Scene, "group_expanded_states"):
        # Criar propriedade individual para cada grupo (até 64)
        for i in range(64):
            setattr(bpy.types.Scene, f"group_expanded_{i}", bpy.props.BoolProperty(
                name=f"Group {i} Expanded",
                default=False
            ))
        bpy.types.Scene.group_expanded_states = True

def unregister_active_group_index():
    if hasattr(bpy.types.Scene, "active_group_index"):
        del bpy.types.Scene.active_group_index
    
    # Remover todas as propriedades individuais para cada grupo
    for i in range(64):
        if hasattr(bpy.types.Scene, f"group_expanded_{i}"):
            delattr(bpy.types.Scene, f"group_expanded_{i}")

# Função auxiliar para determinar o nível hierárquico de um grupo
def get_group_hierarchy_level(context, collection):
    """Determina o nível hierárquico de um grupo em relação a outros grupos"""
    if not collection:
        return 0
        
    # Verificar se a collection está dentro de outras collections de grupo
    storage_scene, groups_collection = get_gngroups_storage(context, create=False)
    if not groups_collection:
        return 0
        
    # Se for uma collection filha direta do GNGroups, está no nível 0
    if collection.name in [coll.name for coll in groups_collection.children]:
        return 0
        
    # Encontrar o objeto de grupo que contém esta collection
    for parent_coll in groups_collection.children:
        for obj in parent_coll.objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                # Este objeto é um grupo, verificar se possui a collection
                group_collection = get_group_collection_from_object(obj)
                if group_collection == collection:
                    # Esta collection está dentro de parent_coll
                    return 1 + get_group_hierarchy_level(context, parent_coll)
    
    # Se não encontramos, assume nível 0
    return 0

class GROUP_OT_toggle_nested_groups(Operator):
    bl_idname = "object.toggle_nested_groups"
    bl_label = "Toggle Nested Groups"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Show or hide nested groups"
    
    group_index: bpy.props.IntProperty()
    
    def execute(self, context):
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if not groups_collection or not groups_collection.children or self.group_index < 0 or self.group_index >= len(groups_collection.children):
            self.report({'WARNING'}, "Invalid group selection")
            return {'CANCELLED'}
        
        # Toggle expanded state using individual properties
        if self.group_index < 64:
            prop_name = f"group_expanded_{self.group_index}"
            current_state = getattr(context.scene, prop_name, False)
            setattr(context.scene, prop_name, not current_state)
        
        return {'FINISHED'}

class GROUP_UL_collections(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # Main item
        row = layout.row(align=True)
        
        # Verificar se estamos em uma visualização local
        is_in_local_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    is_in_local_view = True
                    break
        
        # Verificar se este é o grupo ativo
        is_active_group = False
        if is_in_local_view:
            # Tentamos encontrar quais objetos estão sendo editados e comparamos com os objetos nesta coleção
            storage_scene, groups_collection = get_gngroups_storage(context, create=False)
            if groups_collection:
                # Verificamos se os objetos selecionados fazem parte deste grupo
                selected_objs = context.selected_objects
                if selected_objs:
                    for obj in selected_objs:
                        if obj.name in item.objects:
                            is_active_group = True
                            break
        
        # Determinar o nível hierárquico desta collection
        hierarchy_level = get_group_hierarchy_level(context, item)
        
        # Adicionar indentação visual baseada no nível
        for i in range(hierarchy_level):
            row.label(text="", icon='BLANK1')
        
        # Verificar se tem grupos aninhados
        has_nested_groups = False
        for obj in item.objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                has_nested_groups = True
                break
        
        # Get group index
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        group_index = 0
        for i, coll in enumerate(groups_collection.children):
            if coll == item:
                group_index = i
                break
                
        # Estado expandido/recolhido (somente se tiver grupos aninhados)
        if has_nested_groups:
            # Usar propriedade individual em vez da propriedade vetorial
            is_expanded = False
            if group_index < 64:
                is_expanded = getattr(context.scene, f"group_expanded_{group_index}", False)
                
            expand_icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
            toggle_op = row.operator("object.toggle_nested_groups", text="", icon=expand_icon, emboss=False)
            toggle_op.group_index = group_index
        else:
            # Se não tem grupos aninhados, usar um ícone para manter o alinhamento visual
            row.label(text="", icon='BLANK1')
        
        # Mostrar de forma diferente se for o grupo ativo
        if is_active_group:
            # Grupo ativo - mostrar em destaque
            row.prop(item, "name", text="", emboss=True, icon='GROUP')
        else:
            # Outros grupos - mostrar acinzentados se em modo de edição
            if is_in_local_view:
                row.enabled = False
            row.prop(item, "name", text="", emboss=False, icon='GROUP')
        
        # Botões de ação - alinhados à direita
        # Edit button
        edit_op = row.operator("object.group_list_action", text="", icon='EDITMODE_HLT')
        edit_op.action = 'EDIT'
        edit_op.group_index = group_index
        
        # Select button
        select_op = row.operator("object.group_list_action", text="", icon='RESTRICT_SELECT_OFF')
        select_op.action = 'SELECT'
        select_op.group_index = group_index
        
        # Ungroup button
        ungroup_op = row.operator("object.group_list_action", text="", icon='X')
        ungroup_op.action = 'UNGROUP'
        ungroup_op.group_index = group_index

class GROUP_OT_select_from_list(Operator):
    bl_idname = "object.select_group_from_list"
    bl_label = "Select Group"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Select the group object in the viewport"
    
    group_index: bpy.props.IntProperty()
    
    def execute(self, context):
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if not groups_collection or not groups_collection.children:
            self.report({'WARNING'}, "No groups found")
            return {'CANCELLED'}
            
        try:
            # Get the selected group collection
            group_collection = groups_collection.children[self.group_index]
            
            # Find the corresponding group object in the scene
            group_obj = None
            for obj in context.view_layer.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            # Find the collection input socket
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == group_collection:
                                group_obj = obj
                                break
                    if group_obj:
                        break
            
            if group_obj:
                # Select the group object
                bpy.ops.object.select_all(action='DESELECT')
                group_obj.select_set(True)
                context.view_layer.objects.active = group_obj
                self.report({'INFO'}, f"Selected group '{group_collection.name}'")
                return {'FINISHED'}
            else:
                self.report({'WARNING'}, f"Could not find group object for '{group_collection.name}'")
                return {'CANCELLED'}
                
        except IndexError:
            self.report({'WARNING'}, "Invalid group index")
            return {'CANCELLED'}

class VIEW3D_PT_grouping_tools(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Grouping"
    bl_label = "GN Groups"

    def draw(self, context):
        layout = self.layout
        
        # Group creation tools
        row = layout.row()
        row.operator("object.create_group", text="Create Group")
        
        # Collection list (similar to Materials UI)
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if groups_collection and groups_collection.children:
            row = layout.row()
            
            # Ensure active_group_index exists in the scene
            if not hasattr(context.scene, "active_group_index"):
                register_active_group_index()
                
            # Get the active group index
            active_idx = context.scene.active_group_index if hasattr(context.scene, "active_group_index") else 0
            
            # We'll use this for panel operations to operate on the selected group in the panel
            if 0 <= active_idx < len(groups_collection.children):
                active_group = groups_collection.children[active_idx]
                active_group_name = active_group.name
            else:
                active_group = None
                active_group_name = ""
            
            # Draw the template list
            row.template_list("GROUP_UL_collections", "", groups_collection, "children", 
                              context.scene, "active_group_index", rows=8)
            
            # Secondary buttons column for group operations
            col = row.column(align=True)
            col.operator("object.group_list_action", text="", icon='GREASEPENCIL').action = 'RENAME'
            
            # Only show these operations if a group is actually selected
            if active_group:
                # Add a small box with operations on the selected group
                box = layout.box()
                row = box.row()
                row.label(text=f"Selected: {active_group_name}")
                
                # Row with operations
                row = box.row(align=True)
                
                # Edit button
                edit_op = row.operator("object.group_list_action", text="Edit", icon='EDITMODE_HLT')
                edit_op.action = 'EDIT'
                edit_op.group_index = active_idx
                
                # Select button 
                select_op = row.operator("object.group_list_action", text="Select", icon='RESTRICT_SELECT_OFF')
                select_op.action = 'SELECT'  
                select_op.group_index = active_idx
                
                # Ungroup button
                ungroup_op = row.operator("object.group_list_action", text="Ungroup", icon='X')
                ungroup_op.action = 'UNGROUP'
                ungroup_op.group_index = active_idx
            
            # Help tooltip for TAB usage
            has_nested_groups = False
            for coll in groups_collection.children:
                if self._check_collection_has_groups(coll):
                    has_nested_groups = True
                    break
                    
            if has_nested_groups:
                box = layout.box()
                # Informações sobre a tecla TAB
                row = box.row()
                row.label(text="TAB:", icon='EVENT_TAB')
                row.label(text="Enter/Exit Groups")

    def _check_collection_has_groups(self, collection):
        if not collection:
            return False
            
        try:
            for obj in collection.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    return True
            return False
        except (AttributeError, ReferenceError):
            return False

class SCENE_PT_grouping_tools(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "GN Groups"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        
        # Group creation tools
        row = layout.row()
        row.operator("object.create_group", text="Create Group")
        
        # Collection list (similar to Materials UI)
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if groups_collection and groups_collection.children:
            row = layout.row()
            
            # Ensure active_group_index exists in the scene
            if not hasattr(context.scene, "active_group_index"):
                register_active_group_index()
                
            # Get the active group index
            active_idx = context.scene.active_group_index if hasattr(context.scene, "active_group_index") else 0
            
            # We'll use this for panel operations to operate on the selected group in the panel
            if 0 <= active_idx < len(groups_collection.children):
                active_group = groups_collection.children[active_idx]
                active_group_name = active_group.name
            else:
                active_group = None
                active_group_name = ""
            
            # Draw the template list
            row.template_list("GROUP_UL_collections", "", groups_collection, "children", 
                              context.scene, "active_group_index", rows=8)
            
            # Secondary buttons column for group operations
            col = row.column(align=True)
            col.operator("object.group_list_action", text="", icon='GREASEPENCIL').action = 'RENAME'
            
            # Only show these operations if a group is actually selected
            if active_group:
                # Add a small box with operations on the selected group
                box = layout.box()
                row = box.row()
                row.label(text=f"Selected: {active_group_name}")
                
                # Row with operations
                row = box.row(align=True)
                
                # Edit button
                edit_op = row.operator("object.group_list_action", text="Edit", icon='EDITMODE_HLT')
                edit_op.action = 'EDIT'
                edit_op.group_index = active_idx
                
                # Select button 
                select_op = row.operator("object.group_list_action", text="Select", icon='RESTRICT_SELECT_OFF')
                select_op.action = 'SELECT'  
                select_op.group_index = active_idx
                
                # Ungroup button
                ungroup_op = row.operator("object.group_list_action", text="Ungroup", icon='X')
                ungroup_op.action = 'UNGROUP'
                ungroup_op.group_index = active_idx
            
            # Help tooltip for TAB usage
            has_nested_groups = False
            for coll in groups_collection.children:
                if self._check_collection_has_groups(coll):
                    has_nested_groups = True
                    break
                    
            if has_nested_groups:
                box = layout.box()
                # Informações sobre a tecla TAB
                row = box.row()
                row.label(text="TAB:", icon='EVENT_TAB')
                row.label(text="Enter/Exit Groups")

    def _check_collection_has_groups(self, collection):
        if not collection:
            return False
            
        try:
            for obj in collection.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    return True
            return False
        except (AttributeError, ReferenceError):
            return False

class GROUP_OT_list_action(Operator):
    bl_idname = "object.group_list_action"
    bl_label = "Group List Action"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Perform an action on the selected group"
    
    action: StringProperty()
    group_index: bpy.props.IntProperty()
    nested_group_index: bpy.props.IntProperty(default=-1)
    
    def execute(self, context):
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if not groups_collection or not groups_collection.children or self.group_index < 0 or self.group_index >= len(groups_collection.children):
            self.report({'WARNING'}, "Invalid group selection")
            return {'CANCELLED'}
            
        # Get the group collection
        group_collection = groups_collection.children[self.group_index]
        
        try:
            if self.action == 'RENAME':
                # Modificar abordagem: trabalhar diretamente com a collection
                # e depois encontrar o grupo associado
                group_obj = None
                
                # Encontrar o objeto de grupo que usa esta coleção
                for obj in context.view_layer.objects:
                    if any(f"gng_" in mod.name for mod in obj.modifiers):
                        for mod in obj.modifiers:
                            if f"gng_" in mod.name and mod.type == 'NODES':
                                collection_socket = None
                                for input in mod.node_group.interface.items_tree:
                                    if input.bl_socket_idname == 'NodeSocketCollection':
                                        collection_socket = input
                                        break
                                        
                                if collection_socket and mod[collection_socket.identifier] == group_collection:
                                    group_obj = obj
                                    break
                        if group_obj:
                            break
                
                if group_obj:
                    # Select the group object first
                    bpy.ops.object.select_all(action='DESELECT')
                    group_obj.select_set(True)
                    context.view_layer.objects.active = group_obj
                    
                    # Now invoke the rename operator
                    bpy.ops.object.rename_group('INVOKE_DEFAULT')
                else:
                    self.report({'WARNING'}, f"Could not find group object for '{group_collection.name}'")
                    return {'CANCELLED'}
            
            elif self.action == 'EDIT':
                # Editar diretamente o grupo, sem passar por grupos aninhados
                # Primeiro, encontrar o objeto do grupo na cena
                group_obj = None
                for obj in context.view_layer.objects:
                    if any(f"gng_" in mod.name for mod in obj.modifiers):
                        for mod in obj.modifiers:
                            if f"gng_" in mod.name and mod.type == 'NODES':
                                collection_socket = None
                                for input in mod.node_group.interface.items_tree:
                                    if input.bl_socket_idname == 'NodeSocketCollection':
                                        collection_socket = input
                                        break
                                        
                                if collection_socket and mod[collection_socket.identifier] == group_collection:
                                    group_obj = obj
                                    break
                        if group_obj:
                            break
                
                if group_obj:
                    # Verificar se estamos em uma visualização local (modo de edição de grupo)
                    is_in_local_view = False
                    for area in context.screen.areas:
                        if area.type == 'VIEW_3D':
                            if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                                is_in_local_view = True
                                break
                    
                    # Se já estamos em modo de edição, sair primeiro
                    if is_in_local_view:
                        # Sair do modo de edição atual
                        bpy.ops.view3d.localview()
                        
                        # Resetar visibilidade das coleções
                        if not context.preferences.addons[__name__].preferences.use_separate_scene:
                            # Reset visibility of GNGroups collection and all child collections
                            groups_collection = bpy.data.collections.get("GNGroups")
                            if groups_collection:
                                # Hide the main collection
                                groups_collection.hide_viewport = True
                                groups_collection.hide_render = True
                                
                                # Hide all child collections too
                                for child_collection in groups_collection.children:
                                    child_collection.hide_viewport = True
                                    child_collection.hide_render = True
                                
                                # Also update view layer exclude settings if possible
                                view_layer = context.view_layer
                                groups_layer_collection = None
                                for layer_coll in view_layer.layer_collection.children:
                                    if layer_coll.collection == groups_collection:
                                        groups_layer_collection = layer_coll
                                        groups_layer_collection.exclude = True
                                        break
                                        
                                if groups_layer_collection:
                                    for child_layer_coll in groups_layer_collection.children:
                                        child_layer_coll.exclude = True
                    
                    # Selecionar o grupo
                    bpy.ops.object.select_all(action='DESELECT')
                    group_obj.select_set(True)
                    context.view_layer.objects.active = group_obj
                    
                    # Agora editar o grupo
                    # Código adaptado do GROUP_OT_toggle_edit_mode
                    preferences = context.preferences.addons[__name__].preferences
                    group_name = group_obj.name
                    
                    # Find the GN modifier
                    gn_modifier = None
                    for mod in group_obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            gn_modifier = mod
                            break
                    
                    if not gn_modifier or not gn_modifier.node_group:
                        self.report({'WARNING'}, "Invalid group modifier")
                        return {'CANCELLED'}
                    
                    # Find the collection input socket
                    collection_socket = None
                    for input in gn_modifier.node_group.interface.items_tree:
                        if input.bl_socket_idname == 'NodeSocketCollection':
                            collection_socket = input
                            break
                    
                    if not collection_socket:
                        self.report({'WARNING'}, "Could not find collection in node group")
                        return {'CANCELLED'}
                    
                    # Get the group collection
                    group_collection = gn_modifier[collection_socket.identifier]
                    if not group_collection:
                        self.report({'WARNING'}, "Group collection not found")
                        return {'CANCELLED'}
                    
                    if preferences.use_separate_scene:
                        # Legacy mode - go to separate scene
                        groups_scene = bpy.data.scenes.get("GNGroups")
                        if not groups_scene:
                            self.report({'WARNING'}, "Groups scene not found")
                            return {'CANCELLED'}

                        context.window.scene = groups_scene
                        
                        if group_collection:
                            bpy.ops.object.select_all(action='DESELECT')
                            for obj in group_collection.objects:
                                obj.select_set(True)
                            groups_scene.view_layers[0].objects.active = next(iter(group_collection.objects), None)
                            bpy.ops.view3d.localview()
                        else:
                            self.report({'WARNING'}, f"Group collection '{group_name}' not found")
                            return {'CANCELLED'}
                    else:
                        # New mode - use local view in current scene
                        # First make the GNGroups collection and only the target group collection visible temporarily
                        groups_collection = bpy.data.collections.get("GNGroups")
                        if groups_collection:
                            # Store original visibility states
                            was_main_hidden = groups_collection.hide_viewport
                            
                            # Make main collection visible temporarily
                            groups_collection.hide_viewport = False
                            
                            # Set group collection visibility
                            for child_collection in groups_collection.children:
                                # Hide all collections except the one we're editing
                                if child_collection == group_collection:
                                    child_collection.hide_viewport = False
                                else:
                                    child_collection.hide_viewport = True
                                
                            # Update view layer exclude settings
                            view_layer = context.view_layer
                            groups_layer_collection = None
                            group_layer_collection = None
                            
                            for layer_coll in view_layer.layer_collection.children:
                                if layer_coll.collection == groups_collection:
                                    groups_layer_collection = layer_coll
                                    groups_layer_collection.exclude = False
                                    
                                    # Procurar a layer_collection para a collection do grupo
                                    for child_layer_coll in groups_layer_collection.children:
                                        if child_layer_coll.collection == group_collection:
                                            child_layer_coll.exclude = False
                                            group_layer_collection = child_layer_coll
                                        else:
                                            child_layer_coll.exclude = True
                                    break
                            
                            # Ativar a collection do grupo para que novos objetos sejam adicionados a ela
                            if group_layer_collection:
                                # Definir a collection do grupo como ativa
                                context.view_layer.active_layer_collection = group_layer_collection
                            
                            # Select the objects in the group
                            bpy.ops.object.select_all(action='DESELECT')
                            for obj in group_collection.objects:
                                obj.select_set(True)
                            
                            # Set active object from the group
                            context.view_layer.objects.active = next(iter(group_collection.objects), None)
                            
                            # Enter local view
                            bpy.ops.view3d.localview()
                        else:
                            self.report({'WARNING'}, "GNGroups collection not found")
                            return {'CANCELLED'}
                else:
                    self.report({'WARNING'}, f"Could not find group object for '{group_collection.name}'")
                    return {'CANCELLED'}
            
            elif self.action == 'SELECT':
                # Encontrar e selecionar o objeto do grupo
                group_obj = None
                for obj in context.view_layer.objects:
                    if any(f"gng_" in mod.name for mod in obj.modifiers):
                        for mod in obj.modifiers:
                            if f"gng_" in mod.name and mod.type == 'NODES':
                                collection_socket = None
                                for input in mod.node_group.interface.items_tree:
                                    if input.bl_socket_idname == 'NodeSocketCollection':
                                        collection_socket = input
                                        break
                                        
                                if collection_socket and mod[collection_socket.identifier] == group_collection:
                                    group_obj = obj
                                    break
                        if group_obj:
                            break
                
                if group_obj:
                    # Select the group object
                    bpy.ops.object.select_all(action='DESELECT')
                    group_obj.select_set(True)
                    context.view_layer.objects.active = group_obj
                    self.report({'INFO'}, f"Selected group '{group_collection.name}'")
                else:
                    self.report({'WARNING'}, f"Could not find group object for '{group_collection.name}'")
                    return {'CANCELLED'}
            
            elif self.action == 'UNGROUP':
                # O operador Ungroup pode trabalhar diretamente com a collection
                # A lógica antiga procurava pelo objeto de grupo, selecionava e depois chamava bpy.ops.object.ungroup()
                # Vamos adaptar para trabalhar diretamente com a collection, mas ainda buscando o grupo
                group_obj = None
                for obj in context.view_layer.objects:
                    if any(f"gng_" in mod.name for mod in obj.modifiers):
                        for mod in obj.modifiers:
                            if f"gng_" in mod.name and mod.type == 'NODES':
                                collection_socket = None
                                for input in mod.node_group.interface.items_tree:
                                    if input.bl_socket_idname == 'NodeSocketCollection':
                                        collection_socket = input
                                        break
                                        
                                if collection_socket and mod[collection_socket.identifier] == group_collection:
                                    group_obj = obj
                                    break
                        if group_obj:
                            break
                
                if group_obj:
                    # Em vez de selecionar e chamar o operador padrão, vamos usar nossa própria lógica
                    # Get transformation matrix of the group object
                    group_matrix = group_obj.matrix_world.copy()
                    
                    # Obter a coleção alvo - usar a coleção atual do contexto
                    target_collection = context.collection
                    
                    # Create duplicates of all objects and move to target collection
                    new_objects = []
                    for obj in group_collection.objects:
                        # Create a duplicate
                        new_obj = obj.copy()
                        if obj.data:
                            new_obj.data = obj.data.copy()
                            
                        # Apply materials
                        for slot in obj.material_slots:
                            if slot.material:
                                if slot.material.name not in new_obj.data.materials:
                                    new_obj.data.materials.append(slot.material)
                                    
                        # Link to target collection
                        target_collection.objects.link(new_obj)
                        
                        # Apply transformations (group transformation + relative object position)
                        new_obj.matrix_world = group_matrix @ obj.matrix_world
                        
                        new_objects.append(new_obj)
                        all_new_objects.append(new_obj)  # Adicionar à lista global um por um
                        
                    # Select newly created objects
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj in new_objects:
                        obj.select_set(True)
                    context.view_layer.objects.active = new_objects[0] if new_objects else None
                    
                    # Verificar se existem outras instâncias deste grupo
                    has_other_instances = False
                    for obj in context.view_layer.objects:
                        if obj is not None and obj != group_obj and obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers):
                            for mod in obj.modifiers:
                                if f"gng_" in mod.name and mod.type == 'NODES':
                                    collection_socket = None
                                    for input in mod.node_group.interface.items_tree:
                                        if input.bl_socket_idname == 'NodeSocketCollection':
                                            collection_socket = input
                                            break
                                            
                                    if collection_socket and mod[collection_socket.identifier] == group_collection:
                                        has_other_instances = True
                                        break
                        if has_other_instances:
                            break
                    
                    # Remove the group instance
                    bpy.data.objects.remove(group_obj)
                    
                    # Se for a última instância, remover a coleção também
                    if not has_other_instances:
                        # Armazenar o nome da coleção para relatório
                        group_collection_name = group_collection.name
                        # Limpar qualquer referência à coleção antes de removê-la
                        group_collection = None
                        # Agora remover a coleção pelo nome
                        bpy.data.collections.remove(bpy.data.collections.get(group_collection_name))
                        
                        self.report({'INFO'}, f"Group '{group_collection_name}' ungrouped successfully")
                    else:
                        self.report({'INFO'}, f"Group '{group_collection.name}' ungrouped successfully")
                else:
                    self.report({'WARNING'}, f"Could not find group object for '{group_collection.name}'")
                    return {'CANCELLED'}
            
            elif self.action == 'EDIT_NESTED':
                # Este caso lida com a edição de grupos aninhados
                if self.nested_group_index >= 0:
                    # Primeiro, encontrar os objetos de grupo aninhados nesta collection
                    nested_groups = []
                    for obj in group_collection.objects:
                        if any(f"gng_" in mod.name for mod in obj.modifiers):
                            nested_groups.append(obj)
                    
                    if 0 <= self.nested_group_index < len(nested_groups):
                        # Selecionar o grupo aninhado
                        bpy.ops.object.select_all(action='DESELECT')
                        nested_group = nested_groups[self.nested_group_index]
                        nested_group.select_set(True)
                        context.view_layer.objects.active = nested_group
                        
                        # Entrar no modo de edição deste grupo
                        bpy.ops.object.toggle_group_edit_mode()
                        return {'FINISHED'}
                    else:
                        self.report({'WARNING'}, "Invalid nested group index")
                        return {'CANCELLED'}
                else:
                    self.report({'WARNING'}, "No nested group specified")
                    return {'CANCELLED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Error performing action: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

def register():
    bpy.utils.register_class(GNGroupsPreferences)
    bpy.utils.register_class(GROUP_OT_create_group)
    bpy.utils.register_class(GROUP_OT_toggle_edit_mode)
    bpy.utils.register_class(GROUP_OT_ungroup)
    bpy.utils.register_class(GROUP_OT_rename)
    bpy.utils.register_class(GROUP_UL_collections)
    bpy.utils.register_class(GROUP_OT_select_from_list)
    bpy.utils.register_class(GROUP_OT_list_action)
    bpy.utils.register_class(GROUP_OT_toggle_nested_groups)
    bpy.utils.register_class(GROUP_OT_extract_nested_group)
    bpy.utils.register_class(GROUP_OT_quick_ungroup)
    bpy.utils.register_class(VIEW3D_PT_grouping_tools)
    bpy.utils.register_class(SCENE_PT_grouping_tools)
    
    register_active_group_index()

    # Adicione o keymap
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new(GROUP_OT_create_group.bl_idname, 'G', 'PRESS', ctrl=True)
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new(GROUP_OT_toggle_edit_mode.bl_idname, 'TAB', 'PRESS')
        addon_keymaps.append((km, kmi))
        # Adicionar o atalho Ctrl+Shift+G para desagrupar
        kmi = km.keymap_items.new(GROUP_OT_quick_ungroup.bl_idname, 'G', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))
    
    # Registrar os gizmos
    try:
        gn_groups_gizmo.register()
    except Exception as e:
        print(f"Erro ao registrar gizmos: {e}")

def unregister():
    # Desregistrar os gizmos
    try:
        gn_groups_gizmo.unregister()
    except Exception as e:
        print(f"Erro ao desregistrar gizmos: {e}")
        
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(SCENE_PT_grouping_tools)
    bpy.utils.unregister_class(VIEW3D_PT_grouping_tools)
    bpy.utils.unregister_class(GROUP_OT_extract_nested_group)
    bpy.utils.unregister_class(GROUP_OT_toggle_nested_groups)
    bpy.utils.unregister_class(GROUP_OT_list_action)
    bpy.utils.unregister_class(GROUP_OT_select_from_list)
    bpy.utils.unregister_class(GROUP_UL_collections)
    bpy.utils.unregister_class(GROUP_OT_rename)
    bpy.utils.unregister_class(GROUP_OT_ungroup)
    bpy.utils.unregister_class(GROUP_OT_toggle_edit_mode)
    bpy.utils.unregister_class(GROUP_OT_create_group)
    bpy.utils.unregister_class(GROUP_OT_quick_ungroup)
    bpy.utils.unregister_class(GNGroupsPreferences)
    
    unregister_active_group_index()

class GROUP_OT_extract_nested_group(Operator):
    bl_idname = "object.extract_nested_group"
    bl_label = "Extract Nested Group"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Extract a nested group to the current level"
    
    group_index: bpy.props.IntProperty()
    nested_group_index: bpy.props.IntProperty()
    
    def execute(self, context):
        storage_scene, groups_collection = get_gngroups_storage(context, create=False)
        if not groups_collection or not groups_collection.children:
            self.report({'WARNING'}, "No groups found")
            return {'CANCELLED'}
            
        try:
            # Get the parent group collection
            parent_collection = groups_collection.children[self.group_index]
            
            # Find the nested group object within the parent
            nested_group_objects = []
            for obj in parent_collection.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    nested_group_objects.append(obj)
                    
            if not nested_group_objects or self.nested_group_index >= len(nested_group_objects):
                self.report({'WARNING'}, "Nested group not found")
                return {'CANCELLED'}
                
            nested_group_obj = nested_group_objects[self.nested_group_index]
            
            # Get the collection of the nested group
            nested_collection = None
            for mod in nested_group_obj.modifiers:
                if f"gng_" in mod.name and mod.type == 'NODES':
                    # Find the collection input socket
                    collection_socket = None
                    for input in mod.node_group.interface.items_tree:
                        if input.bl_socket_idname == 'NodeSocketCollection':
                            collection_socket = input
                            break
                            
                    if collection_socket:
                        # Get the collection
                        nested_collection = mod[collection_socket.identifier]
                        break
            
            if not nested_collection:
                self.report({'WARNING'}, "Nested group collection not found")
                return {'CANCELLED'}
                
            # Get transformation matrix of the nested group object
            nested_group_matrix = nested_group_obj.matrix_world.copy()
            
            # Create duplicates of all objects in the nested group at the current position
            new_objects = []
            for obj in nested_collection.objects:
                # Create a duplicate
                new_obj = obj.copy()
                if obj.data:
                    new_obj.data = obj.data.copy()
                    
                # Apply materials
                for slot in obj.material_slots:
                    if slot.material:
                        if slot.material.name not in new_obj.data.materials:
                            new_obj.data.materials.append(slot.material)
                            
                # Link to parent collection (onde o grupo estava aninhado)
                parent_collection.objects.link(new_obj)
                
                # Apply transformations (nested group + relative object position)
                new_obj.matrix_world = nested_group_matrix @ obj.matrix_world
                
                new_objects.append(new_obj)
                
            # Select newly created objects
            bpy.ops.object.select_all(action='DESELECT')
            for obj in new_objects:
                obj.select_set(True)
            context.view_layer.objects.active = new_objects[0] if new_objects else None
            
            # Remove the nested group instance from parent collection
            parent_collection.objects.unlink(nested_group_obj)
            
            self.report({'INFO'}, f"Nested group extracted successfully")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Error extracting nested group: {str(e)}")
            return {'CANCELLED'}

class GROUP_OT_quick_ungroup(Operator):
    bl_idname = "object.quick_ungroup"
    bl_label = "Quick Ungroup"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Rápido desagrupamento com atalho de teclado"

    @classmethod
    def poll(cls, context):
        # Em modo de edição local, permitimos desagrupar objetos selecionados
        is_in_local_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    is_in_local_view = True
                    break
                    
        if is_in_local_view:
            # Em modo de edição, permitir desde que haja objetos selecionados
            return len(context.selected_objects) > 0
        
        # Verificar se existe pelo menos um grupo selecionado
        selected_group_objects = [obj for obj in context.selected_objects if any(f"gng_" in mod.name for mod in obj.modifiers)]
        return len(selected_group_objects) > 0 and context.active_object in selected_group_objects

    def execute(self, context):
        # Verificar se estamos em modo de edição (visualização local)
        is_in_local_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                if hasattr(area.spaces[0], 'local_view') and area.spaces[0].local_view:
                    is_in_local_view = True
                    break
                    
        # Comportamento diferente se estiver em modo de edição local
        if is_in_local_view and context.selected_objects:
            # Estamos em modo de edição e há objetos selecionados
            # Desagrupar os objetos selecionados do grupo em edição
            
            # Primeiro, precisamos encontrar qual é o grupo sendo editado
            active_group_collection = None
            storage_scene, groups_collection = get_gngroups_storage(context, create=False)
            if not groups_collection:
                self.report({'WARNING'}, "Coleção de grupos não encontrada")
                return {'CANCELLED'}
                
            # Tentar identificar qual coleção de grupo está sendo editada
            # baseando-se nos objetos selecionados
            for coll in groups_collection.children:
                for obj in context.selected_objects:
                    if obj.name in coll.objects:
                        active_group_collection = coll
                        break
                if active_group_collection:
                    break
                    
            if not active_group_collection:
                self.report({'WARNING'}, "Não foi possível identificar o grupo em edição")
                return {'CANCELLED'}
            
            # Encontrar o objeto do grupo na cena
            group_obj = None
            for obj in context.view_layer.objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == active_group_collection:
                                group_obj = obj
                                break
                if group_obj:
                    break
                    
            if not group_obj:
                self.report({'WARNING'}, "Objeto de grupo não encontrado")
                return {'CANCELLED'}
            
            # Verificar se existem outras instâncias deste grupo
            has_other_instances = False
            for obj in context.view_layer.objects:
                if obj is not None and obj != group_obj and obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == active_group_collection:
                                has_other_instances = True
                                break
                if has_other_instances:
                    break
            
            # Get transformation matrix of the group object
            group_matrix = group_obj.matrix_world.copy()
            
            # Obter a coleção onde os objetos desagrupados serão movidos
            # Será a coleção do usuário atual, fora da coleção GNGroups
            target_collection = context.scene.collection
            for coll in context.view_layer.layer_collection.children:
                if coll.collection != groups_collection and coll.collection.library is None:
                    # Encontrar a primeira coleção visível que não é a GNGroups
                    if not coll.exclude:
                        target_collection = coll.collection
                        break
            
            # Se houver mais instâncias, criar cópias e mover
            # Caso contrário, mover diretamente
            selected_objects = context.selected_objects.copy()
            for obj in selected_objects:
                if obj.name in active_group_collection.objects:
                    if has_other_instances:
                        # Criar uma cópia
                        new_obj = obj.copy()
                        if obj.data:
                            new_obj.data = obj.data.copy()
                            
                        # Aplicar materiais
                        for slot in obj.material_slots:
                            if slot.material:
                                if slot.material.name not in new_obj.data.materials:
                                    new_obj.data.materials.append(slot.material)
                                    
                        # Aplicar transformações (grupo + posição relativa do objeto)
                        new_obj.matrix_world = group_matrix @ obj.matrix_world
                        
                        # Adicionar à coleção alvo
                        target_collection.objects.link(new_obj)
                    else:
                        # Caso não haja outras instâncias, mover diretamente
                        # Remover da coleção atual
                        active_group_collection.objects.unlink(obj)
                        
                        # Aplicar transformações
                        obj.matrix_world = group_matrix @ obj.matrix_world
                        
                        # Adicionar à coleção alvo
                        target_collection.objects.link(obj)
            
            # Se não houver outras instâncias e não sobrar nenhum objeto no grupo,
            # podemos remover completamente o grupo
            if not has_other_instances and len(active_group_collection.objects) == 0:
                bpy.data.objects.remove(group_obj)
                # Armazenar o nome da coleção antes de removê-la
                collection_name = active_group_collection.name
                # Limpar referências
                active_group_collection = None
                # Remover a coleção pelo nome
                bpy.data.collections.remove(bpy.data.collections.get(collection_name))
                
                self.report({'INFO'}, f"Group '{collection_name}' ungrouped successfully")
            else:
                self.report({'INFO'}, f"Group '{active_group_collection.name}' ungrouped successfully")
            
            return {'FINISHED'}
        
        # Código para desagrupar grupos quando não estamos em modo de edição local
        # Verificar se há grupos selecionados
        selected_group_objects = [obj for obj in context.selected_objects 
                                if obj is not None and obj.modifiers and 
                                any(f"gng_" in mod.name for mod in obj.modifiers)]
        
        if not selected_group_objects:
            # Sem grupos selecionados, manter comportamento padrão
            return {'PASS_THROUGH'}
            
        # Desagrupar cada grupo selecionado
        ungrouped_count = 0
        all_new_objects = []  # Lista para armazenar todos os novos objetos criados
        
        for active_obj in selected_group_objects:
            # Get the group modifier
            gn_modifier = None
            for mod in active_obj.modifiers:
                if f"gng_" in mod.name and mod.type == 'NODES':
                    gn_modifier = mod
                    break
                    
            if not gn_modifier or not gn_modifier.node_group:
                continue
                
            # Find the collection input socket
            collection_socket = None
            for input in gn_modifier.node_group.interface.items_tree:
                if input.bl_socket_idname == 'NodeSocketCollection':
                    collection_socket = input
                    break
                    
            if not collection_socket:
                continue
                
            # Get the group collection
            group_collection = gn_modifier[collection_socket.identifier]
            if not group_collection:
                continue
                
            # Get transformation matrix of the group object
            group_matrix = active_obj.matrix_world.copy()
            
            # Obter a coleção alvo - usar a coleção atual do contexto
            target_collection = context.collection
            
            # Create duplicates of all objects in the group at the current position
            group_new_objects = []  # Lista temporária para objetos deste grupo
            
            for obj in group_collection.objects:
                # Create a duplicate
                new_obj = obj.copy()
                if obj.data:
                    new_obj.data = obj.data.copy()
                    
                # Apply materials
                for slot in obj.material_slots:
                    if slot.material:
                        if slot.material.name not in new_obj.data.materials:
                            new_obj.data.materials.append(slot.material)
                            
                # Link to target collection
                target_collection.objects.link(new_obj)
                
                # Apply transformations (group transformation + relative object position)
                new_obj.matrix_world = group_matrix @ obj.matrix_world
                
                # Adicionar à lista temporária e à lista global
                group_new_objects.append(new_obj)
                all_new_objects.append(new_obj)
                
            # Verificar se existem outras instâncias deste grupo
            has_other_instances = False
            for obj in context.view_layer.objects:
                if obj is not None and obj != active_obj and obj.modifiers and any(f"gng_" in mod.name for mod in obj.modifiers):
                    for mod in obj.modifiers:
                        if f"gng_" in mod.name and mod.type == 'NODES':
                            collection_socket = None
                            for input in mod.node_group.interface.items_tree:
                                if input.bl_socket_idname == 'NodeSocketCollection':
                                    collection_socket = input
                                    break
                                    
                            if collection_socket and mod[collection_socket.identifier] == group_collection:
                                has_other_instances = True
                                break
                if has_other_instances:
                    break
            
            # Remove the group instance
            group_name = active_obj.name
            bpy.data.objects.remove(active_obj)
            
            # Se for a última instância, remover a coleção também
            if not has_other_instances:
                # Armazenar o nome da coleção para relatório
                group_collection_name = group_collection.name
                # Limpar qualquer referência à coleção antes de removê-la
                group_collection = None
                # Agora remover a coleção pelo nome
                bpy.data.collections.remove(bpy.data.collections.get(group_collection_name))
            
            ungrouped_count += 1
        
        # Select newly created objects after processing all groups
        if all_new_objects:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in all_new_objects:
                obj.select_set(True)
            context.view_layer.objects.active = all_new_objects[0]
        
        if ungrouped_count > 0:
            self.report({'INFO'}, f"{ungrouped_count} grupos desagrupados com sucesso")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Nenhum grupo válido para desagrupar")
            return {'CANCELLED'}

if __name__ == "__main__":
    register()