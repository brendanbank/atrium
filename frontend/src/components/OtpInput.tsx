import { TextInput } from '@mantine/core';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  autoFocus?: boolean;
  'aria-label'?: string;
}

/**
 * Single-field one-time-code input.
 *
 * Deliberately NOT Mantine's segmented <PinInput>. A PinInput renders one
 * <input maxlength="1"> per digit; desktop password-manager *extensions*
 * (e.g. 1Password on the desktop) cope because they fill per-field, but
 * mobile *native* autofill (iOS Password AutoFill — which 1Password drives
 * on iOS — and Android Autofill) inserts the whole code into the single
 * focused field in one shot, where maxlength=1 truncates it to a single
 * digit and the code never lands.
 *
 * A single <input autocomplete="one-time-code" inputmode="numeric"> is the
 * autofill target 1Password and Apple document, so it fills correctly on
 * both desktop and mobile. We strip non-digits and clamp to `length` so the
 * field behaves like the PinInput it replaces.
 */
export function OtpInput({
  value,
  onChange,
  length = 6,
  autoFocus,
  'aria-label': ariaLabel,
}: OtpInputProps) {
  return (
    <TextInput
      value={value}
      onChange={(event) =>
        onChange(event.currentTarget.value.replace(/\D/g, '').slice(0, length))
      }
      autoFocus={autoFocus}
      autoComplete="one-time-code"
      inputMode="numeric"
      type="text"
      name="one-time-code"
      maxLength={length}
      aria-label={ariaLabel}
      size="xl"
      w={220}
      styles={{
        input: {
          textAlign: 'center',
          letterSpacing: '0.4em',
          // letter-spacing adds a trailing gap after the last digit; nudge
          // the content right by the same amount so it stays centered.
          textIndent: '0.4em',
          fontFamily: 'var(--mantine-font-family-monospace)',
          fontVariantNumeric: 'tabular-nums',
        },
      }}
    />
  );
}
