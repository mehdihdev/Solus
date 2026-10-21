// The connected-accounts card's step logic (SOLUSDEV-241/242), shared with
// Home's project Sources block (SOLUSDEV-317): what a tool offers next, and the
// one connect wizard both surfaces open it through. Kept out of the card's
// component file so React Fast Refresh keeps working there.
import { useState } from 'react'
import type { WorkspaceProject } from '../../store/workspaceStore'
import type { WizardScope } from '../onboarding/connectSteps'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { plural } from '../onboarding/selectionConfigureStep'
import { useConnectWizard } from '../onboarding/useConnectWizard'
import type { useProjectSources } from '../project/useProjectSources'
import type { useAccountConnections } from './useAccountConnections'

export interface NextStep {
  action: string
  scope: WizardScope
  needsProject: boolean
}

/** What the tool's row offers next — derived from the connector's declared
 *  shape and whether an account is already linked, never from its id. */
export function nextStep(entry: CatalogEntry, linked: boolean): NextStep {
  if (entry.mode === 'export-file')
    return { action: 'Choose file', scope: 'project', needsProject: true }
  if (entry.mode === 'local-bridge')
    return { action: 'Connect', scope: 'project', needsProject: false }
  if (!linked) return { action: 'Connect', scope: 'account', needsProject: false }
  const action = entry.selection
    ? `Pick ${plural(entry.selection.label)}`
    : entry.configFields.length > 0
      ? 'Enter details'
      : 'Add to project'
  return { action, scope: 'project', needsProject: true }
}

/** The card's one wizard, in whichever scope the clicked step needs, plus the
 *  refresh both scopes share once a connect settles. Home's project Sources
 *  block (SOLUSDEV-317) opens the same wizard through it. */
export function useCardWizard(
  currentProject: WorkspaceProject | null,
  accounts: ReturnType<typeof useAccountConnections>,
  sources: ReturnType<typeof useProjectSources>
): {
  wizard: ReturnType<typeof useConnectWizard>
  scope: WizardScope
  open: (entry: CatalogEntry, scope: WizardScope) => void
} {
  // One wizard, two scopes: the account sign-in, or a project-bound step that
  // reuses the linked account (the rail then skips the sign-in).
  const [scope, setScope] = useState<WizardScope>('account')
  const wizard = useConnectWizard({
    projectId: currentProject?.id ?? null,
    scope,
    linkedConnections: accounts.connections,
    onConnected: () => {
      void accounts.refresh()
      void sources.actions.refresh()
    }
  })
  const open = (entry: CatalogEntry, nextScope: WizardScope): void => {
    setScope(nextScope)
    wizard.open(entry)
  }
  return { wizard, scope, open }
}
