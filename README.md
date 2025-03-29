
# GN Groups

## Overview
GN Groups is an advanced grouping addon for Blender that uses Geometry Nodes to create and manage object groups with extended functionality beyond Blender's standard collection system.

## Features
- **Smart grouping**: Create groups from selected objects while preserving all relative transformations
- **Nested groups**: Support for groups within groups, creating complex hierarchies
- **Group editing**: Easily enter a group's edit mode to modify its components
- **Group instancing**: Each group functions as an instance with Geometry Nodes
- **Materials**: Automatic preservation of materials between group instances

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