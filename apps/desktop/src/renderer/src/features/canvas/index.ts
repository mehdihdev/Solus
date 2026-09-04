// SOLUSDEV-235 / EXT-15 — the widget canvas's public surface.
export { WidgetCanvas, type WidgetCanvasProps } from './WidgetCanvas'
export { OFFLINE_NOTE, SAVE_TEXT, prunedNote } from './canvasCopy'
export {
  AddWidgetPicker,
  NO_EXTENSION_WIDGETS,
  type AddWidgetPickerProps,
  type DevWidgetEntry
} from './AddWidgetPicker'
export { WidgetSlot, type WidgetSlotProps } from './WidgetSlot'
export { resolveSlotTarget, slotTitle, slotSizeHint, type SlotTarget } from './slotTarget'
export {
  useWidgetLayout,
  defaultWidgetLayoutDeps,
  SAVE_DEBOUNCE_MS,
  type LayoutStatus,
  type SaveState,
  type WidgetLayoutData,
  type WidgetLayoutDeps
} from './useWidgetLayout'
export {
  useAvailableWidgets,
  builtinWidgetEntries,
  extensionWidgetEntries,
  defaultAvailableWidgetsDeps,
  WIDGETS_POLL_MS,
  type AvailableWidgets,
  type AvailableWidgetsDeps,
  type AvailableWidgetsStatus,
  type BuiltinWidgetEntry,
  type ExtensionWidgetEntry
} from './useAvailableWidgets'
export * from './layout'
