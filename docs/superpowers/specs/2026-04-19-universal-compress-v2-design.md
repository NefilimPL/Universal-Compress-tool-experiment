# Universal Compress V2 Design

Date: 2026-04-19
Status: Approved in conversation, written for final user review

## Summary

Universal Compress V2 will replace the current Tkinter prototype with a Windows-first desktop application built on PySide6/Qt. The product will act as a universal file compression suite with an embedded multimedia studio, not as a media-only tool.

The new default path is a polished native archive format named `*.uca` (`Universal Compress Archive`). Standard formats such as ZIP or 7z remain optional import/export helpers, but they do not define the architecture. Backward compatibility with the current `*.pylc` format is optional and must only be added if it does not constrain the new system.

The core goals are:

- modern desktop UX with drag and drop
- batch processing for files and folders
- strong archive inspection without full extraction
- clear protection modes with honest explanations of cost and security
- separate but integrated media compression workflows for video and audio
- better performance, reliability, and task management than the current app

## Product Direction

The chosen direction is a full rewrite delivered in phases on top of a new architecture. Three options were considered during brainstorming:

1. Full rewrite in a modern GUI stack
2. Partial rewrite with adapters over the old code
3. Incremental evolution of the Tkinter codebase

The selected option is `1`.

This was chosen because the requested scope includes a new visual identity, batch flows, drag and drop, a richer archive format, stronger protection modes, multimedia tooling, and better operational feedback. Those features would be awkward and fragile if built on top of the current Tkinter structure, which mixes UI orchestration with compression logic and assumes single-file workflows in multiple places.

## Platform and Packaging

- Primary target platform: Windows only
- Desktop stack: PySide6/Qt
- Media tooling: FFmpeg and FFprobe integration
- Packaging direction: native Windows desktop distribution for a single-user local workflow

Restricting the product to Windows simplifies drag and drop behavior, shell integration, installer strategy, task execution assumptions, and the design language.

## High-Level Architecture

The application will be split into focused modules with clear boundaries:

- `App Shell`: main window, navigation, settings, global actions, notifications, theming
- `Job Engine`: queued execution, progress reporting, cancellation, task history, background work orchestration
- `Universal Archive Engine`: native `*.uca` archive creation, extraction, inspection, verification, manifest/index handling
- `Standard Format Adapters`: optional import/export support for common formats such as ZIP/7z
- `Media Studio Engine`: audio/video analysis and FFmpeg-based transcode pipelines
- `Preview and Metadata Indexer`: fast listing of archive contents and lightweight metadata access
- `Security Layer`: password gate mode, full encryption mode, and the user-facing explanation of their tradeoffs
- `Compatibility Adapters`: isolated compatibility code for old formats only if low-risk

This separation keeps the new GUI from directly owning compression logic and allows batch operations, archive inspection, and media processing to share the same job model without turning into one monolithic file.

## Main User Experience

The application should open into a single coherent workspace instead of the current tab split between file, text, and decode modes.

Recommended layout:

- left panel: source list and active queue
- center panel: current task workspace
- right panel: inspector with settings, cost hints, and consequences
- bottom area: live task status, logs, and recent history

Primary user journeys:

1. Create archive
   - drag files or folders into the app
   - choose native archive, media workflow, or standard export
   - review settings
   - run now or send to queue

2. Open archive
   - inspect manifest and file tree without full extraction
   - unlock protected content if required
   - extract selected items or everything
   - run verification if needed

3. Batch processing
   - queue multiple jobs
   - apply one profile to many items or customize per selection
   - monitor progress, pause future tasks, or cancel active tasks

4. Multimedia workflow
   - detect video/audio inputs automatically
   - surface task-specific presets and device cost estimates
   - keep media processing inside the same product, not as a separate app

The interface should support both a simple and advanced mode. Simple mode emphasizes presets and explanations. Advanced mode exposes more technical options without overwhelming default users.

## Native Archive Format

The new default archive format will be `*.uca`.

The format should be designed for application-level workflows, not only raw compression ratio. It must support:

- multiple files and folders in one archive
- preserved relative paths
- a manifest and index for fast archive inspection
- per-entry metadata such as size, timestamps, media hints, and storage method
- archive-level metadata such as format version, creation details, and protection mode
- room for future extension without breaking the parser model

The format should use block-oriented storage so that large files can be processed in streaming mode. The index should make it possible to show archive contents quickly, even before extraction. For already compressed file types, the system may choose to store, lightly compress, or warn the user when aggressive compression is unlikely to help.

Standard formats stay available as helper exports, but `*.uca` remains the primary and most capable mode.

## Protection and Security Model

Two protection paths will be supported, both clearly explained in the UI:

1. `App password gate`
   - lightweight protection
   - intended for convenience and casual access control
   - not presented as strong cryptographic security

2. `Full encryption`
   - protects archive data and sensitive metadata
   - requires a password before indexed content can be inspected
   - increases processing time and hardware use

The UI must explain what each mode means in plain language, including:

- what is actually protected
- whether the mode is convenience or real security
- how much extra time the user should expect
- what higher CPU, disk, or memory usage may look like on large jobs

Protected archives should still support archive inspection after successful authentication, without requiring full extraction of all contents.

## Archive Inspection and Preview

The requested preview feature is defined as archive-content inspection, not media playback preview.

The app must allow the user to:

- open an archive and inspect its file/folder structure
- view names, paths, sizes, timestamps, compression state, and protection state
- inspect protected archives after successful password entry
- extract selected items instead of always extracting everything
- run a quick integrity verification pass

This means the archive index and manifest are first-class design requirements, not optional metadata.

## Media Studio

Media support is an integrated subsystem, but it must not distort the universal archive workflow.

The media engine will handle:

- video transcode presets such as `Web`, `Balanced`, `Small`, `Archive Master`, and `Fast Convert`
- audio presets tuned for speech, music, mixed content, and space-saving export
- source analysis for codec, duration, bitrate, resolution, tracks, and compatibility hints
- batch media jobs with shared or per-item settings
- simple and advanced views, where advanced mode exposes deeper FFmpeg-oriented controls

Each profile should carry plain-language feedback about:

- expected output intent
- likely time cost
- likely CPU and disk pressure
- quality implications

Media processing should be executed by the same job engine used by archive tasks, but remain its own subsystem internally.

## Performance and Reliability

The new application must improve operational quality as much as visuals.

Required characteristics:

- queued background tasks instead of direct UI-bound execution
- streaming and block-based processing for large files
- safe temporary output files followed by atomic replacement
- cancellation support
- progress reporting per task and per batch
- clear logs for technical diagnosis
- user-facing errors written in plain language
- preflight analysis for suspiciously expensive or low-value operations

The system should surface estimated cost levels such as `Low`, `Medium`, and `High` for operations involving strong compression, encryption, or heavy media presets.

## Data Flow

The expected high-level data flow is:

1. User drops or selects files, folders, or archives
2. App Shell normalizes the selection into job requests
3. Job Engine queues the requests and resolves the correct subsystem
4. Archive Engine, Media Engine, or Adapter executes streaming work
5. Progress, logs, warnings, and results return to the App Shell
6. History and recent outputs remain available for follow-up actions

For archive opening:

1. User opens an archive
2. Security Layer requests password if needed
3. Archive Engine reads manifest/index
4. Preview and Metadata Indexer builds the visible content tree
5. User extracts selected items or verifies the archive

## Error Handling

The application should move away from popup-heavy flows and toward a more stable notification model.

Recommended behavior:

- non-fatal warnings appear in the side panel or task center
- task failures are attached to specific jobs with expandable detail
- a persistent activity/history area stores the latest operations
- technical logs remain available for troubleshooting
- critical failures still surface clearly, but the app should not bury the user in modal dialogs

This keeps long-running queue workflows usable and reduces frustration during multi-job processing.

## Testing Strategy

The rewrite should be planned with testability from the start.

Core tests:

- archive manifest/index read-write behavior
- multi-file archive round trips
- protected archive open/inspect/extract flows
- verification and corruption detection
- job queue behavior, cancellation, and reporting
- media preset command generation and validation
- format adapter behavior for standard exports/imports

UI tests should focus on key interaction seams rather than every widget detail:

- drag and drop intake
- queue state transitions
- password prompts for protected archives
- archive content inspection flow
- simple versus advanced mode behavior

## Scope for V1

The first major release of the new product should include:

- PySide6/Qt Windows GUI
- drag and drop for files and folders
- multi-file and multi-folder archive creation
- native `*.uca` archive format
- archive content inspection without full extraction
- password gate mode
- full encryption mode
- batch queue and task history
- media module for video and audio
- export to at least one standard archive format
- clear performance and cost hints
- cancellation, safe writes, and structured logging

Items that should be possible later, but do not need to block V1:

- importer for legacy `*.pylc`
- deeper file-type-specific previews
- richer preset comparison tools
- extended Windows shell integrations

## Constraints and Non-Goals

- Backward compatibility with the current format is optional, not a requirement
- Cross-platform support is out of scope
- The old Tkinter UI should not shape the new architecture
- Standard archive formats are secondary, not the primary design center

## Design Decision Summary

- full rewrite rather than incremental extension
- Windows-only product
- PySide6/Qt as the GUI base
- native `*.uca` archive format as the default path
- universal archive product with embedded media studio
- two protection levels with explicit user education
- archive inspection without full extraction as a first-class feature
- job queue and streaming processing as the operational foundation
