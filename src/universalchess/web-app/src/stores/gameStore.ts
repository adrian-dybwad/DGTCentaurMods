import { create } from 'zustand';
import type { GameState, AnalysisResult, ConnectionStatus } from '../types/game';

interface GameStoreState {
  gameState: GameState | null;
  connectionStatus: ConnectionStatus;
  analysis: AnalysisResult | null;
  analysisHistory: AnalysisResult[];
  currentMoveIndex: number;
  
  setGameState: (state: GameState) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setAnalysis: (analysis: AnalysisResult) => void;
  addAnalysisToHistory: (analysis: AnalysisResult) => void;
  setCurrentMoveIndex: (index: number) => void;
  clearAnalysisHistory: () => void;
}

export const useGameStore = create<GameStoreState>((set) => ({
  gameState: null,
  connectionStatus: 'disconnected',
  analysis: null,
  analysisHistory: [],
  currentMoveIndex: -1,

  setGameState: (gameState) => set({ gameState }),
  setConnectionStatus: (connectionStatus) => set({ connectionStatus }),
  setAnalysis: (analysis) => set({ analysis }),
  addAnalysisToHistory: (analysis) =>
    set((state) => ({
      analysisHistory: [...state.analysisHistory, analysis],
    })),
  setCurrentMoveIndex: (currentMoveIndex) => set({ currentMoveIndex }),
  clearAnalysisHistory: () => set({ analysisHistory: [], currentMoveIndex: -1 }),
}));
