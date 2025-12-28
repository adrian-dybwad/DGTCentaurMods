import type { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'muted';
  children: ReactNode;
}

/**
 * Reusable card container component.
 */
export function Card({
  variant = 'default',
  className = '',
  children,
  ...props
}: CardProps) {
  const classes = [
    'card',
    variant === 'muted' ? 'card--muted' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={classes} {...props}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: string;
  action?: ReactNode;
}

/**
 * Card header with title, optional action, and horizontal rule.
 */
export function CardHeader({ title, action }: CardHeaderProps) {
  return (
    <>
      <div className="card-header">
        <h3 className="card-title">{title}</h3>
        {action}
      </div>
      <hr className="card-divider" />
    </>
  );
}

