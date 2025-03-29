import bpy
import bmesh
from bpy.types import (
    Gizmo,
    GizmoGroup,
)
from mathutils import Vector, Matrix

# Gera os vértices e arestas para uma forma de cantoneira em L
# como sugerido pelo usuário
def create_corner_shape():
    # Cantos do cubo unitário
    corners = [
        (-1, -1, -1),  # 0: frente inferior esquerdo
        (1, -1, -1),   # 1: frente inferior direito
        (-1, 1, -1),   # 2: traseira inferior esquerdo
        (1, 1, -1),    # 3: traseira inferior direito
        (-1, -1, 1),   # 4: frente superior esquerdo
        (1, -1, 1),    # 5: frente superior direito
        (-1, 1, 1),    # 6: traseira superior esquerdo
        (1, 1, 1),     # 7: traseira superior direito
    ]
    
    # Função para calcular o offset para "dentro" do cubo
    def offset(coord):
        if coord == -1:
            return 0.3
        else:
            return -0.3
    
    verts = []
    
    # Para cada canto, criar 3 arestas formando um L
    for i, corner in enumerate(corners):
        # Vértice base (o próprio canto)
        base = corner
        
        # Vértices nas pontas dos "braços" do L
        vx = (corner[0] + offset(corner[0]), corner[1], corner[2])
        vy = (corner[0], corner[1] + offset(corner[1]), corner[2])
        vz = (corner[0], corner[1], corner[2] + offset(corner[2]))
        
        # Adicionar as arestas do L no formato de pares de vértices para o tipo 'LINES'
        verts.append(base)
        verts.append(vx)
        
        verts.append(base)
        verts.append(vy)
        
        verts.append(base)
        verts.append(vz)
    
    return verts

# Criar os vértices para o shape personalizado
corner_verts = create_corner_shape()

class GNGroupBoundingBoxGizmo(Gizmo):
    bl_idname = "VIEW3D_GT_gn_group_bbox"
    
    __slots__ = (
        "custom_shape",
        "group_object",
        "original_matrix",
    )
    
    def setup(self):
        if not hasattr(self, "custom_shape"):
            self.custom_shape = self.new_custom_shape('LINES', corner_verts)
        
        # Desativar completamente o escalonamento
        self.use_draw_scale = False
        self.use_draw_offset_scale = False
        self.line_width = 1.0
    
    def draw(self, context):
        # Desenhar o gizmo com tamanho absoluto no espaço 3D
        self.draw_custom_shape(self.custom_shape)
    
    def draw_select(self, context, select_id):
        self.draw_custom_shape(self.custom_shape, select_id=select_id)


class GNGroupBoundingBoxGizmoGroup(GizmoGroup):
    bl_idname = "OBJECT_GGT_gn_group_bbox"
    bl_label = "GN Group Bounding Box"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}
    
    @classmethod
    def poll(cls, context):
        # Verificar se há pelo menos um objeto selecionado que é um grupo GN
        if context.selected_objects:
            for obj in context.selected_objects:
                if any(f"gng_" in mod.name for mod in obj.modifiers):
                    return True
        return False
    
    def setup(self, context):
        # Encontrar todos os objetos de grupo selecionados
        self.gizmos_dict = {}
        
        for obj in context.selected_objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                self.create_gizmo_for_group(obj)
    
    def create_gizmo_for_group(self, group_obj):
        # Calcular o bounding box do grupo
        bbox_min, bbox_max = self.calculate_group_bbox(group_obj)
        
        # Expandir ligeiramente o bounding box
        expand_factor = 0.05  # 5% maior
        bbox_size = Vector((
            max(0.01, bbox_max[0] - bbox_min[0]),
            max(0.01, bbox_max[1] - bbox_min[1]),
            max(0.01, bbox_max[2] - bbox_min[2])
        ))
                
        expand = Vector((
            bbox_size[0] * expand_factor,
            bbox_size[1] * expand_factor,
            bbox_size[2] * expand_factor
        ))
        
        bbox_min -= expand
        bbox_max += expand
        
        # Calcular centro e escala
        center = (bbox_min + bbox_max) / 2
        scale = Vector((
            (bbox_max[0] - bbox_min[0]) / 2,
            (bbox_max[1] - bbox_min[1]) / 2,
            (bbox_max[2] - bbox_min[2]) / 2
        ))
        
        # Criar um único gizmo para o bounding box
        gz = self.gizmos.new(GNGroupBoundingBoxGizmo.bl_idname)
        gz.group_object = group_obj
        
        # Configurar matriz de transformação
        translation_matrix = Matrix.Translation(center)
        scale_matrix = Matrix.Diagonal(scale.to_4d())
        
        # Combinar as transformações
        gz.matrix_basis = translation_matrix @ scale_matrix
        
        # Desabilitar completamente o escalonamento automático
        gz.use_draw_scale = False
        gz.use_draw_offset_scale = False
        
        # Definir a cor magenta (mais saturada)
        gz.color = 1.0, 0.0, 1.0
        gz.alpha = 1.0  # Totalmente visível
        
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
        
        # Armazenar o gizmo
        self.gizmos_dict[group_obj.name] = gz
    
    def calculate_group_bbox(self, group_obj):
        """Calcular o bounding box de um grupo, considerando grupos aninhados"""
        # Inicializar com valores extremos
        bbox_min = Vector((float('inf'), float('inf'), float('inf')))
        bbox_max = Vector((float('-inf'), float('-inf'), float('-inf')))
        
        # Obter a coleção do grupo
        group_collection = self.get_group_collection(group_obj)
        
        # Se não encontrou uma coleção, usar o próprio objeto
        if not group_collection:
            return self.get_object_bbox(group_obj)
        
        # Processar todos os objetos da coleção, incluindo grupos aninhados
        self.process_collection_for_bbox(group_collection, group_obj.matrix_world, bbox_min, bbox_max)
        
        # Se não encontrou objetos válidos, usar o bounding box do próprio objeto de grupo
        if bbox_min.x == float('inf'):
            return self.get_object_bbox(group_obj)
        
        return bbox_min, bbox_max
    
    def process_collection_for_bbox(self, collection, parent_matrix, bbox_min, bbox_max):
        """Processa todos os objetos de uma coleção para o cálculo do bbox, incluindo grupos aninhados"""
        for obj in collection.objects:
            # Se for um grupo aninhado
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                # Obter a coleção do grupo aninhado
                nested_collection = self.get_group_collection(obj)
                if nested_collection:
                    # Calcular a matriz combinada para o grupo aninhado
                    combined_matrix = parent_matrix @ obj.matrix_world
                    # Processar recursivamente os objetos do grupo aninhado
                    self.process_collection_for_bbox(nested_collection, combined_matrix, bbox_min, bbox_max)
            
            # Para objetos regulares
            elif hasattr(obj, 'bound_box'):
                # Transformação combinada
                combined_matrix = parent_matrix @ obj.matrix_world
                
                # Atualizar o bounding box
                for corner in obj.bound_box:
                    world_corner = combined_matrix @ Vector(corner)
                    
                    # Atualizar mínimos e máximos
                    bbox_min.x = min(bbox_min.x, world_corner.x)
                    bbox_min.y = min(bbox_min.y, world_corner.y)
                    bbox_min.z = min(bbox_min.z, world_corner.z)
                    
                    bbox_max.x = max(bbox_max.x, world_corner.x)
                    bbox_max.y = max(bbox_max.y, world_corner.y)
                    bbox_max.z = max(bbox_max.z, world_corner.z)
    
    def get_group_collection(self, group_obj):
        """Obter a coleção de um grupo"""
        for mod in group_obj.modifiers:
            if f"gng_" in mod.name and mod.type == 'NODES':
                for input in mod.node_group.interface.items_tree:
                    if input.bl_socket_idname == 'NodeSocketCollection':
                        return mod[input.identifier]
        return None
    
    def get_object_bbox(self, obj):
        """Obter o bounding box de um único objeto"""
        # Usar a matriz world para transformar os cantos do bound_box
        bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        
        # Encontrar os valores mínimos e máximos
        bbox_min = Vector((
            min(corner.x for corner in bbox_corners),
            min(corner.y for corner in bbox_corners),
            min(corner.z for corner in bbox_corners)
        ))
        
        bbox_max = Vector((
            max(corner.x for corner in bbox_corners),
            max(corner.y for corner in bbox_corners),
            max(corner.z for corner in bbox_corners)
        ))
        
        return bbox_min, bbox_max
    
    def refresh(self, context):
        # Remover gizmos de objetos não mais selecionados
        for obj_name in list(self.gizmos_dict.keys()):
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj not in context.selected_objects:
                # Remover gizmo
                self.gizmos.remove(self.gizmos_dict[obj_name])
                del self.gizmos_dict[obj_name]
        
        # Adicionar ou atualizar gizmos para objetos selecionados
        for obj in context.selected_objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                if obj.name not in self.gizmos_dict:
                    # Novo objeto selecionado
                    self.create_gizmo_for_group(obj)
                else:
                    # Atualizar gizmo existente
                    self.gizmos.remove(self.gizmos_dict[obj.name])
                    self.create_gizmo_for_group(obj)

# Operador para desenhar diretamente o bounding box (como backup)
class GNGroupBoundingBoxOperator(bpy.types.Operator):
    bl_idname = "object.gn_group_draw_bbox"
    bl_label = "Display Group Bounding Box"
    
    _handle = None
    
    @classmethod
    def poll(cls, context):
        return True
    
    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
            
        return {'PASS_THROUGH'}
    
    def invoke(self, context, event):
        args = (self, context)
        self.__class__._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_bbox_callback, args, 'WINDOW', 'POST_VIEW')
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def draw_bbox_callback(self, context):
        """Desenhar o bounding box para todos os grupos selecionados"""
        import gpu
        from gpu_extras.batch import batch_for_shader
        
        # Shader básico
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
        
        for obj in context.selected_objects:
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                self.draw_group_bbox(context, obj, shader)
    
    def draw_group_bbox(self, context, group_obj, shader):
        """Desenhar o bounding box para um grupo específico"""
        # Inicializar com valores extremos
        bbox_min = Vector((float('inf'), float('inf'), float('inf')))
        bbox_max = Vector((float('-inf'), float('-inf'), float('-inf')))
        
        # Obter a coleção do grupo
        group_collection = None
        for mod in group_obj.modifiers:
            if f"gng_" in mod.name and mod.type == 'NODES':
                for input in mod.node_group.interface.items_tree:
                    if input.bl_socket_idname == 'NodeSocketCollection':
                        group_collection = mod[input.identifier]
                        break
                if group_collection:
                    break
        
        if not group_collection:
            # Usar o bounding box do próprio objeto
            bbox_corners = [group_obj.matrix_world @ Vector(corner) for corner in group_obj.bound_box]
            bbox_min = Vector((min(c.x for c in bbox_corners), min(c.y for c in bbox_corners), min(c.z for c in bbox_corners)))
            bbox_max = Vector((max(c.x for c in bbox_corners), max(c.y for c in bbox_corners), max(c.z for c in bbox_corners)))
        else:
            # Processar a coleção recursivamente
            self.process_collection_for_bbox(context, group_collection, group_obj.matrix_world, bbox_min, bbox_max)
            
            # Se não encontrou objetos válidos, usar o bounding box do próprio objeto
            if bbox_min.x == float('inf'):
                bbox_corners = [group_obj.matrix_world @ Vector(corner) for corner in group_obj.bound_box]
                bbox_min = Vector((min(c.x for c in bbox_corners), min(c.y for c in bbox_corners), min(c.z for c in bbox_corners)))
                bbox_max = Vector((max(c.x for c in bbox_corners), max(c.y for c in bbox_corners), max(c.z for c in bbox_corners)))
        
        # Expandir ligeiramente o bounding box
        expand_factor = 0.05
        bbox_size = Vector((
            max(0.01, bbox_max[0] - bbox_min[0]),
            max(0.01, bbox_max[1] - bbox_min[1]),
            max(0.01, bbox_max[2] - bbox_min[2])
        ))
        
        expand = Vector((
            bbox_size[0] * expand_factor,
            bbox_size[1] * expand_factor,
            bbox_size[2] * expand_factor
        ))
        
        bbox_min -= expand
        bbox_max += expand
        
        # Desenhar as cantoneiras em vez do wireframe completo
        vertices = []
        
        # Cantos do bounding box
        corners = [
            Vector((bbox_min[0], bbox_min[1], bbox_min[2])),
            Vector((bbox_max[0], bbox_min[1], bbox_min[2])),
            Vector((bbox_min[0], bbox_max[1], bbox_min[2])),
            Vector((bbox_max[0], bbox_max[1], bbox_min[2])),
            Vector((bbox_min[0], bbox_min[1], bbox_max[2])),
            Vector((bbox_max[0], bbox_min[1], bbox_max[2])),
            Vector((bbox_min[0], bbox_max[1], bbox_max[2])),
            Vector((bbox_max[0], bbox_max[1], bbox_max[2])),
        ]
        
        # Função para calcular o offset para "dentro" do cubo
        def offset(value, is_min):
            edge_length = min(bbox_size) * 0.3
            if is_min:
                return edge_length
            else:
                return -edge_length
        
        # Para cada canto, criar 3 arestas formando um L
        for i, corner in enumerate(corners):
            # Determine se cada coordenada é mínima ou máxima
            is_min_x = corner.x == bbox_min.x
            is_min_y = corner.y == bbox_min.y
            is_min_z = corner.z == bbox_min.z
            
            # Criar os vértices das pontas dos "braços" do L
            vx = Vector((
                corner.x + offset(corner.x, is_min_x),
                corner.y,
                corner.z
            ))
            
            vy = Vector((
                corner.x,
                corner.y + offset(corner.y, is_min_y),
                corner.z
            ))
            
            vz = Vector((
                corner.x,
                corner.y,
                corner.z + offset(corner.z, is_min_z)
            ))
            
            # Adicionar as arestas do L
            vertices.extend([corner, vx])
            vertices.extend([corner, vy])
            vertices.extend([corner, vz])
        
        # Desenhar as linhas
        batch = batch_for_shader(shader, 'LINES', {"pos": vertices})
        
        # Cor magenta
        color = (1.0, 0.0, 1.0, 1.0)
        
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
    
    def process_collection_for_bbox(self, context, collection, parent_matrix, bbox_min, bbox_max):
        """Processa todos os objetos de uma coleção para o cálculo do bbox, incluindo grupos aninhados"""
        for obj in collection.objects:
            # Se for um grupo aninhado
            if any(f"gng_" in mod.name for mod in obj.modifiers):
                # Obter a coleção do grupo aninhado
                nested_collection = None
                for mod in obj.modifiers:
                    if f"gng_" in mod.name and mod.type == 'NODES':
                        for input in mod.node_group.interface.items_tree:
                            if input.bl_socket_idname == 'NodeSocketCollection':
                                nested_collection = mod[input.identifier]
                                break
                        if nested_collection:
                            break
                
                if nested_collection:
                    # Calcular a matriz combinada para o grupo aninhado
                    combined_matrix = parent_matrix @ obj.matrix_world
                    # Processar recursivamente os objetos do grupo aninhado
                    self.process_collection_for_bbox(context, nested_collection, combined_matrix, bbox_min, bbox_max)
            
            # Para objetos regulares
            elif hasattr(obj, 'bound_box'):
                # Transformação combinada
                combined_matrix = parent_matrix @ obj.matrix_world
                
                # Atualizar o bounding box
                for corner in obj.bound_box:
                    world_corner = combined_matrix @ Vector(corner)
                    
                    # Atualizar mínimos e máximos
                    bbox_min.x = min(bbox_min.x, world_corner.x)
                    bbox_min.y = min(bbox_min.y, world_corner.y)
                    bbox_min.z = min(bbox_min.z, world_corner.z)
                    
                    bbox_max.x = max(bbox_max.x, world_corner.x)
                    bbox_max.y = max(bbox_max.y, world_corner.y)
                    bbox_max.z = max(bbox_max.z, world_corner.z)


classes = (
    GNGroupBoundingBoxGizmo,
    GNGroupBoundingBoxGizmoGroup,
    GNGroupBoundingBoxOperator,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Iniciar o operador de desenho
    bpy.ops.object.gn_group_draw_bbox('INVOKE_DEFAULT')

def unregister():
    # Remover o handler de desenho
    if GNGroupBoundingBoxOperator._handle:
        bpy.types.SpaceView3D.draw_handler_remove(GNGroupBoundingBoxOperator._handle, 'WINDOW')
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
