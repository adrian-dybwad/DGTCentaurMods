import type { AnalysisResult } from '../types/game';

/**
 * Stockfish web worker wrapper for chess analysis.
 */
export class StockfishService {
  private worker: Worker | null = null;
  private isReady = false;
  private pendingResolve: ((result: AnalysisResult) => void) | null = null;
  private currentFen = '';
  private currentResult: Partial<AnalysisResult> = {};
  private workerPath: string;

  constructor(workerPath = '/stockfish/stockfish.js') {
    this.workerPath = workerPath;
  }

  async init(): Promise<void> {
    if (this.worker) return;

    return new Promise((resolve, reject) => {
      try {
        this.worker = new Worker(this.workerPath);
        this.worker.onmessage = (e) => this.handleMessage(e.data);
        this.worker.onerror = (e) => {
          console.error('Stockfish worker error:', e);
          reject(e);
        };

        // Initialize UCI
        this.worker.postMessage('uci');
        
        // Wait for uciok
        const checkReady = setInterval(() => {
          if (this.isReady) {
            clearInterval(checkReady);
            resolve();
          }
        }, 100);

        // Timeout after 10s
        setTimeout(() => {
          clearInterval(checkReady);
          if (!this.isReady) {
            reject(new Error('Stockfish init timeout'));
          }
        }, 10000);
      } catch (e) {
        reject(e);
      }
    });
  }

  private handleMessage(line: string): void {
    if (line === 'uciok') {
      this.isReady = true;
      this.worker?.postMessage('isready');
      return;
    }

    if (line === 'readyok') {
      return;
    }

    // Parse score
    if (line.startsWith('info') && line.includes('score')) {
      const cpMatch = line.match(/score cp (-?\d+)/);
      const mateMatch = line.match(/score mate (-?\d+)/);
      const depthMatch = line.match(/depth (\d+)/);

      if (cpMatch) {
        this.currentResult.score = parseInt(cpMatch[1], 10);
        this.currentResult.mate = null;
      }
      if (mateMatch) {
        this.currentResult.mate = parseInt(mateMatch[1], 10);
        this.currentResult.score = null;
      }
      if (depthMatch) {
        this.currentResult.depth = parseInt(depthMatch[1], 10);
      }
    }

    // Parse bestmove
    if (line.startsWith('bestmove')) {
      const match = line.match(/bestmove (\S+)/);
      if (match) {
        this.currentResult.bestMove = match[1];
      }

      if (this.pendingResolve) {
        this.pendingResolve({
          fen: this.currentFen,
          score: this.currentResult.score ?? null,
          mate: this.currentResult.mate ?? null,
          bestMove: this.currentResult.bestMove ?? null,
          depth: this.currentResult.depth ?? 0,
        });
        this.pendingResolve = null;
      }
    }
  }

  async analyze(fen: string, depth = 18): Promise<AnalysisResult> {
    if (!this.worker || !this.isReady) {
      throw new Error('Stockfish not initialized');
    }

    // Cancel any pending analysis
    this.worker.postMessage('stop');

    this.currentFen = fen;
    this.currentResult = {};

    return new Promise((resolve) => {
      this.pendingResolve = resolve;
      this.worker!.postMessage(`position fen ${fen}`);
      this.worker!.postMessage(`go depth ${depth}`);
    });
  }

  stop(): void {
    this.worker?.postMessage('stop');
  }

  destroy(): void {
    this.worker?.terminate();
    this.worker = null;
    this.isReady = false;
  }
}

// Singleton instance
let instance: StockfishService | null = null;

export function getStockfishService(): StockfishService {
  if (!instance) {
    instance = new StockfishService();
  }
  return instance;
}

