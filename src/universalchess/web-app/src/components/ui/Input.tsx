import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  block?: boolean;
}

/**
 * Reusable input component.
 */
export function Input({ block = false, className = '', ...props }: InputProps) {
  const classes = ['input', block ? 'input--block' : '', className].filter(Boolean).join(' ');
  return <input className={classes} {...props} />;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  options: Array<{ value: string; label: string }>;
}

/**
 * Reusable select component.
 */
export function Select({ options, className = '', ...props }: SelectProps) {
  const classes = ['select', className].filter(Boolean).join(' ');
  return (
    <select className={classes} {...props}>
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  block?: boolean;
}

/**
 * Reusable textarea component.
 */
export function Textarea({ block = false, className = '', ...props }: TextareaProps) {
  const classes = ['textarea', block ? 'input--block' : '', className].filter(Boolean).join(' ');
  return <textarea className={classes} {...props} />;
}

