import { ElectronAPI } from '@electron-toolkit/preload'
import type { SolusBridge } from './index'

declare global {
  interface Window {
    electron: ElectronAPI
    api: unknown
    solus: SolusBridge
  }
}
