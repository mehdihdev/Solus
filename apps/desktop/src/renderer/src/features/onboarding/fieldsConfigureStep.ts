// The generic post-auth configure step: ask the user for the connector's own
// `config_fields` and write them onto the source.
//
// This is what makes the OAuth path open-ended. A connector that cannot list its
// documents (Onshape needs document_id/workspace_id/element_id, and the backend
// exposes no picker for them) still connects, because the fields come from the
// live registry rather than from anything hardcoded here. Every future CAD
// connector lands on this path with no frontend change.
import type { ConfigureContext, ConfigureOutcome, ConfigureStep } from './oauthConnect'
import type { ConnectionState } from './onboardingStore'

export interface FieldsConfigureDeps {
  /** The provider's required config keys, straight from GET /integrations. */
  fields: readonly string[]
  /** Push live connection state into the store (surfaces the form). */
  onProgress: (state: ConnectionState) => void
  /** Resolve the in-tile form; null when the user cancels. */
  onSubmitConfig: (fields: readonly string[]) => Promise<Record<string, string> | null>
}

export const NO_FIELDS_ERROR = 'This connector needs configuration the app cannot collect yet.'
export const CANCELLED_ERROR = 'Configuration cancelled.'
export const INCOMPLETE_ERROR = 'Every field is required.'

/** Build the post-auth configure step for providers configured by plain fields. */
export function fieldsConfigureStep(deps: FieldsConfigureDeps): ConfigureStep {
  return async ({ sourceId }: ConfigureContext): Promise<ConfigureOutcome> => {
    // A provider with no config fields would leave nothing to submit; rather
    // than silently sync an unconfigured source, say so.
    if (deps.fields.length === 0) return { error: NO_FIELDS_ERROR }

    deps.onProgress({
      phase: 'busy',
      stage: 'configure',
      label: 'Enter the connector details…',
      sourceId,
      configFields: deps.fields
    })
    const submitted = await deps.onSubmitConfig(deps.fields)
    if (!submitted) return { error: CANCELLED_ERROR }

    // Validate at the boundary: the backend rejects partial config anyway, and
    // an honest tile error beats a failed sync.
    const config: Record<string, string> = {}
    for (const field of deps.fields) {
      const value = submitted[field]?.trim()
      if (!value) return { error: INCOMPLETE_ERROR }
      config[field] = value
    }
    return { config }
  }
}
