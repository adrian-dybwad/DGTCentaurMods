interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
}

/**
 * Reusable toggle switch component.
 */
export function Toggle({ checked, onChange, disabled = false, label }: ToggleProps) {
  return (
    <div className="form-row">
      {label && <label className="form-label">{label}</label>}
      <button
        type="button"
        className="toggle"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-slider" />
      </button>
    </div>
  );
}

