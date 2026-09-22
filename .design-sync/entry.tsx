// Design-system entry for /design-sync (see .design-sync/NOTES.md).
//
// Solus has no standalone DS package: the component library lives inside the
// Electron renderer. This barrel is the curated public surface we sync — the
// 14 UI primitives plus the reusable feature components — so the converter
// bundles exactly these and nothing else.
//
// Regenerate the token/base stylesheet after editing assets/main.css:
//   ./.ds-sync/node_modules/.bin/tailwindcss \
//     -i apps/desktop/src/renderer/src/assets/main.css -o .design-sync/solus-base.css

// Component CSS. hardware.css is already imported by DeviceCard; the rest are
// imported by container components outside this surface, so we pull them in
// here or the class-based styling (.graph-node-*, .widget-*, …) is missing.
import '../apps/desktop/src/renderer/src/features/canvas/canvas.css'
import '../apps/desktop/src/renderer/src/features/graph/hardware/hardware.css'
import '../apps/desktop/src/renderer/src/features/graph/navigation/navigation.css'
import '../apps/desktop/src/renderer/src/features/graph/robots/robots.css'
import '../apps/desktop/src/renderer/src/features/graph/sidebar/sidebar.css'
import '../apps/desktop/src/renderer/src/features/project/localFolder.css'
import '../apps/desktop/src/renderer/src/features/sol/ConfirmationCard.css'
import '../apps/desktop/src/renderer/src/features/workspace/codeEnvironment.css'
import '../apps/desktop/src/renderer/src/features/workspace/solusCard.css'

// Icon set. Exported so previews (and designs) can fill icon-shaped props such as
// ScreenEmptyState.icon and PageHeader's tiles. It is a record of SVG components, not a
// component itself, so componentSrcMap pins it to null — it reaches window.Solus.Icons
// without becoming a card.
export { Icons } from '../apps/desktop/src/renderer/src/components/ui/icons.constants'

// -- UI primitives ---------------------------------------------------------
export { Avatar } from '../apps/desktop/src/renderer/src/components/ui/Avatar'
export { Button } from '../apps/desktop/src/renderer/src/components/ui/Button'
export { Card } from '../apps/desktop/src/renderer/src/components/ui/Card'
export { ContextMenu } from '../apps/desktop/src/renderer/src/components/ui/ContextMenu'
export { DomainChip } from '../apps/desktop/src/renderer/src/components/ui/DomainChip'
export { Field } from '../apps/desktop/src/renderer/src/components/ui/Field'
export { KV } from '../apps/desktop/src/renderer/src/components/ui/KV'
export { Mono } from '../apps/desktop/src/renderer/src/components/ui/Mono'
export { Segmented } from '../apps/desktop/src/renderer/src/components/ui/Segmented'
export { SolusLogo } from '../apps/desktop/src/renderer/src/components/ui/SolusLogo'
export { Spark } from '../apps/desktop/src/renderer/src/components/ui/Spark'
export { Spinner } from '../apps/desktop/src/renderer/src/components/ui/Spinner'
export { Switch } from '../apps/desktop/src/renderer/src/components/ui/Switch'
export { Wordmark } from '../apps/desktop/src/renderer/src/components/ui/Wordmark'

// -- Cards & tiles ---------------------------------------------------------
export { ProjectCard } from '../apps/desktop/src/renderer/src/features/workspace/ProjectCard'
export { GraphCard } from '../apps/desktop/src/renderer/src/features/graph/navigation/GraphCard'
// DeviceCard is excluded: features/graph/hardware/ contains both deviceCard.ts and
// DeviceCard.tsx, and on a case-insensitive filesystem esbuild resolves the card's own
// `import { cardSentence, … } from './deviceCard'` back to DeviceCard.tsx. See NOTES.md.
export {
  ExtensionCard,
  ExtensionIconTile,
  PublisherBadge,
  AvailabilityPill,
  SectionLabel
} from '../apps/desktop/src/renderer/src/features/extensions/ExtensionCard'
// ConnectTile is excluded: it imports ./integrationLogos, which loads brand logos with
// Vite's `import.meta.glob`. esbuild leaves import.meta empty, so the call throws at
// bundle-evaluation time and takes every other preview down with it. See NOTES.md.
export { CodeEnvironmentCard } from '../apps/desktop/src/renderer/src/features/graph/CodeEnvironmentCard'
export { ExtensionIcon } from '../apps/desktop/src/renderer/src/features/extensions/host/ExtensionIcon'

// -- SOL agent surfaces ----------------------------------------------------
export { ModeBadge } from '../apps/desktop/src/renderer/src/features/sol/ModeBadge'
export { RegionCard } from '../apps/desktop/src/renderer/src/features/sol/RegionCard'
export { ClassifyIndicator } from '../apps/desktop/src/renderer/src/features/sol/ClassifyIndicator'
export { SolMarkdown } from '../apps/desktop/src/renderer/src/features/sol/Markdown'
export { SolusComposer } from '../apps/desktop/src/renderer/src/features/graph/SolusComposer'

// -- States & feedback -----------------------------------------------------
export { ScreenEmptyState } from '../apps/desktop/src/renderer/src/features/workspace/ScreenEmptyState'
export { PlanLimitNotice } from '../apps/desktop/src/renderer/src/features/workspace/PlanLimitNotice'
export { AlertScreen } from '../apps/desktop/src/renderer/src/features/graph/AlertScreen'
export { FrameSkeleton, FrameCard } from '../apps/desktop/src/renderer/src/features/extensions/frame/FrameStates'
export { TwoStepDelete } from '../apps/desktop/src/renderer/src/features/graph/sidebar/TwoStepDelete'

// -- Forms & settings ------------------------------------------------------
export { LabeledSelect } from '../apps/desktop/src/renderer/src/features/graph/hardware/LabeledSelect'
export { Section, Row, InlineError } from '../apps/desktop/src/renderer/src/features/settings/settingsUi'
export { StepDots } from '../apps/desktop/src/renderer/src/features/onboarding/StepDots'
export { GithubButton } from '../apps/desktop/src/renderer/src/features/auth/GithubButton'

// -- Chrome & layout -------------------------------------------------------
export { TitleBar } from '../apps/desktop/src/renderer/src/features/workspace/TitleBar'
export { PageHeader, PageIconTile, DevBadge } from '../apps/desktop/src/renderer/src/features/extensions/pageview/PageHeader'
export { WidgetSlot } from '../apps/desktop/src/renderer/src/features/canvas/WidgetSlot'
export { FocusSummaryWidget } from '../apps/desktop/src/renderer/src/features/workspace/widgets/FocusSummaryWidget'
export { NeighborsWidget } from '../apps/desktop/src/renderer/src/features/workspace/widgets/NeighborsWidget'
