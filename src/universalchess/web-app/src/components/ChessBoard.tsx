import { useMemo, useRef } from 'react';
import { Chessboard } from 'react-chessboard';
import type { ChessboardOptions, Arrow } from 'react-chessboard';

interface ChessBoardProps {
  fen: string;
  boardWidth?: number;
  showBestMove?: { from: string; to: string } | null;
  boardOrientation?: 'white' | 'black';
}

/**
 * ChessBoard component using react-chessboard.
 * Handles FEN display and best move arrows.
 */
export function ChessBoard({
  fen,
  boardWidth = 500,
  showBestMove = null,
  boardOrientation = 'white',
}: ChessBoardProps) {
  const boardRef = useRef<HTMLDivElement>(null);

  // Normalize FEN to position-only for display
  const positionFen = useMemo(() => {
    return fen?.split(' ')[0] || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  }, [fen]);

  // Build custom arrows for best move
  const customArrows: Arrow[] = useMemo(() => {
    if (!showBestMove) return [];
    return [{
      startSquare: showBestMove.from,
      endSquare: showBestMove.to,
      color: 'rgba(0, 128, 255, 0.7)',
    }];
  }, [showBestMove]);

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
      maxWidth: '100%',
    },
  };

  return (
    <div ref={boardRef} style={{ width: boardWidth, maxWidth: '100%' }}>
      <Chessboard options={options} />
    </div>
  );
}
