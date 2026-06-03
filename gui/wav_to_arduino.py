#!/usr/bin/env python3
"""
WAV to Arduino Mouth Position Converter - Debug Version
Converts audio amplitude to discrete mouth positions (0-3)
with proper PWM sequences for mechanical mouth control.
"""

import wave
import struct
import numpy as np
import argparse
import serial
import time
from pathlib import Path

class MouthPositions:
    """Defines the 4 mouth positions with their PWM sequences"""
    
    # Two modes for positions 1 and 2
    POSITIONS_SUSTAINED = {
        0: [('F', 0, 14)],
        1: [('F', 100, 104)],
        2: [('F', 155, 104)],
        3: [('F', 255, 104)]
    }
    
    POSITIONS_ATTACK = {
        0: [('F', 0, 14)],
        1: [('F', 255, 14)],
        2: [('F', 255, 54)],
        3: [('F', 255, 104)]
    }
    
    @staticmethod
    def get_sequence(position, use_attack=False):
        """Get PWM sequence for a position"""
        positions = MouthPositions.POSITIONS_ATTACK if use_attack else MouthPositions.SUSTAINED
        return positions.get(position, [('F', 0, 14)])
    
    @staticmethod
    def get_duration(position, use_attack=False):
        """Get total duration for a position"""
        sequence = MouthPositions.get_sequence(position, use_attack)
        return sum(duration for _, _, duration in sequence)


class WavToMouth:
    def __init__(self, 
                 window_ms=100,
                 threshold=0.02,
                 smoothing=0.4,
                 position_thresholds=None,
                 use_attack=False):
        
        self.window_ms = window_ms
        self.threshold = threshold
        self.smoothing = smoothing
        self.use_attack = use_attack
        
        if position_thresholds is None:
            self.position_thresholds = [0.0, 0.15, 0.40, 0.70]
        else:
            self.position_thresholds = position_thresholds
    
    def load_wav(self, filepath):
        """Load and process WAV file"""
        print(f"\n📂 Loading: {filepath}")
        
        with wave.open(str(filepath), 'rb') as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            framerate = wav.getframerate()
            n_frames = wav.getnframes()
            duration = n_frames / framerate
            
            print(f"   Channels: {channels}")
            print(f"   Sample Rate: {framerate} Hz")
            print(f"   Duration: {duration:.2f}s")
            print(f"   Frames: {n_frames}")
            
            raw_data = wav.readframes(n_frames)
            
            if sample_width == 1:
                dtype = np.uint8
                data = np.frombuffer(raw_data, dtype=dtype)
                data = (data.astype(np.float32) - 128) / 128.0
            elif sample_width == 2:
                dtype = np.int16
                data = np.frombuffer(raw_data, dtype=dtype)
                data = data.astype(np.float32) / 32768.0
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")
            
            if channels == 2:
                data = data.reshape(-1, 2).mean(axis=1)
            
            return data, framerate
    
    def calculate_amplitude_windows(self, audio_data, sample_rate):
        """Calculate amplitude for each time window"""
        window_samples = int((self.window_ms / 1000.0) * sample_rate)
        n_windows = len(audio_data) // window_samples
        
        amplitudes = []
        smoothed_amp = 0
        
        for i in range(n_windows):
            start = i * window_samples
            end = start + window_samples
            window = audio_data[start:end]
            
            rms = np.sqrt(np.mean(window**2))
            smoothed_amp = (self.smoothing * smoothed_amp + 
                          (1 - self.smoothing) * rms)
            
            amplitudes.append(smoothed_amp)
        
        return np.array(amplitudes)
    
    def amplitude_to_position(self, amplitude):
        """Map amplitude to mouth position (0-3)"""
        if amplitude < self.threshold:
            return 0
        
        for pos in range(3, 0, -1):
            if amplitude >= self.position_thresholds[pos]:
                return pos
        
        return 0
    
    def amplitudes_to_positions(self, amplitudes):
        """Convert amplitude array to position array"""
        max_amp = np.max(amplitudes)
        if max_amp > 0:
            normalized = amplitudes / max_amp
        else:
            normalized = amplitudes
        
        positions = [self.amplitude_to_position(amp) for amp in normalized]
        return positions
    
    def optimize_positions(self, positions):
        """Remove redundant consecutive positions"""
        if not positions:
            return []
        
        optimized = [positions[0]]
        for pos in positions[1:]:
            if pos != optimized[-1]:
                optimized.append(pos)
        
        return optimized
    
    def positions_to_commands(self, positions):
        """Convert position sequence to Arduino commands"""
        commands = []
        
        for position in positions:
            sequence = MouthPositions.get_sequence(position, self.use_attack)
            for direction, pwm, duration in sequence:
                commands.append((direction, pwm, duration))
        
        return commands
    
    def commands_to_string(self, commands):
        """Convert command list to Arduino command string"""
        parts = []
        for direction, pwm, duration in commands:
            parts.extend([direction, str(pwm), str(duration)])
        
        return ','.join(parts)
    
    def split_into_chunks(self, commands, max_commands=20):
        """Split command list into chunks for Arduino limit"""
        chunks = []
        
        for i in range(0, len(commands), max_commands):
            chunk = commands[i:i + max_commands]
            chunk_string = self.commands_to_string(chunk)
            chunks.append(chunk_string)
        
        return chunks
    
    def calculate_chunk_duration(self, chunk_string):
        """Calculate total duration of a command chunk"""
        parts = chunk_string.split(',')
        duration = 0
        for i in range(2, len(parts), 3):  # Every 3rd element starting at index 2
            try:
                duration += int(parts[i])
            except (ValueError, IndexError):
                pass
        return duration
    
    def process_wav(self, filepath):
        """Main processing pipeline"""
        audio_data, sample_rate = self.load_wav(filepath)
        
        print(f"\n🔊 Analyzing amplitude (window: {self.window_ms}ms)...")
        amplitudes = self.calculate_amplitude_windows(audio_data, sample_rate)
        print(f"   Generated {len(amplitudes)} amplitude windows")
        
        print(f"\n👄 Mapping to mouth positions (0-3)...")
        print(f"   Mode: {'ATTACK (fast 255 PWM)' if self.use_attack else 'SUSTAINED (lower PWM)'}")
        positions = self.amplitudes_to_positions(amplitudes)
        
        pos_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        for pos in positions:
            pos_counts[pos] += 1
        
        print(f"   Position distribution:")
        for pos in range(4):
            count = pos_counts[pos]
            percent = (count / len(positions)) * 100
            bar = '█' * int(percent / 2)
            print(f"     Pos {pos}: {count:4d} ({percent:5.1f}%) {bar}")
        
        print(f"\n⚡ Optimizing sequence...")
        optimized = self.optimize_positions(positions)
        print(f"   Reduced from {len(positions)} to {len(optimized)} positions")
        
        print(f"\n📝 Generating Arduino commands...")
        commands = self.positions_to_commands(optimized)
        print(f"   Total commands: {len(commands)}")
        
        total_duration = sum(duration for _, _, duration in commands)
        print(f"   Total duration: {total_duration}ms ({total_duration/1000:.2f}s)")
        
        chunks = self.split_into_chunks(commands)
        print(f"   Split into {len(chunks)} chunks (max 20 cmds/chunk)")
        
        return chunks, positions, optimized, commands
    
    def save_to_file(self, chunks, positions, output_file):
        """Save commands to file"""
        print(f"\n💾 Saving to: {output_file}")
        
        with open(output_file, 'w') as f:
            f.write("# Arduino Mouth Animation Commands\n")
            f.write(f"# Generated from WAV file\n")
            f.write(f"# Window: {self.window_ms}ms\n")
            f.write(f"# Mode: {'ATTACK' if self.use_attack else 'SUSTAINED'}\n")
            f.write(f"# Position thresholds: {self.position_thresholds}\n")
            f.write(f"# Total chunks: {len(chunks)}\n\n")
            
            for i, chunk in enumerate(chunks, 1):
                duration = self.calculate_chunk_duration(chunk)
                f.write(f"# Chunk {i}/{len(chunks)} - Duration: {duration}ms\n")
                f.write(f"{chunk}\n\n")
        
        print(f"   ✓ Saved {len(chunks)} command chunks")
    
    def send_to_arduino(self, chunks, port, baudrate=115200, inter_chunk_delay=1.0):
        """Send commands to Arduino via serial with proper timing"""
        print(f"\n📡 Connecting to Arduino on {port}...")
        
        try:
            ser = serial.Serial(port, baudrate, timeout=2)
            time.sleep(2.5)  # Wait for Arduino reset
            
            # Clear buffer and read initial messages
            print("\n" + "="*50)
            print("ARDUINO BOOT MESSAGES")
            print("="*50)
            time.sleep(0.5)
            while ser.in_waiting:
                msg = ser.readline().decode('utf-8', errors='ignore').strip()
                if msg:
                    print(msg)
            print("="*50 + "\n")
            
            print(f"▶️  Sending {len(chunks)} command chunks with DEBUG mode\n")
            
            for chunk_num, chunk in enumerate(chunks, 1):
                # Calculate expected duration for this chunk
                chunk_duration_ms = self.calculate_chunk_duration(chunk)
                chunk_duration_sec = chunk_duration_ms / 1000.0
                
                print(f"\n{'='*50}")
                print(f"📤 CHUNK {chunk_num}/{len(chunks)}")
                print(f"{'='*50}")
                print(f"Expected duration: {chunk_duration_ms}ms ({chunk_duration_sec:.2f}s)")
                print(f"Command preview: {chunk[:80]}{'...' if len(chunk) > 80 else ''}")
                print(f"\nSending at: {time.strftime('%H:%M:%S')}")
                
                # Send the chunk
                ser.write(f"{chunk}\n".encode())
                ser.flush()
                
                print(f"\n--- Arduino Response ---")
                
                # Wait for chunk to complete + buffer time
                wait_time = chunk_duration_sec + inter_chunk_delay
                start_time = time.time()
                last_response_time = start_time
                
                while time.time() - start_time < wait_time:
                    if ser.in_waiting:
                        try:
                            response = ser.readline().decode('utf-8', errors='ignore').strip()
                            if response:
                                timestamp = time.strftime('%H:%M:%S')
                                print(f"[{timestamp}] {response}")
                                last_response_time = time.time()
                        except Exception as e:
                            print(f"[ERROR reading] {e}")
                    time.sleep(0.05)
                
                # Check for completion message
                time_since_last = time.time() - last_response_time
                print(f"\n--- Chunk Complete ---")
                print(f"Time since last response: {time_since_last:.2f}s")
                
                # Give extra time if no completion message received
                if time_since_last > 0.5:
                    print("⚠️  Warning: No recent messages from Arduino")
                    print("   Waiting extra 0.5s...")
                    time.sleep(0.5)
            
            print(f"\n{'='*50}")
            print("✅ ALL CHUNKS SENT")
            print(f"{'='*50}")
            
            # Final buffer read
            print("\n--- Final Arduino Messages ---")
            time.sleep(0.5)
            while ser.in_waiting:
                msg = ser.readline().decode('utf-8', errors='ignore').strip()
                if msg:
                    print(msg)
            
            ser.close()
            print("\n🔌 Serial connection closed")
            
        except serial.SerialException as e:
            print(f"\n❌ Serial error: {e}")
            print("\n💡 Troubleshooting:")
            print("   1. Check port: ls /dev/ttyACM* or ls /dev/ttyUSB*")
            print("   2. Verify Arduino is connected")
            print("   3. Close Arduino IDE Serial Monitor if open")
            print("   4. Check permissions: sudo usermod -a -G dialout $USER")
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            if 'ser' in locals() and ser.is_open:
                ser.write(b"STOP\n")
                ser.close()
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description='Convert WAV to Arduino mouth position commands (0-3) - DEBUG VERSION',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Mouth Positions:
  SUSTAINED mode (default):
    0: F,0,14      (closed)
    1: F,100,104   (slight - sustained)
    2: F,155,104   (medium - sustained)
    3: F,255,104   (full)
  
  ATTACK mode (--attack):
    0: F,0,14      (closed)
    1: F,255,14    (slight - fast attack)
    2: F,255,54    (medium - fast attack)
    3: F,255,104   (full)

Examples:
  # Debug: Preview and save
  python wav_to_mouth.py speech.wav --preview
  python wav_to_mouth.py speech.wav -o test.txt
  
  # Debug: Send with verbose output
  python wav_to_mouth.py speech.wav -p /dev/ttyACM0
  
  # Try attack mode for snappier movements
  python wav_to_mouth.py speech.wav --attack -p /dev/ttyACM0
  
  # Adjust inter-chunk delay if chunks are being skipped
  python wav_to_mouth.py speech.wav -p /dev/ttyACM0 --delay 1.5
        """
    )
    
    parser.add_argument('input', help='Input WAV file (mono TTS audio)')
    parser.add_argument('-o', '--output', help='Output file for commands')
    parser.add_argument('-p', '--port', help='Serial port (e.g., /dev/ttyACM0)')
    parser.add_argument('-b', '--baudrate', type=int, default=115200, 
                       help='Serial baudrate (default: 115200)')
    parser.add_argument('-w', '--window', type=int, default=100,
                       help='Analysis window in ms (default: 100)')
    parser.add_argument('-t', '--thresholds', 
                       help='Position thresholds as CSV (e.g., 0.1,0.3,0.6)')
    parser.add_argument('--threshold', type=float, default=0.02,
                       help='Silence threshold 0-1 (default: 0.02)')
    parser.add_argument('-s', '--smoothing', type=float, default=0.4,
                       help='Smoothing factor 0-1 (default: 0.4)')
    parser.add_argument('--attack', action='store_true',
                       help='Use attack mode (fast 255 PWM for pos 1&2)')
    parser.add_argument('--delay', type=float, default=1.0,
                       help='Inter-chunk delay in seconds (default: 1.0)')
    parser.add_argument('--preview', action='store_true',
                       help='Preview position sequence without saving/sending')
    
    args = parser.parse_args()
    
    input_file = Path(args.input)
    if not input_file.exists():
        print(f"❌ Error: File not found: {input_file}")
        return
    
    position_thresholds = None
    if args.thresholds:
        try:
            thresholds = [float(x.strip()) for x in args.thresholds.split(',')]
            if len(thresholds) != 3:
                print("❌ Error: Must provide exactly 3 thresholds (for positions 1, 2, 3)")
                return
            position_thresholds = [0.0] + thresholds
        except ValueError:
            print("❌ Error: Invalid threshold format. Use: 0.1,0.3,0.6")
            return
    
    converter = WavToMouth(
        window_ms=args.window,
        threshold=args.threshold,
        smoothing=args.smoothing,
        position_thresholds=position_thresholds,
        use_attack=args.attack
    )
    
    chunks, positions, optimized, commands = converter.process_wav(input_file)
    
    if args.preview:
        print("\n📊 Position Preview (first 50 windows):")
        for i, pos in enumerate(positions[:50], 1):
            symbols = ['·', '▂', '▄', '█']
            bar = symbols[pos] * (10 + pos * 5)
            print(f"  {i:3d}: Pos {pos} {bar}")
        if len(positions) > 50:
            print(f"  ... ({len(positions) - 50} more windows)")
        
        print(f"\n📊 Optimized sequence (first 30 positions):")
        print(f"  {' → '.join(map(str, optimized[:30]))}")
        if len(optimized) > 30:
            print(f"  ... ({len(optimized) - 30} more)")
        return
    
    if args.output:
        converter.save_to_file(chunks, optimized, args.output)
    
    if args.port:
        converter.send_to_arduino(chunks, args.port, args.baudrate, args.delay)
    
    if not args.output and not args.port:
        print("\n⚠️  No output specified. Use -o to save or -p to send to Arduino")
        print("   Or use --preview to see position sequence")


if __name__ == '__main__':
    main()
