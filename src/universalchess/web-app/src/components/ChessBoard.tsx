import { useMemo, useRef, useState, useEffect } from 'react';
import { Chessboard } from 'react-chessboard';
import type { ChessboardOptions, Arrow } from 'react-chessboard';

interface ChessBoardProps {
  fen: string;
  /** Maximum board width - board will fill container up to this size */
  maxBoardWidth?: number;
  showBestMove?: { from: string; to: string } | null;
  /** The actual move played (shown in red if different from best move) */
  showPlayedMove?: { from: string; to: string } | null;
  boardOrientation?: 'white' | 'black';
}

/**
 * ChessBoard component using react-chessboard.
 * Handles FEN display and best move arrows.
 */
export function ChessBoard({
  fen,
  maxBoardWidth = 600,
  showBestMove = null,
  showPlayedMove = null,
  boardOrientation = 'white',
}: ChessBoardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [boardWidth, setBoardWidth] = useState(maxBoardWidth);

  // Measure container and set board width responsively
  useEffect(() => {
    const updateSize = () => {
      if (containerRef.current) {
        const containerWidth = containerRef.current.offsetWidth;
        // Use container width but cap at maxBoardWidth
        setBoardWidth(Math.min(containerWidth, maxBoardWidth));
      }
    };

    updateSize();
    window.addEventListener('resize', updateSize);
    
    // Also observe container size changes
    const resizeObserver = new ResizeObserver(updateSize);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      window.removeEventListener('resize', updateSize);
      resizeObserver.disconnect();
    };
  }, [maxBoardWidth]);

  // Normalize FEN to position-only for display
  const positionFen = useMemo(() => {
    return fen?.split(' ')[0] || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  }, [fen]);

  // Build custom arrows for best move (green) and played move (red if different)
  const customArrows: Arrow[] = useMemo(() => {
    const arrows: Arrow[] = [];
    
    // Best move arrow (green) - always show if available
    if (showBestMove) {
      arrows.push({
        startSquare: showBestMove.from,
        endSquare: showBestMove.to,
        color: 'rgba(0, 180, 0, 0.8)',  // Green for best move
      });
      
      // Played move arrow (red) - only show if we have a best move AND played move differs
      // We require bestMove to exist to avoid showing red arrow during analysis loading
      if (showPlayedMove) {
        const isSameMove = 
          showBestMove.from === showPlayedMove.from &&
          showBestMove.to === showPlayedMove.to;
        
        if (!isSameMove) {
          arrows.push({
            startSquare: showPlayedMove.from,
            endSquare: showPlayedMove.to,
            color: 'rgba(220, 53, 69, 0.8)',  // Red for suboptimal played move
          });
        }
      }
    }
    
    return arrows;
  }, [showBestMove, showPlayedMove]);

  // Custom square styles for DGT board colors
  const darkSquareStyle = { backgroundColor: '#b2b2b2' };
  const lightSquareStyle = { backgroundColor: '#e5e5e5' };

  const options: ChessboardOptions = {
    position: positionFen,
    boardOrientation,
    arrows: customArrows,
    darkSquareStyle,
    lightSquareStyle,
    allowDragging: false,
    boardStyle: {
      width: boardWidth,
    },
  };

  return (
    <div ref={containerRef} style={{ width: '100%', maxWidth: maxBoardWidth }}>
      <Chessboard options={options} />
    </div>
  );
}
