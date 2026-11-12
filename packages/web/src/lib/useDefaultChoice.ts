import { useEffect } from 'react'

// Create forms preselect the default (else first) option once the list
// loads; edit forms pass enabled=false and keep the stored choice.
export function useDefaultChoice(
  enabled: boolean,
  value: string,
  setValue: (id: string) => void,
  options: Array<{ id: string; is_default?: boolean }> | undefined,
) {
  useEffect(() => {
    if (enabled && !value && options?.length) setValue(options.find((o) => o.is_default)?.id ?? options[0].id)
  }, [enabled, value, setValue, options])
}
