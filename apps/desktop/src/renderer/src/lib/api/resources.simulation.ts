import { api } from './client'

export interface SimulationModelSetupResult {
  model: { id: string }
  created: boolean
}

export function createSimulationModel(projectId: string): Promise<SimulationModelSetupResult> {
  return api.request(`/projects/${encodeURIComponent(projectId)}/simulation-models`, {
    method: 'POST',
    body: { template: 'so101_new_calib_v1' }
  })
}
