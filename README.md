# GN Groups  

## Overview  
GN Groups is a smarter, snappier way to handle object groups in Blender—powered by Geometry Nodes. It builds on Blender's collection system but with some extra magic to make your workflow smoother and more intuitive.  

## Features  

### Easy grouping:  
Select some objects, hit the button, and boom—instant group, keeping all transformations intact. Each group acts like an instance wrapped in a Geometry Nodes setup. Behind the scenes, we’re just tossing everything into a hidden collection and letting GN do the heavy lifting. The best part? You can stack as many modifiers on top as you want—go wild!  

<img src="https://i.imgur.com/x1bBTN0.gif" width="500">
<img src="https://i.imgur.com/9tRJGQl.gif" width="500">  

### Group editing:  
Need to tweak a group? Just press `Tab` to jump into edit mode and adjust whatever you want, right in the scene. Changes apply to all instances of the group, so no need for tedious manual updates.  

### Nested groups:  
Groups inside groups? No problem. Stack them up, mix and match, and even swap materials on the fly—without diving into edit mode. And yes, this still works even if you throw in new objects or materials later!  

## Compatibility
- Blender 2.80 or higher
- Requires Geometry Nodes support (native in recent Blender versions)

## Installation
1. Download the addon zip file
2. In Blender, go to `Edit > Preferences > Add-ons > Install`
3. Select the downloaded zip file
4. Activate the addon by checking the checkbox

## Main Features

### Creating Groups
To create a group:
1. Select the objects you want to group
2. Use the `Ctrl+G` shortcut or execute the "Create Group" command via menu
3. Name your group and confirm

### Editing Groups
To edit a group:
1. Select the group in the viewport
2. Press `Tab` to enter the group's edit mode
3. Modify the objects within the group
4. Press `Tab` again to exit edit mode

### Nested Groups
To create nested groups:
1. Enter a group's edit mode (`Tab`)
2. Select objects within the group
3. Create a new group (`Ctrl+G`)
4. To navigate the group hierarchy, use `Tab` to enter/exit levels

### Ungrouping
To ungroup:
1. Select a group
2. Use the `Ctrl+Shift+G` shortcut to completely ungroup
3. Alternatively, in group edit mode, select specific objects and use `Ctrl+Shift+G` to extract them

## Keyboard Shortcuts
- `Ctrl+G`: Create a new group from selected objects
- `Tab`: Enter/exit group edit mode
- `Ctrl+Shift+G`: Quick ungroup

## How It Works
- The addon creates a special collection called "GNGroups" to store all groups
- Each group is represented by an object with a single vertex and a Geometry Nodes modifier
- The Geometry Nodes modifier links the group object to its corresponding collection
- When you edit a group, the addon uses Blender's local view to isolate the group's objects
- Transformations applied to the group object affect all objects contained within it

## Preferences
The addon offers configuration options in `Edit > Preferences > Add-ons > GN Groups`:
- **Use Separate Scene**: Enable this option to store groups in a separate scene (legacy mode) instead of using collections in the current scene (default)

## Technical Notes
- Groups are stored in a special collection named "GNGroups"
- Each group uses a Geometry Nodes modifier to control its instances
- Relative transformations of objects are preserved when grouped
- The addon checks for cyclicity to prevent circular references between groups

## Credits
Developed by Henrique Miranda

## Version
2.4.1
