#!/usr/bin/env python3
"""
Test script to render chess board widget and save the image.
"""

import sys
import os

# Add current directory to path to import epaper package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from epaper import ChessBoardWidget

def main():
    """Render chess board and save image."""
    # Create chess board widget with starting position
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    chess_board = ChessBoardWidget(0, 0, fen)
    
    # Render the chess board
    print("Rendering chess board...")
    img = chess_board.render()
    
    # Save the image
    output_path = "/tmp/chess_board_render.png"
    img.save(output_path)
    print(f"Chess board image saved to: {output_path}")
    print(f"Image size: {img.size}, mode: {img.mode}")
    
    # Also save as BMP for comparison
    output_path_bmp = "/tmp/chess_board_render.bmp"
    img.save(output_path_bmp)
    print(f"Chess board image (BMP) saved to: {output_path_bmp}")

if __name__ == "__main__":
    main()

