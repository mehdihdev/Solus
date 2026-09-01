// SOLUSDEV-233: the user's standing SOL preference note — load once, save with
// optimistic UI and revert-on-failure (useSettingsData's setSolMode idiom).
import { useCallback, useEffect, useState } from 'react'
import { getSettings, updateCustomInstruction } from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type CustomInstructionStatus = 'loading' | 'ready' | 'offline'

export interface CustomInstructionData {
  instruction: string | null
  status: CustomInstructionStatus
  /** Persist a new note (null/blank clears). Reverts and returns false on failure. */
  save: (instruction: string | null) => Promise<boolean>
}

export function useCustomInstruction(): CustomInstructionData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [instruction, setInstruction] = useState<string | null>(null)
  const [status, setStatus] = useState<CustomInstructionStatus>(
    fetchEnabled ? 'loading' : 'offline'
  )

  useEffect(() => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    let stale = false
    getSettings()
      .then((settings) => {
        if (stale) return
        setInstruction(settings.sol_custom_instruction)
        setStatus('ready')
      })
      .catch(() => {
        if (!stale) setStatus('offline')
      })
    return () => {
      stale = true
    }
  }, [fetchEnabled])

  const save = useCallback(
    async (next: string | null): Promise<boolean> => {
      const cleaned = next?.trim() || null
      const previous = instruction
      setInstruction(cleaned)
      try {
        await updateCustomInstruction(cleaned)
        return true
      } catch {
        setInstruction(previous)
        return false
      }
    },
    [instruction]
  )

  return { instruction, status, save }
}
