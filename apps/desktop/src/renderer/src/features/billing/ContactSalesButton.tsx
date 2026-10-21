// Enterprise "Contact sales": a real button (never an anchor/mailto). The click
// goes through the preload bridge; main opens the hardcoded address.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { contactSales } from './billingBridge'

export function ContactSalesButton(): React.JSX.Element {
  const [hovered, setHovered] = useState(false)
  return (
    <Button
      kind="soft"
      size="sm"
      onClick={contactSales}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        color: hovered ? 'var(--fg)' : 'var(--mut)',
        borderColor: hovered ? 'var(--acc)' : 'var(--bd)',
        textDecoration: hovered ? 'underline' : 'none'
      }}
    >
      Contact sales
    </Button>
  )
}
