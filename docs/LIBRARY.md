# Space and segment management

Use the pencil beside the space title to rename a space. Names are trimmed and limited to 80 characters. Renaming updates the catalog and space manifest, preserving IDs, paths, recordings, maps and backup associations. Existing cloud upload metadata is unchanged.

The trash icon in each recording row removes a local segment whose backup is not marked complete. The confirmation identifies the segment and warns that its raw recording, generated maps and local upload staging copies will be permanently removed. Imported source files and remote cloud data are preserved. No recorded data is deleted merely by installing this update.

Deletion is refused while the segment is recording, importing, uploading, replaying or generating a map. Segments in the current recording session are also protected. The backend repeats these checks under the same locks used to start those operations, including when state changes while the confirmation is open. Backed-up segments are protected regardless of which cloud account is signed in.

Files are moved atomically into a unique `.deleting` folder before catalog removal; database failures restore moved files. Disk cleanup runs outside robot control locks. If cleanup fails, the UI reports the residual folder so its disk space can be reclaimed. The operation never sends a robot command or a cloud delete request.

Validation: 90 backend tests, 13 frontend tests, production build and Ruff pass. Dialog layout and space renaming were checked in an isolated browser preview. Physical server activation remains separate and follows the stop, save and disconnect sequence in AGENTS.md.
