FROM arm32v7/debian:bullseye

# Install minimal dependencies required for the centaur binary
# The binary needs libc6 and basic system libraries from Bullseye
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libc6 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to /centaur (where the entire centaur directory will be mounted)
# The centaur binary and all its libraries/resources are in this directory
WORKDIR /centaur

# Set entrypoint to the centaur binary
# The entire /home/pi/centaur directory is mounted at /centaur
# This includes the binary, libraries (libpython3.5m.so.1.0, libexpat.so.1, etc.), 
# and other resources the binary needs
ENTRYPOINT ["/centaur/centaur"]

