import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import type { MoveToastData } from '../stores/gameStore';
import './MoveBanner.css';

interface MoveBannerProps {
  toast: MoveToastData;
  onDismiss: () => void;
}

/**
 * Banner notification for new moves made while not on the live board.
 * Appears below the navbar as a full-width banner.
 * Background color matches the chess board square color of the player who moved.
 * Auto-dismisses after 8 seconds or on click.
 */
export function MoveBanner({ toast, onDismiss }: MoveBannerProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 8000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);

  const fullMoveNumber = Math.ceil(toast.moveNumber / 2);
  const moveNotation = toast.isWhiteMove
    ? `${fullMoveNumber}. ${toast.move}`
    : `${fullMoveNumber}... ${toast.move}`;
  
  const playerWhoMoved = toast.isWhiteMove ? toast.white : toast.black;
  const bannerClass = toast.isWhiteMove ? 'move-banner move-banner--white' : 'move-banner move-banner--black';

  return (
    <div className={bannerClass}>
      <div className="move-banner-content">
        <span className="move-banner-icon">♟</span>
        <span className="move-banner-text">
          <strong>{playerWhoMoved}</strong> played <strong className="move-notation">{moveNotation}</strong>
        </span>
        <Link to="/" className="move-banner-link">
          View Live Board →
        </Link>
        <button className="move-banner-close" onClick={onDismiss} aria-label="Dismiss">
          ×
        </button>
      </div>
    </div>
  );
}

