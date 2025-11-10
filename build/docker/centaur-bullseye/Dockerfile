FROM arm32v7/debian:bullseye

# Install dependencies required for the centaur binary
# The binary needs libc6 and additional system libraries
# Based on the binary's ELF header, it requires:
# - libc6 (libc.so.6, libdl.so.2, libpthread.so.0, libm.so.6)
# - libgcc1 (libgcc_s.so.1)
# - Additional libraries that might be needed at runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libc6 \
    libgcc1 \
    libstdc++6 \
    libcrypt1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to /centaur (where the entire centaur directory will be mounted)
# The centaur binary and all its libraries/resources are in this directory
WORKDIR /centaur

# Verify the binary exists and is executable (for debugging)
RUN ls -la /centaur/centaur || echo "Note: /centaur/centaur will be mounted at runtime"

# Set entrypoint to the centaur binary
# The entire /home/pi/centaur directory is mounted at /centaur
# This includes the binary, libraries (libpython3.5m.so.1.0, libexpat.so.1, etc.), 
# and other resources the binary needs
ENTRYPOINT ["/centaur/centaur"]

