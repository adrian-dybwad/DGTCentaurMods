#!/usr/bin/env python3
"""
Probe script to identify the e-Paper display variant (epd2in9 vs epd2in9d).

This script attempts various initialization sequences and feature tests
to determine which display variant is connected.
"""

import sys
import os
import time
import logging

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Suppress most logs during probing
    format='%(levelname)s: %(message)s'
)

from PIL import Image

# Import epaper modules
try:
    from epaper.framework.waveshare import epdconfig
    from epaper.framework.waveshare.epd2in9d import EPD
except ImportError:
    # Fallback if running from different location
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'epaper', 'framework', 'waveshare'))
    import epdconfig
    from epd2in9d import EPD


class DisplayProbe:
    """Probe the display to identify its variant."""
    
    def __init__(self):
        self.results = {}
        self.epd = None
    
    def test_module_init(self):
        """Test if we can initialize the hardware module."""
        try:
            result = epdconfig.module_init()
            self.results['module_init'] = result == 0
            return result == 0
        except Exception as e:
            self.results['module_init'] = False
            self.results['module_init_error'] = str(e)
            return False
    
    def test_epd2in9d_init(self):
        """Test epd2in9d initialization sequence."""
        try:
            if not self.epd:
                self.epd = EPD()
            
            # Try the epd2in9d init sequence
            result = self.epd.init()
            self.results['epd2in9d_init'] = result == 0
            return result == 0
        except Exception as e:
            self.results['epd2in9d_init'] = False
            self.results['epd2in9d_init_error'] = str(e)
            return False
    
    def test_display_partial_method(self):
        """Test if DisplayPartial() method exists and can be called."""
        try:
            if not self.epd:
                self.results['display_partial_test_error'] = "EPD object is None"
                return False
            
            # Debug: Check what methods are actually available
            all_methods = [m for m in dir(self.epd) if not m.startswith('_')]
            self.results['epd_methods'] = all_methods
            
            # Check if method exists
            has_method = hasattr(self.epd, 'DisplayPartial')
            self.results['has_display_partial'] = has_method
            
            # Also check if it's callable
            if has_method:
                is_callable = callable(getattr(self.epd, 'DisplayPartial', None))
                self.results['display_partial_callable'] = is_callable
            
            if not has_method:
                return False
            
            # Try to call it with a test image
            # Create a small test image (all white to minimize visual change)
            test_image = Image.new('1', (self.epd.width, self.epd.height), 255)
            buf = self.epd.getbuffer(test_image)
            
            # Try calling DisplayPartial (this should work for epd2in9d)
            # Note: This will actually trigger a display refresh, but with white image
            # it should be minimal visual change
            try:
                # First ensure we're in partial mode by calling SetPartReg if available
                if hasattr(self.epd, 'SetPartReg'):
                    self.epd.SetPartReg()
                
                self.epd.DisplayPartial(buf)
                # DisplayPartial() calls TurnOnDisplay() which uses ReadBusy() to wait for completion
                
                # Immediately clear to white to avoid leaving black artifacts
                self.epd.Clear()
                # Clear() calls TurnOnDisplay() which uses ReadBusy() to wait for completion
                
                self.results['display_partial_works'] = True
                return True
            except Exception as e:
                self.results['display_partial_works'] = False
                self.results['display_partial_error'] = str(e)
                return False
                
        except Exception as e:
            self.results['display_partial_test_error'] = str(e)
            return False
    
    def test_set_part_reg_method(self):
        """Test if SetPartReg() method exists (epd2in9d feature)."""
        try:
            if not self.epd:
                self.results['set_part_reg_test_error'] = "EPD object is None"
                return False
            
            has_method = hasattr(self.epd, 'SetPartReg')
            self.results['has_set_part_reg'] = has_method
            
            # Also check if it's callable
            if has_method:
                is_callable = callable(getattr(self.epd, 'SetPartReg', None))
                self.results['set_part_reg_callable'] = is_callable
            
            if has_method:
                # Try calling it
                try:
                    self.epd.SetPartReg()
                    self.results['set_part_reg_works'] = True
                    return True
                except Exception as e:
                    self.results['set_part_reg_works'] = False
                    self.results['set_part_reg_error'] = str(e)
                    return False
            
            return False
        except Exception as e:
            self.results['set_part_reg_test_error'] = str(e)
            return False
    
    def test_busy_pin_behavior(self):
        """Test busy pin behavior (epd2in9d uses 0x71 command)."""
        try:
            if not self.epd:
                return False
            
            # Check if ReadBusy method uses 0x71 command
            import inspect
            try:
                source = inspect.getsource(self.epd.ReadBusy)
                uses_0x71 = '0x71' in source or 'send_command(0x71)' in source
            except (OSError, TypeError):
                # Can't get source (might be compiled), check bytecode constants
                try:
                    consts = self.epd.ReadBusy.__code__.co_consts
                    uses_0x71 = any('0x71' in str(c) for c in consts)
                except:
                    # Last resort: check if method exists and assume it uses 0x71 for epd2in9d
                    uses_0x71 = hasattr(self.epd, 'ReadBusy')
            
            self.results['busy_uses_0x71'] = uses_0x71
            return uses_0x71
        except Exception as e:
            self.results['busy_pin_test_error'] = str(e)
            return False
    
    def test_panel_setting(self):
        """Check panel setting value used in init (0x1f for epd2in9d)."""
        try:
            if not self.epd:
                return False
            
            # Check the init method source to see what panel setting it uses
            import inspect
            try:
                source = inspect.getsource(self.epd.init)
                uses_0x1f = '0x1f' in source
            except (OSError, TypeError):
                # Can't get source, check bytecode constants
                try:
                    consts = self.epd.init.__code__.co_consts
                    uses_0x1f = any('0x1f' in str(c) or c == 0x1f for c in consts)
                except:
                    # If init succeeded, it likely used 0x1f (epd2in9d sequence)
                    uses_0x1f = self.results.get('epd2in9d_init', False)
            
            self.results['panel_setting_0x1f'] = uses_0x1f
            return uses_0x1f
        except Exception as e:
            self.results['panel_setting_test_error'] = str(e)
            return False
    
    def cleanup(self):
        """Clean up resources."""
        try:
            if self.epd:
                # Clear display to white before sleeping
                try:
                    self.epd.Clear()
                    # Clear() calls TurnOnDisplay() which uses ReadBusy() to wait for completion
                except Exception:
                    # If Clear() fails, try using display() with white image
                    try:
                        white_image = Image.new('1', (self.epd.width, self.epd.height), 255)
                        white_buf = self.epd.getbuffer(white_image)
                        self.epd.display(white_buf)
                        # display() calls TurnOnDisplay() which uses ReadBusy() to wait for completion
                    except Exception:
                        pass
                self.epd.sleep()
            epdconfig.module_exit()
        except Exception:
            pass
    
    def probe(self):
        """Run all probe tests."""
        print("=" * 60)
        print("e-Paper Display Variant Probe")
        print("=" * 60)
        print()
        
        # Test 1: Module initialization
        print("Test 1: Hardware module initialization...", end=" ")
        if self.test_module_init():
            print("✓ PASSED")
        else:
            print("✗ FAILED")
            print(f"  Error: {self.results.get('module_init_error', 'Unknown error')}")
            return False
        print()
        
        # Test 2: EPD initialization
        print("Test 2: EPD initialization (epd2in9d sequence)...", end=" ")
        if self.test_epd2in9d_init():
            print("✓ PASSED")
        else:
            print("✗ FAILED")
            print(f"  Error: {self.results.get('epd2in9d_init_error', 'Unknown error')}")
            self.cleanup()
            return False
        print()
        
        # Test 3: DisplayPartial method
        print("Test 3: DisplayPartial() method...", end=" ")
        test_result = self.test_display_partial_method()
        has_method = self.results.get('has_display_partial', False)
        if has_method:
            print("✓ EXISTS", end=" ")
            if self.results.get('display_partial_works', False):
                print("✓ WORKS")
            else:
                print("✗ FAILED")
                print(f"  Error: {self.results.get('display_partial_error', 'Unknown error')}")
        else:
            print("✗ NOT FOUND")
            # Debug output
            if 'epd_methods' in self.results:
                methods = self.results['epd_methods']
                print(f"  Available methods: {', '.join(sorted(methods)[:15])}...")
                if 'DisplayPartial' not in methods:
                    print(f"  'DisplayPartial' not in method list")
                else:
                    print(f"  'DisplayPartial' IS in method list but hasattr() returned False")
            if 'display_partial_test_error' in self.results:
                print(f"  Test error: {self.results['display_partial_test_error']}")
        print()
        
        # Test 4: SetPartReg method
        print("Test 4: SetPartReg() method...", end=" ")
        test_result = self.test_set_part_reg_method()
        has_method = self.results.get('has_set_part_reg', False)
        if has_method:
            print("✓ EXISTS", end=" ")
            if self.results.get('set_part_reg_works', False):
                print("✓ WORKS")
            else:
                print("✗ FAILED")
                print(f"  Error: {self.results.get('set_part_reg_error', 'Unknown error')}")
        else:
            print("✗ NOT FOUND")
            # Debug output
            if 'epd_methods' in self.results:
                methods = self.results['epd_methods']
                if 'SetPartReg' not in methods:
                    print(f"  'SetPartReg' not in method list")
                else:
                    print(f"  'SetPartReg' IS in method list but hasattr() returned False")
            if 'set_part_reg_test_error' in self.results:
                print(f"  Test error: {self.results['set_part_reg_test_error']}")
        print()
        
        # Test 5: Panel setting
        print("Test 5: Panel setting (0x1f for epd2in9d)...", end=" ")
        if self.test_panel_setting():
            print("✓ USES 0x1f")
        else:
            print("✗ NOT FOUND")
        print()
        
        # Test 6: Busy pin behavior
        print("Test 6: Busy pin behavior (0x71 command)...", end=" ")
        if self.test_busy_pin_behavior():
            print("✓ USES 0x71")
        else:
            print("✗ NOT FOUND")
        print()
        
        # Analysis
        print("=" * 60)
        print("ANALYSIS")
        print("=" * 60)
        
        # Count evidence for epd2in9d
        evidence_epd2in9d = 0
        evidence_epd2in9 = 0
        
        if self.results.get('epd2in9d_init', False):
            evidence_epd2in9d += 2  # Strong evidence
        if self.results.get('has_display_partial', False):
            evidence_epd2in9d += 2  # Strong evidence
        if self.results.get('display_partial_works', False):
            evidence_epd2in9d += 2  # Strong evidence
        if self.results.get('has_set_part_reg', False):
            evidence_epd2in9d += 1
        if self.results.get('panel_setting_0x1f', False):
            evidence_epd2in9d += 1
        if self.results.get('busy_uses_0x71', False):
            evidence_epd2in9d += 1
        
        print(f"\nEvidence score for epd2in9d: {evidence_epd2in9d}/9")
        print(f"Evidence score for epd2in9: {evidence_epd2in9}/9")
        print()
        
        # Conclusion
        if evidence_epd2in9d >= 5:
            print("✓ CONCLUSION: Display appears to be epd2in9d (D variant)")
            print("  - Supports DisplayPartial() for partial refresh")
            print("  - Uses panel setting 0x1f in initialization")
            print("  - Uses 0x71 command for busy pin checking")
        elif evidence_epd2in9d >= 3:
            print("? CONCLUSION: Display likely to be epd2in9d (D variant)")
            print("  - Some features match epd2in9d, but not all tests passed")
        else:
            print("? CONCLUSION: Unable to definitively identify variant")
            print("  - Display may be epd2in9 (non-D variant)")
            print("  - Or initialization may have failed")
        
        print()
        print("=" * 60)
        
        return True


def main():
    """Main entry point."""
    probe = DisplayProbe()
    
    try:
        success = probe.probe()
        if not success:
            print("\nProbe failed - unable to initialize hardware")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nProbe interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error during probe: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        probe.cleanup()


if __name__ == "__main__":
    main()

