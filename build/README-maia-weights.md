# Maia Weight Files Installation

## Overview

The maia chess engine requires neural network weight files to function. These files are downloaded from the maia-chess GitHub repository.

## Installation

### On Raspberry Pi

1. SSH into your Raspberry Pi:
   ```bash
   ssh pi@dgt.local
   ```

2. Navigate to the opt directory:
   ```bash
   cd /opt
   ```

3. Run the download script:
   ```bash
   ./maia_weights.sh
   ```

4. Wait for the download to complete (may take a few minutes)

### From Development Machine

You can also download the files on your development machine and copy them to the Pi:

1. Run the script locally:
   ```bash
   cd DGTCentaurMods/opt
   ./maia_weights.sh
   ```

2. Copy the weight files to the Pi:
   ```bash
   scp -r DGTCentaurMods/engines/maia_weights pi@dgt.local:/opt/universalchess/engines/
   scp DGTCentaurMods/engines/maia-1900.pb.gz pi@dgt.local:/opt/universalchess/engines/
   ```

## Requirements

- Git installed (`sudo apt-get install git`)
- At least 50MB free disk space
- Internet connection

## Weight Files

The following weight files will be downloaded:

- maia-1100.pb.gz (~1.3 MB) - ELO 1100
- maia-1200.pb.gz (~1.2 MB) - ELO 1200
- maia-1300.pb.gz (~1.2 MB) - ELO 1300
- maia-1400.pb.gz (~1.3 MB) - ELO 1400
- maia-1500.pb.gz (~1.3 MB) - ELO 1500
- maia-1600.pb.gz (~1.3 MB) - ELO 1600
- maia-1700.pb.gz (~1.3 MB) - ELO 1700
- maia-1800.pb.gz (~1.3 MB) - ELO 1800
- maia-1900.pb.gz (~1.3 MB) - ELO 1900

Total size: ~11 MB

## Troubleshooting

### "git is not installed"
```bash
sudo apt-get update
sudo apt-get install git
```

### "Not enough disk space"
Free up space on your Raspberry Pi:
```bash
sudo apt-get clean
sudo apt-get autoremove
```

### "Failed to clone repository"
Check your internet connection and try again. You can also manually download the files from:
https://github.com/CSSLab/maia-chess/tree/master/maia_weights

## Verification

After installation, verify the files exist:
```bash
ls -lh /opt/universalchess/engines/maia_weights/
```

You should see 9 `.pb.gz` files.
