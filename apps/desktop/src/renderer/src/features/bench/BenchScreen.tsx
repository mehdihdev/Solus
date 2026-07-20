// Live Bench. The live surface (telemetry streaming, sim generation, anomaly
// detection) arrives with the Live Bench tickets (SOLUSDEV-121+); until then
// this screen is an honest empty state. SOLUSDEV-152 removed the prototype's
// synthesized signals and fake device pairing — simulated data must never be
// labelled REAL, so nothing streams here until real ingestion exists.
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'

export function BenchScreen(): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ScreenEmptyState
        icon={<Icons.bench size={30} />}
        title="Live Bench isn't streaming yet"
        body={
          <>
            When a robot is connected — over serial or ROS — its joint telemetry, system vitals, and
            anomaly detection stream here in real time. Sim mode will generate a bench from your
            CAD, always labelled as simulation.
          </>
        }
        status="NO DEVICE CONNECTED"
      />
    </div>
  )
}
