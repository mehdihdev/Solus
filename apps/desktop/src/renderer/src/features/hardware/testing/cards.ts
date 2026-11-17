// Card fixtures for the Hardware page's slot (SOLUSDEV-326 P3). SAMPLE_CARDS is the spec's
// "Sample cards" table (rover 1 to 15, then the kit 1 to 14): examples of what SOL writes at run
// time, kept verbatim so the card is proven to fit copy of that size.
import type { Card, CardKind, OpenCard } from '@solus/shared-types'

export const card = (over: Partial<Card> = {}): Card => ({
  kind: 'offer',
  title: 'Found: 3 servos on a USB adapter',
  body: 'They match arm.yaml in rover_ws: shoulder_pan, shoulder_lift, elbow.',
  more: null,
  field: null,
  primary: 'Add',
  secondary: 'Not now',
  receipt: '3 servos added',
  resumes: true,
  ...over
})

export const openCard = (over: Partial<OpenCard> = {}, cardOver: Partial<Card> = {}): OpenCard => ({
  confirmation_id: 'c1',
  conversation_id: 'conv1',
  tool: 'hardware.add_parts',
  card: card(cardOver),
  expires_at: '2099-01-01T00:00:00+00:00',
  ...over
})

export interface SampleCard {
  card: Card
  /** A step card's live line. The Card contract carries none yet; HwCard takes it as a prop. */
  status?: string
}

const sample = (
  kind: CardKind,
  title: string,
  body: string,
  primary: string,
  secondary: string | null = null,
  extra: { field?: Card['field']; status?: string } = {}
): SampleCard => ({
  card: card({ kind, title, body, primary, secondary, field: extra.field ?? null }),
  status: extra.status
})

export const SAMPLE_CARDS: readonly SampleCard[] = [
  sample(
    'offer',
    'Plug in your hardware',
    'Anything plugged into this computer shows up here on its own. There is nothing to import: your CAD, schematic and code are already in the Workspace.',
    'Connect a robot computer'
  ),
  sample(
    'offer',
    'Found: 3 servos on a USB adapter',
    'Feetech STS3215 at IDs 1 to 3. They match arm.yaml in rover_ws: shoulder_pan, shoulder_lift, elbow.',
    'Add',
    'Not now',
    { field: { label: 'Robot name', value: 'Rover arm' } }
  ),
  sample(
    'offer',
    'Found: an Arduino Nano',
    'It prints 4 numbers per line, in the same order as nano_sensors.ino: ax, ay, az, temp. I named the channels from the sketch.',
    'Add',
    'Not now'
  ),
  sample(
    'offer',
    'A Raspberry Pi is on your network',
    'raspberrypi.local. Your launch files expect a camera and a lidar on it. Solus signs in with your SSH key and only reads.',
    'Connect',
    'Not now'
  ),
  sample(
    'offer',
    'First time seeing this computer',
    'Fingerprint SHA256:u1Kx...9fQ2. Check that it matches your robot. Solus pins it and stops if it ever changes.',
    'Trust and pin',
    'Cancel'
  ),
  sample(
    'problem',
    'Your SSH key was not accepted',
    'Run this once in your own terminal, then try again: `ssh-copy-id pi@raspberrypi.local`. Solus never asks for a password.',
    'Copy command',
    'Try again'
  ),
  sample(
    'offer',
    'Found on the Pi: wrist_cam, lidar, imu',
    'From its ROS 2 graph (2 sensor topics) and its I2C bus. Add them to Rover arm?',
    'Add 3 parts',
    'Review each'
  ),
  sample(
    'approval',
    'Approve: check which firmware the Nano runs',
    'This restarts Nano 9530F1. It reads the chip signature and flash contents. Nothing is written.',
    'Approve',
    'Skip'
  ),
  sample(
    'offer',
    'elbow looks like the joint "elbow" in Arm assembly',
    'Link them and the twin on Live Bench moves with the servo. Nothing is imported.',
    'Link',
    'Not now'
  ),
  sample(
    'offer',
    'Rover arm is set up',
    '7 parts, all connected. It is in your hardware connections. Add it to the workspace graph to see how it is wired.',
    'Add to workspace graph'
  ),
  sample(
    'problem',
    'Nothing answered yet',
    'A USB serial device is there, but nothing replied. Is it powered, and is another program using the port?',
    'Retry',
    'Not now'
  ),
  sample(
    'offer',
    'Firmware and protocol are unknown',
    'I can keep it as a plain connection and show its raw data, or you can tell me what it is.',
    'Add as a connection',
    'Not now'
  ),
  sample(
    'offer',
    'This is your motor_driver board',
    'Its chip matches U1 in your KiCad schematic, so I already know its pins and the parts on it.',
    'Add',
    'Not now'
  ),
  sample(
    'problem',
    'One pin does not match your schematic',
    'The firmware reads current on PB1. The schematic routes ISENSE to PB0.',
    'Propose a fix',
    'Show both'
  ),
  sample(
    'approval',
    'Approve: flash fw/motor_driver',
    'Board STM32G431 3A07...91 over USB. The firmware on it now is saved first if the chip allows reading it.',
    'Approve',
    'Not now'
  ),
  sample(
    'offer',
    'A USB servo adapter was plugged in',
    'Serial 5B42134331. One reply at ID 1, with collisions. These look like new servos that all still have ID 1.',
    'Set up motor IDs',
    'They already have IDs'
  ),
  sample(
    'approval',
    'Approve: give each motor its own ID',
    'I will write an ID from 1 to 6, and 1,000,000 baud, to the memory of each motor, one motor at a time. Follower arm, 6 motors.',
    'Approve',
    'Cancel'
  ),
  sample(
    'step',
    'Connect only the gripper motor',
    'Unplug the other motors from the board. I am waiting until I see exactly one.',
    'Set it to ID 6',
    null,
    { status: '1 motor seen at ID 1 · STS3215' }
  ),
  sample(
    'step',
    'gripper is ID 6. Now connect only wrist_roll',
    'Then wrist_flex, elbow_flex, shoulder_lift and shoulder_pan, down to ID 1.',
    'Set it to ID 5',
    null,
    { status: '1 of 6 done' }
  ),
  sample(
    'step',
    'All 6 motors have IDs. Chain them and plug in the first',
    'I am waiting for all six on one bus.',
    'Continue',
    null,
    { status: '6 of 6 answer, IDs 1 to 6' }
  ),
  sample(
    'offer',
    'This is an SO-101 follower arm',
    'Six STS3215 at IDs 1 to 6. Names from LeRobot: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper.',
    'Add',
    'Not now',
    { field: { label: 'Robot name', value: 'follower' } }
  ),
  sample(
    'step',
    'Calibrate: put every joint in the middle of its range',
    'Torque is off, so you can move the arm by hand. Tell me when it is there.',
    'It is in the middle',
    'Use a LeRobot file instead',
    { status: 'torque off on 6 motors' }
  ),
  sample(
    'step',
    'Now move each joint through its full range',
    'I record the lowest and highest position of each joint as you move it.',
    'Done',
    null,
    { status: 'shoulder_pan and shoulder_lift done · elbow_flex moving · 3 not moved yet' }
  ),
  sample(
    'approval',
    'Approve: save this calibration',
    'Homing offset and range for 6 joints. Saved in .solus / environment / hardware and written to the motors.',
    'Save',
    'Redo'
  ),
  sample(
    'offer',
    'Also write the LeRobot calibration file?',
    'Same values, in the file LeRobot reads for "follower", so its own scripts use this calibration.',
    'Write the file',
    'Skip'
  ),
  sample(
    'offer',
    'A second servo adapter was plugged in',
    'Is this the leader arm? It gets the same steps. I will show which gear ratio goes on which joint.',
    'Yes, set it up',
    'Not now'
  ),
  sample(
    'offer',
    'Found 2 cameras on this computer',
    'Name them so recordings and the bench use the same names.',
    'Add',
    'Not now',
    { field: { label: 'Names', value: 'front, wrist' } }
  ),
  sample(
    'approval',
    'Approve: move each joint 5 degrees and back',
    'Confirms each joint turns the right way and the calibration holds. This moves the arm.',
    'Run the check',
    'Skip'
  ),
  sample(
    'offer',
    'follower and leader are set up',
    '12 motors and 2 cameras, all connected. Add them to this workspace graph to see how they are wired.',
    'Add to workspace graph'
  )
]
