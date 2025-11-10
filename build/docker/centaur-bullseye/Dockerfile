FROM arm32v7/debian:bullseye

# Install minimal dependencies required for the centaur binary
# The binary needs libc6 and basic system libraries from Bullseye
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libc6 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to /centaur (where the binary will be mounted)
WORKDIR /centaur

# Set entrypoint to the centaur binary
# The binary will be mounted from the host at /home/pi/centaur/centaur
ENTRYPOINT ["/centaur/centaur"]

