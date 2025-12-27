import { useMemo } from 'react';
import { Chess } from 'chess.js';
import './MoveTable.css';

interface MoveTableProps {
  pgn: string;
  currentMoveIndex: number;
  /** Evaluation history: array where index corresponds to move number (1-indexed) */
  evalHistory?: (number | null)[];
  onMoveClick?: (moveIndex: number) => void;
}

interface MoveRow {
  moveNumber: number;
  whiteSan: string;
  whitePly: number;
  whiteEval: number | null;
  blackSan: string | null;
  blackPly: number | null;
  blackEval: number | null;
}

/**
 * Move table component showing game moves in standard notation.
 * Clicking a move navigates to that position.
 */
export function MoveTable({ pgn, currentMoveIndex, evalHistory = [], onMoveClick }: MoveTableProps) {
  const rows = useMemo(() => {
    if (!pgn) return [];

    const chess = new Chess();
    try {
      chess.loadPgn(pgn);
    } catch {
      return [];
    }

    const moves = chess.history();
    if (moves.length === 0) return [];

    const result: MoveRow[] = [];

    for (let ply = 0; ply < moves.length; ply += 2) {
      const moveNumber = Math.floor(ply / 2) + 1;
      const whitePly = ply + 1; // 1-indexed move position
      const blackPly = ply + 2;

      result.push({
        moveNumber,
        whiteSan: moves[ply],
        whitePly,
        whiteEval: evalHistory[whitePly] ?? null,
        blackSan: moves[ply + 1] ?? null,
        blackPly: moves[ply + 1] ? blackPly : null,
        blackEval: moves[ply + 1] ? (evalHistory[blackPly] ?? null) : null,
      });
    }

    return result;
  }, [pgn, evalHistory]);

  const formatEval = (cp: number | null): string => {
    if (cp === null) return '';
    if (Math.abs(cp) >= 10000) {
      return cp > 0 ? 'M' : '-M';
    }
    return (cp / 100).toFixed(1);
  };

  const handleClick = (ply: number) => {
    if (onMoveClick) {
      onMoveClick(ply);
    }
  };

  if (rows.length === 0) {
    return <p className="text-muted">No moves</p>;
  }

  return (
    <div className="move-table-container">
      <table className="move-table">
        <tbody>
          {rows.map((row) => (
            <tr key={row.moveNumber}>
              <td className="move-number">{row.moveNumber}.</td>
              <td
                className={`move-cell ${currentMoveIndex === row.whitePly ? 'current-move' : ''}`}
                onClick={() => handleClick(row.whitePly)}
              >
                {row.whiteSan}
                {row.whiteEval !== null && (
                  <span className="move-eval">{formatEval(row.whiteEval)}</span>
                )}
              </td>
              <td
                className={`move-cell ${row.blackPly && currentMoveIndex === row.blackPly ? 'current-move' : ''}`}
                onClick={() => row.blackPly && handleClick(row.blackPly)}
              >
                {row.blackSan || ''}
                {row.blackEval !== null && (
                  <span className="move-eval">{formatEval(row.blackEval)}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

