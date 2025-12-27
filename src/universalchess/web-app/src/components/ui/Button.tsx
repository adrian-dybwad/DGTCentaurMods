import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'default' | 'primary' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  children: ReactNode;
}

const variantClasses: Record<ButtonVariant, string> = {
  default: 'btn',
  primary: 'btn btn--primary',
  danger: 'btn btn--danger',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'btn--sm',
  md: '',
  lg: 'btn--lg',
};

/**
 * Reusable button component with consistent styling.
 */
export function Button({
  variant = 'default',
  size = 'md',
  block = false,
  className = '',
  children,
  ...props
}: ButtonProps) {
  const classes = [
    variantClasses[variant],
    sizeClasses[size],
    block ? 'btn--block' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <button className={classes} {...props}>
      {children}
    </button>
  );
}

