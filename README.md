# GN Groups

GN Groups is a Blender extension that creates editable object groups backed by Geometry Nodes collections.

## Current status

This repository is now structured as a Blender **Extension** package instead of a legacy single-file add-on:

- `blender_manifest.toml` provides the extension metadata required by Blender's Extensions system.
- `__init__.py` contains the extension entry point and operator/panel registration.
- `gn_groups_gizmo.py` contains the optional viewport gizmo implementation.
- `group_node_tree.blend` stores the Geometry Nodes group used by generated instances.

## Supported Blender versions

- **Blender 4.2+** for installation through the Extensions system.
- Targeted and documented against the Blender 5.1 extension workflow.

## Features

### Group creation

- Create a GN Group from the current selection with `Ctrl+G`.
- The extension moves grouped objects into a hidden storage collection and creates a lightweight controller object with a Geometry Nodes modifier.
- Relative transforms are preserved when the group is created.

### Group editing

- Select a group and press `Tab` to enter or leave group edit mode.
- Edits made inside the stored collection affect every instance of that group.

### Nested groups

- Groups can contain other groups.
- Nested groups can be edited and extracted from the group list UI.
- Basic cycle detection is performed when creating nested structures.

### Ungrouping

- `Ctrl+Shift+G` removes a group instance.
- When used while editing a group, selected objects can be extracted back to the scene.

## Preferences

Open `Edit > Preferences > Extensions > GN Groups`:

- **Use Separate Scene**: legacy storage mode that keeps groups in a dedicated scene named `GNGroups`.
- **Show Group Gizmo**: displays the magenta bounding-box gizmo for selected GN Groups. This option is **disabled by default**.

## Installation

1. Package the repository contents as a zip file, keeping `blender_manifest.toml` at the root of the archive.
2. In Blender, open `Edit > Preferences > Extensions`.
3. Use **Install from Disk** and select the zip file.
4. Enable **GN Groups** in the Extensions list.

## Expected behavior

- Group contents are stored in a hidden `GNGroups` collection by default.
- Disabling the extension unregisters operators, panels, keymaps, and gizmo classes without relying on a persistent viewport draw handler.
- The gizmo only appears when the preference toggle is enabled.

## Notes

- Existing groups are not migrated automatically when switching between collection storage and separate-scene storage.
- The included gizmo is intentionally optional to keep the default viewport behavior lightweight.

## Credits

Developed by Henrique Miranda.
