"""Resource loader for DGTCentaurMods.

Loads and caches resources (fonts, images, sprites) from the resources directory.
Resources are loaded once at application startup and passed to components that need them.

Usage:
    from universalchess.resources import ResourceLoader
    
    # Create loader with resource directories
    loader = ResourceLoader("/opt/universalchess/resources", "/home/pi/resources")
    
    # Load resources
    font = loader.get_font(18)
    sprites = loader.get_chess_sprites()
    logo, mask = loader.get_knight_logo(100)
    
    # Pass to widgets
    widget = SomeWidget(font=font, sprites=sprites)
"""

from PIL import Image, ImageFont
from typing import Dict, Optional, Tuple
import os


class ResourceLoader:
    """Loads and caches resources from the filesystem.
    
    Resources are loaded lazily on first access and cached for reuse.
    Checks user directory first (for overrides), then system directory.
    """
    
    def __init__(self, system_dir: str, user_dir: str = None):
        """Initialize resource loader with resource directories.
        
        Args:
            system_dir: Path to system resources directory (e.g., /opt/universalchess/resources)
            user_dir: Optional path to user resources directory (checked first, for overrides)
        """
        self.system_dir = system_dir
        self.user_dir = user_dir
        
        # Font cache: {(path, size): ImageFont}
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        
        # Image cache: {name: Image}
        self._image_cache: Dict[str, Image.Image] = {}
        
        # Resized image cache: {(name, width, height): Image}
        self._resized_cache: Dict[Tuple[str, int, int], Image.Image] = {}
        
        # Default font path (resolved on first use)
        self._default_font_path: Optional[str] = None
    
    def get_resource_path(self, filename: str) -> Optional[str]:
        """Get full path to a resource file.
        
        Checks user directory first (for overrides), then system directory.
        
        Args:
            filename: Name of the resource file
            
        Returns:
            Full path to the file, or None if not found
        """
        if ".." in filename:
            return None
        
        # Check user directory first for overrides
        if self.user_dir:
            user_path = os.path.join(self.user_dir, filename)
            if os.path.exists(user_path):
                return user_path
        
        # Fall back to system directory
        system_path = os.path.join(self.system_dir, filename)
        if os.path.exists(system_path):
            return system_path
        
        return None
    
    def get_font(self, size: int, path: str = None) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size.
        
        Uses caching to avoid loading the same font multiple times.
        
        Args:
            size: Font size in points
            path: Optional path to font file. If None, uses default Font.ttc
            
        Returns:
            PIL ImageFont object
        """
        # Resolve font path
        if path is None:
            if self._default_font_path is None:
                self._default_font_path = self.get_resource_path("Font.ttc")
            path = self._default_font_path
        
        # Check cache
        cache_key = (path, size)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]
        
        # Load font
        font = None
        if path and os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
            except Exception:
                pass
        
        if font is None:
            font = ImageFont.load_default()
        
        # Cache and return
        self._font_cache[cache_key] = font
        return font
    
    def get_image(self, name: str) -> Optional[Image.Image]:
        """Get an image resource by name.
        
        Images are cached after first load.
        
        Args:
            name: Filename of the image (e.g., "knight_logo.bmp")
            
        Returns:
            PIL Image object, or None if not found
        """
        if name in self._image_cache:
            return self._image_cache[name]
        
        path = self.get_resource_path(name)
        if not path:
            return None
        
        try:
            img = Image.open(path)
            # Load the image data into memory (detach from file)
            img.load()
            self._image_cache[name] = img
            return img
        except Exception:
            return None
    
    def get_chess_sprites(self) -> Optional[Image.Image]:
        """Get chess piece sprite sheet.
        
        Returns the sprite sheet converted to 1-bit mode for e-paper display.
        
        Returns:
            PIL Image in mode '1', or None if not found
        """
        # Check cache first
        cache_key = "chesssprites.bmp:1bit"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]
        
        img = self.get_image("chesssprites.bmp")
        if img is None:
            return None
        
        # Convert to 1-bit mode
        if img.mode != "1":
            if img.mode != "L":
                img = img.convert("L")
            img = img.point(lambda x: 0 if x < 128 else 255, mode="1")
        
        self._image_cache[cache_key] = img
        return img
    
    def get_knight_logo(self, size: int = 100) -> Tuple[Optional[Image.Image], Optional[Image.Image]]:
        """Get knight logo image and its transparency mask.
        
        Args:
            size: Target size (width and height) for the logo
            
        Returns:
            Tuple of (logo_image, mask_image), or (None, None) if not found.
            The mask has 255 where the knight is (black pixels) and 0 elsewhere.
        """
        cache_key = ("knight_logo.bmp", size, size)
        mask_cache_key = ("knight_logo_mask.bmp", size, size)
        
        if cache_key in self._resized_cache and mask_cache_key in self._resized_cache:
            return self._resized_cache[cache_key], self._resized_cache[mask_cache_key]
        
        img = self.get_image("knight_logo.bmp")
        if img is None:
            return None, None
        
        # Resize if needed
        if img.size[0] != size or img.size[1] != size:
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            img = img.resize((size, size), resample)
        
        # Ensure 1-bit mode
        if img.mode != '1':
            img = img.convert('1')
        
        # Create mask where black pixels (knight) are opaque
        mask = Image.new("1", img.size, 0)
        img_pixels = img.load()
        mask_pixels = mask.load()
        for y in range(img.height):
            for x in range(img.width):
                if img_pixels[x, y] == 0:  # Black pixel
                    mask_pixels[x, y] = 255  # Opaque
        
        # Cache both
        self._resized_cache[cache_key] = img
        self._resized_cache[mask_cache_key] = mask
        
        return img, mask
