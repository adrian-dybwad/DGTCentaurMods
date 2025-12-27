import { useEffect, useState, useCallback, useRef } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Chess } from 'chess.js';
import { getStockfishService, StockfishService } from '../services/stockfish';
import type { AnalysisResult } from '../types/game';
import './Analysis.css';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface AnalysisProps {
  pgn: string;
  mode: 'live' | 'static';
  onPositionChange?: (fen: string, moveIndex: number) => void;
}

interface MoveData {
  fen: string;
  san: string;
  analysis: AnalysisResult | null;
}

/**
 * Analysis component with Stockfish evaluation, move navigation, and chart.
 */
export function Analysis({ pgn, mode, onPositionChange }: AnalysisProps) {
  const [moves, setMoves] = useState<MoveData[]>([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [analyzing, setAnalyzing] = useState(false);
  const [currentAnalysis, setCurrentAnalysis] = useState<AnalysisResult | null>(null);
  const [newMoveToast, setNewMoveToast] = useState(false);
  const stockfishRef = useRef<StockfishService | null>(null);
  const analysisQueueRef = useRef<number[]>([]);
  const isAnalyzingRef = useRef(false);

  // Parse PGN and build move history
  useEffect(() => {
    const chess = new Chess();
    const newMoves: MoveData[] = [
      { fen: chess.fen(), san: 'Start', analysis: null },
    ];

    try {
      chess.loadPgn(pgn);
      const history = chess.history({ verbose: true });
      
      // Replay to get FEN at each position
      chess.reset();
      for (const move of history) {
        chess.move(move.san);
        newMoves.push({
          fen: chess.fen(),
          san: move.san,
          analysis: null,
        });
      }
    } catch (e) {
      console.error('Failed to parse PGN:', e);
    }

    const prevLength = moves.length;
    setMoves(newMoves);

    // In live mode, jump to latest and show toast if user was behind
    if (mode === 'live' && newMoves.length > prevLength) {
      if (currentIndex >= 0 && currentIndex < prevLength - 1) {
        setNewMoveToast(true);
        setTimeout(() => setNewMoveToast(false), 3000);
      } else {
        setCurrentIndex(newMoves.length - 1);
      }
    } else if (mode === 'static' && currentIndex < 0) {
      // Static mode: jump to end on initial load
      setCurrentIndex(newMoves.length - 1);
    }
  }, [pgn, mode]);

  // Initialize Stockfish
  useEffect(() => {
    const sf = getStockfishService();
    stockfishRef.current = sf;
    sf.init().catch(console.error);

    return () => {
      sf.stop();
    };
  }, []);

  // Analyze positions in background
  const processAnalysisQueue = useCallback(async () => {
    if (isAnalyzingRef.current || !stockfishRef.current) return;
    if (analysisQueueRef.current.length === 0) {
      setAnalyzing(false);
      return;
    }

    isAnalyzingRef.current = true;
    setAnalyzing(true);

    const index = analysisQueueRef.current.shift()!;
    const move = moves[index];
    if (move && !move.analysis) {
      try {
        const result = await stockfishRef.current.analyze(move.fen, 16);
        setMoves((prev) => {
          const updated = [...prev];
          if (updated[index]) {
            updated[index] = { ...updated[index], analysis: result };
          }
          return updated;
        });
      } catch (e) {
        console.error('Analysis failed:', e);
      }
    }

    isAnalyzingRef.current = false;
    processAnalysisQueue();
  }, [moves]);

  // Queue all positions for analysis on PGN change
  useEffect(() => {
    analysisQueueRef.current = moves.map((_, i) => i).filter((i) => !moves[i].analysis);
    processAnalysisQueue();
  }, [moves.length, processAnalysisQueue]);

  // Analyze current position immediately
  useEffect(() => {
    if (currentIndex < 0 || !stockfishRef.current) return;
    const move = moves[currentIndex];
    if (!move) return;

    if (move.analysis) {
      setCurrentAnalysis(move.analysis);
    } else {
      stockfishRef.current.analyze(move.fen, 18).then((result) => {
        setCurrentAnalysis(result);
        setMoves((prev) => {
          const updated = [...prev];
          if (updated[currentIndex]) {
            updated[currentIndex] = { ...updated[currentIndex], analysis: result };
          }
          return updated;
        });
      });
    }
  }, [currentIndex, moves]);

  // Notify parent of position change
  useEffect(() => {
    if (onPositionChange && currentIndex >= 0 && moves[currentIndex]) {
      onPositionChange(moves[currentIndex].fen, currentIndex);
    }
  }, [currentIndex, moves, onPositionChange]);

  // Navigation
  const goFirst = () => setCurrentIndex(0);
  const goPrev = () => setCurrentIndex((i) => Math.max(0, i - 1));
  const goNext = () => setCurrentIndex((i) => Math.min(moves.length - 1, i + 1));
  const goLast = () => setCurrentIndex(moves.length - 1);
  const jumpToLatest = () => {
    setCurrentIndex(moves.length - 1);
    setNewMoveToast(false);
  };

  // Format eval display
  const formatEval = (analysis: AnalysisResult | null): string => {
    if (!analysis) return '...';
    if (analysis.mate !== null) {
      return `M${analysis.mate > 0 ? '+' : ''}${analysis.mate}`;
    }
    if (analysis.score !== null) {
      const score = analysis.score / 100;
      return score >= 0 ? `+${score.toFixed(2)}` : score.toFixed(2);
    }
    return '...';
  };

  // Build chart data
  const chartData = {
    labels: moves.map((_, i) => (i === 0 ? '' : `${Math.ceil(i / 2)}.${i % 2 === 1 ? '' : '..'}`)),
    datasets: [
      {
        label: 'Evaluation',
        data: moves.map((m) => {
          if (!m.analysis) return 0;
          if (m.analysis.mate !== null) {
            return m.analysis.mate > 0 ? 10 : -10;
          }
          return Math.max(-10, Math.min(10, (m.analysis.score ?? 0) / 100));
        }),
        borderColor: '#aa44aa',
        backgroundColor: 'rgba(170, 68, 170, 0.2)',
        fill: true,
        tension: 0.3,
        pointRadius: 2,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx: any) => {
            const move = moves[ctx.dataIndex];
            return move?.analysis ? formatEval(move.analysis) : '...';
          },
        },
      },
    },
    scales: {
      y: {
        min: -10,
        max: 10,
        ticks: { stepSize: 5 },
      },
    },
    onClick: (_: any, elements: any[]) => {
      if (elements.length > 0) {
        setCurrentIndex(elements[0].index);
      }
    },
  };

  // Eval bar percentage (clamped to -10..10)
  const evalPercent = currentAnalysis
    ? 50 + (currentAnalysis.mate !== null
        ? (currentAnalysis.mate > 0 ? 50 : -50)
        : Math.max(-50, Math.min(50, ((currentAnalysis.score ?? 0) / 100) * 5)))
    : 50;

  return (
    <div className="analysis-container">
      {/* Eval display */}
      <div className="analysis-eval">
        <div className="eval-bar-container">
          <div className="eval-bar" style={{ height: `${evalPercent}%` }} />
        </div>
        <div className="eval-text">
          <span className="eval-score">{formatEval(currentAnalysis)}</span>
          {currentAnalysis?.bestMove && (
            <span className="eval-best-move">Best: {currentAnalysis.bestMove}</span>
          )}
        </div>
      </div>

      {/* Chart */}
      <div className="analysis-chart">
        <Line data={chartData} options={chartOptions} />
      </div>

      {/* Navigation */}
      <div className="analysis-nav">
        <button onClick={goFirst} disabled={currentIndex <= 0}>⏮</button>
        <button onClick={goPrev} disabled={currentIndex <= 0}>◀</button>
        <span className="move-indicator">
          {currentIndex >= 0 && moves[currentIndex]
            ? `${currentIndex === 0 ? 'Start' : moves[currentIndex].san} (${currentIndex}/${moves.length - 1})`
            : '...'
          }
        </span>
        <button onClick={goNext} disabled={currentIndex >= moves.length - 1}>▶</button>
        <button onClick={goLast} disabled={currentIndex >= moves.length - 1}>⏭</button>
      </div>

      {/* New move toast (live mode only) */}
      {mode === 'live' && newMoveToast && (
        <div className="new-move-toast" onClick={jumpToLatest}>
          New move! Click to jump to latest.
        </div>
      )}

      {/* Status */}
      {analyzing && <div className="analysis-status">Analyzing...</div>}
    </div>
  );
}

